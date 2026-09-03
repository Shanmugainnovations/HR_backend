import os
from dotenv import load_dotenv
from user_agents import parse

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from employees.models import Register, AllowedDevice
from pymongo import MongoClient
load_dotenv()

def get_device_info(request):
    ua_string = request.META.get('HTTP_USER_AGENT', '')
    user_agent = parse(ua_string)

    device_details = {
        "browser": user_agent.browser.family,       # e.g. Chrome
        "browser_version": user_agent.browser.version_string,
        "os": user_agent.os.family,                 # e.g. Windows
        "os_version": user_agent.os.version_string,
        "device": user_agent.device.family,         # e.g. iPhone, Desktop
        "is_mobile": user_agent.is_mobile,
        "is_tablet": user_agent.is_tablet,
        "is_pc": user_agent.is_pc,
        "ip_address": (
            request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0]
            or request.META.get('REMOTE_ADDR')
        )
    }
    return JsonResponse(device_details)


from pymongo import MongoClient
from bson import ObjectId

def resolve_department_names(dept_str):
    """Helper to resolve department names from IDs or codes stored in Register model."""
    if not dept_str or dept_str == "Unassigned":
        return "Unassigned"
    
    parts = [p.strip() for p in dept_str.split(',') if p.strip()]
    if not parts:
         return "Unassigned"
    
    try:
        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        db_name = os.getenv("GLOBAL_DB_NAME", "Global")
        client = MongoClient(mongo_uri)
        db = client[db_name]
        
        results = []
        for p in parts:
            query = {"department_id": int(p)} if p.isdigit() else {"department_code": p}
            dept = db['backend_diagnostics_Departments'].find_one(query)
            if dept:
                results.append(dept.get('department_name', p))
            else:
                results.append(p)
        return ",".join(results)
    except:
        return dept_str

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
from bson import ObjectId
import os


def get_db():
    mongo_uri = os.getenv("GLOBAL_DB_HOST")
    db_name = os.getenv("HR_DB_NAME", "HR")
    client = MongoClient(mongo_uri)
    return client[db_name]


