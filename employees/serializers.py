from rest_framework import serializers
from .models import Employee
from .models import EmployeeAttendance, Register, Shift, Department, EmployeeShiftSchedule, LeaveType
from drf_extra_fields.fields import Base64ImageField
from bson import ObjectId

class ObjectIdField(serializers.Field):
    def to_representation(self, value):
        return str(value)  # Convert ObjectId to string for output

    def to_internal_value(self, data):
        return ObjectId(data)

AUDIT_FIELDS = ['created_by', 'created_date', 'lastmodified_by', 'lastmodified_date']

class EmployeeSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = Employee
        fields = ['id', 'employee_id', 'current_face_encoding', 'face_encoding_data_history', 'is_active'] + AUDIT_FIELDS

class EmployeeCreateSerializer(serializers.ModelSerializer):
    # Accept image via base64 or multipart upload
    image = Base64ImageField(required=False)

    class Meta:
        model = Employee
        fields = ['employee_id', 'image','name']
        extra_kwargs = {
            'employee_id': {'validators': []}  # <-- disable uniqueness validation
        }


class AttendanceSerializer(serializers.ModelSerializer):
    employee = EmployeeSerializer(read_only=True)
    class Meta:
        model = EmployeeAttendance
        fields = '__all__'

import ast
from .models import Profile, GridFSFile

class ProfileSerializer(serializers.ModelSerializer):
    qualifications = serializers.SerializerMethodField()
    experiences = serializers.SerializerMethodField()
    familyDetails = serializers.SerializerMethodField()
    kycDetails = serializers.SerializerMethodField()
    salaryDetails = serializers.SerializerMethodField()
    fnfStatus = serializers.SerializerMethodField()
    bankDetails = serializers.SerializerMethodField()
    signature = serializers.CharField(required=False, allow_null=True)

    class Meta:
        model = Profile
        fields = '__all__'

    def parse_field(self, field):
        if isinstance(field, str):
            try:
                return ast.literal_eval(field)
            except Exception:
                return field
        return field

    def _get_field_value(self, obj, field_name):
        return self.parse_field(getattr(obj, field_name))

    def get_qualifications(self, obj):
        return self._get_field_value(obj, 'qualifications')

    def get_experiences(self, obj):
        return self._get_field_value(obj, 'experiences')

    def get_familyDetails(self, obj):
        return self._get_field_value(obj, 'familyDetails')

    def get_kycDetails(self, obj):
        return self._get_field_value(obj, 'kycDetails')

    def get_salaryDetails(self, obj):
        return self._get_field_value(obj, 'salaryDetails')

    def get_fnfStatus(self, obj):
        return self._get_field_value(obj, 'fnfStatus')

    def get_bankDetails(self, obj):
        return self._get_field_value(obj, 'bankDetails')

class GridFSFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = GridFSFile
        fields = '__all__'



class EmployeeStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['employee_id', 'is_active', 'current_face_encoding']

        
class RegisterSerializer(serializers.ModelSerializer):
    confirmPassword = serializers.CharField(write_only=True)

    class Meta:
        model = Register
        fields = ['id', 'name', 'role', 'password', 'confirmPassword', 'employee_id', 'department', 'assigned_departments', 'device', 'fingerprint'] + AUDIT_FIELDS
        extra_kwargs = {'password': {'write_only': True}}

    def validate(self, data):
        if data.get('password') != data.get('confirmPassword'):
            raise serializers.ValidationError({"confirmPassword": "Passwords do not match."})
        return data

    def create(self, validated_data):
        if 'confirmPassword' in validated_data:
            validated_data.pop('confirmPassword')
        return Register.objects.create(**validated_data)

class ShiftSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shift
        fields = '__all__'

class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = '__all__'

_DEPT_NAME_TO_CODE_CACHE = {}

def get_cached_department_code(dept_name):
    global _DEPT_NAME_TO_CODE_CACHE
    if not _DEPT_NAME_TO_CODE_CACHE:
        try:
            from employees.views.common.utils import get_mongo_client
            import os
            client = get_mongo_client()
            db = client[os.environ.get('GLOBAL_DB_NAME', 'Global')]
            g_depts = list(db['backend_diagnostics_Departments'].find({}, {'department_name': 1, 'department_code': 1}))
            _DEPT_NAME_TO_CODE_CACHE = {
                d['department_name'].strip().lower(): d['department_code']
                for d in g_depts if d.get('department_name') and d.get('department_code')
            }
        except Exception:
            pass
    return _DEPT_NAME_TO_CODE_CACHE.get((dept_name or '').strip().lower())

class DepartmentSerializer(serializers.ModelSerializer):
    shifts = serializers.SerializerMethodField()
    department_code = serializers.SerializerMethodField()
    shift_ids = serializers.PrimaryKeyRelatedField(
        queryset=Shift.objects.all(), source='shifts', many=True, write_only=True, required=False
    )

    class Meta:
        model = Department
        fields = ['id', 'name', 'department_code', 'shifts', 'shift_ids'] + AUDIT_FIELDS

    def get_department_code(self, obj):
        return get_cached_department_code(getattr(obj, 'name', ''))

    def get_shifts(self, obj):
        try:
            if hasattr(obj, 'id') and obj.id:
                return ShiftSerializer(obj.shifts.all(), many=True).data
        except Exception:
            pass
        return []

class EmployeeShiftScheduleSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.name', read_only=True)
    shift_name = serializers.CharField(source='shift.name', read_only=True)
    start_time = serializers.TimeField(source='shift.start_time', read_only=True)
    end_time = serializers.TimeField(source='shift.end_time', read_only=True)

    class Meta:
        model = EmployeeShiftSchedule
        fields = ['id', 'employee', 'employee_name', 'shift', 'shift_name', 'start_time', 'end_time', 'date'] + AUDIT_FIELDS