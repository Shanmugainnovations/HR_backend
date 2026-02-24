
from employees.models import Register

users = [
    {"s_no": 1, "employee_id": "50219", "name": "Mr Ravi Shankar", "role": "Manager", "password": "ravi@123"},
    {"s_no": 2, "employee_id": "60463", "name": "Dr Dhana Rangesh Kumar", "role": "Lab Director", "password": "dhana@123"},
    {"s_no": 3, "employee_id": "60371", "name": "Ms Indumathi", "role": "Nursing Superintedent", "password": "indumathi@123"},
    {"s_no": 4, "employee_id": "50025", "name": "Mr Loganathan", "role": "RSO", "password": "loganathan@123"},
    {"s_no": 5, "employee_id": "50996", "name": "Dr Supha Nandhini", "role": "Clinical Pharmacologist", "password": "supha@123"},
    {"s_no": 6, "employee_id": "60252", "name": "Mr John Philip", "role": "Assistant Manager", "password": "john@123"},
]

for user_data in users:
    # Check if user exists by employee_id to avoid duplicates
    if Register.objects.filter(employee_id=user_data["employee_id"]).exists():
        print(f"Skipping {user_data['name']} ({user_data['employee_id']}) - Already exists.")
        # Optional: Update if needed?
        # reg = Register.objects.get(employee_id=user_data["employee_id"])
        # reg.name = user_data["name"]
        # reg.role = user_data["role"]
        # reg.password = user_data["password"]
        # reg.confirmPassword = user_data["password"]
        # reg.save()
    else:
        Register.objects.create(
            employee_id=user_data["employee_id"],
            name=user_data["name"],
            role=user_data["role"],
            password=user_data["password"],
            confirmPassword=user_data["password"], # Assuming confirmPassword should match
            fingerprint_id=None,
            device=None
        )
        print(f"Created {user_data['name']} ({user_data['employee_id']})")

print("Seeding complete.")