@api_view(['GET', 'POST', 'PUT', 'DELETE'])
def registration(request):

    try:
        db = get_db()
        users_col = db['employees_register']

        # ======================================================
        # ✅ GET ALL USERS (Auto-sync Global HR-R-HOD Profiles)
        # ======================================================
        if request.method == 'GET':
            try:
                global_db_name = os.getenv("GLOBAL_DB_NAME", "Global")
                mongo_uri = os.getenv("GLOBAL_DB_HOST")
                if mongo_uri:
                    _client = MongoClient(mongo_uri)
                    _global_db = _client[global_db_name]
                    global_hods = list(_global_db['backend_diagnostics_profile'].find({
                        '$or': [
                            {'primaryRole': 'HR-R-HOD'},
                            {'primaryRole': {'$regex': 'HR-R-HOD', '$options': 'i'}},
                            {'additionalRoles': 'HR-R-HOD'},
                            {'additionalRoles': {'$elemMatch': {'$regex': 'HR-R-HOD', '$options': 'i'}}},
                            {'additionalRoles': {'$regex': 'HR-R-HOD', '$options': 'i'}}
                        ]
                    }))
                    for gh in global_hods:
                        emp_id = str(gh.get('employeeId') or '').strip()
                        if not emp_id:
                            continue
                        name = gh.get('employeeName') or gh.get('name') or emp_id
                        dept = gh.get('department') or ''

                        # Find highest integer ID in Register table
                        existing_user = users_col.find_one({'employee_id': emp_id})
                        if existing_user:
                            users_col.update_one(
                                {'_id': existing_user['_id']},
                                {'$set': {'role': 'HR-R-HOD'}}
                            )
                        else:
                            last_user = users_col.find().sort('id', -1).limit(1)
                            max_id = 1
                            for lu in last_user:
                                if lu.get('id') and isinstance(lu.get('id'), int):
                                    max_id = lu.get('id') + 1

                            users_col.insert_one({
                                'id': max_id,
                                'name': name,
                                'employee_id': emp_id,
                                'department': dept,
                                'role': 'HR-R-HOD',
                                'password': 'Password@123',
                                'confirmPassword': 'Password@123'
                            })
            except Exception as sync_err:
                print(f"HR-R-HOD sync notice: {sync_err}")

            raw_users = list(Register.objects.all().order_by('-id').values())
            # Deduplicate by employee_id and serialize ObjectId to string
            seen_emp = set()
            clean_users = []
            for u in raw_users:
                user_dict = {}
                for k, v in u.items():
                    if isinstance(v, ObjectId):
                        user_dict[k] = str(v)
                    else:
                        user_dict[k] = v
                e_id = str(user_dict.get('employee_id') or user_dict.get('id') or user_dict.get('_id'))
                if e_id not in seen_emp:
                    seen_emp.add(e_id)
                    clean_users.append(user_dict)

            return Response(clean_users, status=200)

        # ======================================================
        # ✅ CREATE USER
        # ======================================================
        if request.method == 'POST':
            data = request.data

            name = data.get('name')
            employee_id = data.get('employee_id')
            department = data.get('department')
            role = data.get('role')
            password = data.get('password')
            confirm_password = data.get('confirmPassword')
            allowed_ip = data.get('allowed_ip')
            device = data.get('device')
            fingerprint = data.get('fingerprint')

            # Lookup device label if fingerprint is provided but device label is empty
            if fingerprint and not device:
                device_obj = AllowedDevice.objects.filter(fingerprint=fingerprint).first()
                if device_obj:
                    device = device_obj.label

            # 🔴 Validation
            if not name or not password:
                return Response({"error": "Name & Password required"}, status=400)

            if password != confirm_password:
                return Response({"error": "Passwords do not match"}, status=400)

            # 🔴 Duplicate checks (ORM)
            if Register.objects.filter(name=name).exists():
                return Response({"error": "User already exists"}, status=400)

            if employee_id and Register.objects.filter(employee_id=employee_id).exists():
                return Response({"error": "Employee ID already exists"}, status=400)

            if allowed_ip and Register.objects.filter(allowed_ip=allowed_ip).exists():
                return Response({"error": "IP already assigned"}, status=400)

            # 🔴 Create user via ORM for automatic ID generation
            user = Register(
                name=name,
                employee_id=employee_id,
                department=department,
                role=role,
                password=password,
                confirmPassword=confirm_password,
                allowed_ip=allowed_ip,
                device=device,
                fingerprint=fingerprint
            )
            user.save_with_audit(request)

            return Response({
                "message": "User created successfully",
                "id": user.id
            }, status=201)

        # ======================================================
        # ✅ UPDATE USER
        # ======================================================
        if request.method == 'PUT':
            user_id = request.data.get('id')
            employee_id = request.data.get('employee_id')
            name = request.data.get('name')

            user = None
            if user_id:
                try:
                    user = Register.objects.filter(id=user_id).first()
                except Exception:
                    user = None

            if not user and employee_id:
                user = Register.objects.filter(employee_id=employee_id).first()

            if not user and name:
                user = Register.objects.filter(name=name).first()

            if not user:
                if employee_id or name:
                    user = Register.objects.create(
                        name=name or employee_id,
                        employee_id=employee_id,
                        department=request.data.get('department', ''),
                        role=request.data.get('role', 'HR-R-HOD'),
                        password='Password@123',
                        confirmPassword='Password@123'
                    )
                else:
                    return Response({"error": "User ID or Employee ID required"}, status=400)

            fields = [
                "name", "employee_id", "department", "assigned_departments",
                "role", "device", "allowed_ip", "fingerprint"
            ]

            for f in fields:
                if f in request.data:
                    setattr(user, f, request.data.get(f))

            password = request.data.get('password')
            confirm_password = request.data.get('confirmPassword')

            if password:
                if password != confirm_password:
                    return Response({"error": "Passwords do not match"}, status=400)
                user.password = password
                user.confirmPassword = confirm_password

            # Lookup device label if fingerprint is provided (or changed) but device is empty
            if user.fingerprint and not user.device:
                device_obj = AllowedDevice.objects.filter(fingerprint=user.fingerprint).first()
                if device_obj:
                    user.device = device_obj.label

            user.save_with_audit(request)

            # Sync department with both HR employees_register and Global profile
            if user.employee_id or user.name:
                try:
                    emp_str = str(user.employee_id).strip() if user.employee_id else ""
                    emp_filter = [
                        {'name': str(user.name)}
                    ]
                    if emp_str:
                        emp_filter.append({'employee_id': emp_str})
                        if emp_str.isdigit():
                            emp_filter.append({'employee_id': int(emp_str)})

                    users_col.update_many(
                        {'$or': emp_filter},
                        {'$set': {
                            'department': str(user.department or ''),
                            'assigned_departments': str(getattr(user, 'assigned_departments', '') or ''),
                            'role': str(user.role or '')
                        }}
                    )

                    global_db_name = os.getenv("GLOBAL_DB_NAME", "Global")
                    mongo_uri = os.getenv("GLOBAL_DB_HOST")
                    if mongo_uri and emp_str:
                        _client = MongoClient(mongo_uri)
                        _global_db = _client[global_db_name]
                        
                        profile_update = {
                            'primaryRole': 'HR-R-HOD' if 'HOD' in str(user.role) else ('Admin' if user.role == 'Admin' else 'Employee')
                        }
                        if getattr(user, 'assigned_departments', None) is not None:
                            profile_update['assigned_departments'] = str(user.assigned_departments or '')
                        
                        # Only update personal department if explicitly provided and not an HOD department allocation
                        if 'department' in request.data and 'assigned_departments' not in request.data:
                            profile_update['department'] = str(user.department or '')

                        _global_db['backend_diagnostics_profile'].update_one(
                            {'$or': [{'employeeId': emp_str}, {'employeeId': int(emp_str) if emp_str.isdigit() else -1}]},
                            {'$set': profile_update}
                        )
                except Exception as sync_err:
                    print(f"Profile sync notice: {sync_err}")

            return Response({"message": "Updated successfully", "id": str(user.id) if user.id is not None else None}, status=200)


        # ======================================================
        # ✅ DELETE USER
        # ======================================================
        if request.method == 'DELETE':
            user_id = request.GET.get('id')
            if not user_id:
                return Response({"error": "User ID is required"}, status=400)

            try:
                user = Register.objects.filter(id=user_id).first()
                if not user:
                    return Response({"error": "User not found"}, status=404)

                user.delete()
                return Response({"message": "User deleted successfully"}, status=200)
            except Exception as e:
                return Response({"error": str(e)}, status=500)

    except Exception as e:
        return Response({"error": str(e)}, status=500)


