import os
from django.core.management.base import BaseCommand
from employees.models import Register, AllowedDevice, SpoofingAttempt, Shift, Department, EmployeeShiftSchedule

class Command(BaseCommand):
    help = 'Populate missing id fields for models in MongoDB'

    def handle(self, *args, **options):
        models_to_check = [
            Register, AllowedDevice, SpoofingAttempt, Shift, Department, EmployeeShiftSchedule
        ]

        for model in models_to_check:
            self.stdout.write(f"Checking {model.__name__}...")
            count = 0
            for i, obj in enumerate(model.objects.all(), 1):
                if not getattr(obj, 'id', None):
                    # Set id = i if not set
                    obj.id = i
                    try:
                        obj.save()
                        count += 1
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"Error saving {model.__name__} {obj}: {e}"))
            
            self.stdout.write(self.style.SUCCESS(f"Updated {count} records for {model.__name__}"))

