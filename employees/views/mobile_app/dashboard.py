from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from employees.models import EmployeeAttendance, EmployeeShiftSchedule, Employee, Shift
from employees.views.common.utils import get_mongo_client
from django.utils import timezone
import datetime
import pytz
import os

from employees.decorators import token_required

@api_view(['GET'])
@permission_classes([AllowAny])
def today_status(request):
    """
    Mobile App Dashboard API: Fetches today's shift timing, punch-in status,
    worked hours, designation, and this week's 7-day attendance capsule strip.
    """
    try:
        # Check token if available
        auth_header = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION')
        auth_emp_id = None
        if auth_header:
            from employees.token_utils import decode_employee_token
            parts = auth_header.split()
            token = parts[1] if len(parts) == 2 else parts[0]
            payload = decode_employee_token(token)
            if payload:
                auth_emp_id = payload.get('employee_id') or payload.get('employeeId')

        employee_id = auth_emp_id or request.GET.get('employee_id')

        if not employee_id:
            return Response({"error": "Employee ID is required"}, status=400)

        emp_str = str(employee_id).strip()
        ist_tz = pytz.timezone('Asia/Kolkata')
        now_ist = timezone.now().astimezone(ist_tz)
        today = now_ist.date()
        yesterday = today - datetime.timedelta(days=1)

        # 1️⃣ Fetch Profile details (Designation & Department) from Mongo / DB
        designation_name = ""
        department_name = ""
        employee_name = ""

        try:
            client = get_mongo_client()
            global_db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
            global_db = client[global_db_name]

            query = {'$or': [{'employeeId': emp_str}, {'employee_id': emp_str}]}
            if emp_str.isdigit():
                query['$or'].extend([{'employeeId': int(emp_str)}, {'employee_id': int(emp_str)}])

            prof = global_db['backend_diagnostics_profile'].find_one(query)
            if prof:
                employee_name = prof.get('employeeName') or prof.get('name') or ''
                desig_code = prof.get('designation')
                dept_code = prof.get('department')

                # Lookup human-readable designation
                if desig_code:
                    desig_doc = global_db['backend_diagnostics_Designation'].find_one({
                        '$or': [{'Designation_code': desig_code}, {'designation_code': desig_code}]
                    })
                    if desig_doc:
                        designation_name = desig_doc.get('designation') or desig_doc.get('Designation_name') or desig_doc.get('designation_name') or desig_code
                    else:
                        designation_name = desig_code

                # Lookup human-readable department
                if dept_code:
                    dept_doc = global_db['backend_diagnostics_Departments'].find_one({
                        '$or': [{'department_code': dept_code}, {'Department_code': dept_code}]
                    })
                    if dept_doc:
                        department_name = dept_doc.get('department_name') or dept_doc.get('Department_name') or dept_code
                    else:
                        department_name = dept_code
        except Exception:
            pass

        # 2️⃣ Helper to get shift
        emp_obj = Employee.objects.filter(employee_id=emp_str).first()
        if emp_obj and not employee_name:
            employee_name = emp_obj.name

        def get_shift_info(d, emp):
            try:
                if emp:
                    schedule = EmployeeShiftSchedule.objects.filter(employee=emp, date=d).first()
                    if schedule and schedule.shift:
                        return {
                            "name": schedule.shift.name,
                            "times": f"{schedule.shift.start_time.strftime('%H:%M')} - {schedule.shift.end_time.strftime('%H:%M')}",
                            "start_time": schedule.shift.start_time,
                            "end_time": schedule.shift.end_time
                        }
            except Exception:
                pass
            return {"name": "General A", "times": "09:30 - 17:30", "start_time": None, "end_time": None}

        today_shift = get_shift_info(today, emp_obj)
        yesterday_shift = get_shift_info(yesterday, emp_obj)

        # 3️⃣ Today's Punch Logs & Worked Time in IST
        start_of_day = ist_tz.localize(datetime.datetime.combine(today, datetime.time.min))
        end_of_day = ist_tz.localize(datetime.datetime.combine(today, datetime.time.max))

        logs = EmployeeAttendance.objects.filter(
            employee_id=emp_str,
            attendence_time__range=(start_of_day, end_of_day)
        ).order_by('attendence_time')

        first_in_time = None
        last_punch_type = None
        last_punch_time = None

        for log in logs:
            t_ist = log.attendence_time.astimezone(ist_tz)
            if first_in_time is None:
                first_in_time = t_ist
            last_punch_type = log.attendence_type
            last_punch_time = t_ist

        if not logs.exists():
            current_status = "Not Checked In"
        elif last_punch_type == 'OUT':
            current_status = "Checked Out"
        else:
            current_status = "Checked In"

        # Calculate worked duration and late entry for today
        worked_hours_str = "0h 00m"
        worked_mins = 0
        progress_pct = 0.0
        today_late_mins = 0
        today_late_str = None

        if first_in_time:
            end_calc_time = last_punch_time if current_status == "Checked Out" else now_ist
            diff_seconds = max(0, (end_calc_time - first_in_time).total_seconds())
            total_mins = int(diff_seconds // 60)
            hrs = total_mins // 60
            mins = total_mins % 60
            worked_mins = total_mins
            worked_hours_str = f"{hrs}h {mins:02d}m"
            # Assuming standard 8-hour shift (480 mins)
            progress_pct = min(100.0, max(5.0, round((total_mins / 480.0) * 100, 1)))

            # Calculate today late login
            if today_shift["times"] and '-' in today_shift["times"]:
                try:
                    start_part = today_shift["times"].split('-')[0].strip()
                    s_h, s_m = map(int, start_part.split(':'))
                    shift_start_dt = ist_tz.localize(datetime.datetime.combine(today, datetime.time(s_h, s_m)))
                    if first_in_time > shift_start_dt + datetime.timedelta(minutes=10):
                        today_late_mins = int((first_in_time - shift_start_dt).total_seconds() // 60)
                        h = today_late_mins // 60
                        m = today_late_mins % 60
                        today_late_str = f"{h}h {m}m" if h > 0 else f"{m}m"
                except Exception:
                    pass

        # 4️⃣ Generate "This Week" 7-Day Attendance Strip (6 days ago -> today in IST)
        all_shifts = {s.id: s for s in Shift.objects.all()}
        this_week = []
        for i in range(6, -1, -1):
            day_date = today - datetime.timedelta(days=i)
            day_dow = day_date.strftime("%a").upper()
            day_num = str(day_date.day)
            is_today = (day_date == today)

            # Query attendance on that day in IST
            day_start = ist_tz.localize(datetime.datetime.combine(day_date, datetime.time.min))
            day_end = ist_tz.localize(datetime.datetime.combine(day_date, datetime.time.max))

            day_logs = EmployeeAttendance.objects.filter(
                employee_id=emp_str,
                attendence_time__range=(day_start, day_end)
            ).order_by('attendence_time')

            # Check shift schedule
            day_sched = EmployeeShiftSchedule.objects.filter(
                employee__employee_id=emp_str,
                date=day_date
            ).first()
            shift_obj = all_shifts.get(day_sched.shift_id) if day_sched else None
            day_shift_name = shift_obj.name if shift_obj else 'Off/Unassigned'

            has_actual_shift = bool(
                shift_obj and shift_obj.start_time and shift_obj.end_time and
                (shift_obj.start_time.strftime('%H:%M') != '00:00' or shift_obj.end_time.strftime('%H:%M') != '00:00') and
                day_shift_name.upper() not in ['OFF', 'WEEK OFF', 'HOLIDAY', 'EL', 'CL', 'SL', 'ML', 'COFF', 'LEAVE']
            )

            is_off = (
                not has_actual_shift or
                day_shift_name.upper() in ['OFF', 'WEEK OFF', 'HOLIDAY', 'EL', 'CL', 'SL', 'ML', 'COFF', 'LEAVE'] or
                day_date.weekday() == 6  # Sunday
            )

            has_punch = day_logs.exists()
            day_status = 'ABSENT'
            day_late_mins = 0
            day_early_mins = 0

            if has_punch:
                in_p = [p for p in day_logs if p.attendence_type == 'IN']
                out_p = [p for p in day_logs if p.attendence_type == 'OUT']
                first_in = in_p[0].attendence_time.astimezone(ist_tz) if in_p else day_logs[0].attendence_time.astimezone(ist_tz)
                last_out = out_p[-1].attendence_time.astimezone(ist_tz) if out_p else (day_logs.last().attendence_time.astimezone(ist_tz) if day_logs.count() > 1 else None)

                if has_actual_shift and shift_obj.start_time:
                    s_start = ist_tz.localize(datetime.datetime.combine(day_date, shift_obj.start_time))
                    if first_in > s_start + datetime.timedelta(minutes=10):
                        day_late_mins = int((first_in - s_start).total_seconds() // 60)

                if has_actual_shift and shift_obj.end_time and last_out:
                    s_end = ist_tz.localize(datetime.datetime.combine(day_date, shift_obj.end_time))
                    if shift_obj.end_time < shift_obj.start_time:
                        s_end += datetime.timedelta(days=1)
                    if last_out < s_end - datetime.timedelta(minutes=10):
                        day_early_mins = int((s_end - last_out).total_seconds() // 60)

                if day_late_mins > 0 and day_early_mins > 0:
                    day_status = 'LATE_AND_EARLY'
                elif day_late_mins > 0:
                    day_status = 'LATE_LOGIN'
                elif day_early_mins > 0:
                    day_status = 'EARLY_EXIT'
                elif day_logs.count() == 1:
                    day_status = 'SINGLE_PUNCH'
                else:
                    day_status = 'PRESENT'
            elif is_today:
                day_status = 'TODAY_PENDING'
            elif is_off:
                day_status = 'OFF'
            else:
                day_status = 'ABSENT'

            this_week.append({
                "dow": day_dow,
                "day_num": day_num,
                "date": day_date.strftime("%Y-%m-%d"),
                "is_today": is_today,
                "status": day_status,
                "shift": day_shift_name,
                "late_mins": day_late_mins,
                "early_mins": day_early_mins,
                "punches_count": day_logs.count()
            })

        # 5️⃣ Upcoming shifts (next 7 days)
        upcoming_shifts = []
        for i in range(1, 8):
            future_date = today + datetime.timedelta(days=i)
            s_info = get_shift_info(future_date, emp_obj)
            upcoming_shifts.append({
                "date": future_date.strftime("%Y-%m-%d"),
                "day": future_date.strftime("%A"),
                "shift": s_info["name"],
                "times": s_info["times"]
            })

        return Response({
            "employee_id": emp_str,
            "name": employee_name or emp_str,
            "designation": designation_name or "Staff Member",
            "department": department_name or "",
            "shift_name": today_shift["name"],
            "shift_times": today_shift["times"],
            "login_time": first_in_time.strftime('%I:%M %p') if first_in_time else "N/A",
            "current_status": current_status,
            "worked_hours": worked_hours_str,
            "worked_mins": worked_mins,
            "progress_pct": progress_pct,
            "late_mins": today_late_mins,
            "late_str": today_late_str,
            "break_time": "—",
            "overtime": "—",
            "this_week": this_week,
            "upcoming_shifts": upcoming_shifts
        }, status=200)

    except Exception as e:
        return Response({"error": str(e)}, status=500)
