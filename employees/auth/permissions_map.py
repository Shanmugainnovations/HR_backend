PAGE_MAPPING = {
    # Core HR Attendance & Kiosk Endpoints
    '/_b_a_c_k_e_n_d/HRA/mark/.*': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/mark/': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/verify-face/.*': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/verify-face/': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/canteen-token/.*': 'CN-API-CT',
    '/_b_a_c_k_e_n_d/HRA/canteen-token/': 'CN-API-CT',
    '/_b_a_c_k_e_n_d/HRA/canteen/.*': 'CN-API-CT',

    # Master Employee Profile & Global Endpoints
    '/_b_a_c_k_e_n_d/HRA/adminreg/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/hrregistration/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/register/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/create_employee/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/check_employee_id/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/upload-gridfs/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/set_employee_password/.*': 'GL-P-EL',
    '/_b_a_c_k_e_n_d/HRA/set-employee-password/.*': 'GL-P-EL',
    '/_b_a_c_k_e_n_d/HRA/data-entitlements/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/get_data_departments/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/get_data_designation/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/get_employees_with_labels/.*': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/getprimaryandadditionalrole/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/get_next_department_code/.*': 'GL-P-NDC',
    '/_b_a_c_k_e_n_d/HRA/get_next_designation_code/.*': 'GL-P-NDC',
    '/_b_a_c_k_e_n_d/HRA/addnew_department/.*': 'GL-P-AND',
    '/_b_a_c_k_e_n_d/HRA/addnew_designation/.*': 'GL-P-AND',
    '/_b_a_c_k_e_n_d/HRA/update_department/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/update_designation/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/get_employee_by_id/.*': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/update_employee/.*': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/UpdateUserStatus-user/.*': 'GL-P-P',
    '/_b_a_c_k_e_n_d/HRA/resend_employee_email/.*': 'GL-P-RSE',
    '/_b_a_c_k_e_n_d/HRA/employees_birthdays_today/.*': 'GL-P-EBT',

    # Employee Management & Directory
    '/_b_a_c_k_e_n_d/HRA/employees/.*': 'GL-P-ED',

    '/_b_a_c_k_e_n_d/HRA/employees/': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/register-device/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/allowed-devices/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/allowed-devices/': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/get_device_info/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/my-ip/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/ip-login/.*': 'GL-P-EAD',

    # Attendance & Roster Reports
    '/_b_a_c_k_e_n_d/HRA/attendance-report/.*': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/attendance-report/': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/spoofing-reports/.*': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/spoofing-reports/': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/shifts/.*': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/shifts/': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/departments/.*': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/departments/': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/roster/.*': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/roster/': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/roster-report/.*': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/roster-report/': 'GL-P-ED',

    # Leaves & Notifications
    '/_b_a_c_k_e_n_d/HRA/leaves/.*': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/leave-types/.*': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/employee/.*': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/admin/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/register-push-token/.*': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/payroll/.*': 'GL-P-ED',

    # Exact matches without trailing slashes
    '/_b_a_c_k_e_n_d/HRA/adminreg/': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/hrregistration/': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/register/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/create_employee/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/check_employee_id/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/upload-gridfs/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/set_employee_password/': 'GL-P-EL',
    '/_b_a_c_k_e_n_d/HRA/set-employee-password/': 'GL-P-EL',
    '/_b_a_c_k_e_n_d/HRA/data-entitlements/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/get_data_departments/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/get_data_designation/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/get_employees_with_labels/': 'GL-P-ED',
    '/_b_a_c_k_e_n_d/HRA/getprimaryandadditionalrole/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/get_next_department_code/': 'GL-P-NDC',
    '/_b_a_c_k_e_n_d/HRA/get_next_designation_code/': 'GL-P-NDC',
    '/_b_a_c_k_e_n_d/HRA/addnew_department/': 'GL-P-AND',
    '/_b_a_c_k_e_n_d/HRA/addnew_designation/': 'GL-P-AND',
    '/_b_a_c_k_e_n_d/HRA/employees_birthdays_today/': 'GL-P-EBT',

    # Fallback non-prefixed routes
    '/adminreg/.*': 'GL-P-EAD',
    '/create_employee/.*': 'GL-P-EP',
    '/check_employee_id/.*': 'GL-P-EP',
    '/set_employee_password/.*': 'GL-P-EL',
    '/get_employees_with_labels/.*': 'GL-P-ED',
    '/get_data_departments/.*': 'GL-P-EP',
    '/get_data_designation/.*': 'GL-P-EP',
    '/getprimaryandadditionalrole/.*': 'GL-P-EP',
    '/addnew_department/.*': 'GL-P-AND',
    '/addnew_designation/.*': 'GL-P-AND',
    '/update_department/.*': 'GL-P-EAD',
    '/update_designation/.*': 'GL-P-EAD',
    '/get_employee_by_id/.*': 'GL-P-ED',
    '/update_employee/.*': 'GL-P-ED',
    '/get_employees_with_labels/': 'GL-P-ED',
    '/employees/.*': 'GL-P-ED',
    '/departments/.*': 'GL-P-ED',
    '/shifts/.*': 'GL-P-ED',
    '/attendance-report/.*': 'GL-P-ED',
    '/allowed-devices/.*': 'GL-P-EAD',
    '/canteen/.*': 'CN-API-CT',
    '/leaves/.*': 'GL-P-ED',
    '/roster/.*': 'GL-P-ED',
}

# Automatically support both /_b_a_c_k_e_n_d/HRA/ and /_b_a_c_k_e_n_d/HR/
_hr_mapping = {}
for pattern, perm in list(PAGE_MAPPING.items()):
    if pattern.startswith('/_b_a_c_k_e_n_d/HRA/'):
        _hr_mapping[pattern.replace('/_b_a_c_k_e_n_d/HRA/', '/_b_a_c_k_e_n_d/HR/', 1)] = perm
PAGE_MAPPING.update(_hr_mapping)

PAGE_ACTION_MAPPING = {
    'xxx': {
        'DELETE': 'RWD',
    },
}

GEN_ACTION_MAPPING = {
    'POST': 'RW',
    'PUT': 'RW',
    'DELETE': 'RW',
    'PATCH': 'RW',
    'GET': 'R',
}