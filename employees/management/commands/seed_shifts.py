from django.core.management.base import BaseCommand
from employees.models import Shift, Department
from datetime import datetime

class Command(BaseCommand):
    help = 'Seeds shifts and departments based on HR requirement'

    def handle(self, *args, **kwargs):
        self.stdout.write("Seeding Shifts and Departments...")

        # 1. Define Shifts (Name -> Start, End)
        # Format: HH:MM
        shift_data = {
            'A': ('09:30', '17:30'),
            'B': ('09:00', '17:00'),
            'C': ('08:00', '16:00'),
            'D': ('10:00', '18:00'),
            'E': ('08:00', '17:00'),
            'F': ('20:00', '08:00'),
            'G': ('09:00', '18:00'),
            'H': ('11:00', '19:00'),
            'I': ('12:00', '20:00'),
            'J': ('11:00', '20:00'),
            'K': ('07:00', '16:00'),
            'L': ('10:00', '17:00'),
            'M': ('10:00', '19:00'),
            'N': ('13:00', '21:00'),
            'O': ('19:00', '07:00'),
            'P': ('06:00', '15:00'),
            'Q': ('07:00', '14:00'),
            'R': ('07:00', '15:00'),
            'S': ('08:30', '16:30'),
            'T': ('09:00', '16:00'),
            'U': ('13:00', '20:00'),
            'V': ('14:00', '22:00'),
            'W': ('19:30', '07:30'),
        }

        # 2. Define Departments (Name -> List of Shift Names)
        dept_data = {
            'Facility': ['C', 'B', 'I', 'F'],
            'House Keeping': ['K', 'P', 'G', 'J', 'E', 'O'],
            'Dietitics': ['C', 'B', 'H'],
            'Bio Medical': ['B'],
            'Front Office': ['R', 'D', 'B', 'H', 'V', 'O'],
            'HR': ['A'],
            'Insurance': ['B', 'A', 'D'],
            'IT': ['A'],
            'Lab': ['A', 'C', 'B', 'I', 'F'],
            'Lab Marketing': ['E', 'M', 'J', 'G'],
            'Marketing': ['D', 'A'],
            'MRD': ['A'],
            'Nursing': ['Q', 'U', 'W', 'K', 'E', 'G', 'N', 'M', 'J'],
            'PA': ['B', 'D'],
            'Operations': ['A'],
            'Pharmacy': ['C', 'B', 'A', 'D', 'H', 'I', 'N', 'F'],
            'Physiotheraphy': ['A', 'L'],
            'RT': ['S', 'B', 'D', 'T', 'L', 'C', 'H', 'I', 'F'],
            'Stores': ['B', 'A'],
            'Transplant': ['A'],
            'CS': ['A'],
            'Cardiology': ['B'],
        }

        # Clear existing data? Or Update?
        # User said "update", but given the massive restructure, it's safer to ensure
        # we have exactly these.
        # However, to avoid breaking existing foreign keys if referenced elsewhere, 
        # we try to get_or_create or update_or_create.
        
        shift_objs = {}

        for name, (start, end) in shift_data.items():
            s_obj, created = Shift.objects.update_or_create(
                name=name,
                defaults={
                    'start_time': datetime.strptime(start, '%H:%M').time(),
                    'end_time': datetime.strptime(end, '%H:%M').time(),
                    'is_active': True
                }
            )
            shift_objs[name] = s_obj
            action = "Created" if created else "Updated"
            self.stdout.write(f"{action} Shift {name}: {start}-{end}")

        for dept_name, shift_names in dept_data.items():
            dept_obj, created = Department.objects.get_or_create(name=dept_name)
            
            # Map shift names to objects
            shifts_to_add = []
            for s_name in shift_names:
                if s_name in shift_objs:
                    shifts_to_add.append(shift_objs[s_name])
                else:
                    self.stdout.write(self.style.WARNING(f"Shift {s_name} not found for {dept_name}"))
            
            # Set shifts (replaces existing if any, to match the requirement exactly)
            dept_obj.shifts.set(shifts_to_add)
            
            action = "Created" if created else "Updated"
            self.stdout.write(f"{action} Dept {dept_name} with {len(shifts_to_add)} shifts")

        self.stdout.write(self.style.SUCCESS('Successfully seeded Shifts and Departments'))
