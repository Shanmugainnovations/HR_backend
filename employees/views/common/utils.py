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


