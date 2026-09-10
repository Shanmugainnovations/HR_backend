from employees.models import Employee
import ast
import os
from pymongo import MongoClient

_MONGO_CLIENT = None

def get_mongo_client():
    """
    Returns a singleton MongoDB client shared across requests in this worker process,
    instead of opening a brand-new connection (with its own handshake/auth) on every call.
    """
    global _MONGO_CLIENT
    if _MONGO_CLIENT is None:
        mongo_uri = os.environ.get("GLOBAL_DB_HOST")
        if mongo_uri:
            _MONGO_CLIENT = MongoClient(mongo_uri)
    return _MONGO_CLIENT

MAX_FACE_ENCODINGS = 5

def save_or_update_encoding(employee_id, encoding, created_by=None, name=None, image_md5=None, encoding_list=None):
    """
    encoding: primary encoding (used for current_face_encoding, kept for backward compatibility
        with every existing caller/endpoint that reads current_face_encoding).
    encoding_list: optional list of encodings (e.g. from multiple registration photos) to store
        in face_encodings for 1:N matching. If omitted, defaults to [encoding] so face_encodings
        stays in sync with the single-encoding callers that already exist.
    """
    encodings_to_save = (encoding_list or ([encoding] if encoding else []))[:MAX_FACE_ENCODINGS]
    primary_encoding = encodings_to_save[0] if encodings_to_save else encoding

    emp, created = Employee.objects.get_or_create(
        employee_id=employee_id,
        defaults={
            "name": name or "",
            "current_face_encoding": primary_encoding,
            "face_encodings": encodings_to_save,
            "image_md5": image_md5,
            "created_by": created_by
        }
    )

    if not created:
        # Update existing record
        emp.name = name or emp.name
        emp.face_encodings = encodings_to_save
        emp.update_encoding(primary_encoding, new_image_md5=image_md5)
        emp.is_active = True  # Always reactivate if updating face
        emp.lastmodified_by = created_by
        emp.save(update_fields=['name', 'lastmodified_by', 'lastmodified_date', 'image_md5', 'is_active', 'face_encodings'])

    # ✅ Force refresh the encoding cache in attendance view
    try:
        from employees.views.attendance_management.attendance import get_optimized_encodings
        get_optimized_encodings(force_refresh=True)
    except ImportError:
        pass

    return emp

def to_list(encoding):
    if isinstance(encoding, str):
        return ast.literal_eval(encoding)
    return encoding

import re

