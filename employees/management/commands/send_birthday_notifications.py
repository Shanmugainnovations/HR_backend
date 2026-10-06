import os
from datetime import datetime, timezone, timedelta
from django.core.management.base import BaseCommand
from employees.views.common.utils import get_mongo_client, get_inactive_employee_ids
from employees.views.global_management.birthdays import trigger_birthday_push_notifications, _parse_dob

try:
    import zoneinfo
    IST = zoneinfo.ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))


class Command(BaseCommand):
    help = 'Check all employee birthdays today and dispatch automatic push notifications & in-app wishes'

    def handle(self, *args, **options):
        today = datetime.now(IST).date()
        today_str = today.strftime('%Y-%m-%d')
        self.stdout.write(f"Checking employee birthdays for date: {today_str}...")

        try:
            client = get_mongo_client()
            db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
            db = client[db_name]

            profiles = list(db['backend_diagnostics_profile'].find({}, {
                'employeeId': 1, 'employeeName': 1, 'dateOfBirth': 1, '_id': 0
            }))
            inactive_ids = get_inactive_employee_ids()

            today_celebrants = []
            for prof in profiles:
                emp_id = str(prof.get('employeeId') or '').strip()
                if not emp_id or emp_id in inactive_ids:
                    continue

                dob_raw = prof.get('dateOfBirth')
                dob_date = _parse_dob(dob_raw)
                if dob_date and dob_date.month == today.month and dob_date.day == today.day:
                    today_celebrants.append({
                        "employeeId": emp_id,
                        "employeeName": prof.get('employeeName') or 'Employee'
                    })

            self.stdout.write(f"Found {len(today_celebrants)} employee(s) celebrating birthday today.")

            if today_celebrants:
                sent_count = trigger_birthday_push_notifications(today_celebrants, today_str)
                self.stdout.write(self.style.SUCCESS(
                    f"Successfully sent {sent_count} new birthday push notifications / in-app messages!"
                ))
            else:
                self.stdout.write("No birthdays today. Nothing to send.")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error checking birthdays: {e}"))
