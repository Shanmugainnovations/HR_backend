import os
import base64
import gridfs
import hashlib
import mimetypes
import requests
import numpy as np
from io import BytesIO
from bson import ObjectId
from pymongo import MongoClient
from dotenv import load_dotenv
import pandas as pd

from django.shortcuts import get_object_or_404
from django.http import JsonResponse, HttpResponse, Http404
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from employees.models import Employee
from employees.serializers import EmployeeCreateSerializer
from employees.face_utils import imagefile_to_encoding, compute_md5

from .utils import save_or_update_encoding, get_mongo_client

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

        client = get_mongo_client()
        fs_hr = gridfs.GridFS(client[hr_db_name])
        fs_global = gridfs.GridFS(client[global_db_name])

        # Department Filtering
        department = request.query_params.get('department')
        employees = Employee.objects.filter(current_face_encoding__isnull=False).order_by("employee_id")

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
            # Resolve SQL Department ID from Mongo profile data
            profile = profile_map.get(str(emp.employee_id), {})
            dept_code = profile.get("department")
            dept_name = mongo_dept_map.get(dept_code, dept_code)
            sql_dept_id = sql_dept_map.get(dept_name)

            image_preview = None
            if emp.image_md5:
                image_preview = request.build_absolute_uri(f"/_b_a_c_k_e_n_d/HR/employees/image-by-md5/{emp.image_md5}/")

            employee_list.append({
                "employee_id": emp.employee_id,
                "name": emp.name,
                "is_active": emp.is_active,
                "image_md5": emp.image_md5,
                "department": dept_name,
                "department_id": sql_dept_id, # Return SQL ID
                "has_global_profile": str(emp.employee_id) in profile_map,
                "created_date": emp.created_date,
                "lastmodified_date": emp.lastmodified_date,
                "image_preview": image_preview,
            })

        # 5️⃣ Return JSON response
        return JsonResponse(employee_list, safe=False, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([AllowAny])
def serve_employee_image_by_md5(request, image_md5):
    """
    Serve employee image binary directly by MD5 hash with HTTP caching.
    """
    try:
        client = get_mongo_client()
        hr_db_name = os.getenv("GLOBAL_DB_NAME_HR", "HR")
        global_db_name = os.getenv("GLOBAL_DB_NAME_GLOBAL", "Global")

        fs_hr = gridfs.GridFS(client[hr_db_name])
        file_obj = fs_hr.find_one({"md5": image_md5})
        if not file_obj:
            fs_global = gridfs.GridFS(client[global_db_name])
            file_obj = fs_global.find_one({"md5": image_md5})

        if not file_obj:
            raise Http404("Image not found")

        response = HttpResponse(file_obj.read(), content_type="image/jpeg")
        response['Cache-Control'] = 'public, max-age=86400'
        return response
    except Exception as e:
        raise Http404("Image not found")


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
        client = get_mongo_client()
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
def get_employee_detail(request, employee_id):
    """
    Fetch employee details and image (preview) by employee_id.
    - First check local SQL 'Employee' model.
    - If not found, check Global MongoDB profiledb.
    """
    try:
        # 1️⃣ Connect to MongoDB first (needed for images anyway)
        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        hr_db_name = os.getenv("GLOBAL_DB_NAME_HR", "HR")
        global_db_name = os.getenv("GLOBAL_DB_NAME_GLOBAL", "Global")
        client = get_mongo_client()

        # 2️⃣ Find employee in SQL
        emp = Employee.objects.filter(employee_id=employee_id).first()
        
        if emp:
            fs_hr = gridfs.GridFS(client[hr_db_name])
            fs_global = gridfs.GridFS(client[global_db_name])
            base64_img = None
            if emp.image_md5:
                # Find image in HR then Global
                file_obj = fs_hr.find_one({"md5": emp.image_md5})
                if not file_obj:
                    file_obj = fs_global.find_one({"md5": emp.image_md5})
                if file_obj:
                    try:
                        img_bytes = file_obj.read()
                        base64_img = f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode('utf-8')}"
                    except: pass
            
            return JsonResponse({
                "employee_id": emp.employee_id,
                "name": emp.name,
                "is_active": emp.is_active,
                "image_preview": base64_img,
                "is_registered_face": True
            }, status=200)

        # 3️⃣ Not in SQL — Fallback to Global Profile (MongoDB)
        db_global = client[global_db_name]
        profile = db_global['backend_diagnostics_profile'].find_one({"employeeId": employee_id})
        
        if profile:
            base_url = request.build_absolute_uri('/')[:-1]
            profile_img_id = profile.get("profileImage")
            preview_url = None
            if profile_img_id:
                preview_url = f"{base_url}/serve-file/{profile_img_id}/"

            return JsonResponse({
                "employee_id": employee_id,
                "name": profile.get("employeeName", ""),
                "is_active": False,
                "image_preview": preview_url,
                "is_registered_face": False,
                "message": "Found in Global Profile (Face not yet registered in HR)"
            }, status=200)

        return JsonResponse({"error": "Employee not found in local records or global profiles"}, status=404)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


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
        client = get_mongo_client()
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

        # ✅ Fetch only face-registered IDs from SQL
        from employees.models import Employee
        face_registered_ids = set(Employee.objects.filter(current_face_encoding__isnull=False).values_list('employee_id', flat=True))

        global_employees = list(profiles_col.find(query))
        
        # ✅ Filter only those with registered faces
        global_employees = [e for e in global_employees if str(e.get("employeeId")) in face_registered_ids]

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

        # ✅ Fetch all locally stored employees (optimized: exclude heavy face_encoding vector arrays)
        local_employees = Employee.objects.all().values("employee_id", "is_active")

        # Build a dictionary of {employee_id: {has_encoding, is_active}}
        local_employee_map = {
            str(emp["employee_id"]): {
                "has_encoding": str(emp["employee_id"]) in face_registered_ids,
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


MAX_FACE_ENCODINGS = 5
MIN_FACE_ENCODINGS_LENIENT = 2  # minimum usable faces required out of an auto-capture batch
DEDUP_DISTANCE_THRESHOLD = 0.15  # skip a candidate nearly identical to one already kept


def _select_face_frames(images_list, lenient):
    """
    Pure selection step, no DB/GridFS writes: decodes each candidate photo, encodes it, and
    keeps up to MAX_FACE_ENCODINGS frames (skipping near-duplicates when lenient). Shared by
    the preview endpoint (called right after a 5s recording finishes, so the frontend can show
    which frames would be used before the user even hits Register/Update) and the actual
    registration endpoint below.

    Returns (kept, skipped, error):
      kept: list of {"index", "decoded_img", "ext", "encoding"} for the frames selected
      skipped: count of candidate frames that were decoded/tried but not kept
      error: None on success, else a user-facing message and `kept` is []
    """
    kept = []
    skipped = 0

    for idx, raw_image in enumerate(images_list):
        if len(kept) >= MAX_FACE_ENCODINGS:
            break

        try:
            if ';base64,' in raw_image:
                header, base64_str = raw_image.split(';base64,')
                ext = header.split('/')[-1]
            else:
                base64_str = raw_image
                ext = 'jpg'
            decoded_img = base64.b64decode(base64_str)
        except Exception as e:
            if lenient:
                skipped += 1
                continue
            return [], skipped, f"Failed to decode image #{idx + 1}: {str(e)}"

        encoding, is_real = imagefile_to_encoding(decoded_img)
        if not encoding:
            if lenient:
                skipped += 1
                continue
            return [], skipped, f"No face detected in photo #{idx + 1} of {len(images_list)}. Please retake."

        # Skip near-duplicate frames so the kept encodings represent genuinely different
        # angles/moments instead of several near-identical consecutive video frames.
        if lenient and kept:
            enc_arr = np.array(encoding)
            too_similar = any(
                np.linalg.norm(enc_arr - np.array(k['encoding'])) < DEDUP_DISTANCE_THRESHOLD
                for k in kept
            )
            if too_similar:
                skipped += 1
                continue

        kept.append({"index": idx, "decoded_img": decoded_img, "ext": ext, "encoding": encoding})

    if not kept or (lenient and len(kept) < MIN_FACE_ENCODINGS_LENIENT):
        return [], skipped, "Couldn't get enough clear face shots from the recording. Please retry with steady framing and good lighting."

    return kept, skipped, None


@api_view(['POST'])
@permission_classes([AllowAny])
def preview_face_frames(request):
    """
    Given a batch of candidate photos (e.g. frames auto-sampled from a 5s recording), returns
    which ones would be selected for registration - without saving anything. Lets the frontend
    show the picked photos right after the recording finishes, before the user submits.
    """
    images_list = request.data.get('images')
    if not isinstance(images_list, list) or len(images_list) == 0:
        return JsonResponse({"error": "images is required"}, status=400)

    images_list = [img for img in images_list if img]
    if not images_list:
        return JsonResponse({"error": "No images provided"}, status=400)

    lenient = len(images_list) > MAX_FACE_ENCODINGS
    kept, skipped, error = _select_face_frames(images_list, lenient)
    if error:
        return JsonResponse({"error": error}, status=400)

    return JsonResponse({
        "success": True,
        "selected_frame_indices": [item["index"] for item in kept],
        "frames_skipped": skipped
    })


def _register_employee_multi(request, images_list):
    """
    Registration path for multiple photos captured at once (e.g. 3 manual angle shots,
    or ~7-8 frames auto-sampled from a 5-second webcam "recording" on the frontend).
    Each photo is separately encoded; all valid encodings are stored so 1:N matching
    (see get_optimized_encodings/match_face_1_to_n) can compare against every angle.
    Leaves the single-image `register_employee` path below completely untouched.
    """
    employee_id = request.data.get('employee_id')
    name = request.data.get('name', '')

    if not employee_id or not employee_id.strip():
        return JsonResponse({"error": "employee_id is required"}, status=400)

    images_list = [img for img in images_list if img]
    if not images_list:
        return JsonResponse({"error": "No images provided"}, status=400)

    # The manual 3-click flow sends exactly MAX_FACE_ENCODINGS frames, each already
    # confirmed by the user via "Use This Photo" - keep that strict (any failure rejects
    # the whole batch, as before). An auto-captured 5s recording sends more candidate
    # frames than that, and can't guarantee every single frame has a clean face (blinks,
    # motion blur) - so we're lenient there: keep the best successful ones, skip the rest.
    lenient = len(images_list) > MAX_FACE_ENCODINGS

    kept, skipped, error = _select_face_frames(images_list, lenient)
    if error:
        return JsonResponse({"error": error}, status=400)

    try:
        global_db = os.getenv("HR_DB_NAME", "HR")
        client = get_mongo_client()
        db = client[global_db]
        fs = gridfs.GridFS(db)
    except Exception as e:
        return JsonResponse({"error": f"Failed to connect to image storage: {str(e)}"}, status=500)

    encodings = []
    gridfs_ids = []
    selected_indices = []
    primary_md5 = None

    for item in kept:
        image_md5 = hashlib.md5(item["decoded_img"]).hexdigest()
        gridfs_file_id = fs.put(
            item["decoded_img"],
            filename=f"{employee_id}_{name}_{item['index'] + 1}.{item['ext']}",
            content_type=f"image/{item['ext']}",
            employeeId=employee_id,
            md5=image_md5
        )

        encodings.append(item["encoding"])
        gridfs_ids.append(str(gridfs_file_id))
        selected_indices.append(item["index"])
        if primary_md5 is None:
            primary_md5 = image_md5

    try:
        emp = save_or_update_encoding(
            employee_id,
            encodings[0],
            created_by=request.user if request.user.is_authenticated else None,
            name=name,
            image_md5=primary_md5,
            encoding_list=encodings
        )
    except Exception as e:
        return JsonResponse({"error": f"Failed to save encodings: {str(e)}"}, status=500)

    return JsonResponse({
        "success": True,
        "employee_id": emp.employee_id,
        "name": emp.name,
        "image_md5": emp.image_md5,
        "gridfs_image_ids": gridfs_ids,
        "encodings_saved": len(emp.face_encodings or []),
        "frames_skipped": skipped,
        # Position of each kept frame within the submitted `images` array, so the frontend
        # can show exactly which photos were used out of everything it sent (e.g. which
        # frames out of a 5s recording were actually picked for encoding).
        "selected_frame_indices": selected_indices
    })


@api_view(['POST'])
@permission_classes([AllowAny])
def register_employee(request):
    # ✅ Multi-photo path: if the frontend sends an `images` array (up to 3 angles),
    # handle it separately and leave the original single-`image` flow below untouched.
    images_list = request.data.get('images')
    if isinstance(images_list, list) and len(images_list) > 0:
        return _register_employee_multi(request, images_list)

    serializer = EmployeeCreateSerializer(data=request.data)
    if not serializer.is_valid():
        return JsonResponse(serializer.errors, status=400)

    data = serializer.validated_data
    employee_id = data['employee_id']
    name = data.get('name', '')
    image_file = data.get('image')

    if not image_file:
        # Sometimes DRF drops the image from validated_data if there are parsing edge cases.
        # Check raw request data just in case.
        raw_image = request.data.get('image')
        if not raw_image:
            return JsonResponse({"error": "No image provided"}, status=400)
        
        # Manually decode raw_image to a ContentFile
        import base64
        from django.core.files.base import ContentFile
        import uuid
        try:
            if ';base64,' in raw_image:
                header, base64_str = raw_image.split(';base64,')
                ext = header.split('/')[-1]
            else:
                base64_str = raw_image
                ext = 'jpg'
            
            decoded_img = base64.b64decode(base64_str)
            image_file = ContentFile(decoded_img, name=f"{uuid.uuid4().hex}.{ext}")
        except Exception as e:
            return JsonResponse({"error": f"Failed to decode base64 image: {str(e)}"}, status=400)

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
        client = get_mongo_client()
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
        client = get_mongo_client()
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
        client = get_mongo_client()
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

@api_view(['GET'])
@permission_classes([AllowAny])
def export_employees_xls(request):
    """
    Export all employees with face recognition status, global profile status, 
    and department info to an Excel file.
    """
    try:
        # 1️⃣ Fetch all employees
        employees = Employee.objects.all().order_by("employee_id")
        
        # 2️⃣ Connect to Global MongoDB for profiles and departments
        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        global_db_name = os.getenv("GLOBAL_DB_NAME_GLOBAL", "Global")
        client = get_mongo_client()
        db_global = client[global_db_name]
        
        # Pre-fetch profiles and departments
        emp_ids = [str(emp.employee_id) for emp in employees]
        profiles = {str(p["employeeId"]): p for p in db_global['backend_diagnostics_profile'].find({"employeeId": {"$in": emp_ids}})}
        
        mongo_dept_map = {
            d.get('department_code'): d.get('department_name')
            for d in db_global['backend_diagnostics_Departments'].find()
        }

        # 3️⃣ Build list for Pandas
        data_list = []
        for emp in employees:
            profile = profiles.get(str(emp.employee_id), {})
            dept_code = profile.get("department")
            dept_name = mongo_dept_map.get(dept_code, dept_code or "Unassigned")
            
            data_list.append({
                "Employee ID": emp.employee_id,
                "Name": emp.name,
                "Department": dept_name,
                "Face Registered": "Yes" if emp.current_face_encoding else "No",
                "Face Enabled": "Active" if emp.is_active else "Disabled",
                "Global Profile": "Available" if str(emp.employee_id) in profiles else "Not Found",
                "Created Date": emp.created_date.strftime("%d/%m/%Y %H:%M") if emp.created_date else "",
                "Last Modified": emp.lastmodified_date.strftime("%d/%m/%Y %H:%M") if emp.lastmodified_date else "",
            })

        # 4️⃣ Create DataFrame and Excel
        df = pd.DataFrame(data_list)
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Employees')
        
        output.seek(0)
        
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="Employee_List.xlsx"'
        return response

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

