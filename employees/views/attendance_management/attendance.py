from datetime import datetime, timedelta
import numpy as np
import os
import pytz
from pymongo import MongoClient
import gridfs

IST = pytz.timezone('Asia/Kolkata')

from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from employees.permissions import HasRoleAndDataPermission
from rest_framework.response import Response

from employees.models import Employee, EmployeeAttendance, SpoofingAttempt
import base64
from pyauth.auth import HasRolePermission

from employees.views.common.utils import to_list, get_mongo_client

# --- Cache Stub (Face recognition disabled) ---
_ENCODING_CACHE = {
    'matrix': np.empty((0, 128)),
    'employees': [],
    'last_updated': None
}

def get_optimized_encodings(force_refresh=False):
    """Face recognition removed - returns empty matrix."""
    return _ENCODING_CACHE['matrix'], _ENCODING_CACHE['employees']

def _save_attendance_record(employee_id, device_id, mode, confidence):
    """
    Internal helper to save attendance data into the database.
    """
    return EmployeeAttendance.objects.create(
        employee_id=employee_id,
        device_id=device_id,
        attendence_type=mode,
        confidence=confidence
    )

@api_view(['POST'])
@permission_classes([AllowAny])
def verify_face(request):
    """Face recognition verification has been disabled."""
    return Response({"error": "Face verification has been disabled."}, status=400)

