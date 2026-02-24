from rest_framework import serializers
from .models import Employee
from .models import EmployeeAttendance, Register, Shift, Department, EmployeeShiftSchedule
from drf_extra_fields.fields import Base64ImageField
from bson import ObjectId

class ObjectIdField(serializers.Field):
    def to_representation(self, value):
        return str(value)  # Convert ObjectId to string for output

    def to_internal_value(self, data):
        return ObjectId(data)

class EmployeeSerializer(serializers.ModelSerializer):
    id = serializers.CharField(read_only=True)
    class Meta:
        model = Employee
        fields = ['id', 'employee_id', 'current_face_encoding', 'face_encoding_data_history', 'is_active', 'created_by', 'created_date', 'lastmodified_by', 'lastmodified_date']

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


class EmployeeStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['employee_id', 'is_active', 'current_face_encoding']

        
class RegisterSerializer(serializers.ModelSerializer):
    confirmPassword = serializers.CharField(write_only=True)

    class Meta:
        model = Register
        fields = ['name', 'role', 'password', 'confirmPassword', 'employee_id', 'department', 'device', 'fingerprint_id']
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

class DepartmentSerializer(serializers.ModelSerializer):
    shifts = ShiftSerializer(many=True, read_only=True)
    shift_ids = serializers.PrimaryKeyRelatedField(
        queryset=Shift.objects.all(), source='shifts', many=True, write_only=True, required=False
    )

    class Meta:
        model = Department
        fields = ['id', 'name', 'shifts', 'shift_ids']

class EmployeeShiftScheduleSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source='employee.name', read_only=True)
    shift_name = serializers.CharField(source='shift.name', read_only=True)
    start_time = serializers.TimeField(source='shift.start_time', read_only=True)
    end_time = serializers.TimeField(source='shift.end_time', read_only=True)

    class Meta:
        model = EmployeeShiftSchedule
        fields = ['id', 'employee', 'employee_name', 'shift', 'shift_name', 'start_time', 'end_time', 'date']