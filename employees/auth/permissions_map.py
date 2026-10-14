PAGE_MAPPING = {
    # =============================================================
    # 1. CORE HARDWARE & FACIAL RECOGNITION (Device / Kiosk)
    # =============================================================
    '/_b_a_c_k_e_n_d/HRA/mark/.*': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/mark/': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/verify-face/.*': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/verify-face/': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/preview-face-frames/.*': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/preview-face-frames/': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/employees/[^/]+/encode_face/.*': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/employees/[^/]+/encode_face/': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/employees/[^/]+/enable_face/.*': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/employees/[^/]+/enable_face/': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/employees/[^/]+/disable_face/.*': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/employees/[^/]+/disable_face/': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/employees/md5/.*': 'FR-API-FR',
    '/_b_a_c_k_e_n_d/HRA/employees/image-by-md5/.*': 'FR-API-FR',

    # =============================================================
    # 2. CANTEEN TOKEN & RULES
    # =============================================================
    '/_b_a_c_k_e_n_d/HRA/canteen/issue-token/.*': 'CN-API-CT',
    '/_b_a_c_k_e_n_d/HRA/canteen/issue-token/': 'CN-API-CT',
    '/_b_a_c_k_e_n_d/HRA/canteen/today-summary/.*': 'CN-API-CT',
    '/_b_a_c_k_e_n_d/HRA/canteen/today-summary/': 'CN-API-CT',
    '/_b_a_c_k_e_n_d/HRA/canteen/history/.*': 'CN-API-CT',
    '/_b_a_c_k_e_n_d/HRA/canteen/history/': 'CN-API-CT',
    '/_b_a_c_k_e_n_d/HRA/canteen/rules/.*': 'CN-API-CT',
    '/_b_a_c_k_e_n_d/HRA/canteen/rules/': 'CN-API-CT',
    '/_b_a_c_k_e_n_d/HRA/canteen/.*': 'CN-API-CT',
    '/_b_a_c_k_e_n_d/HRA/canteen-token/.*': 'CN-API-CT',

    # =============================================================
    # 3. ATTENDANCE & 2-TIER APPROVALS (HOD, AVP, Admin)
    # =============================================================
    '/_b_a_c_k_e_n_d/HRA/attendance/approval-summary/.*': 'HR-P-ATT-APR',
    '/_b_a_c_k_e_n_d/HRA/attendance/approval-summary/': 'HR-P-ATT-APR',
    '/_b_a_c_k_e_n_d/HRA/attendance/department-staff-summary/.*': 'HR-P-ATT-APR',
    '/_b_a_c_k_e_n_d/HRA/attendance/department-staff-summary/': 'HR-P-ATT-APR',
    '/_b_a_c_k_e_n_d/HRA/attendance/department-action/.*': 'HR-P-ATT-APR',
    '/_b_a_c_k_e_n_d/HRA/attendance/department-action/': 'HR-P-ATT-APR',
    '/_b_a_c_k_e_n_d/HRA/attendance/regularize-employee/.*': 'HR-P-ATT-APR',
    '/_b_a_c_k_e_n_d/HRA/attendance/regularize-employee/': 'HR-P-ATT-APR',

    # =============================================================
    # 4. LEAVE MANAGEMENT
    # =============================================================
    # Approvals (HOD, AVP, Admin)
    '/_b_a_c_k_e_n_d/HRA/leaves/pending/.*': 'HR-P-LEV-APR',
    '/_b_a_c_k_e_n_d/HRA/leaves/pending/': 'HR-P-LEV-APR',
    '/_b_a_c_k_e_n_d/HRA/leaves/[0-9]+/status/.*': 'HR-P-LEV-APR',
    '/_b_a_c_k_e_n_d/HRA/leaves/[0-9]+/status/': 'HR-P-LEV-APR',
    '/_b_a_c_k_e_n_d/HRA/leaves/history/.*': 'HR-P-LEV-APR',
    '/_b_a_c_k_e_n_d/HRA/leaves/history/': 'HR-P-LEV-APR',

    # Self-Service (Employee, HOD, AVP, Admin)
    '/_b_a_c_k_e_n_d/HRA/leaves/apply/.*': 'HR-P-LEV-EMP',
    '/_b_a_c_k_e_n_d/HRA/leaves/apply/': 'HR-P-LEV-EMP',
    '/_b_a_c_k_e_n_d/HRA/leaves/my-leaves/.*': 'HR-P-LEV-EMP',
    '/_b_a_c_k_e_n_d/HRA/leaves/my-leaves/': 'HR-P-LEV-EMP',
    '/_b_a_c_k_e_n_d/HRA/leaves/balances/.*': 'HR-P-LEV-EMP',
    '/_b_a_c_k_e_n_d/HRA/leaves/balances/': 'HR-P-LEV-EMP',
    '/_b_a_c_k_e_n_d/HRA/employee/leave-balances/.*': 'HR-P-LEV-EMP',
    '/_b_a_c_k_e_n_d/HRA/employee/leave-balances/': 'HR-P-LEV-EMP',

    # Configuration & Quota Setup (Admin Only)
    '/_b_a_c_k_e_n_d/HRA/leaves/policies/.*': 'HR-P-LEV-CFG',
    '/_b_a_c_k_e_n_d/HRA/leaves/policies/': 'HR-P-LEV-CFG',
    '/_b_a_c_k_e_n_d/HRA/leaves/sync-balances/.*': 'HR-P-LEV-CFG',
    '/_b_a_c_k_e_n_d/HRA/leaves/sync-balances/': 'HR-P-LEV-CFG',
    '/_b_a_c_k_e_n_d/HRA/leave-types/.*': 'HR-P-LEV-CFG',
    '/_b_a_c_k_e_n_d/HRA/leave-types/': 'HR-P-LEV-CFG',

    # =============================================================
    # 5. 1-HOUR PERMISSION REQUESTS
    # =============================================================
    # Approvals (HOD, AVP, Admin)
    '/_b_a_c_k_e_n_d/HRA/permissions/pending/.*': 'HR-P-PRM-APR',
    '/_b_a_c_k_e_n_d/HRA/permissions/pending/': 'HR-P-PRM-APR',
    '/_b_a_c_k_e_n_d/HRA/permissions/review/.*': 'HR-P-PRM-APR',
    '/_b_a_c_k_e_n_d/HRA/permissions/review/': 'HR-P-PRM-APR',
    '/_b_a_c_k_e_n_d/HRA/mobile/permissions/pending/.*': 'HR-P-PRM-APR',
    '/_b_a_c_k_e_n_d/HRA/mobile/permissions/pending/': 'HR-P-PRM-APR',
    '/_b_a_c_k_e_n_d/HRA/mobile/permissions/review/.*': 'HR-P-PRM-APR',
    '/_b_a_c_k_e_n_d/HRA/mobile/permissions/review/': 'HR-P-PRM-APR',

    # Self-Service (Employee)
    '/_b_a_c_k_e_n_d/HRA/permissions/apply/.*': 'HR-P-PRM-EMP',
    '/_b_a_c_k_e_n_d/HRA/permissions/apply/': 'HR-P-PRM-EMP',
    '/_b_a_c_k_e_n_d/HRA/permissions/my-requests/.*': 'HR-P-PRM-EMP',
    '/_b_a_c_k_e_n_d/HRA/permissions/my-requests/': 'HR-P-PRM-EMP',
    '/_b_a_c_k_e_n_d/HRA/mobile/permissions/apply/.*': 'HR-P-PRM-EMP',
    '/_b_a_c_k_e_n_d/HRA/mobile/permissions/apply/': 'HR-P-PRM-EMP',
    '/_b_a_c_k_e_n_d/HRA/mobile/permissions/my-requests/.*': 'HR-P-PRM-EMP',
    '/_b_a_c_k_e_n_d/HRA/mobile/permissions/my-requests/': 'HR-P-PRM-EMP',

    # =============================================================
    # 6. DUTY ROSTER & SHIFTS (HOD & Admin)
    # =============================================================
    '/_b_a_c_k_e_n_d/HRA/roster/.*': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster/': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster/assign/.*': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster/assign/': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster/export/.*': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster/export/': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster/export-xlsx/.*': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster/export-xlsx/': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster/import-xlsx/.*': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster/import-xlsx/': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster/preview-xlsx/.*': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster/preview-xlsx/': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster/approve-data/.*': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster/approve-data/': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster-report/.*': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/roster-report/': 'HR-P-ROS-MGT',

    # =============================================================
    # 7. PAYROLL MANAGEMENT (Admin & AVP)
    # =============================================================
    '/_b_a_c_k_e_n_d/HRA/payroll/monthly/.*': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/monthly/': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/update-entry/.*': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/update-entry/': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/approve/.*': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/approve/': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/department-action/.*': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/department-action/': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/audit-trail/.*': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/audit-trail/': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/purge-drafts/.*': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/purge-drafts/': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/late-hours-deductions/.*': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/late-hours-deductions/': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/permissions/.*': 'HR-P-PAY-MGT',
    '/_b_a_c_k_e_n_d/HRA/payroll/permissions/': 'HR-P-PAY-MGT',

    # Banking & Statutory Exports
    '/_b_a_c_k_e_n_d/HRA/payroll/export-bank-sheet/.*': 'HR-P-PAY-EXP',
    '/_b_a_c_k_e_n_d/HRA/payroll/export-bank-sheet/': 'HR-P-PAY-EXP',
    '/_b_a_c_k_e_n_d/HRA/payroll/export-pf-ecr/.*': 'HR-P-PAY-EXP',
    '/_b_a_c_k_e_n_d/HRA/payroll/export-pf-ecr/': 'HR-P-PAY-EXP',
    '/_b_a_c_k_e_n_d/HRA/payroll/export-esi-return/.*': 'HR-P-PAY-EXP',
    '/_b_a_c_k_e_n_d/HRA/payroll/export-esi-return/': 'HR-P-PAY-EXP',
    '/_b_a_c_k_e_n_d/HRA/payroll/export-csv/.*': 'HR-P-PAY-EXP',
    '/_b_a_c_k_e_n_d/HRA/payroll/export-csv/': 'HR-P-PAY-EXP',

    # Payslips View & Download
    '/_b_a_c_k_e_n_d/HRA/payroll/employee-payslips/.*': 'HR-P-PAY-SLIP',
    '/_b_a_c_k_e_n_d/HRA/payroll/employee-payslips/': 'HR-P-PAY-SLIP',
    '/_b_a_c_k_e_n_d/HRA/payroll/payslip-pdf/.*': 'HR-P-PAY-SLIP',
    '/_b_a_c_k_e_n_d/HRA/payroll/payslip-pdf/': 'HR-P-PAY-SLIP',

    # =============================================================
    # 8. EMPLOYEE SELF-SERVICE PROFILE & NOTIFICATIONS
    # =============================================================
    '/_b_a_c_k_e_n_d/HRA/employee/today-status/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/employee/today-status/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/employee/my-attendance/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/employee/my-attendance/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/employee/full-profile/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/employee/full-profile/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/employee-profile-photo/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/change-password/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/change-password/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/employee/notifications/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/employee/notifications/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/register-push-token/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/register-push-token/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/admin/send-notification/.*': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/admin/send-notification/': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/attendance-push/.*': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/attendance-push/': 'GL-P-BD',

    # =============================================================
    # 9. HELPDESK & SUPPORT TICKETS
    # =============================================================
    '/_b_a_c_k_e_n_d/HRA/tickets/.*': 'HR-P-TK-MGT',
    '/_b_a_c_k_e_n_d/HRA/tickets/': 'HR-P-TK-MGT',
    '/_b_a_c_k_e_n_d/HRA/helpdesk/.*': 'HR-P-TK-MGT',
    '/_b_a_c_k_e_n_d/HRA/helpdesk/': 'HR-P-TK-MGT',

    # =============================================================
    # 10. ORGANIZATION MASTER CONFIGURATION (Admin)
    # =============================================================
    '/_b_a_c_k_e_n_d/HRA/get_data_departments/.*': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/get_data_departments/': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/get_data_designation/.*': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/get_data_designation/': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/getprimaryandadditionalrole/.*': 'GL-P-MST-CFG',
    '/_b_a_c_k_e_n_d/HRA/getprimaryandadditionalrole/': 'GL-P-MST-CFG',
    '/_b_a_c_k_e_n_d/HRA/get_next_department_code/.*': 'GL-P-MST-CFG',
    '/_b_a_c_k_e_n_d/HRA/get_next_department_code/': 'GL-P-MST-CFG',
    '/_b_a_c_k_e_n_d/HRA/get_next_designation_code/.*': 'GL-P-MST-CFG',
    '/_b_a_c_k_e_n_d/HRA/get_next_designation_code/': 'GL-P-MST-CFG',
    '/_b_a_c_k_e_n_d/HRA/addnew_department/.*': 'GL-P-MST-CFG',
    '/_b_a_c_k_e_n_d/HRA/addnew_department/': 'GL-P-MST-CFG',
    '/_b_a_c_k_e_n_d/HRA/addnew_designation/.*': 'GL-P-MST-CFG',
    '/_b_a_c_k_e_n_d/HRA/addnew_designation/': 'GL-P-MST-CFG',
    '/_b_a_c_k_e_n_d/HRA/update_department/.*': 'GL-P-MST-CFG',
    '/_b_a_c_k_e_n_d/HRA/update_department/': 'GL-P-MST-CFG',
    '/_b_a_c_k_e_n_d/HRA/update_designation/.*': 'GL-P-MST-CFG',
    '/_b_a_c_k_e_n_d/HRA/update_designation/': 'GL-P-MST-CFG',
    
    # Shifts & Duty Roster
    '/_b_a_c_k_e_n_d/HRA/shifts/.*': 'HR-P-ROS-MGT',
    '/_b_a_c_k_e_n_d/HRA/shifts/': 'HR-P-ROS-MGT',
    
    # Basic Reference Data: Departments
    '/_b_a_c_k_e_n_d/HRA/departments/.*': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/departments/': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/global-departments/.*': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/global-departments/': 'GL-P-BD',

    # =============================================================
    # 11. EMPLOYEE DIRECTORY & PROFILES (Existing Global Codes)
    # =============================================================
    '/_b_a_c_k_e_n_d/HRA/employees/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/employees/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/employees_from_global/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/employees_from_global/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/get_employees_with_labels/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/get_employees_with_labels/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/get_employee_by_id/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/get_employee_by_id/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/update_employee/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/update_employee/': 'GL-P-EP',

    # Attendance Reports
    '/_b_a_c_k_e_n_d/HRA/attendance-report/.*': 'HR-P-ATT-REP',
    '/_b_a_c_k_e_n_d/HRA/attendance-report/': 'HR-P-ATT-REP',

    # Employee Onboarding & Uploads
    '/_b_a_c_k_e_n_d/HRA/create_employee/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/create_employee/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/check_employee_id/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/check_employee_id/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/register/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/register/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/upload-gridfs/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/upload-gridfs/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/data-entitlements/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/data-entitlements/': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/serve-file/.*': 'GL-P-EP',
    '/_b_a_c_k_e_n_d/HRA/gridfs/.*': 'GL-P-EP',

    # User Account Status & Email
    '/_b_a_c_k_e_n_d/HRA/UpdateUserStatus-user/.*': 'GL-P-P',
    '/_b_a_c_k_e_n_d/HRA/UpdateUserStatus-user/': 'GL-P-P',
    '/_b_a_c_k_e_n_d/HRA/resend_employee_email/.*': 'GL-P-RSE',
    '/_b_a_c_k_e_n_d/HRA/resend_employee_email/': 'GL-P-RSE',

    # Birthday & Greetings
    '/_b_a_c_k_e_n_d/HRA/employees_birthdays_today/.*': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/employees_birthdays_today/': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/employees_birthdays_monthly/.*': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/employees_birthdays_monthly/': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/export_birthdays_csv/.*': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/export_birthdays_csv/': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/send-birthday-wish/.*': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/send-birthday-wish/': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/send_birthday_wish/.*': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/send_birthday_wish/': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/trigger-birthday-notifications/.*': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/trigger-birthday-notifications/': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/trigger_birthday_notifications/.*': 'GL-P-BD',
    '/_b_a_c_k_e_n_d/HRA/trigger_birthday_notifications/': 'GL-P-BD',

    # Hardware Devices & IP Whitelist
    '/_b_a_c_k_e_n_d/HRA/allowed-devices/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/allowed-devices/': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/register-device/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/register-device/': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/get_device_info/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/get_device_info/': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/spoofing-reports/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/spoofing-reports/': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/admin/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/adminreg/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/adminreg/': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/hrregistration/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/hrregistration/': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/my-ip/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/my-ip/': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/ip-login/.*': 'GL-P-EAD',
    '/_b_a_c_k_e_n_d/HRA/ip-login/': 'GL-P-EAD',

    # User Profile Credentials
    '/_b_a_c_k_e_n_d/HRA/set_employee_password/.*': 'GL-P-EL',
    '/_b_a_c_k_e_n_d/HRA/set_employee_password/': 'GL-P-EL',
    '/_b_a_c_k_e_n_d/HRA/set-employee-password/.*': 'GL-P-EL',
    '/_b_a_c_k_e_n_d/HRA/set-employee-password/': 'GL-P-EL',
    '/_b_a_c_k_e_n_d/HRA/user-profile/.*': 'GL-P-EP',
}

# Automatically support /_b_a_c_k_e_n_d/HR/ and root-level routes (e.g. /leaves/pending/)
_additional_mappings = {}
for pattern, perm in list(PAGE_MAPPING.items()):
    if pattern.startswith('/_b_a_c_k_e_n_d/HRA/'):
        # 1. /_b_a_c_k_e_n_d/HR/ variant
        hr_pattern = pattern.replace('/_b_a_c_k_e_n_d/HRA/', '/_b_a_c_k_e_n_d/HR/', 1)
        _additional_mappings[hr_pattern] = perm
        # 2. Root-level variant (e.g. /leaves/pending/)
        root_pattern = pattern.replace('/_b_a_c_k_e_n_d/HRA/', '/', 1)
        _additional_mappings[root_pattern] = perm

PAGE_MAPPING.update(_additional_mappings)

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