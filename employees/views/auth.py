import os
from dotenv import load_dotenv
from user_agents import parse

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from employees.models import Register

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

@api_view(['GET', 'POST', 'PUT'])
@csrf_exempt
def registration(request):
    if request.method == 'POST':
        # Handle Registration
        name = request.data.get('name')
        employee_id = request.data.get('employee_id') # New Field
        department = request.data.get('department') # New Field
        role = request.data.get('role')
        password = request.data.get('password')
        confirm_password = request.data.get('confirmPassword')
        fingerprint_id = request.data.get('fingerprint_id')
        device = request.data.get('device')

        # Validate password match
        if password != confirm_password:
            return Response({"error": "Passwords do not match"}, status=status.HTTP_400_BAD_REQUEST)

        # Check for duplicates (Name or Employee ID)
        if Register.objects.filter(name=name).exists():
             return Response({"error": "User with this name already exists"}, status=status.HTTP_400_BAD_REQUEST)
        
        if employee_id and Register.objects.filter(employee_id=employee_id).exists():
             return Response({"error": "User with this Employee ID already exists"}, status=status.HTTP_400_BAD_REQUEST)

        # Create new record
        Register.objects.create(
            name=name,
            employee_id=employee_id,
            department=department,
            role=role,
            password=password,
            confirmPassword=confirm_password,
            fingerprint_id=fingerprint_id,
            device=device
        )

        return Response({"message": "Registration successful!"}, status=status.HTTP_201_CREATED)


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

        # Fetch Department
        department = user.department if user.department else "Unassigned"
        
        # Fallback to MongoDB if department not set in Register model
        if department == "Unassigned":
            try:
                mongo_uri = os.getenv("GLOBAL_DB_HOST")
                db_name = os.getenv("GLOBAL_DB_NAME", "Global")
                client = MongoClient(mongo_uri)
                db = client[db_name]
                
                # If user has employee_id linked
                search_id = user.employee_id or user.name

                profile = None
                if user.employee_id:
                    profile = db['backend_diagnostics_profile'].find_one({"employeeId": user.employee_id})
                
                if not profile: # Try name if ID not found or not provided
                    profile = db['backend_diagnostics_profile'].find_one({"employeeId": search_id})

                if profile:
                    dept_code = profile.get("department")
                    # Resolve Department Code
                    dept_doc = db['backend_diagnostics_Departments'].find_one({"department_code": dept_code})
                    if dept_doc:
                        department = dept_doc.get("department_name", dept_code)
                    else:
                        department = dept_code
            except Exception as e:
                print(f"Error fetching department: {e}")

        # Construct Token (Legacy logic for device based token kept for compatibility)
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
            "department": department,
            "token": token
        }, status=200)

    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(['POST'])
@permission_classes([AllowAny])
def fingerprint_login(request):
    fingerprint_id = request.data.get('fingerprint_id')

    if not fingerprint_id:
        return JsonResponse({'error': 'Fingerprint ID is required'}, status=400)

    try:
        employee = Register.objects.get(fingerprint_id=fingerprint_id)
        device_name = employee.device
        print(f"Device name from DB: {device_name}")
        token_env_key = f"{device_name}_TOKEN"
        token = os.getenv(token_env_key)

        if not token:
            return JsonResponse({
                'error': f'No token found for device {device_name}. Please check environment settings.'
            }, status=403)

        return JsonResponse({
            'success': True,
            'device': device_name,
            'name': employee.name,
            'role': employee.role,
            'token': token,
            'message': 'Fingerprint authentication successful'
        }, status=200)

    except Register.DoesNotExist:
        return JsonResponse({
            'error': 'Device fingerprint not registered. Please contact administrator.'
        }, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
