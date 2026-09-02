from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from employees.models import EmployeeAttendance, EmployeeShiftSchedule, Employee, Shift
from django.utils import timezone
import datetime
import pytz
import calendar
import collections

from employees.decorators import token_required

@api_view(['GET'])
@permission_classes([AllowAny])
def my_attendance_report(request):
    """
    Mobile App Monthly Attendance API: High-performance attendance report 
    with IST timezone normalization and unified status matching.
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
        month_str = request.GET.get('month') # YYYY-MM
        
        if not employee_id:
            return Response({"error": "Employee ID is required"}, status=400)
            
        ist_tz = pytz.timezone('Asia/Kolkata')
        now_ist = timezone.now().astimezone(ist_tz)
        today = now_ist.date()

        if not month_str:
            month_str = today.strftime("%Y-%m")
            
        year, month = map(int, month_str.split('-'))
        _, last_day = calendar.monthrange(year, month)
        start_date = datetime.date(year, month, 1)
        end_date = datetime.date(year, month, last_day)
        
        # Get employee info
        emp_str = str(employee_id).strip()
        try:
            emp = Employee.objects.get(employee_id=emp_str)
            emp_name = emp.name
        except Employee.DoesNotExist:
            emp_name = emp_str

        # Get shift schedules
        all_shifts = {s.id: s for s in Shift.objects.all()}
        schedules = EmployeeShiftSchedule.objects.filter(
            employee_id=emp_str,
            date__gte=start_date,
            date__lte=end_date
        )
        schedule_map = {s.date: all_shifts.get(s.shift_id) for s in schedules}
        
        start_dt = ist_tz.localize(datetime.datetime.combine(start_date, datetime.time.min))
        end_dt = ist_tz.localize(datetime.datetime.combine(end_date, datetime.time.max))
        
        # Get attendance logs
        logs = EmployeeAttendance.objects.filter(
            employee_id=emp_str,
            attendence_time__gte=start_dt,
            attendence_time__lte=end_dt
        ).order_by('attendence_time')
        
        # Group punches by date in IST timezone
        punches_by_date = collections.defaultdict(list)
        for log in logs:
            log_date = log.attendence_time.astimezone(ist_tz).date()
            punches_by_date[log_date].append(log)
            
        report_data = []
        curr_date = start_date
        while curr_date <= end_date:
            shift = schedule_map.get(curr_date)
            shift_name = shift.name if shift else "Off/Unassigned"
            has_actual_shift_timing = bool(
                shift and shift.start_time and shift.end_time and
                (shift.start_time.strftime('%H:%M') != '00:00' or shift.end_time.strftime('%H:%M') != '00:00') and
                shift_name.upper() not in ['OFF', 'WEEK OFF', 'HOLIDAY', 'EL', 'CL', 'SL', 'ML', 'COFF', 'LEAVE']
            )
            shift_timing = f"{shift.start_time.strftime('%H:%M')} - {shift.end_time.strftime('%H:%M')}" if has_actual_shift_timing else "-"
            
            punches = punches_by_date.get(curr_date, [])
            in_punches = [p for p in punches if p.attendence_type == 'IN']
            out_punches = [p for p in punches if p.attendence_type == 'OUT']
            
            check_in = in_punches[0].attendence_time if in_punches else (punches[0].attendence_time if punches else None)
            check_out = out_punches[-1].attendence_time if out_punches else (punches[-1].attendence_time if len(punches) > 1 else None)
            
            check_in_str = check_in.astimezone(ist_tz).strftime('%I:%M %p') if check_in else "-"
            check_out_str = check_out.astimezone(ist_tz).strftime('%I:%M %p') if (check_out and check_out != check_in) else "-"
            
            total_hours = "-"
            late_mins = 0
            late_str = None
            early_mins = 0
            early_str = None
            ot_mins = 0
            ot_str = None
            
            has_punches = len(punches) > 0
            is_off = (
                not has_actual_shift_timing or
                shift_name.upper() in ['OFF', 'WEEK OFF', 'HOLIDAY', 'EL', 'CL', 'SL', 'ML', 'COFF', 'LEAVE'] or
                curr_date.weekday() == 6  # Sunday
            )

            if has_punches:
                first_in_ist = check_in.astimezone(ist_tz)
                last_out_ist = check_out.astimezone(ist_tz) if check_out else None

                # Calculate late entry
                if has_actual_shift_timing and shift.start_time:
                    shift_start_dt = ist_tz.localize(datetime.datetime.combine(curr_date, shift.start_time))
                    if first_in_ist > shift_start_dt + datetime.timedelta(minutes=10):
                        late_mins = int((first_in_ist - shift_start_dt).total_seconds() // 60)
                        h = late_mins // 60
                        m = late_mins % 60
                        late_str = f"{h}h {m}m" if h > 0 else f"{m}m"

                # Calculate early checkout & overtime
                if has_actual_shift_timing and shift.end_time and last_out_ist and last_out_ist > first_in_ist:
                    shift_end_dt = ist_tz.localize(datetime.datetime.combine(curr_date, shift.end_time))
                    if shift.end_time < shift.start_time:
                        shift_end_dt += datetime.timedelta(days=1)

                    if last_out_ist < shift_end_dt - datetime.timedelta(minutes=10):
                        early_mins = int((shift_end_dt - last_out_ist).total_seconds() // 60)
                        h = early_mins // 60
                        m = early_mins % 60
                        early_str = f"{h}h {m}m" if h > 0 else f"{m}m"
                    elif last_out_ist > shift_end_dt + datetime.timedelta(minutes=15):
                        ot_mins = int((last_out_ist - shift_end_dt).total_seconds() // 60)
                        h = ot_mins // 60
                        m = ot_mins % 60
                        ot_str = f"{h}h {m}m" if h > 0 else f"{m}m"

                if check_in and check_out and check_out > check_in:
                    duration = check_out - check_in
                    total_seconds = duration.total_seconds()
                    hours = int(total_seconds // 3600)
                    minutes = int((total_seconds % 3600) // 60)
                    total_hours = f"{hours}h {minutes}m"

                # Determine detailed status
                if late_mins > 0 and early_mins > 0:
                    status = "Late & Early Exit"
                    base_status = "PRESENT"
                elif late_mins > 0:
                    status = "Late Login"
                    base_status = "PRESENT"
                elif early_mins > 0:
                    status = "Early Exit"
                    base_status = "PRESENT"
                elif len(punches) == 1:
                    status = "Single Punch"
                    base_status = "PRESENT"
                else:
                    status = "Present"
                    base_status = "PRESENT"

            elif curr_date == today:
                status = "Today Pending"
                base_status = "PENDING"
            elif curr_date > today:
                status = "Week Off" if is_off else "Upcoming"
                base_status = "WEEK_OFF" if is_off else "PENDING"
            elif is_off:
                status = "Week Off"
                base_status = "WEEK_OFF"
            else:
                status = "Absent"
                base_status = "ABSENT"
                
            report_data.append({
                "date": curr_date.strftime("%Y-%m-%d"),
                "shift_name": shift_name,
                "shift_timing": shift_timing,
                "check_in": check_in_str,
                "check_out": check_out_str,
                "total_hours": total_hours,
                "status": status,
                "base_status": base_status,
                "late_mins": late_mins,
                "late_str": late_str,
                "early_mins": early_mins,
                "early_str": early_str,
                "ot_mins": ot_mins,
                "ot_str": ot_str,
                "punches_count": len(punches)
            })
            
            curr_date += datetime.timedelta(days=1)
            
        return Response({
            "employee_id": emp_str,
            "employee_name": emp_name,
            "month": month_str,
            "report": report_data
        }, status=200)

    except Exception as e:
        return Response({"error": str(e)}, status=500)