def resolve_department_filter(department_input):
    """
    Standardized, robust department resolver for MongoDB and SQL.
    Resolves codes (e.g. 'DEPT008'), names (e.g. 'IT'), SQL IDs ('3'),
    and comma-separated combinations ('DEPT008,DEPT052').
    """
    if not department_input or department_input == 'All':
        return {
            'is_filtered': False,
            'target_terms': set(),
            'mongo_query': {},
            'matching_employee_ids': None,
            'is_match': lambda d: True
        }

    raw_items = [d.strip() for d in str(department_input).split(',') if d.strip() and d.strip() != 'All']
    if not raw_items:
        return {
            'is_filtered': False,
            'target_terms': set(),
            'mongo_query': {},
            'matching_employee_ids': None,
            'is_match': lambda d: True
        }

    # 1. Resolve SQL department IDs if numeric
    from employees.models import Department as SQLDepartment
    numeric_ids = [r for r in raw_items if r.isdigit()]
    sql_names = []
    if numeric_ids:
        try:
            sql_names = list(SQLDepartment.objects.filter(id__in=numeric_ids).values_list('name', flat=True))
        except Exception:
            pass

    search_terms = list(set(raw_items + sql_names))

    # 2. Resolve via MongoDB Departments collection
    db_name = os.environ.get("GLOBAL_DB_NAME", "Global")
    client = get_mongo_client()
    all_target_terms = set(search_terms)

    if client:
        try:
            db = client[db_name]
            dept_col = db['backend_diagnostics_Departments']
            cursor = list(dept_col.find({
                "$or": [
                    {"department_name": {"$in": search_terms}},
                    {"department_code": {"$in": search_terms}}
                ]
            }))
            for doc in cursor:
                if doc.get("department_code"):
                    all_target_terms.add(doc["department_code"])
                if doc.get("department_name"):
                    all_target_terms.add(doc["department_name"])
        except Exception:
            pass

    # 3. Build Mongo regex query
    regex_patterns = []
    for term in all_target_terms:
        pattern = f"(^|,){re.escape(term)}(,|$)"
        regex_patterns.append({"department": {"$regex": pattern, "$options": "i"}})
        regex_patterns.append({"department_name": {"$regex": pattern, "$options": "i"}})

    mongo_query = {"$or": regex_patterns} if regex_patterns else {}

    # 4. Get matching employee IDs from MongoDB profiles
    matching_employee_ids = set()
    if client and mongo_query:
        try:
            db = client[db_name]
            profiles_col = db['backend_diagnostics_profile']
            docs = list(profiles_col.find(mongo_query, {"employeeId": 1}))
            matching_employee_ids = {str(p["employeeId"]) for p in docs if p.get("employeeId")}
        except Exception:
            pass

    # 5. Python matching predicate
    lower_target_terms = {t.lower() for t in all_target_terms}

    def is_match(raw_val):
        if not raw_val:
            return False
        val_str = str(raw_val).lower().strip()
        val_parts = [p.strip() for p in val_str.split(',') if p.strip()]
        for part in val_parts:
            if part in lower_target_terms:
                return True
        for term in lower_target_terms:
            if term in val_str:
                return True
        return False

    return {
        'is_filtered': True,
        'target_terms': all_target_terms,
        'mongo_query': mongo_query,
        'matching_employee_ids': matching_employee_ids,
        'is_match': is_match
    }


import time
_REF_CACHE = {
    'expires_at': 0,
    'dept_map': {},
    'desig_map': {},
    'shifts_map': {}
}

def get_cached_reference_maps(force_refresh=False):
    """
    Returns cached department, designation, and shifts lookup maps.
    Cached in worker memory for 300 seconds (5 minutes) to avoid repeated Mongo hits.
    """
    global _REF_CACHE
    now = time.time()
    if not force_refresh and _REF_CACHE['expires_at'] > now:
        return _REF_CACHE['dept_map'], _REF_CACHE['desig_map'], _REF_CACHE['shifts_map']

    client = get_mongo_client()
    db_name = os.environ.get("GLOBAL_DB_NAME", "Global")
    dept_map = {}
    desig_map = {}
    shifts_map = {}

    if client:
        try:
            db = client[db_name]
            for d in db['backend_diagnostics_Departments'].find({}, {'_id': 0, 'department_code': 1, 'department_name': 1}):
                c = d.get('department_code')
                n = d.get('department_name')
                if c and n:
                    dept_map[c] = n
            for dg in db['backend_diagnostics_Designation'].find({'is_active': True}, {'_id': 0, 'Designation_code': 1, 'designation': 1}):
                c = dg.get('Designation_code')
                n = dg.get('designation')
                if c and n:
                    desig_map[c] = n
        except Exception:
            pass

    try:
        from employees.models import Shift
        for s in Shift.objects.all():
            shifts_map[s.id] = s
    except Exception:
        pass

    _REF_CACHE = {
        'expires_at': now + 300,
        'dept_map': dept_map,
        'desig_map': desig_map,
        'shifts_map': shifts_map
    }
    return dept_map, desig_map, shifts_map


