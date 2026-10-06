import os
from datetime import datetime, timezone, timedelta
from rest_framework.permissions import AllowAny
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from employees.models import Profile
from employees.views.common.utils import get_mongo_client, get_inactive_employee_ids

try:
    import zoneinfo
    IST = zoneinfo.ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))


def trigger_birthday_push_notifications(today_birthdays, today_str):
    """
    Checks today's birthdays and sends:
    1. A celebratory push notification & in-app message to each employee celebrating their birthday today.
    Idempotent: Only sends once per employee per birthday date (YYYY-MM-DD).
    """
    if not today_birthdays:
        return 0

    sent_count = 0
    try:
        from employees.views.mobile_app.notifications import get_notifications_collection, send_expo_push_notification
        col = get_notifications_collection()
        now_dt = datetime.now()

        for bday in today_birthdays:
            emp_id = str(bday.get('employeeId', '')).strip()
            emp_name = bday.get('employeeName', 'Colleague')
            if not emp_id:
                continue

            emp_match = [emp_id]
            if emp_id.isdigit():
                emp_match.append(int(emp_id))

            # Idempotency check: Don't send multiple times on the same date
            already_sent = col.find_one({
                "employee_id": {"$in": emp_match},
                "category": "birthday",
                "birthday_date": today_str
            })

            if not already_sent:
                title = f"Happy Birthday, {emp_name}! 🎂🎉"
                message = f"Dear {emp_name}, Shanmuga HR wishes you a very Happy Birthday! May your day and year ahead be filled with happiness, health, and great success! 🎈✨"

                # 1. In-App Notification Record
                col.insert_one({
                    "employee_id": str(emp_id),
                    "title": title,
                    "message": message,
                    "category": "birthday",
                    "birthday_date": today_str,
                    "is_read": False,
                    "action_url": "/profile",
                    "created_at": now_dt.strftime('%Y-%m-%d %H:%M:%S'),
                    "created_at_ts": now_dt.timestamp()
                })

                # 2. Remote Expo Push Notification to Employee's Mobile App
                try:
                    send_expo_push_notification(
                        employee_ids=[emp_id],
                        title=title,
                        body=f"Shanmuga HR wishes you a wonderful and joyful Birthday! Tap to celebrate 🎈",
                        data={"category": "birthday", "screen": "Profile"}
                    )
                except Exception as push_err:
                    print(f"[Birthday] Push notification error for {emp_id}:", push_err)

                sent_count += 1
                print(f"[Birthday] Birthday push notification & in-app wish sent to {emp_name} ({emp_id})")

    except Exception as e:
        print("[Birthday] Error triggering birthday notifications:", e)

    return sent_count


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
        inactive_ids = get_inactive_employee_ids()

        for prof in profiles:
            emp_id = str(prof.get('employeeId') if isinstance(prof, dict) else getattr(prof, 'employeeId', '') or '')
            if emp_id in inactive_ids:
                continue
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

        # Auto-send birthday push notifications & in-app wishes for today's celebrants
        if today_birthdays:
            try:
                trigger_birthday_push_notifications(today_birthdays, today.strftime('%Y-%m-%d'))
            except Exception as auto_notif_err:
                print("[Birthday] Auto-notification error:", auto_notif_err)

        return JsonResponse({
            "is_my_birthday": is_my_birthday,
            "today": today_birthdays,
            "upcoming": upcoming_birthdays,
            "employees": today_birthdays # Backward compatibility
        }, status=200)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


MONTH_NAMES = {
    1: 'January', 2: 'February', 3: 'March', 4: 'April',
    5: 'May', 6: 'June', 7: 'July', 8: 'August',
    9: 'September', 10: 'October', 11: 'November', 12: 'December'
}


