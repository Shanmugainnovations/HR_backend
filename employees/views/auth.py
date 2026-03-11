import os
from dotenv import load_dotenv
from user_agents import parse

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from employees.models import Register, AllowedDevice

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

@api_view(['GET', 'POST', 'PUT', 'DELETE'])
@csrf_exempt
def registration(request):
    # Enforce Admin-only access for all registration actions
    # In a real app, this should be done via JWT/Session verification.
    # For now, we'll check the 'role' passed in the request or headers.
    requester_role = request.headers.get('X-User-Role') or request.data.get('requester_role')
    if requester_role != 'Admin':
        return Response({"error": "Unauthorized. Only Admins can manage users."}, status=status.HTTP_403_FORBIDDEN)

    if request.method == 'GET':
        # List all registered users using pymongo to handle ObjectId correctly
        try:
            mongo_uri = os.getenv("GLOBAL_DB_HOST")
            hr_db_name = os.getenv("HR_DB_NAME", "HR")
            client = MongoClient(mongo_uri)
            db = client[hr_db_name]
            users_col = db['employees_register']
            
            # Fetch and convert ObjectId to string ID
            users = list(users_col.find().sort('_id', -1))
            for u in users:
                u['id'] = str(u.pop('_id'))
            
            return Response(users, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    if request.method == 'POST':
        # Handle Registration
        name = request.data.get('name')
        employee_id = request.data.get('employee_id') # New Field
        department = request.data.get('department') # New Field
        role = request.data.get('role')
        password = request.data.get('password')
        confirm_password = request.data.get('confirmPassword')
        fingerprint_id = request.data.get('fingerprint_id')  # kept for backwards compat
        allowed_ip    = request.data.get('allowed_ip')         # new: static IP
        device = request.data.get('device')

        # Validate password match
        if password != confirm_password:
            return Response({"error": "Passwords do not match"}, status=status.HTTP_400_BAD_REQUEST)

        # Check for duplicates (Name or Employee ID)
        if Register.objects.filter(name=name).exists():
             return Response({"error": "User with this name already exists"}, status=status.HTTP_400_BAD_REQUEST)
        
        if employee_id and Register.objects.filter(employee_id=employee_id).exists():
             return Response({"error": "User with this Employee ID already exists"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate IP uniqueness if provided
        if allowed_ip and Register.objects.filter(allowed_ip=allowed_ip).exists():
            return Response({"error": "This IP address is already assigned to another user."}, status=status.HTTP_400_BAD_REQUEST)

        # Create new record
        Register.objects.create(
            name=name,
            employee_id=employee_id,
            department=department,
            role=role,
            password=password,
            confirmPassword=confirm_password,
            allowed_ip=allowed_ip,
            device=device
        )

        return Response({"message": "Registration successful!"}, status=status.HTTP_201_CREATED)

    if request.method == 'PUT':
        # Update User
        user_id = request.data.get('id')
        if not user_id:
            return Response({"error": "User ID is required for update"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            mongo_uri = os.getenv("GLOBAL_DB_HOST")
            hr_db_name = os.getenv("HR_DB_NAME", "HR")
            client = MongoClient(mongo_uri)
            db = client[hr_db_name]
            users_col = db['employees_register']
            
            # Find existing user
            update_data = {}
            fields = ['name', 'employee_id', 'department', 'role', 'device', 'allowed_ip']
            for field in fields:
                if field in request.data:
                    update_data[field] = request.data.get(field)
            
            password = request.data.get('password')
            confirm_password = request.data.get('confirmPassword')
            
            if password:
                if password != confirm_password:
                    return Response({"error": "Passwords do not match"}, status=status.HTTP_400_BAD_REQUEST)
                update_data['password'] = password
                update_data['confirmPassword'] = confirm_password
            
            if not update_data:
                return Response({"message": "No changes to update"}, status=status.HTTP_200_OK)

            result = users_col.update_one(
                {"_id": ObjectId(user_id)},
                {"$set": update_data}
            )
            
            if result.matched_count == 0:
                return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
                
            return Response({"message": "User updated successfully!"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    if request.method == 'DELETE':
        user_id = request.GET.get('id')
        if not user_id:
             return Response({"error": "User ID is required for deletion"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            mongo_uri = os.getenv("GLOBAL_DB_HOST")
            hr_db_name = os.getenv("HR_DB_NAME", "HR")
            client = MongoClient(mongo_uri)
            db = client[hr_db_name]
            users_col = db['employees_register']

            result = users_col.delete_one({"_id": ObjectId(user_id)})
            
            if result.deleted_count == 0:
                return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)
                
            return Response({"message": "User deleted successfully!"}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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

        if user.password != password:
            return Response({"error": "Invalid password"}, status=401)

        # Final department resolution
        dept_id = user.department if user.department else "Unassigned"
        dept_name = resolve_department_names(dept_id)

        # Construct Token
        token = "dummy-token-for-web-user"
        if user.device:
            device_name = user.device
            token_env_key = f"{device_name}_TOKEN"
            token = os.getenv(token_env_key) or token

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
    Device login using static IP address.
    The client sends no body — the server reads the caller's IP
    and matches it against Register.allowed_ip.
    """
    from .ip_guard import get_client_ip
    client_ip = get_client_ip(request)

    if not client_ip:
        return JsonResponse({'error': 'Unable to determine client IP.'}, status=400)

    try:
        employee = Register.objects.get(allowed_ip=client_ip)

        device_name = employee.device or 'DEVICE'
        token_env_key = f"{device_name}_TOKEN"
        token = os.getenv(token_env_key)

        if not token:
            return JsonResponse({
                'error': f'No token configured for device "{device_name}". Contact administrator.'
            }, status=403)

        # Resolve department info
        dept_id = employee.department if employee.department else "Unassigned"
        dept_name = resolve_department_names(dept_id)

        return JsonResponse({
            'success': True,
            'device': device_name,
            'name': employee.name,
            'role': employee.role,
            'department': dept_id,
            'department_id': dept_id,
            'department_name': dept_name,
            'employee_id': employee.employee_id,
            'token': token,
            'matched_ip': client_ip,
            'message': 'Device IP authentication successful'
        }, status=200)

    except Register.DoesNotExist:
        return JsonResponse({
            'error': f'Device IP {client_ip} is not authorized. Please contact HR Administrator.'
        }, status=403)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


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
    requester_role = request.headers.get('X-User-Role') or request.data.get('requester_role')
    if requester_role != 'Admin':
        return Response({'error': 'Unauthorized. Only Admins can manage allowed devices.'}, status=403)

    if request.method == 'GET':
        devices = list(AllowedDevice.objects.all().values('id', 'label', 'ip_address', 'is_active', 'created_at'))
        return Response(devices)

    if request.method == 'POST':
        label = request.data.get('label', '').strip()
        ip    = request.data.get('ip_address', '').strip()
        if not label or not ip:
            return Response({'error': 'label and ip_address are required.'}, status=400)
        if AllowedDevice.objects.filter(ip_address=ip).exists():
            return Response({'error': f'IP {ip} is already whitelisted.'}, status=400)
        d = AllowedDevice.objects.create(label=label, ip_address=ip)
        return Response({'message': 'Device added.', 'id': d.id}, status=201)

    if request.method == 'PUT':
        if not device_id:
            return Response({'error': 'device_id required in URL.'}, status=400)
        try:
            d = AllowedDevice.objects.get(id=device_id)
            if 'label'      in request.data: d.label      = request.data['label']
            if 'ip_address' in request.data: d.ip_address = request.data['ip_address']
            if 'is_active'  in request.data: d.is_active  = request.data['is_active']
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
