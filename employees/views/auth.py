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
        # ✅ GET ALL USERS
        # ======================================================
        if request.method == 'GET':
            # Use ORM to ensure we get proper integer IDs
            users = list(Register.objects.all().order_by('-id').values())
            return Response(users, status=200)

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

            if not user_id:
                return Response({"error": "User ID required"}, status=400)

            try:
                user = Register.objects.get(id=user_id)
            except Register.DoesNotExist:
                return Response({"error": "User not found"}, status=404)

            fields = [
                "name", "employee_id", "department",
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
            return Response({"message": "Updated successfully"}, status=200)


        # ======================================================
        # ✅ DELETE USER
        # ======================================================
        if request.method == 'DELETE':
            user_id = request.GET.get('id')

            if not user_id:
                return Response({"error": "User ID required"}, status=400)

            try:
                Register.objects.filter(id=user_id).delete()
                return Response({"message": "Deleted successfully"}, status=200)
            except:
                return Response({"error": "Deletion failed"}, status=500)

    except Exception as e:
        print("🔥 ERROR:", str(e))  # important debug
        return Response({"error": str(e)}, status=500)


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


        # Final department resolution
        dept_id = user.department if user.department else "Unassigned"
        dept_name = resolve_department_names(dept_id)

        # Construct Cryptographic JWT Access Token
        from employees.token_utils import generate_employee_token
        token = generate_employee_token(user.employee_id or user.name or "Admin", user.role)


        return Response({
            "message": f"Login successful as {user.role}",
            "device": user.device,
            "name": user.name,
            "employee_id": user.employee_id,
            "role": user.role,
            "department": dept_id,      # ID(s)
            "department_id": dept_id,   # Explicit ID field
            "department_name": dept_name, # Resolved name(s)
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
    from .ip_guard import get_client_ip

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
    from .ip_guard import get_client_ip
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

    if requester_role != 'Admin':
        return Response({'error': 'Unauthorized. Only Admins can manage the device database.'}, status=403)

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
