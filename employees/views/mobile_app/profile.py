import os
import json
import logging
import mimetypes
from datetime import datetime, date
from bson import ObjectId
from pymongo import MongoClient
import gridfs
from gridfs import GridFS

from django.http import HttpResponse, Http404
from django.contrib.auth.hashers import make_password, check_password, identify_hasher
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from employees.decorators import token_required
from employees.views.common.utils import get_mongo_client
from employees.models import Employee, EmployeeShiftSchedule

logger = logging.getLogger(__name__)


def _sanitize_doc(doc):
    """Sanitizes Mongo document converting ObjectIds, datetimes and binary data."""
    if not doc:
        return {}
    cleaned = {}
    for k, v in doc.items():
        if k in ['face_encoding', 'current_face_encoding', 'face_encodings', 'face_encoding_data_history']:
            continue
        if isinstance(v, ObjectId):
            cleaned[k] = str(v)
        elif isinstance(v, (datetime, date)):
            cleaned[k] = v.strftime('%Y-%m-%d %H:%M:%S') if isinstance(v, datetime) else v.strftime('%Y-%m-%d')
        elif isinstance(v, dict):
            cleaned[k] = _sanitize_doc(v)
        elif isinstance(v, list):
            cleaned[k] = [_sanitize_doc(x) if isinstance(x, dict) else str(x) if isinstance(x, ObjectId) else x for x in v]
        else:
            cleaned[k] = v
    return cleaned


def _load_reference_maps(db):
    """Loads readable names for departments, designations, and roles."""
    desigs = {}
    try:
        for doc in db['backend_diagnostics_Designation'].find({}, {'Designation_code': 1, 'designation_code': 1, 'designation': 1, '_id': 0}):
            code = doc.get('Designation_code') or doc.get('designation_code')
            name = doc.get('designation')
            if code and name:
                desigs[code] = name
    except Exception as e:
        logger.warning(f"Error loading designations: {e}")

    depts = {}
    try:
        for doc in db['backend_diagnostics_Departments'].find({}, {'department_code': 1, 'department_name': 1, '_id': 0}):
            code = doc.get('department_code')
            name = doc.get('department_name')
            if code and name:
                depts[code] = name
    except Exception as e:
        logger.warning(f"Error loading departments: {e}")

    roles = {}
    try:
        for doc in db['backend_diagnostics_admin_groups'].find({}, {'role_code': 1, 'role_name': 1, '_id': 0}):
            code = doc.get('role_code')
            name = doc.get('role_name')
            if code and name:
                roles[code] = name
    except Exception as e:
        logger.warning(f"Error loading roles: {e}")

    return {'designations': desigs, 'departments': depts, 'roles': roles}


