from django.urls import path
from . import views
from .views.analytics_and_reports import reports
from .views.attendance_management.shifts import (
    shift_list_create, shift_detail,
    department_list_create, department_detail,
    get_monthly_roster, assign_shift
)

from .views.mobile_app.notifications import (
    get_employee_notifications,
    mark_notifications_read,
    clear_notifications,
    get_unread_count,
    send_admin_notification,
    register_push_token,
    get_active_popup_announcement
)






urlpatterns = [
    path('hrregistration/', views.registration),
    path('register/', views.register_employee, name='register-employee'),
    path('preview-face-frames/', views.preview_face_frames, name='preview-face-frames'),
    path('employees/', views.get_all_employees_with_images, name='employee-list'),
    path('employees/export-xls/', views.export_employees_xls, name='export-employees-xls'),
    path('employees/<str:employee_id>/', views.get_employee_detail, name='employee-detail'),
    path('register-device/', views.register_device_api, name='register-device'),
    path('employees_from_global/', views.get_all_employee_from_global, name='global-employees'),
    path('login/', views.login, name='login'),
    path('user-profile/<str:employee_id>/', views.get_user_profile, name='user-profile'),

    path("employees/<str:employee_id>/encode_face/", views.encode_employee_face),
    path('employees/<str:employee_id>/enable_face/', views.enable_facial_recognition),
    path('employees/<str:employee_id>/disable_face/', views.disable_facial_recognition),
    path('serve-file/<str:file_id>/', views.serve_file, name="serve_file"),
    path('get_device_info/', views.get_device_info, name="serve_file"),
    path('employees/md5/<str:image_md5>/', views.get_employee_by_md5, name='get_employee_by_md5'),
    path('employees/image-by-md5/<str:image_md5>/', views.serve_employee_image_by_md5, name='serve_employee_image_by_md5'),
    path('mark/', views.mark_attendance, name='mark_attendance'),
    path('verify-face/', views.verify_face, name='verify_face'),
    path('hrregistration/', views.registration, name='registration'),
    path('login/', views.login, name='login'),
    path('attendance-report/', views.attendance_report_with_employee_details, name='attendance_report'),
    path('ip-login/', views.ip_login, name='ip-login'),
    path('my-ip/', views.my_ip, name='my-ip'),
    path('allowed-devices/', views.allowed_devices, name='allowed-devices'),
    path('allowed-devices/<int:device_id>/', views.allowed_devices, name='allowed-devices-detail'),
    path('global-departments/', views.get_global_departments, name='global-departments'),
    path('spoofing-reports/', views.get_spoofing_attempts, name='get_spoofing_attempts'),
    path('spoofing-reports/delete/', views.delete_spoofing_attempts, name='delete_spoofing_attempts'),
    
    # Manual Shift and Department URLs (Functional Views)
    path('shifts/', shift_list_create, name='shift-list'),
    path('shifts/<int:pk>/', shift_detail, name='shift-detail'),
    path('departments/', department_list_create, name='department-list'),
    path('departments/<int:pk>/', department_detail, name='department-detail'),

    # New Employee Features
    path('employee/today-status/', views.today_status, name='today_status'),
    path('employee/my-attendance/', views.my_attendance_report, name='my_attendance_report'),
    
    # Leave Management
    path('leaves/apply/', views.apply_leave, name='apply_leave'),
    path('leaves/my-leaves/', views.my_leaves, name='my_leaves'),
    path('leaves/pending/', views.pending_leaves, name='pending_leaves'),
    path('leaves/history/', views.leave_history, name='leave_history'),
    path('leaves/<int:leave_id>/status/', views.update_leave_status, name='update_leave_status'),
    path('leave-types/', views.leave_type_list_create, name='leave-type-list'),
    path('leave-types/<int:pk>/', views.leave_type_detail, name='leave-type-detail'),


    # Roster URLs
    path('roster/', get_monthly_roster, name='get-monthly-roster'),
    path('roster/assign/', assign_shift, name='assign-shift'),
    path('roster/export/', views.export_roster_csv, name='export-roster-csv'),
    path('roster/export-xlsx/', views.export_roster_xlsx, name='export-roster-xlsx'),
    path('roster/import-xlsx/', views.import_roster_xlsx, name='import-roster-xlsx'),
    path('roster/preview-xlsx/', views.preview_roster_xlsx, name='preview-roster-xlsx'),
    path('roster/approve-data/', views.approve_roster_data, name='approve-roster-data'),
    
    path('roster-report/', reports.roster_attendance_report, name='roster-attendance-report'),

    # Canteen Token Endpoints
    path('canteen/issue-token/', views.issue_canteen_token, name='canteen-issue-token'),
    path('canteen/today-summary/', views.get_canteen_today_summary, name='canteen-today-summary'),
    path('canteen/history/', views.get_canteen_token_history, name='canteen-history'),
    path('canteen/rules/', views.manage_canteen_rules, name='canteen-rules'),

    # Employee Notifications
    path('employee/notifications/', get_employee_notifications, name='employee-notifications'),
    path('employee/notifications/mark-read/', mark_notifications_read, name='mark-notifications-read'),
    path('employee/notifications/clear/', clear_notifications, name='clear-notifications'),
    path('employee/notifications/unread-count/', get_unread_count, name='get-unread-count'),
    path('admin/send-notification/', send_admin_notification, name='admin-send-notification'),
    path('register-push-token/', register_push_token, name='register-push-token'),
    path('employee/notifications/active-popup/', get_active_popup_announcement, name='active-popup-announcement'),
    path('set-employee-password/', views.set_employee_password, name='set-employee-password'),
    path('set_employee_password/', views.set_employee_password, name='set_employee_password'),
    path('data-entitlements/', views.get_data_entitlements, name='data-entitlements'),
    path('get_data_departments/', views.get_data_departments, name='get-data-departments'),
    path('get_data_designation/', views.get_data_designation, name='get-data-designation'),
    path('getprimaryandadditionalrole/', views.getprimaryandadditionalrole, name='getprimaryandadditionalrole'),
    path('get_next_department_code/', views.get_next_department_code, name='get-next-department-code'),
    path('get_next_designation_code/', views.get_next_designation_code, name='get-next-designation-code'),
    path('addnew_department/', views.addnew_department, name='addnew-department'),
    path('addnew_designation/', views.addnew_designation, name='addnew-designation'),
    path('update_department/<str:dept_code>/', views.update_department, name='update-department'),
    path('update_designation/<str:desig_code>/', views.update_designation, name='update-designation'),
    path('employees_birthdays_today/', views.get_todays_birthdays, name='employees-birthdays-today'),
    path('check_employee_id/', views.check_employee_id, name='check-employee-id'),
    path('create_employee/', views.create_employee, name='create-employee'),

    path('update_employee/<str:employee_id>/', views.update_employee, name='update-employee'),
    path('get_employee_by_id/<str:employee_id>/', views.get_employee_by_id, name='get-employee-by-id'),
    path('get_employees_with_labels/', views.get_employees_with_labels, name='get-employees-with-labels'),
    path('upload-gridfs/', views.upload_file, name='upload-gridfs'),
    path('gridfs/<str:file_id>/', views.serve_file, name='serve-gridfs-file'),

    # HR Helpdesk & Support Tickets
    path('helpdesk/categories/', views.get_helpdesk_categories, name='helpdesk-categories'),
    path('helpdesk/tickets/', views.get_helpdesk_tickets, name='helpdesk-tickets'),
    path('helpdesk/tickets/create/', views.create_helpdesk_ticket, name='helpdesk-tickets-create'),
    path('helpdesk/tickets/<str:ticket_id>/update/', views.update_helpdesk_ticket, name='helpdesk-tickets-update'),

    # Mobile Full Profile, Photo & Change Password
    path('employee/full-profile/', views.get_full_employee_profile, name='employee-full-profile'),
    path('employee-profile-photo/<str:employee_id>/', views.serve_employee_profile_photo, name='employee-profile-photo'),
    path('change-password/', views.change_employee_password, name='change-employee-password'),

    # Mobile Self-Activation / Account Setup
    path('mobile-employee-check/', views.mobile_employee_check, name='mobile-employee-check'),
    path('mobile-create-login/', views.mobile_create_login, name='mobile-create-login'),

    # Payroll & Salary Management
    path('payroll/monthly/', views.monthly_payroll_view, name='monthly-payroll'),
    path('payroll/update-entry/', views.update_payroll_entry, name='update-payroll-entry'),
    path('payroll/approve/', views.approve_monthly_payroll, name='approve-monthly-payroll'),
    path('payroll/export-bank-sheet/', views.export_bank_transfer_sheet, name='export-bank-sheet'),
    path('payroll/export-pf-ecr/', views.export_pf_ecr, name='export-pf-ecr'),
    path('payroll/export-esi-return/', views.export_esi_return, name='export-esi-return'),
    path('payroll/payslip-pdf/<str:employee_id>/', views.download_payslip_html, name='download-payslip-html'),
    path('payroll/employee-payslips/<str:employee_id>/', views.employee_payslip_history, name='employee-payslip-history'),
]





