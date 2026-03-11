from datetime import date, datetime, timedelta
import calendar
import os
from pymongo import MongoClient
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from django.db.models import Min, Max, F
from django.db.models.expressions import RawSQL
from ..models import EmployeeShiftSchedule, EmployeeAttendance, Shift

@api_view(['GET'])
@permission_classes([AllowAny])
def roster_attendance_report(request):
    """
    Combines Shift Roster with Actual Punch timings and Total Hours.
    """
    month_str = request.query_params.get('month')
    department_filter = request.query_params.get('department')
    
    if not month_str:
        return Response({"error": "Month parameter (YYYY-MM) is required"}, status=400)
    
    try:
        year, month = map(int, month_str.split('-'))
    except ValueError:
        return Response({"error": "Invalid format. Use YYYY-MM"}, status=400)

    # Resolve Department Filter (handle numeric IDs from frontend)
    all_names = []
    codes = []
    raw_ids = []
    
    from ..models import Department
    sql_depts = list(Department.objects.all())
    sql_dept_map = {d.id: d.name for d in sql_depts}
    name_to_sql_id = {d.name: d.id for d in sql_depts}

    if department_filter and department_filter != 'All':
        raw_ids = [d.strip() for d in department_filter.split(',')]
        for rid in raw_ids:
            if rid.isdigit():
                d_id = int(rid)
                if d_id in sql_dept_map:
                    all_names.append(sql_dept_map[d_id])
            else:
                all_names.append(rid)

    # 1. Fetch Employees and Department Info from Mongo (Global DB)
    try:
        mongo_uri = os.environ.get("GLOBAL_DB_HOST")
        db_name = os.environ.get("GLOBAL_DB_NAME", "Global")
        client = MongoClient(mongo_uri)
        db = client[db_name]

        profiles_col = db['backend_diagnostics_profile']
        departments_col = db['backend_diagnostics_Departments']
        designations_col = db['backend_diagnostics_Designation']
        
        # Create lookup maps
        dept_map = {
            d.get('department_code'): d.get('department_name')
            for d in departments_col.find() # Removed is_active=True to be safe
        }
        
        # Resolve names to codes
        if all_names:
            resolved_codes = list(departments_col.find(
                {"department_name": {"$in": all_names}},
                {"department_code": 1}
            ))
            codes = [c.get("department_code") for c in resolved_codes]

        search_values = all_names + codes + raw_ids

        desig_map = {
            d.get('Designation_code'): d.get('designation')
            for d in designations_col.find({'is_active': True})
        }

        # Fetch profiles based on department filter
        query = {}
        if search_values:
            query = {
                "$or": [
                    {"department": {"$in": search_values}},
                    {"department_id": {"$in": search_values}},
                    {"department_name": {"$in": search_values}}
                ]
            }
        
        profiles = list(profiles_col.find(query))

        employees_data = {} # {emp_id: {name, department, department_id, designation}}
        for p in profiles:
            emp_id = str(p.get("employeeId"))
            dept_code = p.get("department") # This is the ID/Code
            dept_name = dept_map.get(dept_code, dept_code) or "Unassigned"
            
            # Use SQL ID for department_id in response if possible
            sql_id = name_to_sql_id.get(dept_name, dept_code)

            employees_data[emp_id] = {
                "name": p.get("employeeName"),
                "department": dept_name,
                "department_id": sql_id,
                "designation": desig_map.get(p.get("designation"), p.get("designation")) or "Unassigned"
            }
        
    except Exception as e:
        return Response({"error": f"Error fetching employee data: {str(e)}"}, status=500)

    if not employees_data:
        return Response([], status=200)

    # 2. Date Range
    _, last_day = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)

    # 3. Fetch Shift Schedules
    schedules = EmployeeShiftSchedule.objects.filter(
        date__gte=start_date, 
        date__lte=end_date,
        employee_id__in=employees_data.keys()
    ).select_related('shift', 'employee')

    schedule_map = {} # {(emp_id, date): shift_obj}
    for sch in schedules:
        schedule_map[(sch.employee_id, sch.date)] = sch.shift

    # 4. Fetch Attendance (Grouped by Date & Employee)
    start_dt = datetime.combine(start_date, datetime.min.time())
    end_dt = datetime.combine(end_date, datetime.max.time())
    
    # Using 'attendence_time' and 'employee_id' as per model
    attendance_records = EmployeeAttendance.objects.filter(
        attendence_time__range=(start_dt, end_dt),
        employee_id__in=employees_data.keys()
    ).order_by('employee_id', 'attendence_time')

    # Process attendance: map (emp_id, date) -> list of punches
    attendance_map = {}
    for att in attendance_records:
        d_date = att.attendence_time.date()
        key = (att.employee_id, d_date)
        
        if key not in attendance_map:
            attendance_map[key] = []
        
        attendance_map[key].append(att.attendence_time)

    # 5. Build Final Report Data
    report_data = []
    
    # Sorting employees by name for display
    # This might be slow if many employees, consider using existing pre-sorted if available or sort once.
    sorted_emp_ids = sorted(employees_data.keys(), key=lambda eid: employees_data[eid]['name'])

    for emp_id in sorted_emp_ids:
        emp_info = employees_data[emp_id]
        
        for day in range(1, last_day + 1):
            try:
                current_date = date(year, month, day)
            except ValueError:
                continue # Skip invalid days like Feb 30
            
            key = (emp_id, current_date)
            # Tuple key for shift lookup: (emp_id, date) 
            # Check how schedule_map was built: ((sch.employee.employee_id, sch.date))? No, sch.employee_id is charfield?
            # Model: employee = ForeignKey(Employee). Employee model has primary key 'employee_id'.
            # So sch.employee_id returns the string ID.
            
            shift_obj = schedule_map.get((emp_id, current_date))
            punches = attendance_map.get((emp_id, current_date), [])
            
            # Default values
            shift_name = "Off/Unassigned"
            shift_timing = "-"
            check_in_str = "-"
            check_out_str = "-"
            total_hours_str = "-"
            late_early_hrs = "-"
            status = "Absent"

            if shift_obj:
                shift_name = shift_obj.name
                shift_timing = f"{shift_obj.start_time.strftime('%H:%M')} - {shift_obj.end_time.strftime('%H:%M')}"

            if punches:
                # Assuming sorted by time already due to query order_by
                first_punch = punches[0]
                last_punch = punches[-1]
                
                check_in_str = first_punch.strftime('%H:%M:%S')
                status = "Present" # Basic logic

                if len(punches) > 1:
                    check_out_str = last_punch.strftime('%H:%M:%S')
                    duration = last_punch - first_punch
                    total_seconds = duration.total_seconds()
                    hours = int(total_seconds // 3600)
                    minutes = int((total_seconds % 3600) // 60)
                    total_hours_str = f"{hours}h {minutes}m"
                else:
                    # Only one punch
                    status = "Single Punch"
                    total_hours_str = "0h 0m"

            # Check if Absent (Shift assigned but no punches)
            if shift_obj and not punches:
                status = "Absent"
            # Check if Week Off (No shift assigned)
            elif not shift_obj and not punches:
                status = "Week Off/Holiday"
            
            # Refine status based on shift timings if present and employee was present
            if status == "Present" and shift_obj:
                try:
                    shift_start = shift_obj.start_time
                    shift_end = shift_obj.end_time
                    
                    first_punch_time = first_punch.time()
                    if len(punches) > 1:
                        last_punch_time = last_punch.time()
                    else:
                        last_punch_time = None

                    # Late Login Logic (e.g., > 15 mins grace? defaulting to strict for now or 5 mins)
                    # Adding 10 mins grace for now
                    # Need to combine with dummy date to do arithmetic
                    
                    # Convert to datetime to add timedelta
                    dummy_date = date(2000, 1, 1)
                    shift_start_dt = datetime.combine(dummy_date, shift_start)
                    punch_in_dt = datetime.combine(dummy_date, first_punch_time)
                    
                    late_minutes = 0
                    early_minutes = 0

                    if punch_in_dt > shift_start_dt + timedelta(minutes=15):
                        status = "Late Login"
                        late_minutes = int((punch_in_dt - shift_start_dt).total_seconds() // 60)
                    
                    if last_punch_time:
                         shift_end_dt = datetime.combine(dummy_date, shift_end)
                         punch_out_dt = datetime.combine(dummy_date, last_punch_time)

                         # Handle night shifts
                         if shift_end < shift_start:
                             shift_end_dt += timedelta(days=1)
                         if last_punch_time < first_punch_time:
                             punch_out_dt += timedelta(days=1)
                         
                         if punch_out_dt < shift_end_dt - timedelta(minutes=15):
                             if status == "Late Login":
                                 status = "Late In & Early Out"
                             else:
                                 status = "Early Checkout"
                             early_minutes = int((shift_end_dt - punch_out_dt).total_seconds() // 60)

                    parts = []
                    if late_minutes > 0:
                        parts.append(f"Late: {late_minutes // 60}h {late_minutes % 60}m" if late_minutes >= 60 else f"Late: {late_minutes}m")
                    if early_minutes > 0:
                        parts.append(f"Early: {early_minutes // 60}h {early_minutes % 60}m" if early_minutes >= 60 else f"Early: {early_minutes}m")
                    
                    if parts:
                        late_early_hrs = " | ".join(parts)

                except Exception as e:
                    # Keep as Present if error
                    pass

            report_data.append({
                "date": current_date.strftime("%Y-%m-%d"),
                "employee_id": emp_id,
                "employee_name": emp_info['name'],
                "department": emp_info['department'],
                "department_id": emp_info['department_id'],
                "designation": emp_info['designation'],
                "shift_name": shift_name,
                "shift_timing": shift_timing,
                "check_in": check_in_str,
                "check_out": check_out_str,
                "total_hours": total_hours_str,
                "late_early_hrs": late_early_hrs,
                "status": status
            })

    if request.query_params.get('export') == 'csv':
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv')
        filename = f"Roster_Actual_Report_{month_str}.csv"
        if department_filter:
            filename = f"Roster_Actual_Report_{month_str}_{department_filter}.csv"
            
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow(['Date', 'Employee ID', 'Employee Name', 'Department', 'Designation', 'Allocated Shift', 'Shift Timings', 'Check In', 'Check Out', 'Total Hours', 'Late / Early', 'Status'])

        for row in report_data:
            writer.writerow([
                row['date'],
                row['employee_id'],
                row['employee_name'],
                row['department'],
                row['designation'],
                row['shift_name'],
                row['shift_timing'],
                row['check_in'],
                row['check_out'],
                row['total_hours'],
                row['late_early_hrs'],
                row['status']
            ])
        
        return response

    return Response(report_data)
