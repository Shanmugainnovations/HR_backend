import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hr_backend.settings')
django.setup()

from employees.serializers import EmployeeCreateSerializer
import base64

small_image_b64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="

data = {
    'employee_id': '12345',
    'name': 'Test User',
    'image': small_image_b64
}

serializer = EmployeeCreateSerializer(data=data)
print("Is valid:", serializer.is_valid())
print("Errors:", serializer.errors)
if serializer.is_valid():
    print("Validated data:", serializer.validated_data)
