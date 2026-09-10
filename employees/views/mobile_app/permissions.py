import os
import uuid
from datetime import datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from employees.views.common.utils import get_mongo_client, get_request_user_hod_departments, get_cached_reference_maps
from employees.views.authentication.auth import resolve_department_names
from employees.models import Register
from employees.decorators import token_required
from .notifications import create_in_app_notification, send_expo_push_notification


def resolve_perm_department(r_doc, reg_map=None):
    raw = r_doc.get('department') or r_doc.get('department_code')
    if (not raw or str(raw).strip() == '') and reg_map:
        raw = reg_map.get(str(r_doc.get('employee_id', '')).strip(), '')
    
    if not raw:
        return "General"
    
    resolved = resolve_department_names(str(raw))
    if not resolved or resolved == "Unassigned":
        return str(raw) if not str(raw).upper().startswith("DEPT") else "General"
    return resolved


def get_permissions_collection():
    client = get_mongo_client()
    db_name = os.environ.get("HR_DB_NAME", "HR")
    db = client[db_name]
    return db['employees_permission_requests']


def get_diagnostics_db():
    client = get_mongo_client()
    db_name = os.environ.get("HR_DB_NAME", "HR")
    return client[db_name]


@api_view(['POST'])
@permission_classes([AllowAny])
@token_required
def submit_permission_request(request):
    """
    Submits a 1-hour employee permission request.
    Enforces:
    1. Max 2 permissions per calendar month (max 1 hour each).
    2. Max 1 permission per day.
    """
    try:
        data = request.data
        employee_id = str(data.get('employee_id') or data.get('employeeId', '')).strip()
        date_str = str(data.get('date', '')).strip()
        session = str(data.get('session', 'Morning')).strip() # Morning | Evening | Custom
        time_slot = str(data.get('time_slot', '')).strip()
        reason = str(data.get('reason', '')).strip()

        if not employee_id:
            return Response({"error": "employee_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        if not date_str:
            return Response({"error": "Date is required."}, status=status.HTTP_400_BAD_REQUEST)

        if not reason:
            return Response({"error": "Reason for permission is mandatory."}, status=status.HTTP_400_BAD_REQUEST)

        month_str = date_str[:7]
        db = get_diagnostics_db()
        requests_col = db['employees_permission_requests']
        approved_col = db['backend_diagnostics_permissions']

        # 1. Check daily limit (only 1 permission per day)
        existing_today = requests_col.find_one({
            "employee_id": employee_id,
            "date": date_str,
            "status": {"$in": ["Pending", "Approved"]}
        })
        if not existing_today:
            existing_today = approved_col.find_one({
                "employeeId": employee_id,
                "date": date_str
            })

        if existing_today:
            return Response({
                "error": f"Permission already requested or granted for {date_str}. (Max 1 permission per day allowed)."
            }, status=status.HTTP_400_BAD_REQUEST)

        # 2. Check monthly quota (Max 2 permissions per month)
        month_requests = list(requests_col.find({
            "employee_id": employee_id,
            "month": month_str,
            "status": {"$in": ["Pending", "Approved"]}
        }))
        month_approved = list(approved_col.find({
            "employeeId": employee_id,
            "$or": [{"month": month_str}, {"date": {"$regex": f"^{month_str}"}}]
        }))

        # Merge unique dates between collections
        counted_dates = set()
        for r in month_requests:
            counted_dates.add(r.get('date'))
        for a in month_approved:
            counted_dates.add(a.get('date'))

        if len(counted_dates) >= 2:
            return Response({
                "error": f"Monthly limit reached: You have already used/requested all 2 permissions for {month_str}. (Maximum 2 hours per month)."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Lookup employee name and department from profile
        profiles_col = db['backend_diagnostics_profile']
        profile = profiles_col.find_one({"employeeId": employee_id}) or {}
        employee_name = profile.get('employeeName') or data.get('employee_name') or employee_id
        raw_dept = profile.get('department') or data.get('department') or ''

        dept_name = resolve_department_names(raw_dept) if raw_dept else ""
        if not dept_name or dept_name == "Unassigned":
            reg = Register.objects.filter(employee_id=str(employee_id).strip()).first()
            if reg and reg.department:
                dept_name = resolve_department_names(reg.department)
        if not dept_name or dept_name == "Unassigned":
            dept_name = raw_dept if (raw_dept and not str(raw_dept).upper().startswith("DEPT")) else "General"

        now_dt = datetime.utcnow()
        req_id = f"perm-{uuid.uuid4().hex[:10]}"

        start_time = str(data.get('start_time', '')).strip()
        end_time = str(data.get('end_time', '')).strip()

        if not time_slot:
            if start_time and end_time:
                time_slot = f"{start_time} - {end_time}"
            elif session == 'Morning':
                time_slot = "Morning (1-Hour Late Arrival)"
            elif session == 'Evening':
                time_slot = "Evening (1-Hour Early Departure)"
            else:
                time_slot = "1-Hour Permission"

        doc = {
            "_id": req_id,
            "request_id": req_id,
            "employee_id": employee_id,
            "employee_name": employee_name,
            "department": dept_name,
            "department_code": raw_dept,
            "date": date_str,
            "month": month_str,
            "session": session,
            "time_slot": time_slot,
            "start_time": start_time,
            "end_time": end_time,
            "duration_hours": 1.0,
            "duration_mins": 60,
            "reason": reason,
            "status": "Pending",
            "applied_on": now_dt.strftime('%Y-%m-%d %H:%M:%S'),
            "applied_on_ts": now_dt.timestamp(),
            "reviewed_by": None,
            "reviewed_on": None,
            "admin_remarks": ""
        }

        requests_col.insert_one(doc)

        # Create in-app notification for the employee
        create_in_app_notification(
            employee_id=employee_id,
            title="Permission Request Submitted ⏱️",
            message=f"Your 1-hour permission request for {date_str} ({session}) has been submitted for HOD review.",
            category="permission"
        )

        return Response({
            "message": "Permission request submitted successfully for HOD approval.",
            "request_id": req_id,
            "date": date_str,
            "quota_used": len(counted_dates) + 1,
            "quota_remaining": max(0, 2 - (len(counted_dates) + 1))
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        print("Error submitting permission request:", e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
@token_required
def get_my_permission_requests(request):
    """
    Returns an employee's permission request history and their current monthly quota.
    """
    try:
        employee_id = str(request.GET.get('employee_id') or '').strip()
        if not employee_id:
            return Response({"error": "employee_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        now_dt = datetime.now()
        current_month = request.GET.get('month') or now_dt.strftime('%Y-%m')

        db = get_diagnostics_db()
        requests_col = db['employees_permission_requests']
        approved_col = db['backend_diagnostics_permissions']

        # Fetch employee's requests
        cursor = requests_col.find({"employee_id": employee_id}).sort("applied_on_ts", -1)
        requests_list = []
        for r in cursor:
            requests_list.append({
                "id": str(r.get('_id')),
                "request_id": r.get('request_id') or str(r.get('_id')),
                "date": r.get('date'),
                "month": r.get('month'),
                "session": r.get('session', 'Morning'),
                "time_slot": r.get('time_slot', '1-Hour Permission'),
                "start_time": r.get('start_time', ''),
                "end_time": r.get('end_time', ''),
                "duration_hours": r.get('duration_hours', 1.0),
                "department": resolve_perm_department(r),
                "reason": r.get('reason', ''),
                "status": r.get('status', 'Pending'),
                "applied_on": r.get('applied_on'),
                "reviewed_by": r.get('reviewed_by'),
                "reviewed_on": r.get('reviewed_on'),
                "admin_remarks": r.get('admin_remarks', '')
            })

        # Calculate quota for the selected month
        month_requests = list(requests_col.find({
            "employee_id": employee_id,
            "month": current_month,
            "status": {"$in": ["Pending", "Approved"]}
        }))
        month_approved = list(approved_col.find({
            "employeeId": employee_id,
            "$or": [{"month": current_month}, {"date": {"$regex": f"^{current_month}"}}]
        }))

        counted_dates = set()
        for r in month_requests:
            counted_dates.add(r.get('date'))
        for a in month_approved:
            counted_dates.add(a.get('date'))

        quota_used = len(counted_dates)
        quota_remaining = max(0, 2 - quota_used)

        return Response({
            "requests": requests_list,
            "quota": {
                "max": 2,
                "used": quota_used,
                "remaining": quota_remaining,
                "month": current_month
            }
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print("Error fetching employee permission requests:", e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
@token_required
def get_pending_permission_requests(request):
    """
    Returns pending permission requests for HOD/Admin review.
    Scoped by HOD's assigned departments.
    """
    try:
        is_hod, hod_assigned_depts = get_request_user_hod_departments(request)
        db = get_diagnostics_db()
        requests_col = db['employees_permission_requests']

        query = {"status": "Pending"}

        if is_hod and hod_assigned_depts:
            import re
            dept_map, _, _ = get_cached_reference_maps()
            reverse_dept_map = {str(v).lower(): k for k, v in dept_map.items()}
            all_match_terms = set(hod_assigned_depts)
            for d in hod_assigned_depts:
                code = reverse_dept_map.get(str(d).lower())
                if code:
                    all_match_terms.add(code)

            regex_list = [re.compile(f"^{re.escape(term)}$", re.IGNORECASE) for term in all_match_terms]
            query["$or"] = [
                {"department": {"$in": regex_list}},
                {"department_code": {"$in": regex_list}}
            ]

        cursor = list(requests_col.find(query).sort("applied_on_ts", -1))
        emp_ids = [str(r.get('employee_id', '')).strip() for r in cursor if r.get('employee_id')]
        reg_map = {
            str(reg.employee_id).strip(): (reg.department or '')
            for reg in Register.objects.filter(employee_id__in=emp_ids)
        }

        pending_list = []
        for r in cursor:
            pending_list.append({
                "id": str(r.get('_id')),
                "request_id": r.get('request_id') or str(r.get('_id')),
                "employee_id": r.get('employee_id'),
                "employee_name": r.get('employee_name'),
                "department": resolve_perm_department(r, reg_map),
                "department_code": r.get('department_code') or r.get('department'),
                "date": r.get('date'),
                "month": r.get('month'),
                "session": r.get('session', 'Morning'),
                "time_slot": r.get('time_slot', '1-Hour Permission'),
                "start_time": r.get('start_time', ''),
                "end_time": r.get('end_time', ''),
                "duration_hours": r.get('duration_hours', 1.0),
                "reason": r.get('reason', ''),
                "status": r.get('status', 'Pending'),
                "applied_on": r.get('applied_on')
            })

        return Response({
            "count": len(pending_list),
            "requests": pending_list
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print("Error fetching pending permission requests:", e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
@token_required
def review_permission_request(request):
    """
    Approves or Rejects an employee permission request.
    If Approved:
    - Auto-upserts into `backend_diagnostics_permissions` so Late Hours Deductions & Payroll waive the 60m shortfall.
    - Sends real-time Expo Push Notification and In-App notification to the employee.
    """
    try:
        data = request.data
        request_id = str(data.get('request_id') or data.get('id', '')).strip()
        new_status = str(data.get('status', '')).strip() # Approved | Rejected
        admin_remarks = str(data.get('admin_remarks', '')).strip()
        reviewer_name = str(data.get('reviewer_name') or 'HOD').strip()

        if not request_id:
            return Response({"error": "request_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        if new_status not in ['Approved', 'Rejected']:
            return Response({"error": "status must be either 'Approved' or 'Rejected'."}, status=status.HTTP_400_BAD_REQUEST)

        db = get_diagnostics_db()
        requests_col = db['employees_permission_requests']
        approved_col = db['backend_diagnostics_permissions']

        perm_req = requests_col.find_one({"$or": [{"_id": request_id}, {"request_id": request_id}]})
        if not perm_req:
            return Response({"error": "Permission request not found."}, status=status.HTTP_404_NOT_FOUND)

        now_dt = datetime.utcnow()

        # Update the request record
        requests_col.update_one(
            {"_id": perm_req['_id']},
            {"$set": {
                "status": new_status,
                "reviewed_by": reviewer_name,
                "reviewed_on": now_dt.strftime('%Y-%m-%d %H:%M:%S'),
                "admin_remarks": admin_remarks
            }}
        )

        emp_id = perm_req['employee_id']
        emp_name = perm_req.get('employee_name', emp_id)
        date_str = perm_req['date']
        session_str = perm_req.get('session', 'Morning')

        # If Approved, sync to backend_diagnostics_permissions for Payroll / Late Hours Deductions auto-waive
        if new_status == 'Approved':
            approved_col.update_one(
                {"employeeId": emp_id, "date": date_str},
                {"$set": {
                    "employeeId": emp_id,
                    "employeeName": emp_name,
                    "department": perm_req.get('department', 'General'),
                    "month": perm_req.get('month') or date_str[:7],
                    "date": date_str,
                    "durationHours": 1.0,
                    "durationMins": 60,
                    "reason": perm_req.get('reason', 'Approved Mobile Permission Request'),
                    "approvedBy": reviewer_name,
                    "approvedRole": "HOD",
                    "requestId": str(perm_req['_id']),
                    "session": session_str,
                    "timeSlot": perm_req.get('time_slot', ''),
                    "startTime": perm_req.get('start_time', ''),
                    "endTime": perm_req.get('end_time', ''),
                    "updatedAt": now_dt
                }},
                upsert=True
            )

        # Notify the Employee
        status_symbol = "✅" if new_status == 'Approved' else "❌"
        notif_title = f"Permission {new_status} {status_symbol}"
        if new_status == 'Approved':
            notif_msg = f"Your 1-hour permission for {date_str} ({session_str}) has been approved by {reviewer_name}. Shortfall will be waived in payroll."
        else:
            remark_note = f" Remarks: {admin_remarks}" if admin_remarks else ""
            notif_msg = f"Your 1-hour permission request for {date_str} has been rejected by {reviewer_name}.{remark_note}"

        create_in_app_notification(
            employee_id=emp_id,
            title=notif_title,
            message=notif_msg,
            category="permission"
        )
        send_expo_push_notification(emp_id, notif_title, notif_msg, {"category": "permission", "request_id": str(perm_req['_id'])})

        return Response({
            "message": f"Permission request {new_status.lower()} successfully.",
            "request_id": str(perm_req['_id']),
            "status": new_status,
            "reviewed_by": reviewer_name
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print("Error reviewing permission request:", e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
