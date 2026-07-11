import requests

url = 'http://localhost:8000/_b_a_c_k_e_n_d/HR/register/'
data = {
    "employee_id": "50867",
    "name": "Parthiban M",
    "image": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAA"
}

try:
    response = requests.post(url, json=data)
    print("Status:", response.status_code)
    print("Response:", response.text)
except Exception as e:
    print("Error:", e)
