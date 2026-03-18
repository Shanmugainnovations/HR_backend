from django.urls import path
from . import views
from .views import reports
from .views.shifts import (
    shift_list_create, shift_detail,
    department_list_create, department_detail,
    get_monthly_roster, assign_shift
)

urlpatterns = [
    path('register/', views.register_employee, name='register_employee'),
    path('employees/', views.get_all_employees_with_images, name='get_all_employees'),
    path('employees_from_global/', views.get_all_employee_from_global),
    path("employees/<str:employee_id>/encode_face/", views.encode_employee_face),
    path('employees/<str:employee_id>/enable_face/', views.enable_facial_recognition),
    path('employees/<str:employee_id>/disable_face/', views.disable_facial_recognition),
    path('serve-file/<str:file_id>/', views.serve_file, name="serve_file"),
    path('get_device_info/', views.get_device_info, name="serve_file"),
    path('employees/md5/<str:image_md5>/', views.get_employee_by_md5, name='get_employee_by_md5'),
    path('mark/', views.mark_attendance, name='mark_attendance'),
    path('hrregistration/', views.registration, name='registration'),
    path('login/', views.login, name='login'),
    path('attendance-report/', views.attendance_report_with_employee_details, name='attendance_report'),
    path('ip-login/', views.ip_login, name='ip-login'),
    path('my-ip/', views.my_ip, name='my-ip'),
    path('allowed-devices/', views.allowed_devices, name='allowed-devices'),
    path('allowed-devices/<int:device_id>/', views.allowed_devices, name='allowed-devices-detail'),
    path('spoofing-reports/', views.get_spoofing_attempts, name='get_spoofing_attempts'),
    path('spoofing-reports/delete/', views.delete_spoofing_attempts, name='delete_spoofing_attempts'),
    
    # Manual Shift and Department URLs (Functional Views)
    path('shifts/', shift_list_create, name='shift-list'),
    path('shifts/<int:pk>/', shift_detail, name='shift-detail'),
    path('departments/', department_list_create, name='department-list'),
    path('departments/<int:pk>/', department_detail, name='department-detail'),

    # Roster URLs
    path('roster/', get_monthly_roster, name='get-monthly-roster'),
    path('roster/assign/', assign_shift, name='assign-shift'),
    path('roster/export/', views.export_roster_csv, name='export-roster-csv'),
    path('roster/export-xlsx/', views.export_roster_xlsx, name='export-roster-xlsx'),
    path('roster/import-xlsx/', views.import_roster_xlsx, name='import-roster-xlsx'),
    
    path('roster-report/', reports.roster_attendance_report, name='roster-attendance-report'),
]
