import os
import uuid
from datetime import datetime
from rest_framework.decorators import api_view, permission_classes
from employees.permissions import HasRoleAndDataPermission
from rest_framework.response import Response
from rest_framework import status

from employees.views.common.utils import get_mongo_client, get_request_user_hod_departments, get_cached_reference_maps
from employees.views.authentication.auth import resolve_department_names
from employees.models import Register
from employees.decorators import token_required
from .notifications import create_in_app_notification, send_expo_push_notification


def resolve_perm_department(r_doc, reg_map=None, dept_map=None):
    raw = r_doc.get('department') or r_doc.get('department_code')
    if (not raw or str(raw).strip() == '') and reg_map:
        raw = reg_map.get(str(r_doc.get('employee_id', '')).strip(), '')
    
    if not raw:
        return "General"
    
    if dept_map is not None:
        parts = [p.strip() for p in str(raw).split(',') if p.strip()]
        resolved = ",".join([dept_map.get(p, p) for p in parts])
    else:
        resolved = resolve_department_names(str(raw))
    if not resolved or resolved == "Unassigned":
        return str(raw) if not str(raw).upper().startswith("DEPT") else "General"
    return resolved


def get_permissions_collection():
    client = get_mongo_client()
    from django.conf import settings
    default_db = getattr(settings, 'DATABASES', {}).get('default', {}).get('NAME', 'Global')
    db_name = os.environ.get("HR_DB_NAME") or os.environ.get("GLOBAL_DB_NAME") or default_db
    db = client[db_name]
    return db['employees_permission_requests']


