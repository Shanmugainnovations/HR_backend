import os
import sys
import django
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hr_backend.settings')
django.setup()

from employees.models import LeaveRequest
from rest_framework.test import APIRequestFactory
from employees.views.leave_management.leave_views import apply_leave, update_leave_status

factory = APIRequestFactory()

def run_tests():
    print("==================================================")
    print("TEST 1: Employee applies leave (Department: Nursing)")
    print("==================================================")
    
    # Clean old test requests if any
    LeaveRequest.objects.filter(employee_id__startswith='TEST_').delete()
    
    req1 = factory.post('/leaves/apply/', {
        'employee_id': 'TEST_EMP_NURSE',
        'employee_name': 'Test Nurse',
        'department': 'Nursing',
        'start_date': str(date.today()),
        'end_date': str(date.today()),
        'leave_type': 'EL',
        'reason': 'Medical emergency'
    }, format='json')
    
    resp1 = apply_leave(req1)
    print("Response status code:", resp1.status_code)
    print("Response data:", resp1.data)
    assert resp1.data['status'] == 'Pending Incharge', f"Expected 'Pending Incharge', got {resp1.data['status']}"
    print("✅ Step 1 Passed: Initial status is 'Pending Incharge'!")

    leave_obj = LeaveRequest.objects.filter(employee_id='TEST_EMP_NURSE').first()
    leave_id = leave_obj.id

    print("\n==================================================")
    print("TEST 2: Incharge (Presilla J) reviews & approves")
    print("==================================================")
    req2 = factory.put(f'/leaves/{leave_id}/status/', {
        'status': 'Approved',
        'reviewer_name': 'Presilla J',
        'reviewer_role': 'HR-R-INC',
        'remarks': 'Recommended by Incharge'
    }, format='json', HTTP_USER_ROLE='HR-R-INC', HTTP_AUTH_USER_ID='50257')
    
    resp2 = update_leave_status(req2, leave_id)
    print("Response status code:", resp2.status_code)
    print("Response data:", resp2.data)
    leave_obj.refresh_from_db()
    assert leave_obj.status == 'Pending HOD', f"Expected 'Pending HOD', got {leave_obj.status}"
    assert leave_obj.incharge_name == 'Presilla J', "Incharge name not set!"
    print("✅ Step 2 Passed: Incharge approval routed leave to 'Pending HOD'!")

    print("\n==================================================")
    print("TEST 3: HOD (Indumathi s) reviews & approves")
    print("==================================================")
    req3 = factory.put(f'/leaves/{leave_id}/status/', {
        'status': 'Approved',
        'reviewer_name': 'Indumathi s',
        'reviewer_role': 'HR-R-HOD',
        'remarks': 'Approved by HOD'
    }, format='json', HTTP_USER_ROLE='HR-R-HOD', HTTP_AUTH_USER_ID='60371')
    
    resp3 = update_leave_status(req3, leave_id)
    print("Response status code:", resp3.status_code)
    print("Response data:", resp3.data)
    leave_obj.refresh_from_db()
    assert leave_obj.status == 'Approved', f"Expected 'Approved', got {leave_obj.status}"
    assert leave_obj.hod_name == 'Indumathi s', "HOD name not set!"
    print("✅ Step 3 Passed: HOD approval finalized leave to 'Approved'!")

    print("\n==================================================")
    print("TEST 4: HOD applies leave -> Directly to AVP")
    print("==================================================")
    req4 = factory.post('/leaves/apply/', {
        'employee_id': '60371',
        'employee_name': 'Indumathi s',
        'department': 'Nursing',
        'start_date': str(date.today()),
        'end_date': str(date.today()),
        'leave_type': 'EL',
        'reason': 'Personal leave',
        'role': 'HR-R-HOD'
    }, format='json', HTTP_USER_ROLE='HR-R-HOD', HTTP_AUTH_USER_ID='60371')
    
    resp4 = apply_leave(req4)
    print("Response status code:", resp4.status_code)
    print("Response data:", resp4.data)
    assert resp4.data['status'] == 'Pending AVP', f"Expected 'Pending AVP', got {resp4.data['status']}"
    print("✅ Step 4 Passed: HOD request routed directly to 'Pending AVP'!")

    hod_leave = LeaveRequest.objects.filter(employee_id='60371').order_by('-id').first()

    print("\n==================================================")
    print("TEST 5: AVP (Malavika Mohan) reviews & approves HOD leave")
    print("==================================================")
    req5 = factory.put(f'/leaves/{hod_leave.id}/status/', {
        'status': 'Approved',
        'reviewer_name': 'Malavika Mohan',
        'reviewer_role': 'HR-R-AVP',
        'remarks': 'Approved by AVP'
    }, format='json', HTTP_USER_ROLE='HR-R-AVP', HTTP_AUTH_USER_ID='60521')

    resp5 = update_leave_status(req5, hod_leave.id)
    print("Response status code:", resp5.status_code)
    print("Response data:", resp5.data)
    hod_leave.refresh_from_db()
    assert hod_leave.status == 'Approved', f"Expected 'Approved', got {hod_leave.status}"
    assert hod_leave.avp_name == 'Malavika Mohan', "AVP name not set!"
    print("✅ Step 5 Passed: AVP approval finalized HOD leave to 'Approved'!")

    # Clean up test leaves
    LeaveRequest.objects.filter(employee_id='TEST_EMP_NURSE').delete()
    hod_leave.delete()
    print("\n🎉 ALL 5 TEST SCENARIOS PASSED WITH 100% SUCCESS!")

if __name__ == '__main__':
    run_tests()
