import os
import json
import logging
import mimetypes
from datetime import datetime, date
from bson import ObjectId
from pymongo import MongoClient
import gridfs
from gridfs import GridFS

from django.http import JsonResponse, HttpResponse, Http404
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.core.mail import send_mail
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from employees.models import Profile, GridFSFile
from employees.serializers import ProfileSerializer, GridFSFileSerializer
from employees.permissions import HasRoleAndDataPermission, HasRolePermission
from employees.views.common.utils import get_mongo_client

logger = logging.getLogger(__name__)


def send_welcome_email(employee_name, employee_email, reset_url, employee_id="", department="", designation=""):
    try:
        subject = "Welcome to Shanmuga Hospital Limited - Set Your Password"
        context = {
            "employee_name": employee_name,
            "employee_id": employee_id,
            "employee_email": employee_email,
            "department": department,
            "designation": designation,
            "reset_url": reset_url,
        }
        try:
            html_message = render_to_string("email/welcome_email.html", context)
        except Exception as te:
            logger.warning(f"Template welcome_email.html render failed: {te}, using inline HTML fallback")
            html_message = f"""
            <html>
            <body>
                <h2>Welcome to Shanmuga Hospital Limited!</h2>
                <p>Dear {employee_name},</p>
                <p>Welcome to Shanmuga Hospital Limited! Your employee profile has been created successfully.</p>
                <p><a href="{reset_url}" style="background-color: #0284c7; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px;">Set Your Password</a></p>
            </body>
            </html>
            """
        plain_message = f"Dear {employee_name},\n\nWelcome to Shanmuga Hospital Limited! Please set your password here: {reset_url}\n"

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@shanmugahospital.com"),
            recipient_list=[employee_email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"Welcome email sent successfully to {employee_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send welcome email to {employee_email}: {str(e)}")
        return False



def safe_json_load(data, default=None):
    if default is None:
        default = []
    if not data:
        return default
    if isinstance(data, (list, dict)):
        return data
    if isinstance(data, (str, bytes, bytearray)):
        try:
            return json.loads(data)
        except Exception:
            try:
                import ast
                return ast.literal_eval(str(data))
            except Exception:
                return default
    return default


def parse_array_field(val):
    if not val:
        return []
    if isinstance(val, list):
        res = []
        for item in val:
            if isinstance(item, (str, bytes, bytearray)):
                item_str = str(item).strip()
                if not item_str:
                    continue
                if item_str.startswith('[') or item_str.startswith('{'):
                    try:
                        parsed = json.loads(item_str)
                        if isinstance(parsed, list):
                            res.extend(parsed)
                        else:
                            res.append(parsed)
                        continue
                    except Exception:
                        pass
                if ',' in item_str:
                    res.extend([x.strip() for x in item_str.split(',') if x.strip()])
                    continue
                res.append(item_str)
            elif item is not None:
                res.append(item)
        return res

    if isinstance(val, (str, bytes, bytearray)):
        val_str = str(val).strip()
        if not val_str:
            return []
        if val_str.startswith('[') or val_str.startswith('{'):
            try:
                parsed = json.loads(val_str)
                if isinstance(parsed, list):
                    return parsed
                return [parsed]
            except Exception:
                try:
                    import ast
                    parsed = ast.literal_eval(val_str)
                    if isinstance(parsed, list):
                        return parsed
                    return [parsed]
                except Exception:
                    pass
        if ',' in val_str:
            return [x.strip() for x in val_str.split(',') if x.strip()]
        return [val_str]

    return []




def _load_mongo_reference_data():
    client = get_mongo_client()
    db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
    db = client[db_name]

    desigs = {doc.get('Designation_code'): doc.get('designation', 'N/A')
              for doc in db['backend_diagnostics_Designation'].find({}, {'Designation_code': 1, 'designation': 1, '_id': 0})}

    depts = {doc.get('department_code'): doc.get('department_name', 'N/A')
             for doc in db['backend_diagnostics_Departments'].find({}, {'department_code': 1, 'department_name': 1, '_id': 0})}

    roles = {doc.get('role_code'): doc.get('role_name', 'N/A')
             for doc in db['backend_diagnostics_admin_groups'].find({}, {'role_code': 1, 'role_name': 1, '_id': 0})}

    entitlements = {doc.get('department_code'): doc.get('department_name', 'N/A')
                    for doc in db['backend_diagnostics_Departments'].find({}, {'department_code': 1, 'department_name': 1, '_id': 0})}

    users = {doc.get('employee_id'): {'is_active': doc.get('is_active', True), 'is_password_set': doc.get('is_password_set', False)}
             for doc in db['backend_diagnostics_user'].find({}, {'employee_id': 1, 'is_active': 1, 'is_password_set': 1, '_id': 0})}

    return {
        'designations': desigs,
        'departments': depts,
        'roles': roles,
        'entitlements': entitlements,
        'users': users
    }


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def check_employee_id(request):
    """
    Real-time check: returns whether an employee ID already exists.
    Used for live validation while typing in the create profile form.
    """
    employee_id = request.GET.get('employeeId', '').strip()
    if not employee_id:
        return Response({'exists': False}, status=status.HTTP_200_OK)

    exists = Profile.objects.filter(employeeId=employee_id).exists()
    if not exists:
        try:
            client = get_mongo_client()
            db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
            db = client[db_name]
            doc = db['backend_diagnostics_profile'].find_one({'employeeId': employee_id})
            exists = doc is not None
        except Exception as e:
            logger.warning(f"Mongo check_employee_id error: {e}")

    return Response({'exists': exists}, status=status.HTTP_200_OK)