# ======================================================
# ✅ LOGIN ENDPOINT
# ======================================================
@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    name = request.data.get('name')
    employee_id = request.data.get('employee_id')
    password = request.data.get('password')

    try:
        # Check if login by employee_id (preferred) or name
        user = None
        if employee_id:
            user = Register.objects.filter(employee_id=employee_id).first()
        
        if not user and name:
            user = Register.objects.filter(name=name).first()
            
        if not user:
            return Response({"error": "User not found"}, status=404)

        from django.contrib.auth.hashers import check_password
        if not check_password(password, user.password) and user.password != password:
            return Response({"error": "Invalid password"}, status=401)

        # Check assigned departments for HOD roster scoping
        assigned_depts = getattr(user, 'assigned_departments', '') or user.department or 'Unassigned'
        assigned_depts_name = resolve_department_names(assigned_depts)

        # Home department
        home_dept_id = user.department if user.department else "Unassigned"
        home_dept_name = resolve_department_names(home_dept_id)

        # Construct Cryptographic JWT Access Token
        from employees.token_utils import generate_employee_token
        token = generate_employee_token(user.employee_id or user.name or "Admin", user.role)

        return Response({
            "message": f"Login successful as {user.role}",
            "device": user.device,
            "name": user.name,
            "employee_id": user.employee_id,
            "role": user.role,
            "department": assigned_depts if 'HOD' in str(user.role) else home_dept_id,
            "department_id": assigned_depts if 'HOD' in str(user.role) else home_dept_id,
            "department_name": assigned_depts_name if 'HOD' in str(user.role) else home_dept_name,
            "home_department": home_dept_id,
            "home_department_name": home_dept_name,
            "assigned_departments": assigned_depts,
            "assigned_department_names": assigned_depts_name,
            "token": token
        }, status=200)


    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(['POST'])
