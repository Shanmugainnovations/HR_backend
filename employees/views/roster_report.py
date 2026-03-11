import csv
import os
import calendar
from datetime import date
from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from pymongo import MongoClient
from ..models import EmployeeShiftSchedule

@api_view(['GET'])
@permission_classes([AllowAny])
def export_roster_csv(request):
    month_str = request.query_params.get('month')
    department_filter = request.query_params.get('department') # Optional (IDs)

    if not month_str:
        return HttpResponse("Month parameter (YYYY-MM) is required", status=400)

    try:
        year, month = map(int, month_str.split('-'))
    except ValueError:
        return HttpResponse("Invalid format. Use YYYY-MM", status=400)

    # Resolve Department Filter (handle numeric IDs from frontend)
    all_names = []
    codes = []
    raw_ids = []
    
    from ..models import Department
    sql_depts = list(Department.objects.all())
    sql_dept_map = {d.id: d.name for d in sql_depts}

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
        
        # Create department lookup map
        dept_map = {
            d.get('department_code'): d.get('department_name')
            for d in departments_col.find() # Removed is_active filter
        }

        # Resolve names to codes
        if all_names:
            resolved_codes = list(departments_col.find(
                {"department_name": {"$in": all_names}},
                {"department_code": 1}
            ))
            codes = [c.get("department_code") for c in resolved_codes]

        search_values = all_names + codes + raw_ids

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

        employees_data = []
        for p in profiles:
            emp_id = str(p.get("employeeId"))
            dept_code = p.get("department") # This is the ID/Code
            
            employees_data.append({
                "id": emp_id,
                "name": p.get("employeeName"),
                "department": dept_map.get(dept_code, dept_code) or "Unassigned"
            })

        # Sort employees by department then name
        employees_data.sort(key=lambda x: (x['department'], x['name']))

    except Exception as e:
        return HttpResponse(f"Error fetching employee data: {str(e)}", status=500)

    # 2. Fetch Shift Schedules for the month
    _, last_day = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)

    schedules = EmployeeShiftSchedule.objects.filter(
        date__gte=start_date, 
        date__lte=end_date
    ).select_related('shift', 'employee')

    # Organize schedules: {emp_id: {day: shift_name}}
    schedule_map = {}
    for sch in schedules:
        emp_id = sch.employee.employee_id
        day = sch.date.day
        if emp_id not in schedule_map:
            schedule_map[emp_id] = {}
        
        # Format: ShiftName (HH:MM-HH:MM)
        start_str = sch.shift.start_time.strftime("%H:%M")
        end_str = sch.shift.end_time.strftime("%H:%M")
        schedule_map[emp_id][day] = f"{sch.shift.name} ({start_str}-{end_str})"

    # 3. Generate CSV
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="roster_{month_str}.csv"'

    writer = csv.writer(response)
    
    # Header Row
    header = ["S.No", "Employee ID", "Employee Name", "Department"] + [str(d) for d in range(1, last_day + 1)]
    writer.writerow(header)

    # Data Rows
    for idx, emp in enumerate(employees_data, 1):
        row = [idx, emp['id'], emp['name'], emp['department']]
        emp_schedules = schedule_map.get(emp['id'], {})
        
        for day in range(1, last_day + 1):
            row.append(emp_schedules.get(day, "")) # Empty string if no shift
        
        writer.writerow(row)

    return response
