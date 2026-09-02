from employees.permissions import HasRoleAndDataPermission
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from employees.models import (
    EmployeeAttendance, EmployeeShiftSchedule, Employee, 
    Shift, LeaveRequest, Profile
)
from django.utils import timezone
import datetime
import pytz

@api_view(['GET'])
@permission_classes([AllowAny])
def today_status(request):
    try:
        employee_id = request.GET.get('employee_id')
        if not employee_id:
            employee_id = getattr(request, 'authenticated_employee_id', None) or request.headers.get('auth-user-id')
            
        if not employee_id:
            return Response({"error": "Employee ID is required"}, status=400)
            
        ist_tz = pytz.timezone('Asia/Kolkata')
        now_ist = datetime.datetime.now(ist_tz)
        today = now_ist.date()
        yesterday = today - datetime.timedelta(days=1)
        
        # 1. Employee Profile Info
        emp_name = "Employee"
        department = "General"
        designation = "Staff"
        
        try:
            profile = Profile.objects.filter(employeeId=employee_id).first()
            if profile:
                emp_name = profile.employeeName or emp_name
                department = profile.department or department
                designation = profile.designation or designation
            else:
                emp = Employee.objects.filter(employee_id=employee_id).first()
                if emp:
                    emp_name = emp.name or emp_name
        except Exception:
            pass

        # 2. Shift Info Helper
        all_shifts = {s.id: s for s in Shift.objects.all()}
        
        def get_shift_for_date(d):
            try:
                # Check approved leave
                leave = LeaveRequest.objects.filter(
                    employee_id=employee_id,
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
                    employee_id=employee_id,
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
                            "is_off": False
                        }
            except Exception:
                pass
            return {"name": "General", "times": "09:00 - 18:00", "is_leave": False, "is_off": False}

        today_shift = get_shift_for_date(today)
        yesterday_shift = get_shift_for_date(yesterday)

        # 3. Upcoming 7 Days Shifts
        upcoming_shifts = []
        for i in range(1, 8):
            f_date = today + datetime.timedelta(days=i)
            s_info = get_shift_for_date(f_date)
            upcoming_shifts.append({
                "date": f_date.strftime("%d %b %Y"),
                "day": f_date.strftime("%A"),
                "shift": s_info["name"],
                "times": s_info["times"],
                "is_off": s_info.get("is_off", False),
                "is_leave": s_info.get("is_leave", False)
            })

        # 4. Today's Logs (Accurate IST -> UTC Range)
        start_today_ist = ist_tz.localize(datetime.datetime.combine(today, datetime.time.min))
        end_today_ist = ist_tz.localize(datetime.datetime.combine(today, datetime.time.max))
        start_today_utc = start_today_ist.astimezone(pytz.UTC)
        end_today_utc = end_today_ist.astimezone(pytz.UTC)

        today_logs = EmployeeAttendance.objects.filter(
            employee_id=employee_id,
            attendence_time__gte=start_today_utc,
            attendence_time__lte=end_today_utc
        ).order_by('attendence_time')

        punches_list = []
        in_punches = []
        out_punches = []

        for log in today_logs:
            time_ist = log.attendence_time.astimezone(ist_tz)
            time_str = time_ist.strftime('%I:%M:%S %p')
            p_type = (log.attendence_type or 'IN').upper()
            punches_list.append({
                "time": time_str,
                "raw_time": time_ist.strftime('%H:%M'),
                "type": p_type
            })
            if p_type == 'IN':
                in_punches.append(time_ist)
            elif p_type == 'OUT':
                out_punches.append(time_ist)

        first_in = in_punches[0] if in_punches else None
        last_out = out_punches[-1] if out_punches else None

        # Today's Working Duration
        total_worked_today_str = "0h 0m"
        if first_in:
            calc_end = last_out if (last_out and last_out > first_in) else now_ist
            total_sec = max(0, (calc_end - first_in).total_seconds())
            hours = int(total_sec // 3600)
            minutes = int((total_sec % 3600) // 60)
            total_worked_today_str = f"{hours}h {minutes}m"

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

        # 5. Yesterday's Logs
        start_yest_ist = ist_tz.localize(datetime.datetime.combine(yesterday, datetime.time.min))
        end_yest_ist = ist_tz.localize(datetime.datetime.combine(yesterday, datetime.time.max))
        start_yest_utc = start_yest_ist.astimezone(pytz.UTC)
        end_yest_utc = end_yest_ist.astimezone(pytz.UTC)

        yest_logs = EmployeeAttendance.objects.filter(
            employee_id=employee_id,
            attendence_time__gte=start_yest_utc,
            attendence_time__lte=end_yest_utc
        ).order_by('attendence_time')

        y_in = [l.attendence_time.astimezone(ist_tz) for l in yest_logs if l.attendence_type == 'IN']
        y_out = [l.attendence_time.astimezone(ist_tz) for l in yest_logs if l.attendence_type == 'OUT']

        yest_status = "Absent"
        yest_in_str = y_in[0].strftime('%I:%M %p') if y_in else "--"
        yest_out_str = y_out[-1].strftime('%I:%M %p') if y_out else "--"
        yest_hours_str = "--"

        if y_in and y_out and y_out[-1] > y_in[0]:
            yest_status = "Present"
            sec = (y_out[-1] - y_in[0]).total_seconds()
            yest_hours_str = f"{int(sec // 3600)}h {int((sec % 3600) // 60)}m"
        elif y_in or y_out:
            yest_status = "Single Punch"
        elif yesterday_shift.get("is_leave"):
            yest_status = "On Leave"
        elif yesterday_shift.get("is_off") or yesterday_shift["name"] in ["Not Assigned", "Off", "Week Off"]:
            yest_status = "Week Off"

        # 6. Current Month Summary
        start_month = datetime.date(today.year, today.month, 1)
        start_month_utc = ist_tz.localize(datetime.datetime.combine(start_month, datetime.time.min)).astimezone(pytz.UTC)
        
        month_logs = EmployeeAttendance.objects.filter(
            employee_id=employee_id,
            attendence_time__gte=start_month_utc,
            attendence_time__lte=end_today_utc
        ).values('attendence_time', 'attendence_type')

        month_punches_by_date = {}
        for ml in month_logs:
            d_val = ml['attendence_time'].astimezone(ist_tz).date()
            if d_val not in month_punches_by_date:
                month_punches_by_date[d_val] = {'IN': 0, 'OUT': 0}
            p_t = (ml['attendence_type'] or 'IN').upper()
            month_punches_by_date[d_val][p_t] = month_punches_by_date[d_val].get(p_t, 0) + 1

        present_count = 0
        single_punch_count = 0
        for d_key, p_counts in month_punches_by_date.items():
            if p_counts.get('IN', 0) > 0 and p_counts.get('OUT', 0) > 0:
                present_count += 1
            elif p_counts.get('IN', 0) > 0 or p_counts.get('OUT', 0) > 0:
                single_punch_count += 1

        return Response({
            "employee_id": employee_id,
            "employee_name": emp_name,
            "department": department,
            "designation": designation,
            "today_date": today.strftime("%A, %d %B %Y"),
            "shift_name": today_shift["name"],
            "shift_times": today_shift["times"],
            "login_time": first_in.strftime('%I:%M:%S %p') if first_in else "N/A",
            "logout_time": last_out.strftime('%I:%M:%S %p') if last_out else "N/A",
            "working_hours": total_worked_today_str,
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
            "upcoming_shifts": upcoming_shifts
        }, status=200)

    except Exception as e:
        return Response({"error": str(e)}, status=500)
