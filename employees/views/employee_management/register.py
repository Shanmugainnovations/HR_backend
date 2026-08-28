"""
Employee Profile Registration Package
Handles employee profile creation, biometric face enrollment, and detail lookup.
"""
from employees.views.employee import (
    register_employee,
    register_face,
    get_all_employees,
    get_employee_detail
)

__all__ = [
    'register_employee',
    'register_face',
    'get_all_employees',
    'get_employee_detail'
]
