import os
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from employees.permissions import HasRoleAndDataPermission, HasRolePermission, AllowAny
from datetime import datetime
import zoneinfo
from employees.views.common.utils import get_mongo_client

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


def _get_db():
    client = get_mongo_client()
    db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
    return client[db_name]


def _get_dept_col():
    return _get_db()['backend_diagnostics_Departments']


def _get_desig_col():
    return _get_db()['backend_diagnostics_Designation']


def _generate_next_code(collection, prefix, code_field):
    docs = list(collection.find({}, {code_field: 1, '_id': 0}))
    max_num = 0
    for d in docs:
        val = d.get(code_field, "")
        if isinstance(val, str) and val.startswith(prefix):
            num_part = val[len(prefix):]
            if num_part.isdigit():
                num = int(num_part)
                if num > max_num:
                    max_num = num
    next_num = max_num + 1
    return f"{prefix}{next_num:03d}"


@api_view(['POST', 'GET'])
@permission_classes([HasRoleAndDataPermission])
def get_data_entitlements(request):
    db = _get_db()
    collection = db['backend_diagnostics_DataEntitlements']
    entitlements_list = list(collection.find({}, {'_id': 0}))
    return JsonResponse({'dataEntitlements': entitlements_list})


@api_view(['POST', 'GET'])
@permission_classes([AllowAny])
def get_data_departments(request):
    db = _get_db()
    collection = db['backend_diagnostics_Departments']
    data_departments = collection.find({}, {'_id': 0})
    departments_list = []
    for item in data_departments:
        if 'department_code' in item or 'department_name' in item:
            if 'is_active' not in item or item['is_active'] is None:
                item['is_active'] = True
            departments_list.append(item)
    return JsonResponse({'departments': departments_list})


@api_view(['POST', 'GET'])
@permission_classes([AllowAny])
def get_data_designation(request):
    db = _get_db()
    collection = db['backend_diagnostics_Designation']
    data_designation = collection.find({}, {'_id': 0})
    designation_list = []
    for item in data_designation:
        if 'Designation_code' in item or 'designation' in item:
            if 'is_active' not in item or item['is_active'] is None:
                item['is_active'] = True
            designation_list.append(item)
    return JsonResponse({'designations': designation_list})


@api_view(['POST', 'GET'])
@permission_classes([AllowAny])
def getprimaryandadditionalrole(request):
    db = _get_db()
    collection = db['backend_diagnostics_RoleMapping']
    get_data = collection.find({"is_active": True}, {'_id': 0})
    data_list = list(get_data)
    return JsonResponse({'designations': data_list})


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_next_department_code(request):
    try:
        next_code = _generate_next_code(_get_dept_col(), "DEPT", "department_code")
        return JsonResponse({"department_code": next_code})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_next_designation_code(request):
    try:
        next_code = _generate_next_code(_get_desig_col(), "DESG", "Designation_code")
        return JsonResponse({"Designation_code": next_code})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def addnew_department(request):
    try:
        dept_name = request.data.get("department_name")
        dept_code = request.data.get("department_code") or _generate_next_code(_get_dept_col(), "DEPT", "department_code")
        if not dept_name:
            return JsonResponse({"error": "department_name is required"}, status=400)

        doc = {
            "department_code": dept_code,
            "department_name": dept_name,
            "description": request.data.get("description", dept_name),
            "is_active": True,
            "created_date": datetime.now(IST).isoformat(),
        }
        _get_dept_col().insert_one(doc)
        return JsonResponse({"message": "Department added successfully", "data": doc}, status=201)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def addnew_designation(request):
    try:
        desig_name = request.data.get("designation")
        desig_code = request.data.get("Designation_code") or _generate_next_code(_get_desig_col(), "DESG", "Designation_code")
        if not desig_name:
            return JsonResponse({"error": "designation is required"}, status=400)

        doc = {
            "Designation_code": desig_code,
            "designation": desig_name,
            "is_active": True,
            "created_date": datetime.now(IST).isoformat(),
        }
        _get_desig_col().insert_one(doc)
        return JsonResponse({"message": "Designation added successfully", "data": doc}, status=201)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['PUT', 'PATCH', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def update_department(request, dept_code):
    try:
        col = _get_dept_col()
        existing = col.find_one({"department_code": dept_code})
        if not existing:
            # Fallback check case-insensitively
            existing = col.find_one({"department_code": {"$regex": f"^{re.escape(dept_code)}$", "$options": "i"}})
            if not existing:
                return JsonResponse({"error": f"Department with code {dept_code} not found"}, status=404)
            dept_code = existing["department_code"]

        update_fields = {}
        if "department_name" in request.data:
            update_fields["department_name"] = request.data["department_name"]
        if "description" in request.data:
            update_fields["description"] = request.data["description"]
        if "email" in request.data:
            update_fields["email"] = request.data["email"]
        if "is_active" in request.data:
            update_fields["is_active"] = bool(request.data["is_active"])

        update_fields["lastmodified_date"] = datetime.now(IST).isoformat()

        col.update_one({"department_code": dept_code}, {"$set": update_fields})
        updated = col.find_one({"department_code": dept_code}, {"_id": 0})
        return JsonResponse({"message": "Department updated successfully", "data": updated}, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['PUT', 'PATCH', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def update_designation(request, desig_code):
    try:
        col = _get_desig_col()
        existing = col.find_one({"$or": [
            {"Designation_code": desig_code},
            {"designation_code": desig_code},
            {"Designation_code": {"$regex": f"^{re.escape(desig_code)}$", "$options": "i"}},
            {"designation_code": {"$regex": f"^{re.escape(desig_code)}$", "$options": "i"}}
        ]})
        if not existing:
            return JsonResponse({"error": f"Designation with code {desig_code} not found"}, status=404)

        code_field = "Designation_code" if "Designation_code" in existing else "designation_code"
        code_val = existing[code_field]

        update_fields = {}
        if "designation" in request.data:
            update_fields["designation"] = request.data["designation"]
        if "description" in request.data:
            update_fields["description"] = request.data["description"]
        if "is_active" in request.data:
            update_fields["is_active"] = bool(request.data["is_active"])

        update_fields["lastmodified_date"] = datetime.now(IST).isoformat()

        col.update_one({code_field: code_val}, {"$set": update_fields})
        updated = col.find_one({code_field: code_val}, {"_id": 0})
        return JsonResponse({"message": "Designation updated successfully", "data": updated}, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