@permission_classes([AllowAny])
def ip_login(request):
    """
    Fingerprint-based Login (FingerprintJS visitor ID only).
    """
    from employees.views.attendance_management.ip_guard import get_client_ip

    try:
        # 🔹 Mongo connection
        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        db_name = os.environ.get('HR_DB_NAME', 'HR')
        client = MongoClient(mongo_uri)
        db = client[db_name]

        # Use correct Django-prefixed collection names
        allowed_devices_col = db["employees_alloweddevice"]
        register_col = db["employees_register"]

        # 🔹 Get client details
        client_fingerprint = request.data.get("fingerprint")

        if not client_fingerprint:
            return Response(
                {"error": "Fingerprint ID missing"},
                status=400
            )

        # ============================================================
        # 1️⃣ CHECK ALLOWED DEVICE (WHITELIST)
        # ============================================================
        device_obj = allowed_devices_col.find_one({
            "fingerprint": client_fingerprint,
            "is_active": True
        })

        if not device_obj:
            return Response({
                "error": f"Fingerprint '{client_fingerprint[:8]}...' is not authorized. Register this terminal first."
            }, status=403)

        # ============================================================
        # 2️⃣ GENERIC KIOSK LOGIN (NO USER LINK REQUIRED)
        # ============================================================
        # As per user request: "any user not link on this ok"
        # We grant access as a generic Kiosk entity.
        
        device_name = device_obj.get('label') or "KIOSK"
        token_env_key = f"{device_name}_TOKEN"
        token = os.getenv(token_env_key, "kiosk-generic-token")

        # ============================================================
        # 3️⃣ RESPONSE (Generic Kiosk Role)
        # ============================================================
        return Response({
            "success": True,
            "message": f"Kiosk Access Granted: {device_name}",
            "name": f"Kiosk Terminal ({device_name})",
            "employee_id": "KIOSK-001",
            "role": "Kiosk",  # Specific role for attendance terminals
            "department_id": "All",
            "department_name": "Shared Hardware",
            "token": token
        }, status=200)

    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
@permission_classes([AllowAny])
def my_ip(request):
    """Returns the caller's IP address. Used by frontend to show device IP."""
    from employees.views.attendance_management.ip_guard import get_client_ip
    return JsonResponse({'ip': get_client_ip(request)})


