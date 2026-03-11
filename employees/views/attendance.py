from datetime import datetime
import numpy as np
import os
from pymongo import MongoClient

from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from employees.models import Employee, EmployeeAttendance, SpoofingAttempt
import base64
from employees.face_utils import base64_to_encoding, compare_encodings, imagefile_to_encoding, SpoofingDetectedError
from pyauth.auth import HasRolePermission

from .utils import to_list

@api_view(['POST'])
# @permission_classes([HasRolePermission])
def mark_attendance(request):
    image_file = request.FILES.get('image')
    image_b64 = request.data.get('image')
    employee_id = request.data.get('auth-user-id')
    
    unknown_encoding = []
    is_real = True

    # 1. Extract Encoding & Liveness
    try:
        if image_file:
            unknown_encoding, is_real = imagefile_to_encoding(image_file)
        elif image_b64:
            unknown_encoding, is_real = base64_to_encoding(image_b64)
        else:
            return Response({"error": "Image is required"}, status=400)
    except Exception as e:
        print(f"🚨 DEBUG: Error extracting face: {e}")
        return Response({"error": "Error processing image"}, status=400)

    # 2. Check Face Existence
    if not unknown_encoding:
        return Response({"error": "No face found in image"}, status=400)

    # 3. Find Matching Employee
    employees = Employee.objects.exclude(current_face_encoding__isnull=True)
    matched_employee = None
    candidate_matches = []

    for emp in employees:
        if not emp.is_active:
            continue

        emp_encoding = to_list(emp.current_face_encoding)
        unknown_encoding_np = np.array(unknown_encoding)

        if len(emp_encoding) == 0 or len(unknown_encoding_np) == 0:
            continue

        _, dist = compare_encodings(emp_encoding, unknown_encoding_np)
        
        # Store all comparisons
        candidate_matches.append((dist, emp))

    # Sort candidates by distance (lowest is best match)
    candidate_matches.sort(key=lambda x: x[0])

    # PRINT DEBUG: Top 5 matches
    print("\n--- 🔍 Top Matching Candidates ---")
    for i, (d, e) in enumerate(candidate_matches[:5]):
        print(f"#{i+1}: {e.name} ({e.employee_id}) - Dist: {d:.4f}")
    print("----------------------------------\n")

    if candidate_matches:
        best_distance, matched_employee = candidate_matches[0]
    else:
        best_distance = float('inf')
        matched_employee = None

    # 4. Handle "User Not Found" (Prioritized over Spoofing)
    if not matched_employee or best_distance > 0.5:
        # If user is not found, we don't care if it's a spoof or not (for this specific requirement).
        # We simply return User Not Found.
        return Response({"error": "User Not Found"}, status=404)

    # 5. Handle Spoofing (Only if User Found)
    if not is_real:
        print(f"🚨 DEBUG: Spoofing detected for employee {matched_employee.employee_id}!")
        
        # 🚨 Capture Spoofing Attempt
        spoofed_image_b64 = ""
        try:
            if image_b64:
                spoofed_image_b64 = image_b64
            elif image_file:
                image_file.seek(0)
                file_content = image_file.read()
                spoofed_image_b64 = base64.b64encode(file_content).decode('utf-8')
        except Exception as e:
            print(f"🚨 DEBUG: Error processing spoofed image for storage: {e}")

        try:
            SpoofingAttempt.objects.create(
                employee_id=matched_employee.employee_id,  # Matched ID
                device_id=request.data.get('auth-user-id', 'unknown_device'),
                image=spoofed_image_b64
            )
            print("✅ DEBUG: SpoofingAttempt record created.")
        except Exception as e:
            print(f"🚨 DEBUG: Error creating SpoofingAttempt record: {e}")

        return Response({"error": "Spoofing detected! Real face required."}, status=400)

    # 6. Mark Attendance (Success)
    mode = request.data.get('mode', 'IN')

    att = EmployeeAttendance.objects.create(
        employee_id=matched_employee.employee_id,
        device_id=request.data.get('auth-user-id', 'unknown_device'),
        attendence_type=mode,
        confidence=best_distance
    )

    print(f"✅ ATTENDANCE SUCCESS: {matched_employee.name} (ID: {matched_employee.employee_id}) | Liveness Verified: {is_real}")

    return Response({
        "employee": matched_employee.employee_id,
        "name": matched_employee.name,
        "mode": att.attendence_type,
        "timestamp": att.attendence_time,
        "confidence": best_distance
    }, status=201)