def _parse_dob(dob_raw):
    """Safely parse various DOB types into datetime.date."""
    if not dob_raw:
        return None
    if isinstance(dob_raw, datetime):
        return dob_raw.date()
    if hasattr(dob_raw, 'date') and callable(getattr(dob_raw, 'date')):
        return dob_raw.date()
    if isinstance(dob_raw, str):
        dob_str = dob_raw.strip()
        try:
            return datetime.fromisoformat(dob_str.replace('Z', '+00:00')).date()
        except Exception:
            pass
        for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d', '%d %b %Y', '%d-%b-%Y'):
            try:
                return datetime.strptime(dob_str[:10], fmt).date()
            except Exception:
                continue
    return None


@api_view(['POST', 'GET'])
@permission_classes([AllowAny])
def trigger_birthday_notifications_api(request):
    """
    Dedicated endpoint to manually or cron-trigger birthday push notifications.
    Can be called daily via cron or external scheduler.
    """
    try:
        today = datetime.now(IST).date()
        today_str = today.strftime('%Y-%m-%d')
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

        sent = trigger_birthday_push_notifications(today_celebrants, today_str)
        return JsonResponse({
            "success": True,
            "date": today_str,
            "celebrants_count": len(today_celebrants),
            "notifications_dispatched": sent,
            "celebrants": today_celebrants
        })
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@api_view(['POST'])
@permission_classes([AllowAny])
def send_birthday_wish_api(request):
    """
    Sends a birthday wish notification from one colleague to another.
    Creates an in-app notification doc and dispatches a real-time Expo push notification.
    """
    try:
        sender_id = str(request.data.get('sender_id') or getattr(request, 'authenticated_employee_id', '') or '').strip()
        sender_name = request.data.get('sender_name') or 'A Colleague'
        receiver_id = str(request.data.get('receiver_id') or '').strip()
        receiver_name = request.data.get('receiver_name') or 'Colleague'
        custom_message = request.data.get('message')

        if not receiver_id:
            return JsonResponse({"error": "receiver_id is required"}, status=400)

        if sender_id and sender_id == receiver_id:
            return JsonResponse({"error": "You cannot wish yourself"}, status=400)

        from employees.views.mobile_app.notifications import get_notifications_collection, send_expo_push_notification
        col = get_notifications_collection()
        now_dt = datetime.now()

        title = f"{sender_name} wished you a Happy Birthday! 🎂🎉"
        body = custom_message or f"{sender_name} sent you warm birthday wishes! Wishing you a fantastic and successful year ahead! 🎈✨"

        # 1. Store in-app notification in MongoDB for the receiver
        col.insert_one({
            "employee_id": str(receiver_id),
            "sender_id": str(sender_id) if sender_id else "",
            "sender_name": sender_name,
            "title": title,
            "message": body,
            "category": "birthday_wish",
            "is_read": False,
            "action_url": "/profile",
            "created_at": now_dt.strftime('%Y-%m-%d %H:%M:%S'),
            "created_at_ts": now_dt.timestamp()
        })

        # 2. Send Expo push notification to receiver's mobile device
        try:
            send_expo_push_notification(
                employee_ids=[receiver_id],
                title=title,
                body=body,
                data={"category": "birthday_wish", "sender_id": sender_id, "screen": "Profile"}
            )
        except Exception as push_err:
            print(f"[Birthday Wish] Error sending push notification to {receiver_id}:", push_err)

        return JsonResponse({
            "success": True,
            "message": f"Birthday wish sent to {receiver_name} successfully! 🎉"
        }, status=200)

    except Exception as e:
        print("[Birthday Wish] Server error:", e)
        return JsonResponse({"error": str(e)}, status=500)


def _calculate_days_until(dob_date, today):
    """Calculate days left until next birthday."""
    try:
        bday_this_year = datetime(today.year, dob_date.month, dob_date.day).date()
    except ValueError:
        bday_this_year = datetime(today.year, dob_date.month, 28).date()
    
    if bday_this_year < today:
        try:
            bday_this_year = datetime(today.year + 1, dob_date.month, dob_date.day).date()
        except ValueError:
            bday_this_year = datetime(today.year + 1, dob_date.month, 28).date()
    
    return (bday_this_year - today).days


