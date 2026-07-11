import requests

url = 'http://localhost:8000/_b_a_c_k_e_n_d/HR/register/'
data = {
    'employee_id': '12345',
    'name': 'Test User',
    'image': ''
}

response = requests.post(url, json=data)
print("Status:", response.status_code)
print("Response:", response.text)
