import os
import base64
import gridfs
import hashlib
import mimetypes
import requests
from io import BytesIO
from bson import ObjectId
from pymongo import MongoClient
from dotenv import load_dotenv

from django.shortcuts import get_object_or_404
from django.http import JsonResponse, HttpResponse, Http404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from employees.models import Employee
from employees.serializers import EmployeeCreateSerializer
from employees.face_utils import imagefile_to_encoding, compute_md5

from .utils import save_or_update_encoding

load_dotenv()

@api_view(['GET'])
@permission_classes([AllowAny])
def get_all_employees_with_images(request):
    """
    Fetch all employees from Django DB with image previews.
    - First checks the 'HR' MongoDB database for the image.
    - If not found, checks the 'Global' MongoDB database.
    """
    try:
        # 1️⃣ Fetch employees from local Django DB
        employees = Employee.objects.all().order_by("employee_id")
        if not employees.exists():
            return JsonResponse({"message": "No employees found"}, status=404)

        # 2️⃣ Connect to MongoDB & GridFS for both databases
        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        hr_db_name = os.getenv("GLOBAL_DB_NAME_HR", "HR")
        global_db_name = os.getenv("GLOBAL_DB_NAME_GLOBAL", "Global")

        client = MongoClient(mongo_uri)
        fs_hr = gridfs.GridFS(client[hr_db_name])
        fs_global = gridfs.GridFS(client[global_db_name])

        # Department Filtering
        department = request.query_params.get('department')
        employees = Employee.objects.all().order_by("employee_id")

        if department and department != 'All':
            db = client[global_db_name]
            raw_ids = [d.strip() for d in department.split(',')]
            
            # Resolve numeric IDs to names
            from ..models import Department
            numeric_ids = [rid for rid in raw_ids if rid.isdigit()]
            resolved_names = list(Department.objects.filter(id__in=numeric_ids).values_list('name', flat=True))
            
            search_values = raw_ids + resolved_names

            # Find employees in these departments using IDs (dept_code) or names
            query = {
                "$or": [
                    {"department": {"$in": search_values}},
                    {"department_name": {"$in": search_values}}
                ]
            }
            dept_profiles = list(db['backend_diagnostics_profile'].find(query, {"employeeId": 1}))
            dept_emp_ids = [str(p["employeeId"]) for p in dept_profiles]
            
            employees = employees.filter(employee_id__in=dept_emp_ids)

        # 3️⃣ Create SQL Department Name to ID Map
        from ..models import Department
        sql_dept_map = {d.name: d.id for d in Department.objects.all()}

        # 4️⃣ Build response list
        employee_list = []
        
        # Connect to Global Profiles for department data
        db_global = client[global_db_name]
        profiles_col = db_global['backend_diagnostics_profile']
        
        # Pre-fetch all profiles for the current set of employees to avoid N+1
        emp_ids_list = [str(emp.employee_id) for emp in employees]
        profile_map = {str(p["employeeId"]): p for p in profiles_col.find({"employeeId": {"$in": emp_ids_list}})}
        
        # Dept Name Lookup Map (Mongo codes to names)
        departments_col = db_global['backend_diagnostics_Departments']
        mongo_dept_map = {
            d.get('department_code'): d.get('department_name')
            for d in departments_col.find() # Remove is_active filter
        }

        for emp in employees:
            base64_img = None
            
            # Resolve SQL Department ID from Mongo profile data
            profile = profile_map.get(str(emp.employee_id), {})
            dept_code = profile.get("department")
            dept_name = mongo_dept_map.get(dept_code, dept_code)
            sql_dept_id = sql_dept_map.get(dept_name)

            if emp.image_md5:
                file_obj = fs_hr.find_one({"md5": emp.image_md5})
                if not file_obj:  # ⏩ Check Global DB if not found in HR
                    file_obj = fs_global.find_one({"md5": emp.image_md5})

                if file_obj:
                    try:
                        img_bytes = file_obj.read()
                        base64_img = (
                            f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode('utf-8')}"
                        )
                    except Exception:
                        base64_img = None

            employee_list.append({
                "employee_id": emp.employee_id,
                "name": emp.name,
                "is_active": emp.is_active,
                "image_md5": emp.image_md5,
                "department": dept_name,
                "department_id": sql_dept_id, # Return SQL ID
                "created_date": emp.created_date,
                "lastmodified_date": emp.lastmodified_date,
                "image_preview": base64_img,
            })

        # 5️⃣ Return JSON response
        return JsonResponse(employee_list, safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_employee_by_md5(request, image_md5):
    """
    Fetch employee details and image (preview) by image_md5
    """
    try:
        # 1️⃣ Find employee in Django DB
        emp = Employee.objects.filter(image_md5=image_md5).first()
        if not emp:
            return JsonResponse({"error": "No employee found for this MD5"}, status=404)

        # 2️⃣ Connect to MongoDB to fetch image
        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        global_db = os.getenv("GLOBAL_DB_NAME", "HR")
        client = MongoClient(mongo_uri)
        fs = gridfs.GridFS(client[global_db])

        # 3️⃣ Find image file by MD5 hash in GridFS
        file_obj = fs.find_one({"md5": image_md5})
        if not file_obj:
            # Image not found in GridFS — still return employee info
            return JsonResponse({
                "employee_id": emp.employee_id,
                "name": emp.name,
                "is_active": emp.is_active,
                "image_md5": emp.image_md5,
                "image_preview": None,
                "message": "Employee found, but image not found in GridFS"
            }, status=200)

        # 4️⃣ Read image bytes
        img_bytes = file_obj.read()
        base64_img = base64.b64encode(img_bytes).decode('utf-8')

        # 5️⃣ Return employee + base64 preview
        return JsonResponse({
            "employee_id": emp.employee_id,
            "name": emp.name,
            "is_active": emp.is_active,
            "image_md5": emp.image_md5,
            "created_date": emp.created_date,
            "lastmodified_date": emp.lastmodified_date,
            "image_preview": f"data:image/jpeg;base64,{base64_img}",
        }, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['POST'])
def enable_facial_recognition(request, employee_id):
    emp = get_object_or_404(Employee, employee_id=employee_id)
    emp.is_active = True
    emp.save(update_fields=['is_active'])
    return Response({"success": True, "employee_id": emp.employee_id})


@api_view(['POST'])
def disable_facial_recognition(request, employee_id):
    emp = get_object_or_404(Employee, employee_id=employee_id)

    if not emp.current_face_encoding:
        return Response({"error": "No active face encoding found"}, status=400)

    emp.is_active = False
    emp.save(update_fields=['is_active'])
    return Response({"success": True, "employee_id": emp.employee_id})


@api_view(['GET'])
@permission_classes([AllowAny])
def get_all_employee_from_global(request):
    """
    Get ALL employee profiles with department & designation names resolved,
    include profile image URLs, encoding status, and local is_active flag.
    """
    try:
        # ✅ Connect to Global MongoDB
        mongo_uri = os.environ.get("GLOBAL_DB_HOST")
        db_name = os.environ.get("GLOBAL_DB_NAME", "Global")
        client = MongoClient(mongo_uri)
        db = client[db_name]

        profiles_col = db['backend_diagnostics_profile']
        departments_col = db['backend_diagnostics_Departments']
        designations_col = db['backend_diagnostics_Designation']

        # ✅ Fetch all employees from Global DB
        query = {}
        department_filter = request.query_params.get('department')
        
        if department_filter and department_filter != 'All':
            raw_values = [d.strip() for d in department_filter.split(',')]
            
            # Resolve numeric IDs to names
            from ..models import Department
            numeric_ids = [rv for rv in raw_values if rv.isdigit()]
            resolved_names = list(Department.objects.filter(id__in=numeric_ids).values_list('name', flat=True))
            
            search_values = raw_values + resolved_names

            # Resolve department names/codes to Mongo codes
            dept_cursor = departments_col.find({
                "$or": [
                    {"department_name": {"$in": search_values}},
                    {"department_code": {"$in": search_values}}
                ]
            })
            dept_codes = [d.get("department_code") for d in dept_cursor]
            
            # Fallback to search values if no codes found
            if not dept_codes:
                dept_codes = search_values
                
            query['department'] = {"$in": dept_codes}

        global_employees = list(profiles_col.find(query))

        # ✅ Create SQL department map (Name -> ID)
        from ..models import Department
        sql_dept_map = {d.name: d.id for d in Department.objects.all()}

        # ✅ Create department & designation lookup maps
        dept_map = {
            d.get('department_code'): d.get('department_name')
            for d in departments_col.find() # Remove is_active filter
        }
        desig_map = {
            d.get('Designation_code'): d.get('designation')
            for d in designations_col.find({'is_active': True})
        }

        # ✅ Fetch all locally stored employees
        local_employees = Employee.objects.all().values(
            "employee_id", "current_face_encoding", "is_active"
        )

        # Build a dictionary of {employee_id: {has_encoding, is_active}}
        local_employee_map = {
            str(emp["employee_id"]): {
                "has_encoding": bool(emp["current_face_encoding"]),
                "is_active": emp["is_active"]
            }
            for emp in local_employees
        }

        # ✅ Base URL for image serving
        base_url = request.build_absolute_uri('/')[:-1]

        result = []
        for emp in global_employees:
            emp_id = str(emp.get("employeeId"))

            # Determine encoding and active status
            if emp_id in local_employee_map:
                encoding_status = (
                    "Encoded" if local_employee_map[emp_id]["has_encoding"] else "No Encoding"
                )
                is_active = local_employee_map[emp_id]["is_active"]
            else:
                encoding_status = "Not Found Locally"
                is_active = False  # Default for missing local record

            emp_data = {
                "employeeId": emp_id,
                "employeeName": emp.get("employeeName"),
                "email": emp.get("email"),
                "department": dept_map.get(emp.get("department"), emp.get("department")),
                "department_id": sql_dept_map.get(dept_map.get(emp.get("department")), emp.get("department")), # NEW: SQL ID
                "designation": desig_map.get(emp.get("designation"), emp.get("designation")),
                "mobileNumber": emp.get("mobileNumber"),
                "gender": emp.get("gender"),
                "age": emp.get("age"),
                "primaryRole": emp.get("primaryRole"),
                "additionalRoles": emp.get("additionalRoles", []),
                "profileImage": None,
                "encodingStatus": encoding_status,  # ✅ Add encoding check result
                "is_active": is_active,             # ✅ Add local is_active flag
            }

            # ✅ Add profile image URL if available
            profile_img_id = emp.get("profileImage")
            if profile_img_id:
                emp_data["profileImage"] = f"{base_url}/serve-file/{profile_img_id}/"

            result.append(emp_data)

        return JsonResponse(result, safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['POST'])
@permission_classes([AllowAny])
def register_employee(request):
    serializer = EmployeeCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return JsonResponse(serializer.errors, status=400)

    data = serializer.validated_data
    employee_id = data['employee_id']
    name = data.get('name', '')
    image_file = data.get('image')

    if not image_file:
        return JsonResponse({"error": "No image provided"}, status=400)

    # ✅ Compute image MD5 hash
    image_md5 = compute_md5(image_file)

    # ✅ Convert image to face encoding
    encoding, is_real = imagefile_to_encoding(image_file)
    # if not is_real:
    #     return JsonResponse({"error": "Spoofing attempt detected. Registration failed."}, status=400)

    if not encoding:
        return JsonResponse({"error": "No face detected in uploaded image"}, status=400)

    try:
        # ✅ Connect to MongoDB (use your local or cloud URI)
        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        global_db = os.getenv("HR_DB_NAME", "HR")
        client = MongoClient(mongo_uri)
        db = client[global_db]
        fs = gridfs.GridFS(db)

        # ✅ Save image to GridFS
        image_file.seek(0)  # reset pointer
        gridfs_file_id = fs.put(
            image_file.read(),
            filename=f"{employee_id}_{name}.jpg",
            content_type=image_file.content_type,
            employeeId=employee_id,
            md5=image_md5
        )

        # ✅ Save encoding & metadata in Employee model
        emp = save_or_update_encoding(
            employee_id,
            encoding,
            created_by=request.user if request.user.is_authenticated else None,
            name=name,
            image_md5=image_md5
        )

        # ✅ Store reference to GridFS ID in model (if field exists)
        if hasattr(emp, "gridfs_image_id"):
            emp.gridfs_image_id = str(gridfs_file_id)
            emp.save(update_fields=["gridfs_image_id"])

        return JsonResponse({
            "success": True,
            "employee_id": emp.employee_id,
            "name": emp.name,
            "image_md5": emp.image_md5,
            "gridfs_image_id": str(gridfs_file_id),
            "current_face_encoding_count": len(emp.current_face_encoding or []),
            "face_encoding_history_count": len(emp.face_encoding_data_history or [])
        })

    except Exception as e:
        return JsonResponse({"error": f"Failed to save image in GridFS: {str(e)}"}, status=500)


@api_view(['POST'])
@permission_classes([AllowAny])
def encode_employee_face(request, employee_id):
    try:
        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        global_db = os.getenv("GLOBAL_DB_NAME", "Global")
        client = MongoClient(mongo_uri)
        global_profiles = client[global_db]['backend_diagnostics_profile']

        emp = global_profiles.find_one({"employeeId": employee_id})
        if not emp:
            return JsonResponse({"error": f"Employee {employee_id} not found"}, status=404)

        profile_img_id = emp.get("profileImage")
        name = emp.get("employeeName", "")
        if not profile_img_id:
            return JsonResponse({"error": "Profile image missing"}, status=400)

        base_url = request.build_absolute_uri('/')[:-1]
        image_url = f"{base_url}/serve-file/{profile_img_id}/"
        resp = requests.get(image_url, timeout=10)
        resp.raise_for_status()

        img_bytes = BytesIO(resp.content)
        
        # ✅ Compute MD5 for fetched image
        image_md5 = hashlib.md5(resp.content).hexdigest()

        encoding, is_real = imagefile_to_encoding(img_bytes)
        if not is_real:
            return JsonResponse({"error": "Spoofing attempt detected. Encoding failed."}, status=400)

        if not encoding:
            return JsonResponse({"error": "No face detected in image"}, status=422)

        emp_obj = save_or_update_encoding(
            employee_id,
            encoding,
            created_by=request.user if request.user.is_authenticated else None,
            name=name,
            image_md5=image_md5
        )

        return JsonResponse({
            "success": True,
            "employee_id": emp_obj.employee_id,
            "name": emp_obj.name,
            "image_md5": emp_obj.image_md5,
            "is_active": emp_obj.is_active,
            "current_face_encoding": emp_obj.current_face_encoding
        })

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['GET'])
def serve_file(request, file_id):
    try:
        client = MongoClient(os.getenv('GLOBAL_DB_HOST'))
        db = client[os.getenv('GLOBAL_DB_NAME','Global')]
        fs = gridfs.GridFS(db)

        file_id = ObjectId(file_id)
        file = fs.get(file_id)

        # Try to detect MIME type from filename
        content_type, _ = mimetypes.guess_type(file.filename)
        if not content_type:
            content_type = file.content_type or 'application/octet-stream'  # fallback

        response = HttpResponse(file.read(), content_type=content_type)
        response['Content-Disposition'] = f'inline; filename="{file.filename}"'
        return response

    except Exception as e:
        raise Http404(f"File not found or invalid: {str(e)}")
