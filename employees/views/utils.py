from employees.models import Employee
import ast

def save_or_update_encoding(employee_id, encoding, created_by=None, name=None, image_md5=None):
    emp, created = Employee.objects.get_or_create(
        employee_id=employee_id,
        defaults={
            "name": name or "",
            "current_face_encoding": encoding,
            "image_md5": image_md5,
            "created_by": created_by
        }
    )

    if not created:
        # Update existing record
        emp.name = name or emp.name
        emp.update_encoding(encoding, new_image_md5=image_md5)
        emp.is_active = True  # Always reactivate if updating face
        emp.lastmodified_by = created_by
        emp.save(update_fields=['name', 'lastmodified_by', 'lastmodified_date', 'image_md5', 'is_active'])

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
