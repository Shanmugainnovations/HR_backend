import os
from datetime import datetime, timezone, timedelta
from rest_framework.permissions import AllowAny
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from employees.models import Profile
from employees.views.common.utils import get_mongo_client

try:
    import zoneinfo
    IST = zoneinfo.ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))


@api_view(['GET'])
@permission_classes([AllowAny])
def get_todays_birthdays(request):
    """Fetch all employees celebrating their birthday today and upcoming."""
    try:
        today = datetime.now(IST).date()
        today_birthdays = []
        upcoming_birthdays = []
        
        current_emp_id = str(request.GET.get('employee_id') or request.GET.get('current_employee_id') or '').strip()
        department_filter = request.GET.get('department')
        from employees.views.common.utils import resolve_department_filter
        dept_ctx = resolve_department_filter(department_filter)
        is_dept_match = dept_ctx['is_match']

        dept_map = {}
        desig_map = {}
        profiles = []

        try:
            client = get_mongo_client()
            db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
            db = client[db_name]
            
            # Build department & designation lookups
            for d in db['backend_diagnostics_Departments'].find({}, {'department_code': 1, 'department_name': 1, '_id': 0}):
                if d.get('department_code'):
                    dept_map[d['department_code']] = d.get('department_name')
            for dg in db['backend_diagnostics_Designation'].find({}, {'Designation_code': 1, 'designation': 1, '_id': 0}):
                if dg.get('Designation_code'):
                    desig_map[dg['Designation_code']] = dg.get('designation')

            profiles = list(db['backend_diagnostics_profile'].find({}, {
                'employeeId': 1, 'employeeName': 1, 'department': 1,
                'designation': 1, 'email': 1, 'mobileNumber': 1,
                'profileImage': 1, 'dateOfBirth': 1, '_id': 0
            }))
        except Exception:
            profiles = Profile.objects.all().values(
                'employeeId', 'employeeName', 'department',
                'designation', 'email', 'mobileNumber',
                'profileImage', 'dateOfBirth'
            )

        is_my_birthday = False

        for prof in profiles:
            emp_id = str(prof.get('employeeId') if isinstance(prof, dict) else getattr(prof, 'employeeId', '') or '')
            raw_dept = str(prof.get('department') if isinstance(prof, dict) else getattr(prof, 'department', '') or '')
            
            # Resolve department names
            resolved_dept_names = []
            for dcode in raw_dept.split(','):
                dcode = dcode.strip()
                resolved_dept_names.append(dept_map.get(dcode, dcode))
            display_dept = ", ".join(resolved_dept_names) if resolved_dept_names else "General"

            raw_desig = str(prof.get('designation') if isinstance(prof, dict) else getattr(prof, 'designation', '') or '')
            display_desig = desig_map.get(raw_desig, raw_desig) or "Employee"

            if dept_ctx['is_filtered'] and not (is_dept_match(raw_dept) or is_dept_match(display_dept)):
                continue

            dob_raw = prof.get('dateOfBirth') if isinstance(prof, dict) else getattr(prof, 'dateOfBirth', None)
            if not dob_raw:
                continue

            dob_date = None
            if isinstance(dob_raw, datetime):
                dob_date = dob_raw.date()
            elif hasattr(dob_raw, 'date'):
                dob_date = dob_raw.date()
            elif isinstance(dob_raw, str):
                try:
                    dob_date = datetime.fromisoformat(dob_raw.replace('Z', '+00:00')).date()
                except Exception:
                    try:
                        dob_date = datetime.strptime(dob_raw[:10], '%Y-%m-%d').date()
                    except Exception:
                        pass

            if not dob_date:
                continue

            # Check if Today
            if dob_date.month == today.month and dob_date.day == today.day:
                if current_emp_id and emp_id == current_emp_id:
                    is_my_birthday = True

                today_birthdays.append({
                    "employeeId": emp_id,
                    "employeeName": prof.get('employeeName') if isinstance(prof, dict) else prof.employeeName,
                    "department": display_dept,
                    "designation": display_desig,
                    "email": prof.get('email') if isinstance(prof, dict) else prof.email,
                    "mobileNumber": prof.get('mobileNumber') if isinstance(prof, dict) else prof.mobileNumber,
                    "profileImage": prof.get('profileImage') if isinstance(prof, dict) else getattr(prof, 'profileImage', None),
                    "dateOfBirth": dob_date.strftime("%d %b"),
                    "is_today": True
                })
            else:
                # Check upcoming (next 14 days)
                try:
                    this_year_bday = datetime(today.year, dob_date.month, dob_date.day).date()
                    if this_year_bday < today:
                        this_year_bday = datetime(today.year + 1, dob_date.month, dob_date.day).date()
                    days_diff = (this_year_bday - today).days
                    if 1 <= days_diff <= 14:
                        upcoming_birthdays.append({
                            "employeeId": emp_id,
                            "employeeName": prof.get('employeeName') if isinstance(prof, dict) else prof.employeeName,
                            "department": display_dept,
                            "designation": display_desig,
                            "dateOfBirth": dob_date.strftime("%d %b"),
                            "days_left": days_diff,
                            "is_today": False
                        })
                except Exception:
                    pass

        # Sort upcoming by days_left
        upcoming_birthdays.sort(key=lambda x: x.get('days_left', 99))

        return JsonResponse({
            "is_my_birthday": is_my_birthday,
            "today": today_birthdays,
            "upcoming": upcoming_birthdays,
            "employees": today_birthdays # Backward compatibility
        }, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