@api_view(['POST'])
@permission_classes([AllowAny])
def mark_attendance(request):
    """Face attendance marking has been disabled."""
    return Response({"error": "Face attendance has been disabled."}, status=400)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def attendance_report_with_employee_details(request):
    """
    Get attendance records filtered by date and merged with employee details.
    Example: /api/attendance-report/?from_date=2025-10-01&to_date=2025-10-14
    """
    try:
        # ---- Date Filtering ----
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')

        if not from_date or not to_date:
            from employees.views.common.utils import get_current_active_cycle
            _, from_str, to_str, _ = get_current_active_cycle()
            from_date = datetime.strptime(from_str, "%Y-%m-%d")
            to_date = datetime.strptime(to_str, "%Y-%m-%d") + timedelta(days=1)
        else:
            from_date = datetime.strptime(from_date, "%Y-%m-%d")
            to_date = datetime.strptime(to_date, "%Y-%m-%d") + timedelta(days=1)

        # ---- Mongo Connection ----
        db_name = os.environ.get("GLOBAL_DB_NAME", "Global")
        client = get_mongo_client()
        db = client[db_name]

        profiles = db['backend_diagnostics_profile']

        # ---- Fetch Attendance Records (Fast Direct Mongo Query) ----
        # Fetch from previous day to correctly pair night shifts
        from_date_ext = from_date - timedelta(days=1)
        records = list(db['employees_employeeattendance'].find(
            {'attendence_time': {'$gte': from_date_ext, '$lt': to_date}},
            {'_id': 0, 'attendence_id': 1, 'employee_id': 1, 'attendence_time': 1, 'attendence_type': 1, 'device_id': 1}
        ).sort([('employee_id', 1), ('attendence_time', 1)]))

        if not records:
            return Response([], status=200)

        # ---- SQL Department Map ----
        from employees.models import Department
        sql_dept_map = {d.name: d.id for d in Department.objects.all()}

        # ---- Cached Lookup Maps (Fast in-memory) ----
        from employees.views.common.utils import get_cached_reference_maps, get_inactive_employee_ids
        dept_map, desig_map, _ = get_cached_reference_maps()
        inactive_ids = get_inactive_employee_ids()

        # ---- Department Filtering Resolution ----
        department_filter = request.GET.get('department')
        from employees.views.common.utils import resolve_department_filter
        dept_ctx = resolve_department_filter(department_filter)
        profile_query = dept_ctx['mongo_query']

        # ---- Fetch Employee Lookup ----
        employee_map = {}

        # Fetch matching profiles from Mongo with projection
        all_profiles = list(profiles.find(profile_query, {'_id': 0, 'employeeId': 1, 'employeeName': 1, 'department': 1, 'designation': 1}))
        for emp in all_profiles:
            emp_id = str(emp.get("employeeId"))
            if emp_id in inactive_ids:
                continue
                
            dept_code = emp.get("department")
            dept_name = dept_map.get(dept_code, dept_code)
            employee_map[emp_id] = {
                "employeeName": emp.get("employeeName"),
                "department": dept_name,
                "department_id": sql_dept_map.get(dept_name, dept_code),
                "designation": desig_map.get(emp.get("designation"), emp.get("designation")),
            }
            
        # Fallback for SQL registered employees missing from Global DB
        if not dept_ctx['is_filtered'] or "Unassigned" in dept_ctx['target_terms']:
            registered_sql_emps = Employee.objects.all()
            for sql_emp in registered_sql_emps:
                emp_id_str = str(sql_emp.employee_id)
                if emp_id_str in inactive_ids:
                    continue
                if emp_id_str not in employee_map:
                    employee_map[emp_id_str] = {
                        "employeeName": sql_emp.name,
                        "department": "Unassigned",
                        "department_id": None,
                        "designation": "Unassigned"
                    }

        # ---- Prepare Result ----
        result = []

        # Date range for iteration (to_date was already +1 day)
        report_dates = []
        curr = from_date
        while curr < to_date:
            report_dates.append(curr.date())
            curr += timedelta(days=1)

        # Group actual records by (employee_id, date) with Shift Date Logic
        records_by_emp_day = {}
        
        current_emp_id = None
        current_shift_date = None
        last_in_time = None
        
        from datetime import time
        noon_time = time(12, 0)
        
        for r in records:
            raw_time = r.get('attendence_time')
            if not raw_time:
                continue
            ist_time = raw_time.astimezone(IST) if hasattr(raw_time, 'astimezone') else to_ist(raw_time)
            if not ist_time:
                continue
            punch_date = ist_time.date()
            
            r_eid = str(r.get('employee_id', ''))
            if current_emp_id != r_eid:
                current_emp_id = r_eid
                current_shift_date = None
                last_in_time = None
                
            punch_type = r.get('attendence_type')
            assigned_date = punch_date
            
            if punch_type == 'IN':
                current_shift_date = punch_date
                last_in_time = ist_time
                assigned_date = current_shift_date
            elif punch_type == 'OUT':
                if current_shift_date and last_in_time:
                    if (ist_time - last_in_time).total_seconds() <= 16 * 3600:
                        assigned_date = current_shift_date
                    else:
                        if ist_time.time() < noon_time:
                            assigned_date = punch_date - timedelta(days=1)
                else:
                    if ist_time.time() < noon_time:
                        assigned_date = punch_date - timedelta(days=1)
            
            key = (r_eid, assigned_date)
            if key not in records_by_emp_day:
                records_by_emp_day[key] = []
            
            records_by_emp_day[key].append({
                'attendence_id': r.get('attendence_id'),
                'attendence_time': ist_time,
                'attendence_type': punch_type,
                'device_id': r.get('device_id'),
                'employee_id': r_eid
            })

        # Iterate over ALL employees and ALL dates
        # Sorting by name for consistency
        sorted_emp_ids = sorted(employee_map.keys(), key=lambda eid: employee_map[eid]['employeeName'] or "")

        for emp_id in sorted_emp_ids:
            emp_info = employee_map[emp_id]
            # (Additional in-loop filter not needed as employee_map is already filtered)

            for d in report_dates:
                key = (emp_id, d)
                day_records = records_by_emp_day.get(key, [])
                
                if day_records:
                    for r in day_records:
                        result.append({
                            "employee_id": emp_id,
                            "employee_name": emp_info.get("employeeName", "Unknown"),
                            "department": emp_info.get("department", "N/A"),
                            "department_id": emp_info.get("department_id"),
                            "designation": emp_info.get("designation", "N/A"),
                            "device_id": r.get("device_id") if isinstance(r, dict) else getattr(r, 'device_id', 'N/A'),
                            "attendence_type": r.get("attendence_type") if isinstance(r, dict) else getattr(r, 'attendence_type', ''),
                            "attendence_time": r.get("attendence_time") if isinstance(r, dict) else getattr(r, 'attendence_time', None),
                            "confidence": r.get("confidence", 100) if isinstance(r, dict) else getattr(r, 'confidence', 100),
                        })
                else:
                    # No records for this employee on this day -> Add placeholder
                    # Use start of day as placeholder time (localized to IST)
                    placeholder_time = IST.localize(datetime.combine(d, datetime.min.time()))
                    result.append({
                        "employee_id": emp_id,
                        "employee_name": emp_info.get("employeeName", "Unknown"),
                        "department": emp_info.get("department", "N/A"),
                        "department_id": emp_info.get("department_id"),
                        "designation": emp_info.get("designation", "N/A"),
                        "device_id": "N/A",
                        "attendence_type": "ABSENT",
                        "attendence_time": placeholder_time,
                        "confidence": 0,
                    })

        # ---- Export Support ----
        export_mode = request.GET.get('export')
        if export_mode in ['xlsx', 'csv', 'detailed_xlsx']:
            import pandas as pd
            from django.http import HttpResponse

            if export_mode == 'detailed_xlsx':
                from openpyxl import Workbook
                from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
                
                wb = Workbook()
                ws = wb.active
                ws.title = "Detailed Attendance"
                
                # Header Styling
                header_font = Font(bold=True, color="000000")
                header_fill = PatternFill(start_color="e2e8f0", end_color="e2e8f0", fill_type="solid")
                alignment_center = Alignment(horizontal="center", vertical="center")
                thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))

                # Prepare the Matrix Headers
                base_cols = ['S.No', 'Employee ID', 'Employee Name', 'Department', 'Designation']
                # Row 1: Employee info headers (merged vertically) + Dates (merged horizontally 3 cols each)
                # Row 2: Empty under info headers + In/Out/Total under dates
                
                for i, col_name in enumerate(base_cols, start=1):
                    ws.cell(row=1, column=i, value=col_name).font = header_font
                    ws.cell(row=1, column=i).fill = header_fill
                    ws.cell(row=1, column=i).alignment = alignment_center
                    ws.cell(row=1, column=i).border = thin_border
                    ws.merge_cells(start_row=1, start_column=i, end_row=2, end_column=i)

                curr_col = len(base_cols) + 1
                for d in report_dates:
                    date_str = d.strftime('%d/%m/%Y')
                    ws.cell(row=1, column=curr_col, value=date_str).font = header_font
                    ws.cell(row=1, column=curr_col).fill = header_fill
                    ws.cell(row=1, column=curr_col).alignment = alignment_center
                    ws.cell(row=1, column=curr_col).border = thin_border
                    ws.merge_cells(start_row=1, start_column=curr_col, end_row=1, end_column=curr_col + 2)
                    
                    # Row 2 headers
                    for sub_idx, sub_name in enumerate(['In', 'Out', 'Total']):
                        c = curr_col + sub_idx
                        ws.cell(row=2, column=c, value=sub_name).font = header_font
                        ws.cell(row=2, column=c).fill = header_fill
                        ws.cell(row=2, column=c).alignment = alignment_center
                        ws.cell(row=2, column=c).border = thin_border
                    
                    curr_col += 3

                # Data rows
                # Regroup result data by employee and date
                data_map = {} # (emp_id, date) -> {in, out, total}
                # result is a list of all raw punch/absent recs
                
                # To calculate in/out/total, let's group pulses in result
                for r in result:
                    eid = r.get('employee_id')
                    dt_obj = pd.to_datetime(r.get('attendence_time'))
                    d_key = dt_obj.date()
                    if (eid, d_key) not in data_map:
                        data_map[(eid, d_key)] = {'in': None, 'out': None, 'type': r.get('attendence_type')}
                    
                    entry = data_map[(eid, d_key)]
                    p_type = r.get('attendence_type')
                    if p_type == 'IN':
                        if not entry['in'] or dt_obj < pd.to_datetime(entry['in']):
                            entry['in'] = r.get('attendence_time')
                    elif p_type == 'OUT':
                        if not entry['out'] or dt_obj > pd.to_datetime(entry['out']):
                            entry['out'] = r.get('attendence_time')

                # Write employees (sorted)
                sorted_ids = sorted(employee_map.keys())
                row_idx = 3
                for s_idx, eid in enumerate(sorted_ids, 1):
                    info = employee_map[eid]
                    ws.cell(row=row_idx, column=1, value=s_idx).border = thin_border
                    ws.cell(row=row_idx, column=2, value=eid).border = thin_border
                    ws.cell(row=row_idx, column=3, value=info.get('employeeName', 'Unknown')).border = thin_border
                    ws.cell(row=row_idx, column=4, value=info.get('department', 'N/A')).border = thin_border
                    ws.cell(row=row_idx, column=5, value=info.get('designation', 'N/A')).border = thin_border
                    
                    c_idx = 6
                    for d in report_dates:
                        entry = data_map.get((eid, d), {})
                        in_t = "-"
                        out_t = "-"
                        total_h = 0
                        
                        if entry.get('in'):
                            in_t = pd.to_datetime(entry['in']).strftime('%H:%M:%S')
                        if entry.get('out'):
                            out_t = pd.to_datetime(entry['out']).strftime('%H:%M:%S')
                        
                        if entry.get('in') and entry.get('out'):
                            # Calculate hours (Gross)
                            diff = pd.to_datetime(entry['out']) - pd.to_datetime(entry['in'])
                            total_h = round(diff.total_seconds() / 3600, 2)
                            if total_h < 0: total_h = 0
                        
                        ws.cell(row=row_idx, column=c_idx, value=in_t).border = thin_border
                        ws.cell(row=row_idx, column=c_idx+1, value=out_t).border = thin_border
                        ws.cell(row=row_idx, column=c_idx+2, value=total_h).border = thin_border
                        c_idx += 3
                    
                    row_idx += 1

                # Final response
                response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                response['Content-Disposition'] = 'attachment; filename="Detailed_Attendance_Report.xlsx"'
                wb.save(response)
                return response

            # Flat Export 
            df = pd.DataFrame(result)
            if not df.empty:
                # Add Day, Month, Year
                df['Timestamp_obj'] = pd.to_datetime(df['attendence_time'])
                df['Day'] = df['Timestamp_obj'].dt.day
                df['Month'] = df['Timestamp_obj'].dt.month
                df['Year'] = df['Timestamp_obj'].dt.year
                
                df = df[['employee_id', 'employee_name', 'department', 'designation', 'Day', 'Month', 'Year', 'attendence_type', 'attendence_time']]
                df.columns = ['Employee ID', 'Name', 'Department', 'Designation', 'Day', 'Month', 'Year', 'Punch Type', 'Timestamp']
                df['Timestamp'] = pd.to_datetime(df['Timestamp']).dt.strftime('%d/%m/%Y %H:%M:%S')
                df.loc[df['Punch Type'] == 'ABSENT', 'Timestamp'] = '-'

            if export_mode == 'xlsx':
                response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                response['Content-Disposition'] = r'attachment; filename="Attendance_Report.xlsx"'
                df.to_excel(response, index=False, engine='openpyxl')
                return response
            else:
                response = HttpResponse(content_type='text/csv')
                response['Content-Disposition'] = r'attachment; filename="Attendance_Report.csv"'
                df.to_csv(response, index=False)
                return response

        return Response(result, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)





