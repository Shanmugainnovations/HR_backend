import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hr_backend.settings')
django.setup()

from django.test import Client
import base64

small_image_b64 = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="

data = {
    'employee_id': '12345',
    'name': 'Test User',
    'image': small_image_b64
}

client = Client()
response = client.post('/_b_a_c_k_e_n_d/HR/register/', data, content_type='application/json')
print("Status:", response.status_code)
print("Response:", response.json())
