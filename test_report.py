import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hr_backend.settings")
django.setup()

from datetime import datetime, date
import pytz
from employees.models import EmployeeAttendance

IST = pytz.timezone('Asia/Kolkata')
att = EmployeeAttendance.objects.last()
print("DB time:", att.attendence_time)
print("IST time:", att.attendence_time.astimezone(IST))
print("Formatted:", att.attendence_time.astimezone(IST).strftime('%H:%M:%S'))