@api_view(['GET'])
@permission_classes([AllowAny])
def get_full_employee_profile(request):
    """
    Mobile & Web API: Fetches complete employee profile details matching employee_id
    from Global backend_diagnostics_profile with reference mapping and photo URL.
    """
    # Extract employee_id from header token, query param, or payload
    emp_id = None
    auth_header = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION')
    if auth_header:
        parts = auth_header.split()
        token = parts[1] if len(parts) == 2 else parts[0]
        try:
            from employees.token_utils import decode_employee_token
            payload = decode_employee_token(token)
            if payload:
                emp_id = payload.get('aud') or payload.get('employee_id') or payload.get('employeeId') or payload.get('sub')
        except Exception:
            pass

    if not emp_id:
        emp_id = request.GET.get('employee_id') or request.GET.get('employeeId')

    if not emp_id:
        return Response({"error": "employee_id is required"}, status=status.HTTP_400_BAD_REQUEST)

    emp_str = str(emp_id).strip()

    try:
        client = get_mongo_client()
        global_db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
        hr_db_name = os.environ.get('HR_DB_NAME', 'HR')

        global_db = client[global_db_name]
        hr_db = client[hr_db_name]

        # 1. Search in Global profile
        query = {'$or': [{'employeeId': emp_str}, {'employee_id': emp_str}]}
        if emp_str.isdigit():
            query['$or'].extend([{'employeeId': int(emp_str)}, {'employee_id': int(emp_str)}])

        prof_doc = global_db['backend_diagnostics_profile'].find_one(query)

        # Fallback to HR employees_register or employee_profiles
        if not prof_doc:
            prof_doc = hr_db['employees_register'].find_one({'employee_id': emp_str}) or hr_db['employee_profiles'].find_one({'employee_id': emp_str})

        ref_maps = _load_reference_maps(global_db)

        # Build clean response profile
        profile_data = {}
        if prof_doc:
            profile_data = _sanitize_doc(prof_doc)

        # Resolve field mappings
        raw_dept = profile_data.get('department') or ''
        raw_desig = profile_data.get('designation') or ''
        raw_role = profile_data.get('primaryRole') or profile_data.get('role') or ''

        dept_name = ref_maps['departments'].get(raw_dept) or (raw_dept if not raw_dept.startswith('DEPT') else 'General')
        desig_name = ref_maps['designations'].get(raw_desig) or (raw_desig if not raw_desig.startswith('DESIG') else 'Staff')
        role_name = ref_maps['roles'].get(raw_role) or raw_role

        # Profile Image
        profile_img_id = profile_data.get('profileImage') or profile_data.get('profile_image') or profile_data.get('image_id')
        photo_url = f"/_b_a_c_k_e_n_d/HR/employee-profile-photo/{emp_str}/" if profile_img_id else ""

        # Assigned shift lookup
        assigned_shift = "Not Assigned"
        try:
            from django.utils import timezone
            import pytz
            ist_tz = pytz.timezone('Asia/Kolkata')
            today = timezone.now().astimezone(ist_tz).date()
            emp_obj = Employee.objects.filter(employee_id=emp_str).first()
            if emp_obj:
                sched = EmployeeShiftSchedule.objects.filter(employee=emp_obj, date=today).first()
                if sched and sched.shift:
                    assigned_shift = sched.shift.name
                elif emp_obj.shift:
                    assigned_shift = emp_obj.shift.name
        except Exception:
            pass

        # Format Date of Birth
        dob_raw = profile_data.get('dateOfBirth') or profile_data.get('date_of_birth')
        dob_formatted = ""
        if dob_raw:
            try:
                if isinstance(dob_raw, str):
                    dob_formatted = dob_raw.split(' ')[0]
            except Exception:
                dob_formatted = str(dob_raw)

        # Format Date of Joining / Registration
        doj_raw = profile_data.get('created_date') or profile_data.get('dateOfJoining')
        doj_formatted = ""
        if doj_raw:
            try:
                if isinstance(doj_raw, str):
                    doj_formatted = doj_raw.split(' ')[0]
            except Exception:
                doj_formatted = str(doj_raw)

        # Qualifications
        qual_list = profile_data.get('qualifications') or []
        highest_degree = ""
        if isinstance(qual_list, list) and len(qual_list) > 0:
            highest_degree = qual_list[0].get('degree', '') if isinstance(qual_list[0], dict) else str(qual_list[0])

        # Family / Emergency
        guardian_num = profile_data.get('guardianNumber') or profile_data.get('emergencyContactNumber') or ''
        father_name = profile_data.get('fatherName') or ''
        mother_name = profile_data.get('motherName') or ''
        family_obj = profile_data.get('familyDetails') or {}
        spouse_name = family_obj.get('spouseName') if isinstance(family_obj, dict) else ''

        enriched_profile = {
            "employee_id": emp_str,
            "name": profile_data.get('employeeName') or profile_data.get('name') or emp_str,
            "department": dept_name,
            "department_code": raw_dept,
            "designation": desig_name,
            "designation_code": raw_desig,
            "role": role_name,
            "primary_role_code": raw_role,
            "email": profile_data.get('email') or '',
            "mobile_number": profile_data.get('mobileNumber') or profile_data.get('mobile_number') or '',
            "gender": (profile_data.get('gender') or '').capitalize(),
            "blood_group": profile_data.get('bloodGroup') or profile_data.get('blood_group') or '',
            "marital_status": (profile_data.get('maritalStatus') or profile_data.get('marital_status') or '').capitalize(),
            "date_of_birth": dob_formatted,
            "date_of_joining": doj_formatted,
            "emergency_contact": guardian_num,
            "father_name": father_name,
            "mother_name": mother_name,
            "spouse_name": spouse_name,
            "highest_qualification": highest_degree,
            "qualifications": qual_list,
            "experiences": profile_data.get('experiences') or [],
            "bank_details": profile_data.get('bankDetails') or {},
            "assigned_shift": assigned_shift,
            "profile_image_id": str(profile_img_id) if profile_img_id else "",
            "photo_url": photo_url,
            "employment_status": (profile_data.get('employmentStatus') or 'Full-Time').capitalize(),
        }

        return Response({"success": True, "profile": enriched_profile}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error fetching full employee profile for {emp_str}: {str(e)}")
        return Response({"error": f"Failed to retrieve profile: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def serve_employee_profile_photo(request, employee_id):
    """
    Direct image serving view for employee:
    Prioritizes the face punch-in / kiosk registration image (image_md5 / employeeId filename),
    and falls back to profileImage from Global profile.
    """
    emp_str = str(employee_id).strip()
    try:
        client = get_mongo_client()
        global_db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
        hr_db_name = os.environ.get('HR_DB_NAME', 'HR')

        global_db = client[global_db_name]
        hr_db = client[hr_db_name]

        fs_hr = GridFS(hr_db)
        fs_global = GridFS(global_db)

        grid_file = None

        # 1️⃣ Check Punch-in Face Recognition Registration Image (image_md5)
        try:
            emp_obj = Employee.objects.filter(employee_id=emp_str).first()
            if emp_obj and emp_obj.image_md5:
                grid_file = fs_hr.find_one({"md5": emp_obj.image_md5}) or fs_global.find_one({"md5": emp_obj.image_md5})
        except Exception:
            pass

        # 2️⃣ Check GridFS by filename prefix or employeeId metadata
        if not grid_file:
            import re
            pattern = re.compile(f"^{re.escape(emp_str)}_", re.IGNORECASE)
            grid_file = (
                fs_hr.find_one({"filename": pattern}) or
                fs_global.find_one({"filename": pattern}) or
                fs_hr.find_one({"employeeId": emp_str}) or
                fs_global.find_one({"employeeId": emp_str})
            )

        # 3️⃣ Fallback to profileImage from Global backend_diagnostics_profile
        if not grid_file:
            query = {'$or': [{'employeeId': emp_str}, {'employee_id': emp_str}]}
            if emp_str.isdigit():
                query['$or'].extend([{'employeeId': int(emp_str)}, {'employee_id': int(emp_str)}])

            prof_doc = global_db['backend_diagnostics_profile'].find_one(query, {'profileImage': 1, 'profile_image': 1})
            img_id = None
            if prof_doc:
                img_id = prof_doc.get('profileImage') or prof_doc.get('profile_image')

            if not img_id and ObjectId.is_valid(emp_str):
                img_id = emp_str

            if img_id and ObjectId.is_valid(str(img_id)):
                oid = ObjectId(str(img_id))
                if fs_global.exists(oid):
                    grid_file = fs_global.get(oid)
                elif fs_hr.exists(oid):
                    grid_file = fs_hr.get(oid)

        if not grid_file:
            raise Http404("No punch-in or profile image found for employee")

        content_type, _ = mimetypes.guess_type(grid_file.filename or 'image.jpg')
        if not content_type:
            content_type = grid_file.content_type or 'image/jpeg'

        response = HttpResponse(grid_file.read(), content_type=content_type)
        response['Cache-Control'] = 'public, max-age=86400'
        return response

    except Http404:
        raise
    except Exception as e:
        logger.error(f"Error serving profile photo for {emp_str}: {e}")
        raise Http404("Error retrieving image")


@api_view(['POST'])
@permission_classes([AllowAny])
def change_employee_password(request):
    """
    Password Change API for Mobile App and Web:
    Validates current password, hashes new password with pbkdf2_sha256,
    and updates backend_diagnostics_user and Django/Mongo user records.
    """
    emp_id = None
    auth_header = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION')
    if auth_header:
        parts = auth_header.split()
        token = parts[1] if len(parts) == 2 else parts[0]
        try:
            from employees.token_utils import decode_employee_token
            payload = decode_employee_token(token)
            if payload:
                emp_id = payload.get('aud') or payload.get('employee_id') or payload.get('employeeId') or payload.get('sub')
        except Exception:
            pass

    if not emp_id:
        emp_id = request.data.get('employee_id') or request.data.get('employeeId')

    old_password = request.data.get('old_password') or request.data.get('current_password')
    new_password = request.data.get('new_password')
    confirm_password = request.data.get('confirm_password')

    if not emp_id:
        return Response({"error": "Employee ID is required"}, status=status.HTTP_400_BAD_REQUEST)

    if not old_password or not new_password:
        return Response({"error": "Both current password and new password are required"}, status=status.HTTP_400_BAD_REQUEST)

    if len(new_password) < 4:
        return Response({"error": "New password must be at least 4 characters long"}, status=status.HTTP_400_BAD_REQUEST)

    if confirm_password and new_password != confirm_password:
        return Response({"error": "New password and Confirm password do not match"}, status=status.HTTP_400_BAD_REQUEST)

    emp_str = str(emp_id).strip()

    try:
        client = get_mongo_client()
        global_db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
        hr_db_name = os.environ.get('HR_DB_NAME', 'HR')

        global_db = client[global_db_name]
        user_col = global_db['backend_diagnostics_user']

        query = {'$or': [{'employeeId': emp_str}, {'employee_id': emp_str}]}
        if emp_str.isdigit():
            query['$or'].extend([{'employeeId': int(emp_str)}, {'employee_id': int(emp_str)}])

        user_doc = user_col.find_one(query)
        if not user_doc:
            return Response({"error": "User account not found for this employee"}, status=status.HTTP_404_NOT_FOUND)

        # Verify old password
        stored_hash = user_doc.get('password', '')
        is_valid = False
        try:
            if stored_hash.startswith('pbkdf2_') or stored_hash.startswith('bcrypt') or '$' in stored_hash:
                is_valid = check_password(old_password, stored_hash)
            else:
                is_valid = (old_password == stored_hash)
        except Exception as e:
            logger.warning(f"Error checking password hash: {e}")
            is_valid = (old_password == stored_hash)

        if not is_valid:
            return Response({"error": "Current password is incorrect. Please verify and try again."}, status=status.HTTP_400_BAD_REQUEST)

        # Hash new password
        hashed_pw = make_password(new_password)
        now_dt = datetime.now()

        # Update in MongoDB Global user collection
        user_col.update_one(
            {'_id': user_doc['_id']},
            {'$set': {
                'password': hashed_pw,
                'is_password_set': True,
                'is_active': True,
                'password_updated_at': now_dt,
                'updated_at': now_dt,
                'lastmodified_date': now_dt,
                'lastmodified_by': emp_str
            }}
        )

        # Also sync to HR employees_user if exists
        try:
            hr_db = client[hr_db_name]
            hr_db['employees_user'].update_many(
                {'$or': [{'employeeId': emp_str}, {'employee_id': emp_str}]},
                {'$set': {'password': hashed_pw, 'is_password_set': True}}
            )
        except Exception:
            pass

        return Response({
            "success": True,
            "message": "Password changed successfully! Please use your new password for future logins."
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error changing password for {emp_str}: {str(e)}")
        return Response({"error": f"Failed to change password: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
