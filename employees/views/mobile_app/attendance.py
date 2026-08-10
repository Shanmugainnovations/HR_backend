from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from employees.models import EmployeeAttendance, EmployeeShiftSchedule, Employee, Shift
from django.utils import timezone
import datetime
import pytz
import calendar
import collections

@api_view(['GET'])
@permission_classes([AllowAny])
def my_attendance_report(request):
    """
    Mobile App Monthly Attendance API: High-performance attendance report 
    with IST timezone normalization and single-query JOIN shift lookups.
    """
    try:
        employee_id = request.GET.get('employee_id')
        month_str = request.GET.get('month') # YYYY-MM
        
        if not employee_id:
            return Response({"error": "Employee ID is required"}, status=400)
            
        if not month_str:
            return Response({"error": "Month parameter is required (YYYY-MM)"}, status=400)
            
        year, month = map(int, month_str.split('-'))
        _, last_day = calendar.monthrange(year, month)
        start_date = datetime.date(year, month, 1)
        end_date = datetime.date(year, month, last_day)
        
        # Get employee info
        try:
            emp = Employee.objects.get(employee_id=employee_id)
            emp_name = emp.name
        except Employee.DoesNotExist:
            emp_name = "Unknown"
            
        ist_tz = pytz.timezone('Asia/Kolkata')

        # Get shift schedules
        all_shifts = {s.id: s for s in Shift.objects.all()}
        schedules = EmployeeShiftSchedule.objects.filter(
            employee_id=employee_id,
            date__gte=start_date,
            date__lte=end_date
        )
        schedule_map = {s.date: all_shifts.get(s.shift_id) for s in schedules}
        
        start_dt = timezone.make_aware(datetime.datetime.combine(start_date, datetime.time.min))
        end_dt = timezone.make_aware(datetime.datetime.combine(end_date, datetime.time.max))
        
        # Get attendance logs
        logs = EmployeeAttendance.objects.filter(
            employee_id=employee_id,
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
            shift_timing = f"{shift.start_time.strftime('%H:%M')} - {shift.end_time.strftime('%H:%M')}" if shift else "-"
            
            punches = punches_by_date.get(curr_date, [])
            in_punches = [p for p in punches if p.attendence_type == 'IN']
            out_punches = [p for p in punches if p.attendence_type == 'OUT']
            
            check_in = in_punches[0].attendence_time if in_punches else None
            check_out = out_punches[-1].attendence_time if out_punches else None
            
            check_in_str = check_in.astimezone(ist_tz).strftime('%H:%M:%S') if check_in else "-"
            check_out_str = check_out.astimezone(ist_tz).strftime('%H:%M:%S') if check_out else "-"
            
            total_hours = "-"
            status = "Absent"
            
            if check_in and check_out and check_out > check_in:
                duration = check_out - check_in
                total_seconds = duration.total_seconds()
                hours = int(total_seconds // 3600)
                minutes = int((total_seconds % 3600) // 60)
                total_hours = f"{hours}h {minutes}m"
                status = "Present"
            elif check_in or check_out:
                status = "Single Punch"
            elif shift_name == "Off/Unassigned" or shift_name.upper() in ['OFF', 'WEEK OFF']:
                status = "Week Off"
                
            report_data.append({
                "date": curr_date.strftime("%Y-%m-%d"),
                "shift_name": shift_name,
                "shift_timing": shift_timing,
                "check_in": check_in_str,
                "check_out": check_out_str,
                "total_hours": total_hours,
                "status": status
            })
            
            curr_date += datetime.timedelta(days=1)
            
        return Response({
            "employee_id": employee_id,
            "employee_name": emp_name,
            "month": month_str,
            "report": report_data
        }, status=200)

    except Exception as e:
        return Response({"error": str(e)}, status=500)
