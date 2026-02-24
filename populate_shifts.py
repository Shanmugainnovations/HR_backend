import os
import django
import sys
from datetime import datetime

# Setup Django environment
sys.path.append('/Users/parthibanmurugan/Desktop/HR/hr_backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hr_backend.settings')
django.setup()

from employees.models import Shift, Department

def parse_time(t_str):
    # Normalize input strings
    t_str = t_str.strip().replace("To", "").strip()
    t_str = t_str.replace("p.m", " PM").replace("P.M", " PM").replace("a.m", " AM").replace("A.M", " AM")
    # Handle "2p.m to 10p.m" type strings
    if "to" in t_str.lower():
         t_str = t_str.lower().replace("to", "").upper()
    
    formats = ["%I:%M %p", "%I %p", "%H:%M"]
    
    for fmt in formats:
        try:
            return datetime.strptime(t_str, fmt).time()
        except ValueError:
            continue
    return None

def run():
    # 1. Shifts Data (A-W)
    shifts_data = [
        ("A", "9:30 AM", "5:30 PM"),
        ("B", "09 AM", "05 PM"),
        ("C", "08 AM", "04 PM"),
        ("D", "10 AM", "06 PM"),
        ("E", "08 AM", "05 PM"),
        ("F", "08 PM", "08 AM"),
        ("G", "09 AM", "06 PM"),
        ("H", "11 AM", "07 PM"),
        ("I", "12 PM", "08 PM"),
        ("J", "11 AM", "08 PM"),
        ("K", "07 AM", "04 PM"),
        ("L", "10 AM", "05 PM"),
        ("M", "10 AM", "07 PM"),
        ("N", "01 PM", "09 PM"),
        ("O", "07 PM", "07 AM"),
        ("P", "06 AM", "03 PM"),
        ("Q", "07 AM", "02 PM"),
        ("R", "07 AM", "03 PM"),
        ("S", "8:30 AM", "4:30 PM"),
        ("T", "09 AM", "04 PM"),
        ("U", "01 PM", "08 PM"),
        ("V", "02 PM", "10 PM"), # "2p.m to 10p.m"
        ("W", "07:30 PM", "07:30 AM"),
    ]

    print("Creating/Updating Shifts...")
    shift_objs = {}
    for name, start, end in shifts_data:
        s_time = parse_time(start)
        e_time = parse_time(end)
        
        if not s_time or not e_time:
            print(f"Error parsing time for Shift {name}: {start} - {end}")
            continue

        shift, created = Shift.objects.get_or_create(
            name=name,
            defaults={'start_time': s_time, 'end_time': e_time}
        )
        shift_objs[name] = shift
        if created:
            print(f"Created Shift {name}")
        else:
            shift.start_time = s_time
            shift.end_time = e_time
            shift.save()
            print(f"Updated Shift {name}")

    # 2. Departments Mapping
    # Based on "Department & Timings" table
    dept_map = {
        "Facility": ["A", "B", "C", "D"], # Assuming D based on list, though image text was slightly ambiguous/repetitive
        "House Keeping": ["A", "B", "C", "D", "E", "F"],
        "Dietitics": ["A", "B", "C"],
        "Bio Medical": ["A"],
        "Front Office": ["A", "B", "C", "D", "E", "F"], # F is 07 PM to 07 AM (O in main list? Or F? F is 08PM-08AM. 07PM-07AM is O. The mismatch is real.)
                                                       # Wait, User provided "Overall Shift Details" with codes A-W.
                                                       # And "Dept & Timings" with codes A,B,C... under specific depts.
                                                       # Crucially, under "Front Office", "F" is listed as 07 PM To 07 AM.
                                                       # But in Overall list, "F" is 08 PM To 08 AM. "O" is 07 PM To 07 AM.
                                                       # It seems the Dept table uses local codes (A,B,C...) OR the Overall list is the master key.
                                                       # Given the user requested "All Over Shift Details", I will assume the Overall List (A-W) is the source of truth for NAMES.
                                                       # I will map departments to the Overall Shift Names based on the TIMINGS or explicit codes if they match.
                                                       
        "HR": ["A"],
        "Insurance": ["A", "B", "C"],
        "IT": ["A"],
        "Lab": ["A", "B", "C", "D", "E"], # E here is 08 PM to 08 AM (which is F globally).
        "Lab Marketing": ["A", "B", "C", "D"], # D is 09 AM to 06 PM (which is G globally).
        "Marketing": ["A", "B"],
        "MRD": ["A"],
        "Nursing": ["A", "B", "C", "K", "E", "G", "N", "M", "J"], # Mapped based on timings from previous analysis or visually
        "PA": ["A", "B"],
        "Operations": ["A"],
        "Pharmacy": ["A", "B", "C", "D", "H", "I", "N", "F"], # Mapped loosely
        "Physiotheraphy": ["A", "L"], 
        "RT": ["S", "T", "D", "R", "H", "I", "F"], # 8:30-4:30(S), 09-05(T? B?), 10-06(D) ...
        "STores": ["A", "B"],
        "Transplant": ["A"],
        "CS": ["A"],
        "Cardiology": ["B"]
    }

    # Redoing logic: The User explicitly gave "S.no, Timings, Name of Shift, No Depts".
    # And then "S.no Department ... A B C".
    # It is highly likely the codes A, B, C in the Dept table refer to the GLOBAL codes A, B, C.
    # Where there is a mismatch (e.g. Lab E = 08PM-08AM, but Global E = 08AM-05PM), it implies the Dept table might have typos OR "E" provides a slot.
    # HOWEVER, to be safe and precise, I will map based on the Shift NAME if present in the dept list, 
    # AND I will robustly handle the "Timings" provided in the Dept table by finding the matching Global Shift.

    # Let's trust the Global List (A-W) as the definitions.
    # Then for each Dept, we look at the Timings string strings.
    
    dept_timings_raw = {
        "Facility": ["08 AM To 04 PM", "09 AM To 05 PM", "12 PM To 08 PM", "08 PM To 08 AM"],
        "House Keeping": ["07 AM To 04 PM", "06 AM To 03 PM", "09 AM To 06 PM", "11 AM To 08 PM", "08 AM To 05 PM", "07 PM To 07 AM"],
        "Dietitics": ["08 AM To 04 PM", "09 AM To 05 PM", "11 AM To 07 PM"],
        "Bio Medical": ["09 AM To 05 PM"],
        "Front Office": ["07 AM To 03 PM", "10 AM To 06 PM", "09 AM To 05 PM", "11 AM To 07 PM", "02 PM To 10 PM", "07 PM To 07 AM"],
        "HR": ["9:30 AM To 5:30 PM"],
        "Insurance": ["09 AM To 05 PM", "9:30 AM To 5:30 PM", "10 AM To 06 PM"],
        "IT": ["9:30 AM To 5:30 PM"],
        "Lab": ["9:30 AM To 5:30 PM", "08 AM To 04 PM", "09 AM To 05 PM", "12 PM To 08 PM", "08 PM To 08 AM"],
        "Lab Marketing": ["08 AM To 05 PM", "10 AM To 07 PM", "11 AM To 08 PM", "09 AM To 06 PM"],
        "Marketing": ["10 AM To 06 PM", "9:30 AM To 5:30 PM"],
        "MRD": ["9:30 AM To 5:30 PM"],
        "Nursing": ["07 AM To 02 PM", "01 PM To 08 PM", "7:30 PM To 7:30 AM", "07 AM To 04 PM", "08 AM To 05 PM", "09 AM To 06 PM", "01 PM To 09 PM", "10 AM To 07 PM", "11 AM To 08 PM"],
        "PA": ["09 AM To 05 PM", "10 AM To 06 PM"],
        "Operations": ["9:30 AM To 5:30 PM"],
        "Pharmacy": ["08 AM To 04 PM", "09 AM To 05 PM", "9:30 AM To 5:30 PM", "10 AM To 06 PM", "11 AM To 07 PM", "12 PM To 08 PM", "01 PM To 09 PM", "08 PM To 08 AM"],
        "Physiotheraphy": ["9:30 AM To 5:30 PM", "10 AM To 05 PM"],
        "RT": ["8:30 AM To 4:30 PM", "09 AM To 05 PM", "10 AM To 06 PM", "09 AM To 04 PM", "10 AM To 05 PM", "08 AM To 04 PM", "10 AM To 06 PM", "11 AM To 07 PM", "12 PM To 08 PM", "08 PM To 08 AM"],
        "STores": ["09 AM To 05 PM", "9:30 AM To 5:30 PM"],
        "Transplant": ["9:30 AM To 5:30 PM"],
        "CS": ["9:30 AM To 5:30 PM"],
        "Cardiology": ["09 AM To 05 PM"]
    }

    print("Mapping Departments to Global Shifts...")
    # Reverse lookup map: (Start, End) -> Shift
    time_map = {}
    for s in Shift.objects.all():
        time_map[(s.start_time, s.end_time)] = s

    for dept_name, timings in dept_timings_raw.items():
        dept, _ = Department.objects.get_or_create(name=dept_name)
        shifts_found = []
        
        for t_str in timings:
            if "flexible" in t_str: t_str = "09 AM To 05 PM"
            
            parts = t_str.split(" To ")
            if len(parts) != 2: 
                # Try simple ' to ' case from RT
                parts = t_str.lower().split(" to ")
                if len(parts) != 2:
                    continue
            
            s = parse_time(parts[0])
            e = parse_time(parts[1])
            
            if s and e:
                # Find matching shift
                match = time_map.get((s, e))
                if match:
                    shifts_found.append(match)
                else:
                    print(f"  No exact global shift for {dept_name}: {s}-{e}")
        
        if shifts_found:
            dept.shifts.clear() # Clear existing to avoid duplicates
            dept.shifts.set(shifts_found)
            print(f"Updated {dept_name} with {len(shifts_found)} shifts")

        else:
            print(f"Warning: No shifts mapped for {dept_name}")

if __name__ == "__main__":
    run()
