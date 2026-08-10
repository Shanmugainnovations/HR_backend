from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from employees.models import EmployeeAttendance, EmployeeShiftSchedule, Employee
from django.utils import timezone
import datetime
import pytz

@api_view(['GET'])
@permission_classes([AllowAny])
def today_status(request):
    """
    Mobile App Dashboard API: Fetches today's shift timing, punch-in status,
    and upcoming week roster for the logged-in employee.
    """
    try:
        employee_id = request.GET.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee ID is required"}, status=400)
        ist_tz = pytz.timezone('Asia/Kolkata')
        today = timezone.now().astimezone(ist_tz).date()
        yesterday = today - datetime.timedelta(days=1)
        
        # Helper to get shift
        def get_shift_info(d, emp):
            try:
                schedule = EmployeeShiftSchedule.objects.filter(employee=emp, date=d).first()
                if schedule:
                    return {
                        "name": schedule.shift.name,
                        "times": f"{schedule.shift.start_time.strftime('%H:%M')} - {schedule.shift.end_time.strftime('%H:%M')}"
                    }
            except Exception:
                pass
            return {"name": "Not Assigned", "times": ""}
            
        emp_obj = None
        try:
            emp_obj = Employee.objects.get(employee_id=employee_id)
        except Employee.DoesNotExist:
            pass
            
        today_shift = get_shift_info(today, emp_obj)
        yesterday_shift = get_shift_info(yesterday, emp_obj)
        
        # Upcoming shifts (next 7 days)
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
            
        # Today's logs
        start_of_day = timezone.make_aware(datetime.datetime.combine(today, datetime.time.min))
        end_of_day = start_of_day + datetime.timedelta(days=1)
        
        logs = EmployeeAttendance.objects.filter(
            employee_id=employee_id,
            attendence_time__gte=start_of_day,
            attendence_time__lt=end_of_day
        ).order_by('attendence_time')
        
        login_time = None
        current_status = "Not Checked In"
        
        for log in logs:
            time_str = log.attendence_time.astimezone(ist_tz).strftime('%H:%M:%S')
            if log.attendence_type == 'IN':
                if login_time is None:
                    login_time = time_str
                current_status = "Working"
            elif log.attendence_type == 'OUT':
                current_status = "Checked Out"
                
        # Yesterday's logs
        start_of_yest = timezone.make_aware(datetime.datetime.combine(yesterday, datetime.time.min))
        end_of_yest = start_of_yest + datetime.timedelta(days=1)
        yest_logs = EmployeeAttendance.objects.filter(
            employee_id=employee_id,
            attendence_time__gte=start_of_yest,
            attendence_time__lt=end_of_yest
        ).order_by('attendence_time')
        
        yest_in = [l for l in yest_logs if l.attendence_type == 'IN']
        yest_out = [l for l in yest_logs if l.attendence_type == 'OUT']
        
        yest_status = "Absent"
        if yest_in and yest_out:
            yest_status = "Present"
        elif yest_in or yest_out:
            yest_status = "Single Punch"
        elif yesterday_shift["name"] in ["Not Assigned", "Off", "Week Off"]:
            yest_status = "Week Off"
                
        return Response({
            "shift_name": today_shift["name"],
            "shift_times": today_shift["times"],
            "login_time": login_time or "N/A",
            "current_status": current_status,
            "yesterday": {
                "shift_name": yesterday_shift["name"],
                "status": yest_status
            },
            "upcoming_shifts": upcoming_shifts
        }, status=200)

    except Exception as e:
        return Response({"error": str(e)}, status=500)
