"""
Attendance Kiosk Views Package
Handles face recognition kiosk attendance marking and identity verification.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from employees.views.attendance_management.attendance import mark_attendance, get_optimized_encodings

# Export kiosk attendance endpoints
__all__ = ['mark_attendance', 'get_optimized_encodings']
