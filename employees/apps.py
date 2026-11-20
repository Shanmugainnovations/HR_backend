import os
import sys

from django.apps import AppConfig


class EmployeesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'employees'

    def ready(self):
        if len(sys.argv) > 1 and sys.argv[1] not in ('runserver', 'run_gunicorn'):
            return
        if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
            return
        if os.environ.get('RUN_MAIN') == 'false':
            return

        try:
            from employees.services.attendance_listener import start_attendance_listener
            start_attendance_listener()
        except Exception as e:
            print(f"⚠️ Attendance listener start skipped: {e}")