@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@permission_classes([AllowAny])
def allowed_devices(request, device_id=None):
    """Admin-only CRUD for the AllowedDevice whitelist."""
    # Requester identity handling for audit if needed, but we allow anyone with valid credentials to manage? 
    # Actually, Management (Edit/Delete) should probably still be restricted to Admin in the LIST view, 
    # but the USER said "all users can register device". 
    # Let's keep the management CRUD for Admins but the Registration API for all.
    requester_role = request.headers.get('X-User-Role') or request.data.get('requester_role')
    
    if request.method == 'GET':
        devices = list(AllowedDevice.objects.all().values('id', 'label', 'ip_address', 'fingerprint', 'is_active', 'created_at'))
        return Response(devices)

    if request.method == 'POST':
        label = request.data.get('label', '').strip()
        ip    = request.data.get('ip_address', '').strip()
        fingerprint = request.data.get('fingerprint', '').strip()
        
        if not label:
            return Response({'error': 'label is required.'}, status=400)
            
        if ip and AllowedDevice.objects.filter(ip_address=ip).exists():
            return Response({'error': f'IP {ip} is already whitelisted.'}, status=400)
            
        if fingerprint and AllowedDevice.objects.filter(fingerprint=fingerprint).exists():
            return Response({'error': f'Device Fingerprint {fingerprint} is already registered.'}, status=400)
            
        d = AllowedDevice.objects.create(label=label, ip_address=ip, fingerprint=fingerprint)
        return Response({'message': 'Device added.', 'id': d.id}, status=201)

    if request.method == 'PUT':
        if not device_id:
            return Response({'error': 'device_id required in URL.'}, status=400)
        try:
            d = AllowedDevice.objects.get(id=device_id)
            if 'label'       in request.data: d.label       = request.data['label']
            if 'ip_address'  in request.data: d.ip_address  = request.data['ip_address']
            if 'fingerprint' in request.data: d.fingerprint = request.data['fingerprint']
            if 'is_active'   in request.data: d.is_active   = request.data['is_active']
            d.save()
            return Response({'message': 'Device updated.'})
        except AllowedDevice.DoesNotExist:
            return Response({'error': 'Device not found.'}, status=404)

    if request.method == 'DELETE':
        if not device_id:
            return Response({'error': 'device_id required in URL.'}, status=400)
        try:
            AllowedDevice.objects.get(id=device_id).delete()
            return Response({'message': 'Device removed.'})
        except AllowedDevice.DoesNotExist:
            return Response({'error': 'Device not found.'}, status=404)

@api_view(['POST'])
@permission_classes([AllowAny])
def register_device_api(request):
    """
    Dedicated endpoint for whitelisting a device.
    Now uses Django ORM for reliable ID generation and data consistency.
    """
    label = request.data.get('label')
    fingerprint = request.data.get('fingerprint')
    ip_address = request.data.get('ip_address')
    password = request.data.get('password')

    if not all([label, fingerprint, password]):
        return Response({"error": "Missing required fields (Label, Fingerprint, or Password)"}, status=400)

    try:
        # 1️⃣ Verification: Find user by password (the user authorizing this device)
        user = Register.objects.filter(password=password).first()

        if not user:
            return Response({"error": "Account not found for this password. Registration denied."}, status=403)

        # 2️⃣ Whitelist the Device (AllowedDevice)
        # Using ORM to ensure 'id' is generated
        device_obj, created = AllowedDevice.objects.update_or_create(
            fingerprint=fingerprint,
            defaults={
                "label": label,
                "ip_address": ip_address or "127.0.0.1",
                "is_active": True
            }
        )

        # 3️⃣ Link Fingerprint to User (Register)
        # We update the SPECIFIC user record found in step 1
        user.fingerprint = fingerprint
        user.device = label
        user.allowed_ip = ip_address or "127.0.0.1"
        user.save()

        return Response({
            "success": True,
            "message": f"Device '{label}' successfully whitelisted and linked to user '{user.name}'!"
        }, status=201)

    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