@api_view(['GET'])
@permission_classes([AllowAny])
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
            now = datetime.now()
            from_date = datetime(now.year, now.month, 1)
            to_date = datetime(now.year, now.month + 1, 1) if now.month < 12 else datetime(now.year + 1, 1, 1)
        else:
            from_date = datetime.strptime(from_date, "%Y-%m-%d")
            to_date = datetime.strptime(to_date, "%Y-%m-%d")

        # ---- Fetch Attendance Records ----
        records = EmployeeAttendance.objects.filter(
            attendence_time__gte=from_date,
            attendence_time__lt=to_date
        ).order_by('-attendence_time')

        if not records.exists():
            return Response([], status=200)

        # ---- Mongo Connection ----
        mongo_uri = os.environ.get("GLOBAL_DB_HOST")
        db_name = os.environ.get("GLOBAL_DB_NAME", "Global")
        client = MongoClient(mongo_uri)
        db = client[db_name]

        profiles = db['backend_diagnostics_profile']
        departments = db['backend_diagnostics_Departments']
        designations = db['backend_diagnostics_Designation']

        # ---- SQL Department Map ----
        from employees.models import Department
        sql_dept_map = {d.name: d.id for d in Department.objects.all()}

        # ---- Create Lookup Maps ----
        dept_map = {
            d.get('department_code'): d.get('department_name')
            for d in departments.find() # Remove is_active filter
        }
        desig_map = {
            d.get('Designation_code'): d.get('designation')
            for d in designations.find({'is_active': True})
        }

        # ---- Create Employee Lookup ----
        employee_map = {}
        for emp in profiles.find():
            dept_code = emp.get("department")
            dept_name = dept_map.get(dept_code, dept_code)
            employee_map[emp.get("employeeId")] = {
                "employeeName": emp.get("employeeName"),
                "department": dept_name,
                "department_id": sql_dept_map.get(dept_name, dept_code), # SQL ID if name matches
                "designation": desig_map.get(emp.get("designation"), emp.get("designation")),
            }

        # ---- Combine Attendance + Employee Info ----
        result = []
        department_filter = request.GET.get('department')
        
        allowed_dept_ids = []
        if department_filter and department_filter != 'All':
            raw_ids = [d.strip() for d in department_filter.split(',')]
            # Resolve numeric IDs to names if they exist
            from employees.models import Department
            resolved_names = list(Department.objects.filter(id__in=[id for id in raw_ids if id.isdigit()]).values_list('name', flat=True))
            allowed_dept_ids = raw_ids + resolved_names

        for r in records:
            emp_info = employee_map.get(r.employee_id, {})
            emp_dept_name = emp_info.get("department") # Resolved name
            emp_dept_id = emp_info.get("department_id") # Raw code/ID
            
            # Filter if requested
            if allowed_dept_ids:
                # Match against ID (as string) OR Name to be flexible
                if str(emp_dept_id) not in allowed_dept_ids and emp_dept_name not in allowed_dept_ids:
                    continue

            result.append({
                "employee_id": r.employee_id,
                "employee_name": emp_info.get("employeeName", "Unknown"),
                "department": emp_info.get("department", "N/A"),
                "department_id": emp_info.get("department_id"), # SQL ID or raw code
                "designation": emp_info.get("designation", "N/A"),
                "device_id": r.device_id,
                "attendence_type": r.attendence_type,
                "attendence_time": r.attendence_time,
                "confidence": r.confidence,
            })

        return Response(result, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([AllowAny])  # Or admin permission
def get_spoofing_attempts(request):
    """
    Get all recorded spoofing attempts.
    Query Params:
    - month: int (1-12)
    - year: int (e.g. 2025)
    """
    month = request.GET.get('month')
    year = request.GET.get('year')

    queryset = SpoofingAttempt.objects.all()

    if month and year:
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
            mongo_uri = os.environ.get("GLOBAL_DB_HOST")
            db_name = os.environ.get("GLOBAL_DB_NAME", "Global")
            client = MongoClient(mongo_uri)
            db = client[db_name]
            
            raw_values = [d.strip() for d in department.split(',')]
            
            # Resolve numeric IDs to names
            from employees.models import Department
            numeric_ids = [rv for rv in raw_values if rv.isdigit()]
            resolved_names = list(Department.objects.filter(id__in=numeric_ids).values_list('name', flat=True))
            
            dept_query_values = raw_values + resolved_names
            
            # Resolve department codes from names OR treat them as codes directly
            dept_cursor = db['backend_diagnostics_Departments'].find({
                "$or": [
                    {"department_name": {"$in": dept_query_values}},
                    {"department_code": {"$in": dept_query_values}}
                ]
            })
            dept_codes = [d.get("department_code") for d in dept_cursor]
            
            # If nothing found in mongo, fallback to raw values (might be codes already)
            if not dept_codes:
                dept_codes = dept_query_values

            query = {"department": {"$in": dept_codes}}
            dept_profiles = list(db['backend_diagnostics_profile'].find(query, {"employeeId": 1}))
            dept_emp_ids = [str(p["employeeId"]) for p in dept_profiles]

            queryset = queryset.filter(employee_id__in=dept_emp_ids)

        except Exception as e:
            print(f"Error filtering spoofing reports by department: {e}")

    attempts = queryset.order_by('-timestamp')
    data = []
    for attempt in attempts:
        data.append({
            "id": attempt.id,
            "employee_id": attempt.employee_id,
            "device_id": attempt.device_id,
            "timestamp": attempt.timestamp,
            "image": attempt.image # Base64 string
        })
    return Response(data, status=200)

@api_view(['POST'])
@permission_classes([AllowAny]) # Should be protected in production
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
