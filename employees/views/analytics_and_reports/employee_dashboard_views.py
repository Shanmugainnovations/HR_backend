import os
import datetime
import pytz
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from employees.models import (
    EmployeeShiftSchedule, Employee, 
    Shift, LeaveRequest
)
from employees.views.common.utils import get_mongo_client


@api_view(['GET'])
@permission_classes([AllowAny])
def today_status(request):
    """
    Unified Dashboard API for both Web and Mobile apps.
    Fetches real-time punch logs, working duration, live status,
    month-to-date stats, yesterday summary, and upcoming shift schedule.
    """
    try:
        # Check token / auth header if available
        auth_header = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION')
        auth_emp_id = None
        if auth_header:
            from employees.token_utils import decode_employee_token
            parts = auth_header.split()
            token = parts[1] if len(parts) == 2 else parts[0]
            payload = decode_employee_token(token)
            if payload:
                auth_emp_id = payload.get('employee_id') or payload.get('employeeId')

        employee_id = request.GET.get('employee_id') or auth_emp_id or getattr(request, 'authenticated_employee_id', None) or request.headers.get('auth-user-id')
        if not employee_id:
            return Response({"error": "Employee ID is required"}, status=400)

        emp_str = str(employee_id).strip()
        ist_tz = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.datetime.now(ist_tz)
        today = now_ist.date()
        yesterday = today - datetime.timedelta(days=1)

        client = get_mongo_client()
        hr_db_name = os.environ.get('HR_DB_NAME', 'HR')
        global_db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
        hr_db = client[hr_db_name]
        global_db = client[global_db_name]

        # 1. Employee Profile Info & Human-Readable Labels
        emp_name = "Employee"
        department_name = "General"
        designation_name = "Staff"

        try:
            prof_query = {'$or': [{'employeeId': emp_str}, {'employee_id': emp_str}]}
            if emp_str.isdigit():
                prof_query['$or'].extend([{'employeeId': int(emp_str)}, {'employee_id': int(emp_str)}])

            prof = global_db['backend_diagnostics_profile'].find_one(prof_query)
            if prof:
                emp_name = prof.get('employeeName') or prof.get('name') or emp_name
                raw_dept = prof.get('department')
                raw_desig = prof.get('designation')

                # Resolve department display name
                if raw_dept:
                    dept_doc = global_db['backend_diagnostics_Departments'].find_one({
                        '$or': [{'department_code': raw_dept}, {'department_name': raw_dept}]
                    })
                    department_name = dept_doc.get('department_name') if dept_doc else raw_dept
                
                # Resolve designation display name
                if raw_desig:
                    desig_doc = global_db['backend_diagnostics_Designation'].find_one({
                        '$or': [
                            {'Designation_code': raw_desig}, {'designation_code': raw_desig},
                            {'designation': raw_desig}
                        ]
                    })
                    if desig_doc:
                        designation_name = desig_doc.get('designation') or desig_doc.get('Designation_name') or raw_desig
                    else:
                        designation_name = raw_desig
            else:
                emp_obj = Employee.objects.filter(employee_id=emp_str).first()
                if emp_obj:
                    emp_name = emp_obj.name or emp_name
        except Exception:
            pass

        # 2. Shift Info Helper
        all_shifts = {s.id: s for s in Shift.objects.all()}

        def get_shift_for_date(d):
            try:
                # Check approved leave
                leave = LeaveRequest.objects.filter(
                    employee_id=emp_str,
                    start_date__lte=d,
                    end_date__gte=d,
                    status='Approved'
                ).first()
                if leave:
                    return {
                        "name": f"Leave ({leave.leave_type or 'Approved'})",
                        "times": "Full Day",
                        "is_leave": True,
                        "is_off": False
                    }

                # Check schedule
                schedule = EmployeeShiftSchedule.objects.filter(
                    employee_id=emp_str,
                    date=d
                ).first()
                if not schedule:
                    schedule = EmployeeShiftSchedule.objects.filter(
                        employee__employee_id=emp_str,
                        date=d
                    ).first()

                if schedule:
                    shift_obj = schedule.shift or all_shifts.get(schedule.shift_id)
                    if shift_obj:
                        s_name = shift_obj.name
                        if s_name.upper() in ['OFF', 'WEEK OFF', 'WO']:
                            return {"name": "Week Off", "times": "-", "is_leave": False, "is_off": True}
                        st_str = shift_obj.start_time.strftime('%H:%M') if shift_obj.start_time else ""
                        et_str = shift_obj.end_time.strftime('%H:%M') if shift_obj.end_time else ""
                        return {
                            "name": s_name,
                            "times": f"{st_str} - {et_str}" if st_str and et_str else "",
                            "is_leave": False,
                            "is_off": False,
                            "start_time": shift_obj.start_time,
                            "end_time": shift_obj.end_time
                        }
            except Exception:
                pass
            return {"name": "General", "times": "09:00 - 18:00", "is_leave": False, "is_off": False, "start_time": None, "end_time": None}

        today_shift = get_shift_for_date(today)
        yesterday_shift = get_shift_for_date(yesterday)

        # 3. Upcoming 7 Days Shifts
        upcoming_shifts = []
        for i in range(1, 8):
            f_date = today + datetime.timedelta(days=i)
            s_info = get_shift_for_date(f_date)
            upcoming_shifts.append({
                "date": f_date.strftime("%Y-%m-%d"),
                "formatted_date": f_date.strftime("%d %b %Y"),
                "day": f_date.strftime("%A"),
                "shift": s_info["name"],
                "times": s_info["times"],
                "is_off": s_info.get("is_off", False),
                "is_leave": s_info.get("is_leave", False)
            })

        # 4. Today's Logs (Direct PyMongo Query in UTC)
        start_today_ist = ist_tz.localize(datetime.datetime.combine(today, datetime.time.min))
        end_today_ist = ist_tz.localize(datetime.datetime.combine(today, datetime.time.max))
        start_today_utc = start_today_ist.astimezone(pytz.UTC).replace(tzinfo=None)
        end_today_utc = end_today_ist.astimezone(pytz.UTC).replace(tzinfo=None)

        attendance_col = hr_db['employees_employeeattendance']
        # Try both string and integer formats for employee_id
        emp_match = {'$in': [emp_str, int(emp_str)]} if emp_str.isdigit() else emp_str

        today_punches_raw = list(attendance_col.find({
            'employee_id': emp_match,
            'attendence_time': {'$gte': start_today_utc, '$lte': end_today_utc}
        }).sort('attendence_time', 1))

        punches_list = []
        in_punches = []
        out_punches = []

        for p in today_punches_raw:
            raw_time = p.get('attendence_time')
            if not raw_time:
                continue
            time_ist = raw_time.replace(tzinfo=pytz.UTC).astimezone(ist_tz)
            time_str = time_ist.strftime('%I:%M:%S %p')
            p_type = (p.get('attendence_type') or 'IN').upper()
            punches_list.append({
                "time": time_str,
                "raw_time": time_ist.strftime('%H:%M'),
                "type": p_type,
                "device": p.get('device_id') or 'N/A'
            })
            if p_type == 'IN':
                in_punches.append(time_ist)
            elif p_type == 'OUT':
                out_punches.append(time_ist)

        first_in = in_punches[0] if in_punches else (today_punches_raw[0]['attendence_time'].replace(tzinfo=pytz.UTC).astimezone(ist_tz) if today_punches_raw else None)
        last_out = out_punches[-1] if out_punches else None

        # Today's Working Duration
        total_worked_today_str = "0h 0m"
        worked_mins = 0
        progress_pct = 0.0
        today_late_mins = 0
        today_late_str = None

        if first_in:
            calc_end = last_out if (last_out and last_out > first_in) else now_ist
            total_sec = max(0, (calc_end - first_in).total_seconds())
            hours = int(total_sec // 3600)
            minutes = int((total_sec % 3600) // 60)
            total_worked_today_str = f"{hours}h {minutes:02d}m"
            worked_mins = int(total_sec // 60)
            progress_pct = min(100.0, max(5.0, round((worked_mins / 480.0) * 100, 1)))

            # Late login calculation
            if today_shift.get("start_time"):
                s_start = ist_tz.localize(datetime.datetime.combine(today, today_shift["start_time"]))
                if first_in > s_start + datetime.timedelta(minutes=10):
                    today_late_mins = int((first_in - s_start).total_seconds() // 60)
                    lh = today_late_mins // 60
                    lm = today_late_mins % 60
                    today_late_str = f"{lh}h {lm}m" if lh > 0 else f"{lm}m"

        # Current Status determination
        if today_shift.get("is_leave"):
            current_status = "On Leave"
            status_type = "leave"
        elif today_shift.get("is_off") and not punches_list:
            current_status = "Week Off"
            status_type = "week_off"
        elif not punches_list:
            current_status = "Not Checked In"
            status_type = "not_checked_in"
        else:
            last_punch = punches_list[-1]
            if last_punch["type"] == "IN":
                current_status = "Working"
                status_type = "working"
            else:
                current_status = "Checked Out"
                status_type = "checked_out"

        # 5. Yesterday's Logs (PyMongo)
        start_yest_ist = ist_tz.localize(datetime.datetime.combine(yesterday, datetime.time.min))
        end_yest_ist = ist_tz.localize(datetime.datetime.combine(yesterday, datetime.time.max))
        start_yest_utc = start_yest_ist.astimezone(pytz.UTC).replace(tzinfo=None)
        end_yest_utc = end_yest_ist.astimezone(pytz.UTC).replace(tzinfo=None)

        yest_punches_raw = list(attendance_col.find({
            'employee_id': emp_match,
            'attendence_time': {'$gte': start_yest_utc, '$lte': end_yest_utc}
        }).sort('attendence_time', 1))

        y_in = [p['attendence_time'].replace(tzinfo=pytz.UTC).astimezone(ist_tz) for p in yest_punches_raw if p.get('attendence_type') == 'IN']
        y_out = [p['attendence_time'].replace(tzinfo=pytz.UTC).astimezone(ist_tz) for p in yest_punches_raw if p.get('attendence_type') == 'OUT']

        yest_status = "Absent"
        yest_in_str = y_in[0].strftime('%I:%M %p') if y_in else "--"
        yest_out_str = y_out[-1].strftime('%I:%M %p') if y_out else "--"
        yest_hours_str = "--"

        if y_in and y_out and y_out[-1] > y_in[0]:
            yest_status = "Present"
            sec = (y_out[-1] - y_in[0]).total_seconds()
            yest_hours_str = f"{int(sec // 3600)}h {int((sec % 3600) // 60):02d}m"
        elif y_in or y_out:
            yest_status = "Single Punch"
        elif yesterday_shift.get("is_leave"):
            yest_status = "On Leave"
        elif yesterday_shift.get("is_off") or yesterday_shift["name"] in ["Not Assigned", "Off", "Week Off"]:
            yest_status = "Week Off"

        # 6. Current Month Summary (PyMongo)
        start_month = datetime.date(today.year, today.month, 1)
        start_month_utc = ist_tz.localize(datetime.datetime.combine(start_month, datetime.time.min)).astimezone(pytz.UTC).replace(tzinfo=None)

        month_punches_raw = list(attendance_col.find({
            'employee_id': emp_match,
            'attendence_time': {'$gte': start_month_utc, '$lte': end_today_utc}
        }, {'attendence_time': 1, 'attendence_type': 1}))

        month_punches_by_date = {}
        for ml in month_punches_raw:
            rt = ml.get('attendence_time')
            if not rt:
                continue
            d_val = rt.replace(tzinfo=pytz.UTC).astimezone(ist_tz).date()
            if d_val not in month_punches_by_date:
                month_punches_by_date[d_val] = {'IN': 0, 'OUT': 0}
            p_t = (ml.get('attendence_type') or 'IN').upper()
            month_punches_by_date[d_val][p_t] = month_punches_by_date[d_val].get(p_t, 0) + 1

        present_count = 0
        single_punch_count = 0
        for d_key, p_counts in month_punches_by_date.items():
            if p_counts.get('IN', 0) > 0 and p_counts.get('OUT', 0) > 0:
                present_count += 1
            elif p_counts.get('IN', 0) > 0 or p_counts.get('OUT', 0) > 0:
                single_punch_count += 1

        # 7. 7-Day Capsule Strip (`this_week` for mobile app)
        this_week = []
        for i in range(6, -1, -1):
            day_date = today - datetime.timedelta(days=i)
            day_dow = day_date.strftime("%a").upper()
            day_num = str(day_date.day)
            is_today = (day_date == today)

            day_start_utc = ist_tz.localize(datetime.datetime.combine(day_date, datetime.time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
            day_end_utc = ist_tz.localize(datetime.datetime.combine(day_date, datetime.time.max)).astimezone(pytz.UTC).replace(tzinfo=None)

            d_logs = list(attendance_col.find({
                'employee_id': emp_match,
                'attendence_time': {'$gte': day_start_utc, '$lte': day_end_utc}
            }).sort('attendence_time', 1))

            d_shift = get_shift_for_date(day_date)
            has_punch = len(d_logs) > 0
            day_status = 'ABSENT'
            day_late = 0
            day_early = 0

            if has_punch:
                d_in = [p for p in d_logs if p.get('attendence_type') == 'IN']
                d_out = [p for p in d_logs if p.get('attendence_type') == 'OUT']
                f_in = d_in[0]['attendence_time'].replace(tzinfo=pytz.UTC).astimezone(ist_tz) if d_in else d_logs[0]['attendence_time'].replace(tzinfo=pytz.UTC).astimezone(ist_tz)
                l_out = d_out[-1]['attendence_time'].replace(tzinfo=pytz.UTC).astimezone(ist_tz) if d_out else (d_logs[-1]['attendence_time'].replace(tzinfo=pytz.UTC).astimezone(ist_tz) if len(d_logs) > 1 else None)

                if d_shift.get("start_time"):
                    st = ist_tz.localize(datetime.datetime.combine(day_date, d_shift["start_time"]))
                    if f_in > st + datetime.timedelta(minutes=10):
                        day_late = int((f_in - st).total_seconds() // 60)

                if d_shift.get("end_time") and l_out:
                    et = ist_tz.localize(datetime.datetime.combine(day_date, d_shift["end_time"]))
                    if d_shift["end_time"] < d_shift["start_time"]:
                        et += datetime.timedelta(days=1)
                    if l_out < et - datetime.timedelta(minutes=10):
                        day_early = int((et - l_out).total_seconds() // 60)

                if day_late > 0 and day_early > 0:
                    day_status = 'LATE_AND_EARLY'
                elif day_late > 0:
                    day_status = 'LATE_LOGIN'
                elif day_early > 0:
                    day_status = 'EARLY_EXIT'
                elif len(d_logs) == 1:
                    day_status = 'SINGLE_PUNCH'
                else:
                    day_status = 'PRESENT'
            elif is_today:
                day_status = 'TODAY_PENDING'
            elif d_shift.get("is_off"):
                day_status = 'OFF'
            elif d_shift.get("is_leave"):
                day_status = 'ON_LEAVE'
            else:
                day_status = 'ABSENT'

            this_week.append({
                "dow": day_dow,
                "day_num": day_num,
                "date": day_date.strftime("%Y-%m-%d"),
                "is_today": is_today,
                "status": day_status,
                "shift": d_shift["name"],
                "late_mins": day_late,
                "early_mins": day_early,
                "punches_count": len(d_logs)
            })

        return Response({
            "employee_id": emp_str,
            "name": emp_name,
            "employee_name": emp_name,
            "department": department_name,
            "designation": designation_name,
            "today_date": today.strftime("%A, %d %B %Y"),
            "shift_name": today_shift["name"],
            "shift_times": today_shift["times"],
            "login_time": first_in.strftime('%I:%M:%S %p') if first_in else "N/A",
            "logout_time": last_out.strftime('%I:%M:%S %p') if last_out else "N/A",
            "working_hours": total_worked_today_str,
            "worked_hours": total_worked_today_str,
            "worked_mins": worked_mins,
            "progress_pct": progress_pct,
            "late_mins": today_late_mins,
            "late_str": today_late_str,
            "break_time": "—",
            "overtime": "—",
            "current_status": current_status,
            "status_type": status_type,
            "today_punches": punches_list,
            "month_summary": {
                "month_name": today.strftime("%B %Y"),
                "present_days": present_count,
                "single_punches": single_punch_count,
                "days_elapsed": today.day
            },
            "yesterday": {
                "shift_name": yesterday_shift["name"],
                "status": yest_status,
                "in_time": yest_in_str,
                "out_time": yest_out_str,
                "working_hours": yest_hours_str
            },
            "this_week": this_week,
            "upcoming_shifts": upcoming_shifts
        }, status=200)

    except Exception as e:
        return Response({"error": str(e)}, status=500)
