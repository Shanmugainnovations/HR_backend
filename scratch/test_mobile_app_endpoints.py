import os
import sys
import json
import django

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hr_backend.settings')
django.setup()

from rest_framework.test import APIRequestFactory
import employees.views as views
from employees.views.mobile_app.notifications import (
    get_employee_notifications,
    mark_notifications_read,
    clear_notifications,
    get_unread_count,
    get_active_popup_announcement
)

factory = APIRequestFactory()
results = []

def get_payload(resp):
    if hasattr(resp, 'data'):
        return resp.data
    try:
        return json.loads(resp.content.decode('utf-8'))
    except Exception:
        return {}

def record(screen, function_tested, endpoint, status_code, ok, details=""):
    results.append({
        'screen': screen,
        'function': function_tested,
        'endpoint': endpoint,
        'status_code': status_code,
        'ok': ok,
        'details': details
    })
    sym = "✅ PASS" if ok else "❌ FAIL"
    print(f"[{sym}] {screen:22} | {function_tested:30} ({endpoint:38}) -> HTTP {status_code} | {details}")

def run_mobile_tests():
    print("=" * 115)
    print("TESTING ALL HR MOBILE APPLICATION SCREENS & BACKEND INTEGRATION ENDPOINTS")
    print("=" * 115)

    import employees.permissions
    employees.permissions.isSecurityDisabled = lambda: True

    emp_id = '50867'
    mob_headers = {
        'HTTP_X_EMPLOYEE_ID': emp_id,
        'HTTP_AUTH_USER_ID': emp_id,
        'HTTP_USER_ROLE': 'HR-R-HOD',
        'HTTP_DEPARTMENT': 'DEPT003',
        'HTTP_BRANCH_CODE': 'SHB001'
    }

    # 1. LoginScreen: mobile-employee-check
    print("\n--- 1. LoginScreen (Authentication & Onboarding) ---")
    try:
        req = factory.post('/mobile-employee-check/', {'employee_id': emp_id}, format='json', **mob_headers)
        resp = views.mobile_employee_check(req)
        p = get_payload(resp)
        record("LoginScreen", "Mobile Employee Check", "/mobile-employee-check/", resp.status_code, resp.status_code in [200, 400], f"Found: {p.get('status', 'OK')}")
    except Exception as e:
        record("LoginScreen", "Mobile Check Exception", "/mobile-employee-check/", 500, False, str(e))

    # 2. DashboardScreen: Today Status, Full Profile, Unread Count, Popup, Balances
    print("\n--- 2. DashboardScreen (Home Feed & Quick Actions) ---")
    try:
        req = factory.get(f'/employee/today-status/?employee_id={emp_id}', **mob_headers)
        resp = views.today_status(req)
        p = get_payload(resp)
        record("DashboardScreen", "Today's Punch Status", "/employee/today-status/", resp.status_code, resp.status_code == 200, f"Status: {p.get('punch_status', 'N/A')}")

        req = factory.get(f'/employee/full-profile/?employee_id={emp_id}', **mob_headers)
        resp = views.get_full_employee_profile(req)
        p = get_payload(resp)
        record("DashboardScreen", "Full Profile Card", "/employee/full-profile/", resp.status_code, resp.status_code == 200, f"Emp Name: {p.get('name', 'N/A')}")

        req = factory.get(f'/employee/notifications/unread-count/?employee_id={emp_id}', **mob_headers)
        resp = get_unread_count(req)
        p = get_payload(resp)
        record("DashboardScreen", "Notification Bell Badge", "/employee/notifications/unread-count/", resp.status_code, resp.status_code == 200, f"Unread: {p.get('unread_count', 0)}")

        req = factory.get(f'/employee/notifications/active-popup/?employee_id={emp_id}', **mob_headers)
        resp = get_active_popup_announcement(req)
        record("DashboardScreen", "Broadcast Popup Modal", "/employee/notifications/active-popup/", resp.status_code, resp.status_code == 200, "Active announcement loaded")

        req = factory.get(f'/leaves/balances/?employee_id={emp_id}', **mob_headers)
        resp = views.get_leave_balances(req)
        p = get_payload(resp)
        record("DashboardScreen", "Leave Balances Widget", "/leaves/balances/", resp.status_code, resp.status_code == 200, f"Balances retrieved")
    except Exception as e:
        record("DashboardScreen", "Dashboard Endpoints", "Exception", 500, False, str(e))

    # 3. ProfileScreen: Profile Info, Change Password
    print("\n--- 3. ProfileScreen (Employee Profile & Security) ---")
    try:
        req = factory.get(f'/employee/full-profile/?employee_id={emp_id}')
        resp = views.get_full_employee_profile(req)
        record("ProfileScreen", "Personal & Job Details", "/employee/full-profile/", resp.status_code, resp.status_code == 200, "Details loaded")

        req = factory.get('/employees_birthdays_today/')
        resp = views.get_todays_birthdays(req)
        record("ProfileScreen", "Birthday Carousel", "/employees_birthdays_today/", resp.status_code, resp.status_code == 200, "Loaded birthdays")
    except Exception as e:
        record("ProfileScreen", "Profile Endpoints", "Exception", 500, False, str(e))

    # 4. LeavesScreen: Leave Types, My Leaves, Balances, Pending Approvals
    print("\n--- 4. LeavesScreen (Leave Apply & 3-Tier Approvals) ---")
    try:
        req = factory.get('/leave-types/')
        resp = views.leave_type_list_create(req)
        record("LeavesScreen", "Leave Types Picker", "/leave-types/", resp.status_code, resp.status_code == 200, "Types loaded")

        req = factory.get(f'/leaves/my-leaves/?employee_id={emp_id}')
        resp = views.my_leaves(req)
        p = get_payload(resp)
        record("LeavesScreen", "My Leave History List", "/leaves/my-leaves/", resp.status_code, resp.status_code == 200, f"History: {len(p)} items")

        req = factory.get('/leaves/pending/?department=DEPT003', HTTP_USER_ROLE='HR-R-HOD', HTTP_AUTH_USER_ID='50867')
        resp = views.pending_leaves(req)
        p = get_payload(resp)
        record("LeavesScreen", "HOD/Incharge Approval Tab", "/leaves/pending/", resp.status_code, resp.status_code == 200, f"Pending queue: {len(p)} items")
    except Exception as e:
        record("LeavesScreen", "Leaves Endpoints", "Exception", 500, False, str(e))

    # 5. PermissionsScreen: My Requests, Pending Approvals
    print("\n--- 5. PermissionsScreen (1-Hour Shortfall Permissions) ---")
    try:
        req = factory.get(f'/mobile/permissions/my-requests/?employee_id={emp_id}', **mob_headers)
        resp = views.get_my_permission_requests(req)
        p = get_payload(resp)
        perms = p.get('permissions', []) if isinstance(p, dict) else (p if isinstance(p, list) else [])
        record("PermissionsScreen", "My Permissions List", "/mobile/permissions/my-requests/", resp.status_code, resp.status_code == 200, f"Permissions: {len(perms)}")

        req = factory.get('/mobile/permissions/pending/?department=DEPT003', **mob_headers)
        resp = views.get_pending_permission_requests(req)
        p = get_payload(resp)
        pend_perms = p.get('permissions', []) if isinstance(p, dict) else (p if isinstance(p, list) else [])
        record("PermissionsScreen", "Supervisor Permission Queue", "/mobile/permissions/pending/", resp.status_code, resp.status_code == 200, f"Pending: {len(pend_perms)}")
    except Exception as e:
        record("PermissionsScreen", "Permissions Endpoints", "Exception", 500, False, str(e))

    # 6. MyAttendanceScreen: Monthly calendar & punch history
    print("\n--- 6. MyAttendanceScreen (Monthly Biometric Punches) ---")
    try:
        req = factory.get(f'/employee/my-attendance/?employee_id={emp_id}&month=2026-09', **mob_headers)
        resp = views.my_attendance_report(req)
        p = get_payload(resp)
        record("MyAttendanceScreen", "Monthly Punches & Status", "/employee/my-attendance/", resp.status_code, resp.status_code == 200, f"Attendance month 2026-09 loaded")
    except Exception as e:
        record("MyAttendanceScreen", "Attendance Endpoints", "Exception", 500, False, str(e))

    # 7. RosterScreen: Monthly shift roster
    print("\n--- 7. RosterScreen (Duty Shift Schedule) ---")
    try:
        req = factory.get('/roster/?month=2026-09', **mob_headers)
        resp = views.get_monthly_roster(req)
        record("RosterScreen", "Monthly Shift Calendar", "/roster/", resp.status_code, resp.status_code == 200, "Roster shifts loaded")
    except Exception as e:
        record("RosterScreen", "Roster Endpoints", "Exception", 500, False, str(e))

    # 8. PayslipsScreen: Monthly payslip history & details
    print("\n--- 8. PayslipsScreen (Salary Slip History & View) ---")
    try:
        req = factory.get(f'/payroll/employee-payslips/{emp_id}/', **mob_headers)
        resp = views.employee_payslip_history(req, employee_id=emp_id)
        p = get_payload(resp)
        slips = p.get('payslips', []) if isinstance(p, dict) else (p if isinstance(p, list) else [])
        record("PayslipsScreen", "Payslip History List", f"/payroll/employee-payslips/{emp_id}/", resp.status_code, resp.status_code == 200, f"Generated slips: {len(slips)}")
    except Exception as e:
        record("PayslipsScreen", "Payslips Endpoints", "Exception", 500, False, str(e))

    # 9. CanteenScreen: Meal token usage
    print("\n--- 9. CanteenScreen (Meal History & Tokens) ---")
    try:
        req = factory.get(f'/canteen/history/?employee_id={emp_id}', **mob_headers)
        resp = views.get_canteen_token_history(req)
        p = get_payload(resp)
        hist = p.get('history', []) if isinstance(p, dict) else (p if isinstance(p, list) else [])
        record("CanteenScreen", "Canteen Token History", "/canteen/history/", resp.status_code, resp.status_code == 200, f"Token history: {len(hist)}")
    except Exception as e:
        record("CanteenScreen", "Canteen Endpoints", "Exception", 500, False, str(e))

    # 10. IdCardScreen: Employee Digital ID Card & QR
    print("\n--- 10. IdCardScreen (Digital Hospital ID Card) ---")
    try:
        req = factory.get(f'/employees/{emp_id}/', **mob_headers)
        resp = views.get_employee_detail(req, employee_id=emp_id)
        p = get_payload(resp)
        record("IdCardScreen", "Digital ID Card Details", f"/employees/{emp_id}/", resp.status_code, resp.status_code == 200, f"ID card ready for {p.get('name', emp_id)}")
    except Exception as e:
        record("IdCardScreen", "ID Card Endpoints", "Exception", 500, False, str(e))

    # 11. HelpdeskScreen: Support Tickets
    print("\n--- 11. HelpdeskScreen (HR Grievance & Tickets) ---")
    try:
        req = factory.get(f'/helpdesk/tickets/?employee_id={emp_id}', **mob_headers)
        resp = views.get_helpdesk_tickets(req)
        p = get_payload(resp)
        tix = p.get('tickets', []) if isinstance(p, dict) else (p if isinstance(p, list) else [])
        record("HelpdeskScreen", "Ticket History", "/helpdesk/tickets/", resp.status_code, resp.status_code == 200, f"Tickets: {len(tix)}")
    except Exception as e:
        record("HelpdeskScreen", "Helpdesk Endpoints", "Exception", 500, False, str(e))

    # 12. NotificationsScreen: In-App Notifications
    print("\n--- 12. NotificationsScreen (HR Push & Alerts) ---")
    try:
        req = factory.get(f'/employee/notifications/?employee_id={emp_id}', **mob_headers)
        resp = get_employee_notifications(req)
        p = get_payload(resp)
        notifs = p.get('notifications', []) if isinstance(p, dict) else (p if isinstance(p, list) else [])
        record("NotificationsScreen", "Notifications Feed", "/employee/notifications/", resp.status_code, resp.status_code == 200, f"Notifications: {len(notifs)}")
    except Exception as e:
        record("NotificationsScreen", "Notifications Endpoints", "Exception", 500, False, str(e))

    print("\n" + "=" * 115)
    total = len(results)
    passed = sum(1 for r in results if r['ok'])
    failed = sum(1 for r in results if not r['ok'])
    print(f"MOBILE TEST SUMMARY: TOTAL SCREEN ENDPOINTS: {total} | PASSED: {passed} | FAILED: {failed}")
    print("=" * 115)

if __name__ == '__main__':
    run_mobile_tests()
