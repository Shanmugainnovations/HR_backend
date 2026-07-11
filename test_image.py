import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hr_backend.settings')
django.setup()

from employees.serializers import EmployeeCreateSerializer

data = {
    'employee_id': '50867',
    'name': 'Parthiban M',
    'image': 'data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAA'
}
serializer = EmployeeCreateSerializer(data=data)
print("Is valid:", serializer.is_valid())
print("Errors:", serializer.errors)
print("Validated data:", serializer.validated_data)