@permission_classes([AllowAny])
def get_global_departments(request):
    """Retrieve all unique departments from Global MongoDB."""
    try:
        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        db_name = os.getenv("GLOBAL_DB_NAME", "Global")
        client = MongoClient(mongo_uri)
        db = client[db_name]
        dept_col = db['backend_diagnostics_Departments']
        
        # Get all departments, sorted by name
        departments = list(dept_col.find(
            {}, 
            {"_id": 0, "department_name": 1, "department_code": 1}
        ).sort("department_name", 1))
        
        # Fallback to unique department_name from profiles if Departments collection is empty
        if not departments:
            profile_col = db['backend_diagnostics_profile']
            dept_names = profile_col.distinct("department_name")
            departments = [{"department_name": name, "department_code": name} for name in dept_names if name]
            
        return Response(departments, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST', 'PATCH', 'PUT'])
@permission_classes([AllowAny])
def set_employee_password(request):
    """
    Set/Reset employee password with make_password hashing for user model.
    """
    from employees.models import user
    from django.contrib.auth.hashers import make_password, identify_hasher

    employee_id = request.data.get("employeeId") or request.data.get("employee_id")
    password = request.data.get("password")

    if not employee_id or not password:
        return Response(
            {"error": "employeeId and password are required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    user_obj = user.objects.filter(employeeId=employee_id).first()
    if not user_obj:
        user_obj = user(employeeId=employee_id)

    try:
        identify_hasher(password)
    except ValueError:
        password = make_password(password)

    user_obj.password = password
    user_obj.is_password_set = True
    user_obj.is_active = True
    user_obj.save()

    return Response(
        {"message": "Password updated successfully", "employeeId": employee_id},
        status=status.HTTP_200_OK
    )


@api_view(['GET'])
@permission_classes([AllowAny])
def get_user_profile(request, employee_id):
    """Fetch assigned departments, role, and profile info for a user."""
    try:
        emp_str = str(employee_id).strip()
        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        global_db_name = os.getenv("GLOBAL_DB_NAME", "Global")
        hr_db_name = os.getenv("HR_DB_NAME", "HR")

        dept = ""
        role = ""
        name = ""

        if mongo_uri:
            client = MongoClient(mongo_uri)
            # 1. Check HR employees_register
            hr_user = client[hr_db_name]['employees_register'].find_one({
                '$or': [{'employee_id': emp_str}, {'employee_id': int(emp_str) if emp_str.isdigit() else -1}]
            })
            if hr_user:
                dept = hr_user.get('department') or ''
                role = hr_user.get('role') or ''
                name = hr_user.get('name') or ''

            # 2. Check Global profile
            g_user = client[global_db_name]['backend_diagnostics_profile'].find_one({
                '$or': [{'employeeId': emp_str}, {'employeeId': int(emp_str) if emp_str.isdigit() else -1}]
            })
            if g_user:
                if not dept:
                    dept = g_user.get('department') or ''
                if not name:
                    name = g_user.get('employeeName') or g_user.get('name') or ''
                if not role:
                    role = g_user.get('primaryRole') or ''

        return Response({
            "employee_id": emp_str,
            "name": name,
            "role": role,
            "department": dept
        }, status=200)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(['POST'])
@permission_classes([AllowAny])
def mobile_employee_check(request):
    """
    Check if an employee is registered in the Attendance system and whether
    they already have a user login in Global user DB (backend_diagnostics_user).
    """
    try:
        emp_id = request.data.get('employeeId') or request.data.get('employee_id')
        if not emp_id:
            return Response({"error": "Employee ID is required"}, status=status.HTTP_400_BAD_REQUEST)

        emp_str = str(emp_id).strip()

        # 1. Connect to Mongo DBs
        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        global_db_name = os.getenv("GLOBAL_DB_NAME", "Global")
        hr_db_name = os.getenv("HR_DB_NAME", "HR")
        client = MongoClient(mongo_uri) if mongo_uri else None

        if not client:
            return Response({"error": "Database connection error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        global_db = client[global_db_name]
        hr_db = client[hr_db_name]

        # 2. Check if employee exists in Attendance Registry (Employee model / backend_diagnostics_profile)
        from employees.models import Employee
        in_sql_attendance = Employee.objects.filter(employee_id=emp_str).exists()

        query_emp = {'$or': [{'employeeId': emp_str}, {'employee_id': emp_str}]}
        if emp_str.isdigit():
            query_emp['$or'].extend([{'employeeId': int(emp_str)}, {'employee_id': int(emp_str)}])

        profile_doc = global_db['backend_diagnostics_profile'].find_one(query_emp)

        if not in_sql_attendance and not profile_doc:
            return Response({
                "error": "Employee ID is not registered in the Attendance system. Please contact HR or register at the attendance kiosk first.",
                "registered_in_attendance": False
            }, status=status.HTTP_404_NOT_FOUND)

        # Resolve employee metadata
        emp_name = ""
        dept_name = ""
        desig_name = ""
        if profile_doc:
            emp_name = profile_doc.get('employeeName') or profile_doc.get('name') or ""
            dept_code = profile_doc.get('department')
            if dept_code:
                dept_doc = global_db['backend_diagnostics_Departments'].find_one({
                    '$or': [{'department_code': str(dept_code)}, {'department_id': int(dept_code) if str(dept_code).isdigit() else -1}]
                })
                dept_name = dept_doc.get('department_name') if dept_doc else str(dept_code)
            desig_code = profile_doc.get('designation')
            if desig_code:
                desig_doc = global_db['backend_diagnostics_Designation'].find_one({
                    '$or': [{'Designation_code': str(desig_code)}, {'designation_id': int(desig_code) if str(desig_code).isdigit() else -1}]
                })
                desig_name = desig_doc.get('designation') if desig_doc else str(desig_code)

        if not emp_name and in_sql_attendance:
            sql_emp = Employee.objects.filter(employee_id=emp_str).first()
            if sql_emp:
                emp_name = sql_emp.name
                if hasattr(sql_emp, 'department') and sql_emp.department:
                    dept_name = sql_emp.department.name

        # 3. Check if user already exists in Global backend_diagnostics_user or HR employees_register
        user_doc = global_db['backend_diagnostics_user'].find_one(query_emp)
        reg_user = hr_db['employees_register'].find_one(query_emp)

        has_login = False
        if user_doc and (user_doc.get('password') or user_doc.get('is_password_set')):
            has_login = True
        elif reg_user and reg_user.get('password'):
            has_login = True

        return Response({
            "employeeId": emp_str,
            "employeeName": emp_name,
            "department": dept_name,
            "designation": desig_name,
            "registered_in_attendance": True,
            "has_login": has_login,
            "can_create_login": not has_login,
            "message": "Account already active. Please sign in." if has_login else "Employee verified. You can now create your password."
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def mobile_create_login(request):
    """
    Allows an attendance-registered employee who doesn't have a login yet
    to set their password and activate their user account directly from the mobile app.
    Returns JWT access token & profile info for immediate login.
    """
    from django.contrib.auth.hashers import make_password
    from employees.token_utils import generate_employee_token
    from employees.models import Employee, Register

    try:
        emp_id = request.data.get('employeeId') or request.data.get('employee_id')
        password = request.data.get('password')
        confirm_password = request.data.get('confirmPassword') or request.data.get('confirm_password')

        if not emp_id or not password:
            return Response({"error": "Employee ID and Password are required"}, status=status.HTTP_400_BAD_REQUEST)

        if len(str(password)) < 4:
            return Response({"error": "Password must be at least 4 characters long"}, status=status.HTTP_400_BAD_REQUEST)

        if confirm_password and str(password) != str(confirm_password):
            return Response({"error": "Password and Confirm Password do not match"}, status=status.HTTP_400_BAD_REQUEST)

        emp_str = str(emp_id).strip()

        # Connect to Mongo DBs
        mongo_uri = os.getenv("GLOBAL_DB_HOST")
        global_db_name = os.getenv("GLOBAL_DB_NAME", "Global")
        hr_db_name = os.getenv("HR_DB_NAME", "HR")
        client = MongoClient(mongo_uri) if mongo_uri else None

        if not client:
            return Response({"error": "Database connection error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        global_db = client[global_db_name]
        hr_db = client[hr_db_name]

        # 1. Guard: Check attendance registration
        in_sql_attendance = Employee.objects.filter(employee_id=emp_str).exists()
        query_emp = {'$or': [{'employeeId': emp_str}, {'employee_id': emp_str}]}
        if emp_str.isdigit():
            query_emp['$or'].extend([{'employeeId': int(emp_str)}, {'employee_id': int(emp_str)}])

        profile_doc = global_db['backend_diagnostics_profile'].find_one(query_emp)

        if not in_sql_attendance and not profile_doc:
            return Response({
                "error": "Only employees registered in the Attendance system are allowed to create an account."
            }, status=status.HTTP_403_FORBIDDEN)

        # 2. Check if already has login (prevent overwriting active accounts)
        user_col = global_db['backend_diagnostics_user']
        existing_user = user_col.find_one(query_emp)
        if existing_user and existing_user.get('is_password_set') and existing_user.get('password'):
            return Response({
                "error": "A login account already exists for this employee. Please sign in with your existing password."
            }, status=status.HTTP_400_BAD_REQUEST)

        emp_name = emp_str
        dept_id = ""
        dept_name = ""
        role = "Employee"

        if profile_doc:
            emp_name = profile_doc.get('employeeName') or profile_doc.get('name') or emp_str
            dept_id = str(profile_doc.get('department') or '')
            role = profile_doc.get('primaryRole') or "Employee"
            if dept_id:
                dept_doc = global_db['backend_diagnostics_Departments'].find_one({
                    '$or': [{'department_code': dept_id}, {'department_id': int(dept_id) if dept_id.isdigit() else -1}]
                })
                dept_name = dept_doc.get('department_name') if dept_doc else dept_id
        elif in_sql_attendance:
            sql_emp = Employee.objects.filter(employee_id=emp_str).first()
            if sql_emp:
                emp_name = sql_emp.name
                if hasattr(sql_emp, 'department') and sql_emp.department:
                    dept_name = sql_emp.department.name
                    dept_id = str(sql_emp.department.id)

        # Hash password securely
        hashed_password = make_password(str(password))

        # 3. Create or update backend_diagnostics_user in Global DB
        user_data = {
            'employee_id': emp_str,
            'employeeId': emp_str,
            'name': emp_name,
            'password': hashed_password,
            'is_password_set': True,
            'is_active': True,
            'role': role,
            'primaryRole': role,
            'department': dept_id,
            'created_at': timezone.now().isoformat()
        }

        user_col.update_one(
            query_emp,
            {'$set': user_data},
            upsert=True
        )

        # 4. Sync in HR employees_register for backwards compatibility
        register_col = hr_db['employees_register']
        register_col.update_one(
            query_emp,
            {'$set': {
                'employee_id': emp_str,
                'name': emp_name,
                'department': dept_id,
                'role': role,
                'password': hashed_password,
                'confirmPassword': hashed_password,
                'is_active': True
            }},
            upsert=True
        )

        # 5. Generate JWT token and return success
        token = generate_employee_token(emp_str, role)

        return Response({
            "message": "Account created successfully! Welcome to Shanmuga HR.",
            "success": True,
            "access_token": token,
            "token": token,
            "user": {
                "name": emp_name,
                "employeeName": emp_name,
                "employee_id": emp_str,
                "employeeId": emp_str,
                "role": role,
                "primaryRole": role,
                "department": dept_id,
                "department_id": dept_id,
                "department_name": dept_name,
                "selected_branch": "SHB001"
            },
            "name": emp_name,
            "employee_id": emp_str,
            "role": role,
            "department": dept_id,
            "department_name": dept_name,
            "selected_branch": "SHB001"
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