def get_inactive_employee_ids():
    """
    Returns a set of employee IDs (strings) that are marked as inactive/disabled
    across backend_diagnostics_user, employees_employee, and employee profiles in Global and HR databases.
    """
    inactive_ids = set()
    client = get_mongo_client()
    if client:
        try:
            global_db_name = os.environ.get("GLOBAL_DB_NAME", "Global")
            hr_db_name = os.environ.get("GLOBAL_DB_NAME_HR", "HR")
            
            # 1. Global db checks
            db_global = client[global_db_name]
            if 'backend_diagnostics_user' in db_global.list_collection_names():
                for d in db_global['backend_diagnostics_user'].find({'is_active': False}, {'employeeId': 1, 'employee_id': 1, '_id': 0}):
                    eid = str(d.get('employeeId') or d.get('employee_id') or '').strip()
                    if eid:
                        inactive_ids.add(eid)

            if 'employees_employee' in db_global.list_collection_names():
                for d in db_global['employees_employee'].find({'is_active': False}, {'employee_id': 1, '_id': 0}):
                    eid = str(d.get('employee_id') or '').strip()
                    if eid:
                        inactive_ids.add(eid)

            for prof_col_name in ['backend_diagnostics_employee_profile', 'backend_diagnostics_profile']:
                if prof_col_name in db_global.list_collection_names():
                    for d in db_global[prof_col_name].find({
                        '$or': [
                            {'is_active': False},
                            {'status': {'$in': ['Inactive', 'inactive', 'Disabled', 'disabled', 'Resigned', 'resigned', 'Left', 'left']}}
                        ]
                    }, {'employeeId': 1, '_id': 0}):
                        eid = str(d.get('employeeId') or '').strip()
                        if eid:
                            inactive_ids.add(eid)

            # 2. HR db checks
            if hr_db_name in client.list_database_names():
                db_hr = client[hr_db_name]
                if 'employees_employee' in db_hr.list_collection_names():
                    for d in db_hr['employees_employee'].find({'is_active': False}, {'employee_id': 1, '_id': 0}):
                        eid = str(d.get('employee_id') or '').strip()
                        if eid:
                            inactive_ids.add(eid)
        except Exception:
            pass
    return inactive_ids


def get_request_user_hod_departments(request):
    """
    Identifies if the requester is an HOD, and returns:
    (is_hod, list_of_assigned_department_names)
    If Admin, HR, or non-HOD, returns (False, []).
    """
    from employees.models import Register
    from django.db.models import Q

    auth_user_id = (
        request.headers.get('auth-user-id') or
        request.headers.get('X-Employee-ID') or
        request.headers.get('auth_user_id') or
        request.GET.get('auth_user_id') or
        request.GET.get('userId') or
        request.GET.get('employee_id') or
        (request.data.get('userId') if hasattr(request, 'data') and isinstance(request.data, dict) else None) or
        getattr(request.user, 'employee_id', None) or
        getattr(request.user, 'username', None)
    )

    # Fallback to decode JWT token if header not explicitly passed
    if not auth_user_id:
        auth_header = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION')
        if auth_header:
            from employees.token_utils import decode_employee_token
            payload = decode_employee_token(auth_header)
            if payload and payload.get('employee_id'):
                auth_user_id = payload['employee_id']

    if not auth_user_id:
        return False, []

    user = Register.objects.filter(
        Q(employee_id=str(auth_user_id).strip()) | Q(name=str(auth_user_id).strip())
    ).first()
    if not user:
        return False, []

    role = str(user.role or '').strip()
    is_hod = 'HOD' in role.upper()
    if not is_hod:
        return False, []

    assigned = getattr(user, 'assigned_departments', '') or user.department or ''
    if not assigned or str(assigned).strip() in ['Unassigned', '', 'None']:
        return True, []

    resolved = resolve_department_filter(assigned)
    dept_map, _, _ = get_cached_reference_maps()

    names = set()
    for term in resolved.get('target_terms', []):
        if term in dept_map:
            names.add(dept_map[term])
        elif not term.upper().startswith('DEPT'):
            names.add(term)

    return True, sorted(list(names))


