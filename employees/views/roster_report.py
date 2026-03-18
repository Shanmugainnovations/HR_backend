import csv
import os
import calendar
import pandas as pd
from datetime import date, datetime
from django.http import HttpResponse, JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from pymongo import MongoClient
from ..models import EmployeeShiftSchedule, Employee, Shift

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
    filename = f"roster_{month_str}.csv"
    if all_names and len(all_names) == 1:
        filename = f"roster_{month_str}_{all_names[0]}.csv"
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    
    # Header Row
    date_cols = []
    for d in range(1, last_day + 1):
        day_name = date(year, month, d).strftime("%a")
        date_cols.append(f"{d} ({day_name})")
        
    header = ["S.No", "Employee ID", "Employee Name", "Department"] + date_cols
    writer.writerow(header)

    # Data Rows
    for idx, emp in enumerate(employees_data, 1):
        row = [idx, emp['id'], emp['name'], emp['department']]
        emp_schedules = schedule_map.get(emp['id'], {})
        
        for day in range(1, last_day + 1):
            row.append(emp_schedules.get(day, "")) # Empty string if no shift
        
        writer.writerow(row)

    return response

@api_view(['GET'])
@permission_classes([AllowAny])
def export_roster_xlsx(request):
    month_str = request.query_params.get('month')
    department_filter = request.query_params.get('department')

    if not month_str:
        return HttpResponse("Month parameter (YYYY-MM) is required", status=400)

    try:
        year, month = map(int, month_str.split('-'))
    except ValueError:
        return HttpResponse("Invalid format. Use YYYY-MM", status=400)

    # Resolve Department Info
    from ..models import Department
    sql_depts = list(Department.objects.all())
    sql_dept_map = {d.id: d.name for d in sql_depts}
    all_names = []
    if department_filter and department_filter != 'All':
        raw_ids = [d.strip() for d in department_filter.split(',')]
        for rid in raw_ids:
            if rid.isdigit():
                d_id = int(rid)
                if d_id in sql_dept_map:
                    all_names.append(sql_dept_map[d_id])
            else:
                all_names.append(rid)

    # 1. Fetch Employees from Mongo
    try:
        mongo_uri = os.environ.get("GLOBAL_DB_HOST")
        db_name = os.environ.get("GLOBAL_DB_NAME", "Global")
        client = MongoClient(mongo_uri)
        db = client[db_name]
        profiles_col = db['backend_diagnostics_profile']
        departments_col = db['backend_diagnostics_Departments']
        
        dept_lookup = {d.get('department_code'): d.get('department_name') for d in departments_col.find()}
        
        query = {}
        if all_names:
            resolved_codes = [d.get("department_code") for d in departments_col.find({"department_name": {"$in": all_names}}, {"department_code": 1})]
            search_values = all_names + resolved_codes
            query = {"$or": [{"department": {"$in": search_values}}, {"department_id": {"$in": search_values}}, {"department_name": {"$in": search_values}}]}
        
        profiles = list(profiles_col.find(query))
        employees_data = [{"id": str(p.get("employeeId")), "name": p.get("employeeName"), "department": dept_lookup.get(p.get("department"), p.get("department")) or "Unassigned"} for p in profiles]
        employees_data.sort(key=lambda x: (x['department'], x['name']))
    except Exception as e:
        return HttpResponse(f"Error fetching data: {str(e)}", status=500)

    # 2. Fetch Schedules
    _, last_day = calendar.monthrange(year, month)
    schedules = EmployeeShiftSchedule.objects.filter(date__gte=date(year, month, 1), date__lte=date(year, month, last_day)).select_related('shift', 'employee')
    schedule_map = {}
    for sch in schedules:
        emp_id = sch.employee.employee_id
        if emp_id not in schedule_map: schedule_map[emp_id] = {}
        schedule_map[emp_id][sch.date.day] = sch.shift.name

    # 3. Create DataFrame
    data = []
    for emp in employees_data:
        row = {"Employee ID": emp['id'], "Employee Name": emp['name'], "Department": emp['department']}
        emp_schedules = schedule_map.get(emp['id'], {})
        for day in range(1, last_day + 1):
            day_name = date(year, month, day).strftime("%a")
            col_name = f"{day} ({day_name})"
            row[col_name] = emp_schedules.get(day, "")
        data.append(row)

    df = pd.DataFrame(data)
    
    filename = f"roster_{month_str}.xlsx"
    if all_names and len(all_names) == 1:
        filename = f"roster_{month_str}_{all_names[0]}.xlsx"
    
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    sheet_name = 'Roster'
    if all_names and len(all_names) == 1:
        sheet_name = all_names[0][:31] # Excel limit is 31 chars
        
    with pd.ExcelWriter(response, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
        worksheet = writer.sheets[sheet_name]
        # Styling
        from openpyxl.styles import PatternFill, Font
        from openpyxl.utils import get_column_letter

        sunday_fill = PatternFill(start_color='FFC7CE', end_color='FFC7CE', fill_type='solid') # Light Red
        sunday_font = Font(color='9C0006') # Dark Red text

        for idx, col in enumerate(df.columns):
            # 1. Width adjustment
            max_len = max(df[col].astype(str).map(len).max(), len(col)) + 2
            col_letter = get_column_letter(idx + 1)
            worksheet.column_dimensions[col_letter].width = min(max_len, 30)

            # 2. Sunday Highlighting
            if "(Sun)" in str(col):
                # Header
                worksheet[f"{col_letter}1"].fill = sunday_fill
                worksheet[f"{col_letter}1"].font = sunday_font
                # Data rows (1-indexed, header is 1)
                for row_idx in range(2, len(df) + 2):
                    cell = worksheet.cell(row=row_idx, column=idx + 1)
                    cell.fill = sunday_fill

    return response

@api_view(['POST'])
@permission_classes([AllowAny])
def import_roster_xlsx(request):
    file = request.FILES.get('file')
    month_str = request.data.get('month')
    
    if not file or not month_str:
        return JsonResponse({"error": "File and month are required"}, status=400)

    try:
        year, month = map(int, month_str.split('-'))
        df = pd.read_excel(file)
        
        if "Employee ID" not in df.columns:
            return JsonResponse({"error": "Missing 'Employee ID' column"}, status=400)

        updated_count = 0
        errors = []
        all_shifts = {s.name.upper(): s for s in Shift.objects.all()}
        
        for _, row in df.iterrows():
            emp_id = str(row['Employee ID']).strip()
            if not emp_id or emp_id == 'nan': continue
            
            try:
                employee = Employee.objects.get(employee_id=emp_id)
            except Employee.DoesNotExist:
                errors.append(f"Employee {emp_id} not found")
                continue

            for col in df.columns:
                # Extract Leading Digits (e.g. "1 (Mon)" -> 1)
                import re
                match = re.match(r'^(\d+)', str(col))
                if match:
                    day = int(match.group(1))
                    try:
                        _, last_day = calendar.monthrange(year, month)
                        if day > last_day: continue
                        
                        target_date = date(year, month, day)
                        val = row[col]
                        shift_name = str(val).strip().upper() if pd.notna(val) else ""
                        
                        if not shift_name:
                            EmployeeShiftSchedule.objects.filter(employee=employee, date=target_date).delete()
                        elif shift_name in all_shifts:
                            EmployeeShiftSchedule.objects.update_or_create(
                                employee=employee,
                                date=target_date,
                                defaults={'shift': all_shifts[shift_name]}
                            )
                            updated_count += 1
                        else:
                            errors.append(f"Invalid shift {shift_name} for {emp_id} on day {day}")
                    except Exception as e:
                        errors.append(f"Error on day {day} for {emp_id}: {str(e)}")

        return JsonResponse({"message": f"Updated {updated_count} shifts", "errors": errors[:10]})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