@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_spoofing_attempts(request):
    """
    Get all recorded spoofing attempts.
    Query Params:
    - month: int (1-12)
    - year: int (e.g. 2025)
    """
    month = request.GET.get('month')
    year = request.GET.get('year')
    from_date_str = request.GET.get('from_date')
    to_date_str = request.GET.get('to_date')

    queryset = SpoofingAttempt.objects.all()

    if from_date_str and to_date_str:
        try:
            start_date = datetime.strptime(from_date_str, "%Y-%m-%d")
            # For 'to_date', we want to include the entire day, so we go to the start of the next day
            end_date_inclusive = datetime.strptime(to_date_str, "%Y-%m-%d")
            end_date = end_date_inclusive + timedelta(days=1)
            queryset = queryset.filter(timestamp__gte=start_date, timestamp__lt=end_date)
        except (ValueError, TypeError):
            pass
    elif month and year:
        try:
            m = int(month)
            y = int(year)
            start_date = datetime(y, m, 1)
            if m == 12:
                end_date = datetime(y + 1, 1, 1)
            else:
                end_date = datetime(y, m + 1, 1)
            
            queryset = queryset.filter(timestamp__gte=start_date, timestamp__lt=end_date)
        except (ValueError, TypeError):
            pass # Invalid month/year, return all


    department = request.GET.get('department')
    if department and department != 'All':
        try:
            from employees.views.common.utils import resolve_department_filter
            dept_ctx = resolve_department_filter(department)
            dept_emp_ids = dept_ctx['matching_employee_ids'] or set()
            queryset = queryset.filter(employee_id__in=dept_emp_ids)
        except Exception as e:
            print(f"Error filtering spoofing reports by department: {e}")

    attempts = list(queryset.order_by('-timestamp')[:200])
    data = []
    for attempt in attempts:
        data.append({
            "id": attempt.id,
            "employee_id": attempt.employee_id,
            "device_id": attempt.device_id,
            "timestamp": attempt.timestamp.astimezone(IST) if attempt.timestamp else None,
            "image": attempt.image # Base64 string
        })
    return Response(data, status=200)

@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def delete_spoofing_attempts(request):
    """
    Delete spoofing attempts by ID.
    Body: { "ids": [1, 2, 3] } or { "ids": "all", "month": 10, "year": 2025 }
    """
    ids = request.data.get('ids')
    
    if ids == "all":
        # Delete all or filtered all
        # (Optional: Add filtering logic for "delete all in this month" if needed)
        # For now, simplistic "delete selected" vs "delete all" logic based on frontend
        # If user wants "delete all in current filter", frontend sends list of all IDs or we handle filter params here.
        # Let's support list of IDs for safety usually.
        # If the user sends "all", we delete EVERYTHING? That's dangerous. 
        # Better to delete everything matching the current filter if filter params provided?
        # Let's stick to list of IDs for explicit deletion unless requested otherwise.
        # Re-reading request: "table type select all and delete" usually implies client-side select all -> send all IDs.
        pass

    if not ids or not isinstance(ids, list):
         return Response({"error": "Invalid IDs provided"}, status=400)

    try:
        SpoofingAttempt.objects.filter(id__in=ids).delete()
        return Response({"message": "Deleted successfully"}, status=200)
    except Exception as e:
        return Response({"error": str(e)}, status=500)
