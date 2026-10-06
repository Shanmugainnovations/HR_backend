import os
import django

import sys
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hr_backend.settings')
django.setup()

from employees.models import Register, LeaveRequest
from employees.views.common.utils import resolve_department_filter
from django.db.models import Q

def test_routing():
    print("=== Testing Leave Routing Logic ===")
    
    # Test 1: Employee in Nursing (DEPT003) - has Incharge Presilla J
    dept_key = 'Nursing'
    dept_ctx = resolve_department_filter(dept_key)
    target_terms = dept_ctx.get('target_terms', set()) or {dept_key}
    q_dept = Q()
    for t in target_terms:
        q_dept |= Q(department__icontains=t) | Q(assigned_departments__icontains=t)
    inc_user = Register.objects.filter(
        Q(role__in=['HR-R-INC', 'Incharge', 'INCHARGE']) | Q(role__icontains='INCHARGE') | Q(role__icontains='HR-R-INC'),
        q_dept
    ).first()
    print("Dept 'Nursing' -> Has Incharge?", bool(inc_user), inc_user.name if inc_user else "None")
    
    # Test 2: Employee in IT / Software (DEPT041) - check if has Incharge
    dept_key = 'DEPT041'
    dept_ctx = resolve_department_filter(dept_key)
    target_terms = dept_ctx.get('target_terms', set()) or {dept_key}
    q_dept = Q()
    for t in target_terms:
        q_dept |= Q(department__icontains=t) | Q(assigned_departments__icontains=t)
    inc_user_it = Register.objects.filter(
        Q(role__in=['HR-R-INC', 'Incharge', 'INCHARGE']) | Q(role__icontains='INCHARGE') | Q(role__icontains='HR-R-INC'),
        q_dept
    ).first()
    print("Dept 'DEPT041' -> Has Incharge?", bool(inc_user_it), inc_user_it.name if inc_user_it else "None")

    # Test 3: HOD applying (Indumathi s, HR-R-HOD)
    reg_hod = Register.objects.filter(role__icontains='HOD').first()
    requester_role = str(reg_hod.role or '').strip().upper()
    if 'HOD' in requester_role:
        initial = 'Pending AVP'
    print(f"HOD ({reg_hod.name}) applying -> Initial Status: {initial}")

if __name__ == '__main__':
    test_routing()