@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def create_employee(request):
    try:
        data = request.data.copy()
        employee_id = data.get('auth-user-id') or data.get('employee_id', 'system')

        required_fields = ['employeeId', 'employeeName', 'gender']
        missing_fields = [f for f in required_fields if not data.get(f)]

        data_entitlements_val = data.get('dataEntitlements')
        if not data_entitlements_val or data_entitlements_val == [] or data_entitlements_val == '[]':
            missing_fields.append('dataEntitlements')

        if missing_fields:
            return Response({'error': f"Missing required fields: {', '.join(missing_fields)}"}, status=status.HTTP_400_BAD_REQUEST)

        email = data.get('email')
        if email:
            try:
                validate_email(email)
            except ValidationError:
                return Response({'error': "Invalid email format"}, status=status.HTTP_400_BAD_REQUEST)

        existing_profile = Profile.objects.filter(employeeId=data.get('employeeId')).first()
        if existing_profile:
            return Response({'error': f"Employee ID '{data.get('employeeId')}' already exists."}, status=status.HTTP_409_CONFLICT)

        now_ist = datetime.utcnow()

        additional_roles = safe_json_load(data.get('additionalRoles'), [])
        data_entitlements = safe_json_load(data.get('dataEntitlements'), [])
        qualifications_data = safe_json_load(data.get('qualifications'), [])
        experiences_data = safe_json_load(data.get('experiences'), [])
        kids_details = safe_json_load(data.get('kidsDetails'), [])

        kyc_details = {
            'aadhaarNumber': data.get('kyc_aadhaarNumber') or '',
            'panNumber': data.get('kyc_panNumber') or '',
            'panType': data.get('kyc_panType') or '',
            'uanNumber': data.get('kyc_uanNumber') or data.get('salary_uanNumber') or '',
        }
        family_details = {
            'fatherAadhaar': data.get('family_fatherAadhaar') or '',
            'fatherDob': data.get('family_fatherDob') or None,
            'motherAadhaar': data.get('family_motherAadhaar') or '',
            'motherDob': data.get('family_motherDob') or None,
            'spouseName': data.get('family_spouseName') or '',
            'spouseAadhaar': data.get('family_spouseAadhaar') or '',
            'spouseDob': data.get('family_spouseDob') or None,
            'kidsDetails': kids_details,
        }
        bank_details = {
            'bankName': data.get('bank_bankName') or '',
            'ifscCode': data.get('bank_ifscCode') or '',
            'accountNumber': data.get('bank_accountNumber') or '',
            'branch': data.get('bank_branch') or '',
        }
        salary_details = {
            'basicSalary': data.get('salary_basicSalary') or '',
            'hra': data.get('salary_hra') or '',
            'allowances': data.get('salary_allowances') or '',
            'grossSalary': data.get('salary_grossSalary') or '',
            'pfApplicable': bool(data.get('salary_pfApplicable') in [True, 'true', 'True', 1, '1']),
            'pfNumber': data.get('salary_pfNumber') or '',
            'uanNumber': data.get('salary_uanNumber') or data.get('kyc_uanNumber') or '',
            'pfEmployee': data.get('salary_pfEmployee') or '',
            'pfEmployer': data.get('salary_pfEmployer') or '',
            'esiApplicable': bool(data.get('salary_esiApplicable') in [True, 'true', 'True', 1, '1']),
            'esiNumber': data.get('salary_esiNumber') or '',
            'professionalTax': data.get('salary_professionalTax') or '',
        }
        fnf_status = {'remarks': data.get('fnf_remarks') or ''}

        profile_doc = {
            '_id': data.get('employeeId'),
            'employeeId': data.get('employeeId'),
            'employeeName': data.get('employeeName') or '',
            'fatherName': data.get('fatherName') or '',
            'motherName': data.get('motherName') or '',
            'gender': data.get('gender') or '',
            'mobileNumber': data.get('mobileNumber') or '',
            'bloodGroup': data.get('bloodGroup') or '',
            'maritalStatus': data.get('maritalStatus') or '',
            'guardianNumber': data.get('guardianNumber') or '',
            'dateOfBirth': data.get('dateOfBirth') or None,
            'age': None,
            'email': data.get('email') or '',
            'department': data.get('department') or '',
            'designation': data.get('designation') or '',
            'primaryRole': data.get('primaryRole') or '',
            'additionalRoles': additional_roles,
            'dataEntitlements': data_entitlements,
            'hospitalCode': data.get('hospitalCode') or 'SH001',
            'employmentStatus': data.get('employmentStatus') or '',
            'registrationNumber': data.get('registrationNumber') or '',
            'validityDate': data.get('validityDate') or None,
            'kycDetails': kyc_details,
            'familyDetails': family_details,
            'qualifications': qualifications_data,
            'experiences': experiences_data,
            'bankDetails': bank_details,
            'salaryDetails': salary_details,
            'fnfStatus': fnf_status,
            'profileImage': data.get('profileImage') or None,
            'signatureFileId': data.get('signatureFileId') or None,
            'created_by': employee_id,
            'created_date': now_ist,
            'lastmodified_by': employee_id,
            'lastmodified_date': now_ist,
        }

        _client = get_mongo_client()
        _db = _client[os.environ.get('GLOBAL_DB_NAME', 'Global')]
        _profiles_col = _db['backend_diagnostics_profile']
        _profiles_col.insert_one(profile_doc)

        profile = Profile.objects.get(employeeId=data.get('employeeId'))
        serializer = ProfileSerializer(profile)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error creating employee profile: {str(e)}")
        return Response({'error': f"Server error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PUT'])
@permission_classes([HasRoleAndDataPermission])
def update_employee(request, employee_id):
    try:
        _client = get_mongo_client()
        _db = _client[os.environ.get('GLOBAL_DB_NAME', 'Global')]
        _profiles_col = _db['backend_diagnostics_profile']

        existing_doc = _profiles_col.find_one({'employeeId': str(employee_id)})
        if not existing_doc:
            return Response({'success': False, 'error': f'Employee with ID {employee_id} not found'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data.copy()
        lastmodified_by = data.get('auth-user-id') or data.get('employee_id') or 'system'

        additional_roles = parse_array_field(data.get('additionalRoles')) if 'additionalRoles' in data else existing_doc.get('additionalRoles', [])
        data_entitlements = parse_array_field(data.get('dataEntitlements')) if 'dataEntitlements' in data else existing_doc.get('dataEntitlements', [])
        qualifications_data = parse_array_field(data.get('qualifications')) if 'qualifications' in data else existing_doc.get('qualifications', [])
        experiences_data = parse_array_field(data.get('experiences')) if 'experiences' in data else existing_doc.get('experiences', [])
        kids_details = parse_array_field(data.get('kidsDetails')) if 'kidsDetails' in data else existing_doc.get('familyDetails', {}).get('kidsDetails', [])

        existing_kyc = existing_doc.get('kycDetails', {}) or {}
        existing_family = existing_doc.get('familyDetails', {}) or {}
        existing_bank = existing_doc.get('bankDetails', {}) or {}
        existing_salary = existing_doc.get('salaryDetails', {}) or {}
        existing_fnf = existing_doc.get('fnfStatus', {}) or {}

        kyc_details = {
            'aadhaarNumber': data.get('kyc_aadhaarNumber', existing_kyc.get('aadhaarNumber', '')),
            'panNumber': data.get('kyc_panNumber', existing_kyc.get('panNumber', '')),
            'panType': data.get('kyc_panType', existing_kyc.get('panType', '')),
            'uanNumber': data.get('kyc_unaNumber', data.get('kyc_uanNumber', data.get('salary_uanNumber', existing_kyc.get('uanNumber', '')))),
            'aadhaarFileId': data.get('aadhaarFileId', existing_kyc.get('aadhaarFileId')),
            'panFileId': data.get('panFileId', existing_kyc.get('panFileId')),
        }
        family_details = {
            'fatherAadhaar': data.get('family_fatherAadhaar', existing_family.get('fatherAadhaar', '')),
            'fatherDob': data.get('family_fatherDob', existing_family.get('fatherDob')),
            'fatherAadhaarFileId': data.get('fatherAadhaarFileId', existing_family.get('fatherAadhaarFileId')),
            'motherAadhaar': data.get('family_motherAadhaar', existing_family.get('motherAadhaar', '')),
            'motherDob': data.get('family_motherDob', existing_family.get('motherDob')),
            'motherAadhaarFileId': data.get('motherAadhaarFileId', existing_family.get('motherAadhaarFileId')),
            'spouseName': data.get('family_spouseName', existing_family.get('spouseName', '')),
            'spouseAadhaar': data.get('family_spouseAadhaar', existing_family.get('spouseAadhaar', '')),
            'spouseDob': data.get('family_spouseDob', existing_family.get('spouseDob')),
            'spouseAadhaarFileId': data.get('spouseAadhaarFileId', existing_family.get('spouseAadhaarFileId')),
            'kidsDetails': kids_details,
        }
        bank_details = {
            'bankName': data.get('bank_bankName', existing_bank.get('bankName', '')),
            'ifscCode': data.get('bank_ifscCode', existing_bank.get('ifscCode', '')),
            'accountNumber': data.get('bank_accountNumber', existing_bank.get('accountNumber', '')),
            'branch': data.get('bank_branch', existing_bank.get('branch', '')),
        }
        salary_details = {
            'basicSalary': data.get('salary_basicSalary', existing_salary.get('basicSalary', '')),
            'hra': data.get('salary_hra', existing_salary.get('hra', '')),
            'allowances': data.get('salary_allowances', existing_salary.get('allowances', '')),
            'grossSalary': data.get('salary_grossSalary', existing_salary.get('grossSalary', '')),
            'pfApplicable': bool(data.get('salary_pfApplicable') in [True, 'true', 'True', 1, '1']) if 'salary_pfApplicable' in data else existing_salary.get('pfApplicable', False),
            'pfNumber': data.get('salary_pfNumber', existing_salary.get('pfNumber', '')),
            'uanNumber': data.get('salary_uanNumber', data.get('kyc_uanNumber', existing_salary.get('uanNumber', existing_kyc.get('uanNumber', '')))),
            'pfEmployee': data.get('salary_pfEmployee', existing_salary.get('pfEmployee', '')),
            'pfEmployer': data.get('salary_pfEmployer', existing_salary.get('pfEmployer', '')),
            'esiApplicable': bool(data.get('salary_esiApplicable') in [True, 'true', 'True', 1, '1']) if 'salary_esiApplicable' in data else existing_salary.get('esiApplicable', False),
            'esiNumber': data.get('salary_esiNumber', existing_salary.get('esiNumber', '')),
            'professionalTax': data.get('salary_professionalTax', existing_salary.get('professionalTax', '')),
        }
        fnf_status = {'remarks': data.get('fnf_remarks', existing_fnf.get('remarks', ''))}

        now_ist = datetime.utcnow()
        update_fields = {
            'employeeName': data.get('employeeName', existing_doc.get('employeeName', '')),
            'fatherName': data.get('fatherName', existing_doc.get('fatherName', '')),
            'motherName': data.get('motherName', existing_doc.get('motherName', '')),
            'gender': data.get('gender', existing_doc.get('gender', '')),
            'mobileNumber': data.get('mobileNumber', existing_doc.get('mobileNumber', '')),
            'bloodGroup': data.get('bloodGroup', existing_doc.get('bloodGroup', '')),
            'maritalStatus': data.get('maritalStatus', existing_doc.get('maritalStatus', '')),
            'guardianNumber': data.get('guardianNumber', existing_doc.get('guardianNumber', '')),
            'dateOfBirth': data.get('dateOfBirth', existing_doc.get('dateOfBirth')),
            'email': data.get('email', existing_doc.get('email', '')),
            'department': data.get('department', existing_doc.get('department', '')),
            'designation': data.get('designation', existing_doc.get('designation', '')),
            'primaryRole': data.get('primaryRole', existing_doc.get('primaryRole', '')),
            'additionalRoles': additional_roles,
            'dataEntitlements': data_entitlements,
            'hospitalCode': data.get('hospitalCode', existing_doc.get('hospitalCode', 'SH001')),
            'employmentStatus': data.get('employmentStatus', existing_doc.get('employmentStatus', '')),
            'registrationNumber': data.get('registrationNumber', existing_doc.get('registrationNumber', '')),
            'validityDate': data.get('validityDate', existing_doc.get('validityDate')),
            'kycDetails': kyc_details,
            'familyDetails': family_details,
            'qualifications': qualifications_data,
            'experiences': experiences_data,
            'bankDetails': bank_details,
            'salaryDetails': salary_details,
            'fnfStatus': fnf_status,
            'profileImage': data.get('profileImage', existing_doc.get('profileImage')),
            'signatureFileId': data.get('signatureFileId', existing_doc.get('signatureFileId')),
            'lastmodified_by': lastmodified_by,
            'lastmodified_date': now_ist,
        }

        _profiles_col.update_one({'employeeId': str(employee_id)}, {'$set': update_fields})
        updated_doc = _profiles_col.find_one({'employeeId': str(employee_id)}, {'_id': 0})

        return Response({'success': True, 'message': 'Profile updated successfully', 'data': _sanitize_mongo_doc(updated_doc)}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error updating employee profile: {str(e)}")
        return Response({'success': False, 'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _sanitize_mongo_doc(doc):
    if isinstance(doc, dict):
        new_doc = {}
        for k, v in doc.items():
            if isinstance(v, (datetime, date)):
                new_doc[k] = v.isoformat()
            elif isinstance(v, dict):
                new_doc[k] = _sanitize_mongo_doc(v)
            elif isinstance(v, list):
                new_doc[k] = [_sanitize_mongo_doc(i) for i in v]
            else:
                new_doc[k] = v
        return new_doc
    elif isinstance(doc, (datetime, date)):
        return doc.isoformat()
    return doc


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_employee_by_id(request, employee_id):
    try:
        client = get_mongo_client()
        db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
        db = client[db_name]
        collection = db['backend_diagnostics_profile']
        emp = collection.find_one({'employeeId': employee_id}, {'_id': 0})
        if not emp:
            return Response({"success": False, "message": "Employee not found."}, status=404)
        return Response({"success": True, "employee": _sanitize_mongo_doc(emp)}, status=200)
    except Exception as e:
        return Response({"success": False, "message": "Error retrieving employee."}, status=500)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_employees_with_labels(request):
    try:
        client = get_mongo_client()
        db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
        db = client[db_name]
        collection = db['backend_diagnostics_profile']

        raw_employees = list(collection.find({}, {'_id': 0}))
        reference_data = _load_mongo_reference_data()
        employees = []

        for raw_emp in raw_employees:
            emp = _sanitize_mongo_doc(raw_emp)
            emp['designation_name'] = reference_data['designations'].get(emp.get('designation'), 'N/A')
            emp['department_name'] = reference_data['departments'].get(emp.get('department'), 'N/A')
            emp['primary_role_name'] = reference_data['roles'].get(emp.get('primaryRole'), 'N/A')

            additional_roles = safe_json_load(emp.get('additionalRoles', '[]'))
            emp['additional_role_names'] = [reference_data['roles'].get(code, 'N/A') for code in additional_roles]

            entitlement_codes = safe_json_load(emp.get('dataEntitlements', '[]'))
            emp['data_entitlement_names'] = [reference_data['entitlements'].get(code, 'N/A') for code in entitlement_codes]

            user_info = reference_data['users'].get(emp.get('employeeId'), {})
            emp['is_active'] = user_info.get('is_active', True)
            emp['is_password_set'] = user_info.get('is_password_set', False)
            employees.append(emp)

        return Response({'employees': employees}, status=200)
    except Exception as e:
        logger.error(f"Error in get_employees_with_labels: {str(e)}")
        return Response({'error': 'Could not fetch enriched employee data'}, status=500)




@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def upload_file(request):
    try:
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        client = get_mongo_client()
        db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
        db = client[db_name]
        fs = gridfs.GridFS(db)

        file_id = fs.put(
            uploaded_file.read(),
            filename=uploaded_file.name,
            content_type=uploaded_file.content_type,
            upload_date=datetime.utcnow()
        )

        gridfs_file = GridFSFile.objects.create(
            file_id=str(file_id),
            filename=uploaded_file.name,
            content_type=uploaded_file.content_type,
            file_size=uploaded_file.size,
            uploaded_by=request.data.get('uploaded_by', 'system'),
            file_type=request.data.get('fileType', 'document')
        )
        serializer = GridFSFileSerializer(gridfs_file)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({'error': f'GridFS upload failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def serve_file(request, file_id):
    try:
        client = get_mongo_client()
        db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
        db = client[db_name]
        fs = GridFS(db)

        grid_file = fs.get(ObjectId(file_id))
        content_type, _ = mimetypes.guess_type(grid_file.filename)
        if not content_type:
            content_type = grid_file.content_type or 'application/octet-stream'

        response = HttpResponse(grid_file.read(), content_type=content_type)
        response['Content-Disposition'] = f'inline; filename="{grid_file.filename}"'
        return response
    except Exception as e:
        raise Http404(f"File not found or invalid: {str(e)}")
