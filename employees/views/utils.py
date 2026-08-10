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
        from .attendance import get_optimized_encodings
        get_optimized_encodings(force_refresh=True)
    except ImportError:
        pass

    return emp

def to_list(encoding):
    if isinstance(encoding, str):
        return ast.literal_eval(encoding)
    return encoding