def _compute_birthdays(request):
    """Internal helper to compute birthday records and aggregations."""
    today = datetime.now(IST).date()
    selected_month = str(request.GET.get('month', today.month)).strip().lower()
    search_query = str(request.GET.get('search', '')).strip().lower()
    dept_query = str(request.GET.get('department', '')).strip()

    from employees.views.common.utils import resolve_department_filter
    dept_ctx = resolve_department_filter(dept_query if dept_query else None)
    is_dept_match = dept_ctx['is_match']

    dept_map = {}
    desig_map = {}
    profiles = []

    try:
        client = get_mongo_client()
        db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
        db = client[db_name]

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

    month_counts = {m: 0 for m in range(1, 13)}
    today_count = 0
    upcoming_count = 0
    all_departments = set()

    processed_profiles = []
    inactive_ids = get_inactive_employee_ids()

    for prof in profiles:
        emp_id = str(prof.get('employeeId') if isinstance(prof, dict) else getattr(prof, 'employeeId', '') or '')
        if emp_id in inactive_ids:
            continue
        emp_name = str(prof.get('employeeName') if isinstance(prof, dict) else getattr(prof, 'employeeName', '') or '')
        raw_dept = str(prof.get('department') if isinstance(prof, dict) else getattr(prof, 'department', '') or '')

        resolved_dept_names = []
        for dcode in raw_dept.split(','):
            dcode = dcode.strip()
            resolved_dept_names.append(dept_map.get(dcode, dcode))
        display_dept = ", ".join(resolved_dept_names) if resolved_dept_names else "General"
        if display_dept:
            all_departments.add(display_dept)

        raw_desig = str(prof.get('designation') if isinstance(prof, dict) else getattr(prof, 'designation', '') or '')
        display_desig = desig_map.get(raw_desig, raw_desig) or "Employee"

        # Check department filter
        if dept_ctx['is_filtered'] and not (is_dept_match(raw_dept) or is_dept_match(display_dept)):
            continue

        dob_raw = prof.get('dateOfBirth') if isinstance(prof, dict) else getattr(prof, 'dateOfBirth', None)
        dob_date = _parse_dob(dob_raw)
        if not dob_date:
            continue

        # Update counters
        month_counts[dob_date.month] += 1
        is_today = (dob_date.month == today.month and dob_date.day == today.day)
        if is_today:
            today_count += 1

        days_until = _calculate_days_until(dob_date, today)
        is_upcoming = (1 <= days_until <= 14)
        if is_upcoming:
            upcoming_count += 1

        current_age = today.year - dob_date.year - ((today.month, today.day) < (dob_date.month, dob_date.day))
        turning_age = today.year - dob_date.year if (dob_date.month, dob_date.day) >= (today.month, today.day) else (today.year - dob_date.year + 1)

        emp_data = {
            "employeeId": emp_id,
            "employeeName": emp_name,
            "department": display_dept,
            "designation": display_desig,
            "email": prof.get('email') if isinstance(prof, dict) else getattr(prof, 'email', ''),
            "mobileNumber": prof.get('mobileNumber') if isinstance(prof, dict) else getattr(prof, 'mobileNumber', ''),
            "profileImage": prof.get('profileImage') if isinstance(prof, dict) else getattr(prof, 'profileImage', None),
            "dateOfBirth": dob_date.strftime("%Y-%m-%d"),
            "formatted_dob": dob_date.strftime("%d %b %Y"),
            "birthday_display": dob_date.strftime("%d %B"),
            "birthday_short": dob_date.strftime("%d %b"),
            "birth_day": dob_date.day,
            "birth_month": dob_date.month,
            "birth_month_name": MONTH_NAMES.get(dob_date.month, ""),
            "age": current_age,
            "turning_age": turning_age,
            "days_until": days_until,
            "is_today": is_today,
            "is_upcoming": is_upcoming,
        }
        processed_profiles.append(emp_data)

    # Apply search filter if present
    if search_query:
        processed_profiles = [
            p for p in processed_profiles
            if search_query in p['employeeName'].lower() or search_query in p['employeeId'].lower()
        ]

    # Apply month / quick filter
    if selected_month in ('today', 'todays'):
        filtered = [p for p in processed_profiles if p['is_today']]
        filtered.sort(key=lambda x: x['employeeName'])
        active_month_name = "Today's Birthdays"
    elif selected_month in ('upcoming', 'upcoming_14'):
        filtered = [p for p in processed_profiles if p['is_upcoming']]
        filtered.sort(key=lambda x: x['days_until'])
        active_month_name = "Upcoming Birthdays (Next 14 Days)"
    elif selected_month in ('all', 'all_months', '0'):
        filtered = processed_profiles
        filtered.sort(key=lambda x: (x['birth_month'], x['birth_day']))
        active_month_name = "All Months"
    else:
        try:
            m_int = int(selected_month)
            if 1 <= m_int <= 12:
                filtered = [p for p in processed_profiles if p['birth_month'] == m_int]
                filtered.sort(key=lambda x: (x['birth_day'], x['employeeName']))
                active_month_name = MONTH_NAMES.get(m_int, "")
            else:
                filtered = processed_profiles
                active_month_name = "All Months"
        except ValueError:
            filtered = processed_profiles
            active_month_name = "All Months"

    formatted_month_counts = [
        {
            "month": m,
            "name": MONTH_NAMES[m],
            "short_name": MONTH_NAMES[m][:3],
            "count": month_counts[m]
        }
        for m in range(1, 13)
    ]

    return {
        "today": today,
        "selected_month": selected_month,
        "active_month_name": active_month_name,
        "total_birthdays": len(filtered),
        "today_count": today_count,
        "upcoming_count": upcoming_count,
        "all_total": len(processed_profiles),
        "month_counts": formatted_month_counts,
        "departments": sorted(list(all_departments)),
        "birthdays": filtered
    }