def get_diagnostics_db():
    client = get_mongo_client()
    from django.conf import settings
    default_db = getattr(settings, 'DATABASES', {}).get('default', {}).get('NAME', 'Global')
    db_name = os.environ.get("HR_DB_NAME") or os.environ.get("GLOBAL_DB_NAME") or default_db
    return client[db_name]


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
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

        from employees.views.common.utils import get_cycle_for_date
        month_str, cycle_from, cycle_to = get_cycle_for_date(date_str)
        db = get_diagnostics_db()
        requests_col = db['employees_permission_requests']
        approved_col = db['backend_diagnostics_permissions']

        # 1. Check daily limit (only 1 permission per day)
        existing_today = requests_col.find_one({
            "employee_id": employee_id,
            "date": date_str,
            "status": {"$in": ["Pending", "Pending Incharge", "Pending HOD", "Approved"]}
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

        # 2. Check cycle quota (Max 2 permissions per attendance cycle: 26th to 25th)
        month_requests = list(requests_col.find({
            "employee_id": employee_id,
            "date": {"$gte": cycle_from, "$lte": cycle_to},
            "status": {"$in": ["Pending", "Pending Incharge", "Pending HOD", "Approved"]}
        }))
        month_approved = list(approved_col.find({
            "employeeId": employee_id,
            "date": {"$gte": cycle_from, "$lte": cycle_to}
        }))

        # Merge unique dates between collections
        counted_dates = set()
        for r in month_requests:
            counted_dates.add(r.get('date'))
        for a in month_approved:
            counted_dates.add(a.get('date'))

        if len(counted_dates) >= 2:
            return Response({
                "error": f"Monthly limit reached: You have already used/requested 2 permissions for the {month_str} attendance cycle ({cycle_from} to {cycle_to}). (Maximum 2 hours per cycle)."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Lookup employee name, department and role
        profiles_col = db['backend_diagnostics_profile']
        profile = profiles_col.find_one({"employeeId": employee_id}) or {}
        employee_name = profile.get('employeeName') or data.get('employee_name') or employee_id
        raw_dept = profile.get('department') or data.get('department') or ''

        dept_name = resolve_department_names(raw_dept) if raw_dept else ""
        requester_role = ""
        reg = Register.objects.filter(employee_id=str(employee_id).strip()).first()
        if reg:
            if not dept_name or dept_name == "Unassigned":
                if reg.department:
                    dept_name = resolve_department_names(reg.department)
            if reg.role:
                requester_role = str(reg.role).strip().upper()

        if not dept_name or dept_name == "Unassigned":
            dept_name = raw_dept if (raw_dept and not str(raw_dept).upper().startswith("DEPT")) else "General"

        # Determine 3-tier initial status (Incharge -> HOD -> AVP)
        # If department has no Incharge and no HOD, route directly to AVP
        from django.db.models import Q
        from employees.views.common.utils import resolve_department_filter

        has_incharge = False
        has_hod = False
        dept_to_check = raw_dept or dept_name
        if dept_to_check:
            resolved_info = resolve_department_filter(dept_to_check)
            target_terms = resolved_info.get('target_terms', set()) or {dept_to_check}
            q_dept = Q()
            for t in target_terms:
                if t:
                    q_dept |= Q(department__icontains=t) | Q(assigned_departments__icontains=t)
            matching_emp_ids = resolved_info.get('matching_employee_ids', set())
            if matching_emp_ids:
                q_dept |= Q(employee_id__in=matching_emp_ids)

            inc_users = list(Register.objects.filter(
                Q(role__in=['HR-R-INC', 'Incharge', 'INCHARGE']) | Q(role__icontains='INCHARGE') | Q(role__icontains='HR-R-INC') | Q(role__endswith='-INC'),
                q_dept
            ))
            has_incharge = any('AVP' not in (u.role or '').upper() and 'HOD' not in (u.role or '').upper() for u in inc_users)

            hod_users = list(Register.objects.filter(
                Q(role__in=['HR-R-HOD', 'HOD']) | Q(role__icontains='HOD'),
                q_dept
            ))
            has_hod = any('AVP' not in (u.role or '').upper() for u in hod_users)

        if 'HOD' in requester_role or 'HR-R-HOD' in requester_role:
            initial_status = 'Pending AVP'
            target_reviewer = 'AVP/HR'
        elif 'INCHARGE' in requester_role or 'HR-R-INC' in requester_role or requester_role.endswith('-INC'):
            initial_status = 'Pending HOD' if has_hod else 'Pending AVP'
            target_reviewer = 'HOD' if has_hod else 'AVP'
        else:
            if has_incharge:
                initial_status = 'Pending Incharge'
                target_reviewer = 'Incharge'
            elif has_hod:
                initial_status = 'Pending HOD'
                target_reviewer = 'HOD'
            else:
                initial_status = 'Pending AVP'
                target_reviewer = 'AVP'

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
            "status": initial_status,
            "applied_on": now_dt.strftime('%Y-%m-%d %H:%M:%S'),
            "applied_on_ts": now_dt.timestamp(),
            "incharge_id": None,
            "incharge_name": None,
            "incharge_action": None,
            "incharge_remarks": None,
            "incharge_date": None,
            "hod_id": None,
            "hod_name": None,
            "hod_action": None,
            "hod_remarks": None,
            "hod_date": None,
            "reviewed_by": None,
            "reviewed_on": None,
            "admin_remarks": ""
        }

        requests_col.insert_one(doc)

        # Create in-app and remote push notification for the employee
        notif_sub_title = "Permission Request Submitted ⏱️"
        notif_sub_msg = f"Your 1-hour permission request for {date_str} ({session}) has been submitted for {target_reviewer} review."
        create_in_app_notification(
            employee_id=employee_id,
            title=notif_sub_title,
            message=notif_sub_msg,
            category="permission"
        )
        try:
            send_expo_push_notification(
                employee_ids=[employee_id],
                title=notif_sub_title,
                body=notif_sub_msg,
                data={"category": "permission", "request_id": req_id}
            )
        except Exception as push_err:
            print("[Permission] Error sending submit push:", push_err)

        return Response({
            "message": f"Permission request submitted successfully for {target_reviewer} review.",
            "request_id": req_id,
            "date": date_str,
            "status": initial_status,
            "quota_used": len(counted_dates) + 1,
            "quota_remaining": max(0, 2 - (len(counted_dates) + 1))
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        print("Error submitting permission request:", e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
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
                "incharge_id": r.get('incharge_id'),
                "incharge_name": r.get('incharge_name'),
                "incharge_action": r.get('incharge_action'),
                "incharge_remarks": r.get('incharge_remarks'),
                "incharge_date": r.get('incharge_date'),
                "hod_id": r.get('hod_id'),
                "hod_name": r.get('hod_name'),
                "hod_action": r.get('hod_action'),
                "hod_remarks": r.get('hod_remarks'),
                "hod_date": r.get('hod_date'),
                "reviewed_by": r.get('reviewed_by') or r.get('hod_name') or r.get('incharge_name'),
                "reviewed_on": r.get('reviewed_on') or r.get('hod_date') or r.get('incharge_date'),
                "admin_remarks": r.get('admin_remarks') or r.get('hod_remarks') or r.get('incharge_remarks', '')
            })

        # Calculate quota for the selected month
        month_requests = list(requests_col.find({
            "employee_id": employee_id,
            "month": current_month,
            "status": {"$in": ["Pending", "Pending Incharge", "Pending HOD", "Approved"]}
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
@permission_classes([HasRoleAndDataPermission])
@token_required
def get_pending_permission_requests(request):
    """
    Returns pending/all permission requests for Incharge / HOD / Admin review.
    Scoped by approver's assigned departments and hierarchical level:
    - Incharge: Level 1 ('Pending Incharge' or 'Pending')
    - HOD: Level 2 ('Pending HOD' or 'Pending')
    - Admin / AVP: All levels
    When status=All or status=Approved:
    - Incharge sees approved permissions and their recommended permissions (Pending HOD).
    - HOD / Admin sees all department permissions.
    """
    try:
        from employees.views.common.utils import get_request_user_approval_context, is_admin_user, resolve_department_filter

        ctx = get_request_user_approval_context(request)
        is_avp = ctx['is_avp']
        is_hod = ctx['is_hod']
        is_incharge = ctx['is_incharge']
        is_admin = ctx['is_admin']
        hod_assigned_depts = ctx['assigned_departments']
        caller_id = ctx['employee_id']

        if not (is_avp or is_hod or is_incharge or is_admin):
            # Non-approver users cannot view pending approvals
            return Response({"count": 0, "requests": []}, status=status.HTTP_200_OK)

        dept_param = request.GET.get('department')
        if (is_hod or is_incharge or is_avp) and dept_param and dept_param != 'All':
            if not hod_assigned_depts:
                hod_assigned_depts = [dept_param]
            elif dept_param not in hod_assigned_depts:
                hod_assigned_depts.append(dept_param)

        db = get_diagnostics_db()
        requests_col = db['employees_permission_requests']

        status_param = request.GET.get('status')
        query = {}

        if status_param and status_param != 'All':
            if status_param.lower() == 'approved':
                if is_incharge and not (is_hod or is_admin):
                    # Incharge sees both final Approved and their recommended items (Pending HOD)
                    query["$or"] = [
                        {"status": "Approved"},
                        {"status": "Pending HOD"},
                        {"incharge_id": str(caller_id).strip()}
                    ]
                else:
                    query["status"] = "Approved"
            elif status_param.lower() == 'pending':
                if is_incharge and not (is_hod or is_admin):
                    query["status"] = {"$in": ["Pending Incharge", "Pending"]}
                elif is_hod and not is_avp:
                    query["status"] = {"$in": ["Pending HOD", "Pending"]}
                elif is_avp:
                    query["status"] = {"$in": ["Pending AVP", "Pending HOD", "Pending"]}
                else:
                    query["status"] = {"$in": ["Pending", "Pending Incharge", "Pending HOD", "Pending AVP"]}
            else:
                query["status"] = status_param
        elif status_param == 'All':
            # No status constraint - return all statuses
            pass
        else:
            # Default to appropriate pending level
            if is_incharge and not (is_hod or is_admin):
                query["status"] = {"$in": ["Pending Incharge", "Pending"]}
            elif is_hod and not is_avp:
                query["status"] = {"$in": ["Pending HOD", "Pending"]}
            elif is_avp:
                query["status"] = {"$in": ["Pending AVP", "Pending HOD", "Pending"]}
            else:
                query["status"] = {"$in": ["Pending", "Pending Incharge", "Pending HOD", "Pending AVP"]}

        target_depts_to_filter = []
        if (is_hod or is_incharge or is_avp) and hod_assigned_depts:
            target_depts_to_filter = list(hod_assigned_depts)
        elif is_admin and dept_param and dept_param != 'All':
            target_depts_to_filter = [dept_param]
        elif (is_hod or is_incharge) and not hod_assigned_depts:
            return Response({"count": 0, "requests": []}, status=status.HTTP_200_OK)

        if target_depts_to_filter:
            import re
            dept_map, _, _ = get_cached_reference_maps()
            reverse_dept_map = {str(v).lower(): k for k, v in dept_map.items()}
            all_match_terms = set()
            resolved_info = resolve_department_filter(",".join(target_depts_to_filter))
            target_terms = resolved_info.get('target_terms', [])
            for t in target_terms:
                all_match_terms.add(t)
                if t in dept_map:
                    all_match_terms.add(dept_map[t])
                code = reverse_dept_map.get(str(t).lower())
                if code:
                    all_match_terms.add(code)
            for d in target_depts_to_filter:
                code = reverse_dept_map.get(str(d).lower())
                if code:
                    all_match_terms.add(code)
                all_match_terms.add(str(d).strip())

            regex_list = [re.compile(f"^{re.escape(term)}$", re.IGNORECASE) for term in all_match_terms if term]
            dept_condition = [
                {"department": {"$in": regex_list}},
                {"department_code": {"$in": regex_list}}
            ]
            if "$or" in query:
                # Merge existing status $or with dept condition via $and
                status_or = query.pop("$or")
                query["$and"] = [{"$or": status_or}, {"$or": dept_condition}]
            else:
                query["$or"] = dept_condition

        if (is_hod or is_incharge or is_avp) and caller_id:
            query["employee_id"] = {"$ne": str(caller_id).strip()}

        cursor = list(requests_col.find(query).sort("applied_on_ts", -1))
        emp_ids = [str(r.get('employee_id', '')).strip() for r in cursor if r.get('employee_id')]
        reg_map = {
            str(reg.employee_id).strip(): (reg.department or '')
            for reg in Register.objects.filter(employee_id__in=emp_ids)
        }

        dept_map, _, _ = get_cached_reference_maps()

        pending_list = []
        for r in cursor:
            pending_list.append({
                "id": str(r.get('_id')),
                "request_id": r.get('request_id') or str(r.get('_id')),
                "employee_id": r.get('employee_id'),
                "employee_name": r.get('employee_name'),
                "department": resolve_perm_department(r, reg_map, dept_map),
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
                "applied_on": r.get('applied_on'),
                "incharge_id": r.get('incharge_id'),
                "incharge_name": r.get('incharge_name'),
                "incharge_action": r.get('incharge_action'),
                "incharge_remarks": r.get('incharge_remarks'),
                "incharge_date": r.get('incharge_date'),
                "hod_id": r.get('hod_id'),
                "hod_name": r.get('hod_name'),
                "hod_action": r.get('hod_action'),
                "hod_remarks": r.get('hod_remarks'),
                "hod_date": r.get('hod_date'),
                "reviewed_by": r.get('reviewed_by') or r.get('hod_name') or r.get('incharge_name'),
                "reviewed_on": r.get('reviewed_on') or r.get('hod_date') or r.get('incharge_date'),
                "admin_remarks": r.get('admin_remarks') or r.get('hod_remarks') or r.get('incharge_remarks', '')
            })

        return Response({
            "count": len(pending_list),
            "requests": pending_list
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print("Error fetching pending permission requests:", e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
@token_required
def review_permission_request(request):
    """
    Approves or Rejects an employee permission request following 2-tier approval flow:
    - Incharge review:
        If Approved -> status becomes 'Pending HOD' (Recommended), incharge fields recorded.
        Does NOT insert into backend_diagnostics_permissions yet.
    - HOD / Admin / AVP review:
        If Approved -> status becomes 'Approved', hod fields recorded.
        Auto-upserts into backend_diagnostics_permissions so Late Hours Deductions & Payroll waive 60m shortfall.
    - Sends real-time Expo Push Notification and In-App notification to the employee.
    """
    try:
        from employees.views.common.utils import get_request_user_approval_context

        data = request.data
        request_id = str(data.get('request_id') or data.get('id', '')).strip()
        new_status = str(data.get('status') or data.get('action', '')).strip() # Approved | Rejected
        admin_remarks = str(data.get('admin_remarks') or data.get('remarks', '')).strip()
        reviewer_name = str(data.get('reviewer_name') or '').strip()
        reviewer_role = str(data.get('reviewer_role') or '').strip().upper()

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

        ctx = get_request_user_approval_context(request)
        is_incharge = ctx['is_incharge'] or ('INCHARGE' in reviewer_role) or ('HR-R-INC' in reviewer_role) or reviewer_role.endswith('-INC')
        is_hod = (ctx['is_hod'] or ('HOD' in reviewer_role) or ('HR-R-HOD' in reviewer_role)) and not ctx['is_avp']
        is_avp = ctx['is_avp'] or ('AVP' in reviewer_role) or ('HR-R-AVP' in reviewer_role)
        is_admin = ctx['is_admin'] or ('ADMIN' in reviewer_role) or (reviewer_role in ['HR', 'HR-ADMIN'])

        if not reviewer_name:
            reg_user = ctx.get('user')
            reviewer_name = getattr(reg_user, 'name', None) if reg_user else None
            if not reviewer_name:
                reviewer_name = 'Incharge' if (is_incharge and not is_hod and not is_admin) else 'HOD'

        now_dt = datetime.utcnow()
        now_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')

        emp_id = perm_req['employee_id']
        emp_name = perm_req.get('employee_name', emp_id)
        date_str = perm_req['date']
        session_str = perm_req.get('session', 'Morning')

        final_approved = False
        action_msg = ""
        update_fields = {}

        if is_incharge and not (is_hod or is_avp or is_admin):
            # Incharge (Level 1 Review):
            update_fields["incharge_id"] = ctx['employee_id'] or ''
            update_fields["incharge_name"] = reviewer_name
            update_fields["incharge_action"] = new_status
            update_fields["incharge_remarks"] = admin_remarks
            update_fields["incharge_date"] = now_str
            update_fields["reviewed_by"] = reviewer_name
            update_fields["reviewed_on"] = now_str
            update_fields["admin_remarks"] = admin_remarks

            if new_status == 'Approved':
                # Check if department has HOD; if no HOD exists, forward directly to AVP
                req_dept = perm_req.get('department_code') or perm_req.get('department')
                has_hod = False
                if req_dept:
                    from employees.views.common.utils import resolve_department_filter
                    from django.db.models import Q
                    resolved_info = resolve_department_filter(req_dept)
                    target_terms = resolved_info.get('target_terms', set()) or {req_dept}
                    q_dept = Q()
                    for t in target_terms:
                        if t:
                            q_dept |= Q(department__icontains=t) | Q(assigned_departments__icontains=t)
                    hod_users = list(Register.objects.filter(
                        Q(role__in=['HR-R-HOD', 'HOD']) | Q(role__icontains='HOD'),
                        q_dept
                    ))
                    has_hod = any('AVP' not in (u.role or '').upper() for u in hod_users)

                if has_hod:
                    resulting_status = 'Pending HOD'
                    action_msg = f"Permission recommended by Incharge {reviewer_name} and forwarded to HOD."
                    notif_title = "Permission Recommended ⏱️"
                    notif_msg = f"Your 1-hour permission request for {date_str} ({session_str}) has been recommended by Incharge {reviewer_name} and forwarded to HOD for final approval."
                else:
                    resulting_status = 'Pending AVP'
                    action_msg = f"Permission recommended by Incharge {reviewer_name} and forwarded to AVP."
                    notif_title = "Permission Recommended ⏱️"
                    notif_msg = f"Your 1-hour permission request for {date_str} ({session_str}) has been recommended by Incharge {reviewer_name} and forwarded to AVP for final approval."
                update_fields["status"] = resulting_status
            else:
                resulting_status = 'Rejected'
                update_fields["status"] = resulting_status
                action_msg = f"Permission rejected by Incharge {reviewer_name}."
                notif_title = "Permission Rejected ❌"
                remark_note = f" Remarks: {admin_remarks}" if admin_remarks else ""
                notif_msg = f"Your 1-hour permission request for {date_str} has been rejected by Incharge {reviewer_name}.{remark_note}"

        elif is_hod and not is_avp:
            # HOD (Level 2 or Direct Approver):
            update_fields["hod_id"] = ctx['employee_id'] or ''
            update_fields["hod_name"] = reviewer_name
            update_fields["hod_action"] = new_status
            update_fields["hod_remarks"] = admin_remarks
            update_fields["hod_date"] = now_str
            update_fields["reviewed_by"] = reviewer_name
            update_fields["reviewed_on"] = now_str
            update_fields["admin_remarks"] = admin_remarks

            if new_status == 'Approved':
                resulting_status = 'Approved'
                update_fields["status"] = resulting_status
                final_approved = True
                action_msg = f"Permission approved by HOD {reviewer_name}."
                notif_title = "Permission Approved ✅"
                notif_msg = f"Your 1-hour permission for {date_str} ({session_str}) has been approved by HOD {reviewer_name}. Shortfall will be waived in payroll."
            else:
                resulting_status = 'Rejected'
                update_fields["status"] = resulting_status
                action_msg = f"Permission rejected by HOD {reviewer_name}."
                notif_title = "Permission Rejected ❌"
                remark_note = f" Remarks: {admin_remarks}" if admin_remarks else ""
                notif_msg = f"Your 1-hour permission request for {date_str} has been rejected by HOD {reviewer_name}.{remark_note}"

        elif is_avp:
            # AVP (For HOD permissions):
            update_fields["avp_id"] = ctx['employee_id'] or ''
            update_fields["avp_name"] = reviewer_name
            update_fields["avp_action"] = new_status
            update_fields["avp_remarks"] = admin_remarks
            update_fields["avp_date"] = now_str
            update_fields["reviewed_by"] = reviewer_name
            update_fields["reviewed_on"] = now_str
            update_fields["admin_remarks"] = admin_remarks

            if new_status == 'Approved':
                resulting_status = 'Approved'
                update_fields["status"] = resulting_status
                final_approved = True
                action_msg = f"Permission approved by AVP {reviewer_name}."
                notif_title = "Permission Approved ✅"
                notif_msg = f"Your 1-hour permission for {date_str} ({session_str}) has been approved by AVP {reviewer_name}. Shortfall will be waived in payroll."
            else:
                resulting_status = 'Rejected'
                update_fields["status"] = resulting_status
                action_msg = f"Permission rejected by AVP {reviewer_name}."
                notif_title = "Permission Rejected ❌"
                remark_note = f" Remarks: {admin_remarks}" if admin_remarks else ""
                notif_msg = f"Your 1-hour permission request for {date_str} has been rejected by AVP {reviewer_name}.{remark_note}"

        else:
            # Admin / HR fallback:
            update_fields["reviewed_by"] = reviewer_name
            update_fields["reviewed_on"] = now_str
            update_fields["admin_remarks"] = admin_remarks
            update_fields["status"] = new_status
            resulting_status = new_status

            if new_status == 'Approved':
                final_approved = True
                action_msg = f"Permission approved by {reviewer_name}."
                notif_title = "Permission Approved ✅"
                notif_msg = f"Your 1-hour permission for {date_str} ({session_str}) has been approved by {reviewer_name}. Shortfall will be waived in payroll."
            else:
                action_msg = f"Permission rejected by {reviewer_name}."
                notif_title = "Permission Rejected ❌"
                remark_note = f" Remarks: {admin_remarks}" if admin_remarks else ""
                notif_msg = f"Your 1-hour permission request for {date_str} has been rejected by {reviewer_name}.{remark_note}"

        # Update the request record in employees_permission_requests
        requests_col.update_one(
            {"_id": perm_req['_id']},
            {"$set": update_fields}
        )

        # If Final Approved, sync to backend_diagnostics_permissions for Payroll waiver
        if final_approved:
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
                    "approvedRole": "HOD" if (is_hod or not is_admin) else "Admin",
                    "requestId": str(perm_req['_id']),
                    "session": session_str,
                    "timeSlot": perm_req.get('time_slot', ''),
                    "startTime": perm_req.get('start_time', ''),
                    "endTime": perm_req.get('end_time', ''),
                    "updatedAt": now_dt
                }},
                upsert=True
            )

        # Send in-app and push notification
        create_in_app_notification(
            employee_id=emp_id,
            title=notif_title,
            message=notif_msg,
            category="permission"
        )
        send_expo_push_notification(emp_id, notif_title, notif_msg, {"category": "permission", "request_id": str(perm_req['_id'])})

        return Response({
            "message": action_msg,
            "request_id": str(perm_req['_id']),
            "status": resulting_status,
            "reviewed_by": reviewer_name
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print("Error reviewing permission request:", e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