def _generate_csv_response(data):
    """Generate CSV HttpResponse from birthday data."""
    import csv
    from django.http import HttpResponse

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    today_year = data["today"].year
    month_slug = data["active_month_name"].replace(" ", "_")
    filename = f"Employee_Birthdays_{month_slug}_{today_year}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        'S.No', 'Employee ID', 'Employee Name', 'Department',
        'Designation', 'Birthday (Date & Month)', 'Date of Birth',
        'Age', 'Contact Number', 'Email'
    ])

    for idx, emp in enumerate(data["birthdays"], start=1):
        writer.writerow([
            idx,
            emp.get('employeeId', ''),
            emp.get('employeeName', ''),
            emp.get('department', ''),
            emp.get('designation', ''),
            emp.get('birthday_display', ''),
            emp.get('formatted_dob', ''),
            emp.get('age', ''),
            emp.get('mobileNumber', '') or '',
            emp.get('email', '') or ''
        ])

    return response


@api_view(['GET'])
@permission_classes([AllowAny])
def get_monthly_birthdays(request):
    """
    Fetch employee birthdays month-wise (Jan - Dec, 'all', 'today', or 'upcoming').
    Provides monthly birthday counts, search, department filtering, and CSV export.
    """
    try:
        data = _compute_birthdays(request)
        export_mode = request.GET.get('export', '').strip().lower() == 'csv' or request.GET.get('format', '').strip().lower() == 'csv'
        if export_mode:
            return _generate_csv_response(data)

        # Remove internal datetime object before json serialization
        data.pop('today', None)
        return JsonResponse(data, status=200)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


def export_birthdays_csv(request):
    """Direct Django view to download birthday CSV."""
    try:
        data = _compute_birthdays(request)
        return _generate_csv_response(data)
    except Exception as e:
        from django.http import HttpResponse
        return HttpResponse(f"Error generating CSV: {e}", status=500)


