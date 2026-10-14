import os
import re
import calendar
import logging
from datetime import datetime, date, timedelta
from bson import ObjectId
import pytz
from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from employees.permissions import HasRoleAndDataPermission
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient

logger = logging.getLogger(__name__)
IST = pytz.timezone('Asia/Kolkata')

def get_mongo_db():
    from employees.views.common.utils import get_mongo_client
    client = get_mongo_client()
    db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
    if client:
        return client[db_name]
    mongo_uri = os.environ.get('GLOBAL_DB_HOST', 'mongodb://admin:SMRFT%40prod2026@45.252.190.162:27017/')
    client = MongoClient(mongo_uri)
    return client[db_name]


def get_period_dates(target_month=None, from_date_in=None, to_date_in=None, cycle='hospital'):
    """
    Resolves start_date and end_date for an attendance month cycle.
    Hospital standard cycle is 26th of previous month to 25th of target month.
    """
    if from_date_in and to_date_in:
        from_str = str(from_date_in).strip()
        to_str = str(to_date_in).strip()
        t_month = target_month or to_str[:7]
        return t_month, from_str, to_str, f"{from_str}_{to_str}"

    if not target_month:
        target_month = datetime.now().strftime('%Y-%m')

    try:
        parts = str(target_month).split('-')
        y, m = int(parts[0]), int(parts[1])
    except Exception:
        now = datetime.now()
        y, m = now.year, now.month
        target_month = f"{y:04d}-{m:02d}"

    cycle_str = str(cycle or 'hospital').lower().strip()
    if cycle_str in ['hospital', '26-25']:
        if m == 1:
            prev_y, prev_m = y - 1, 12
        else:
            prev_y, prev_m = y, m - 1
        from_str = f"{prev_y:04d}-{prev_m:02d}-26"
        to_str = f"{y:04d}-{m:02d}-25"
        period_key = f"{from_str}_{to_str}"
    else:
        _, last_d = calendar.monthrange(y, m)
        from_str = f"{y:04d}-{m:02d}-01"
        to_str = f"{y:04d}-{m:02d}-{last_d:02d}"
        period_key = target_month

    return target_month, from_str, to_str, period_key


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_attendance_approval_summary(request):
    """
    Returns department-wise attendance verification summary for the specified month.
    - If user is HOD: Scoped strictly to their assigned department(s).
    - If user is Admin: Returns all departments with counts across approval tiers.
    """
    try:
        db = get_mongo_db()
        approval_col = db['backend_diagnostics_attendance_approval']
        profiles_col = db['backend_diagnostics_profile']
        reg_col = db['backend_diagnostics_attendance_regularization']

        from employees.views.common.utils import (
            get_inactive_employee_ids,
            get_request_user_approval_context,
            resolve_department_filter
        )
        from employees.views.payroll.payroll_views import calculate_attendance_metrics_from_roster

        target_month = request.GET.get('month') or datetime.now().strftime('%Y-%m')
        from_date_in = request.GET.get('fromDate') or request.GET.get('from_date')
        to_date_in = request.GET.get('toDate') or request.GET.get('to_date')
        cycle = request.GET.get('cycle', 'hospital')
        recalculate = str(request.GET.get('recalculate', '')).lower() in ['true', '1', 'yes']

        target_month, from_str, to_str, period_key = get_period_dates(target_month, from_date_in, to_date_in, cycle)

        user_ctx = get_request_user_approval_context(request)
        is_restricted_supervisor = (user_ctx.get('is_hod') or user_ctx.get('is_avp') or user_ctx.get('is_incharge')) and not user_ctx.get('is_admin', False)
        is_admin = user_ctx.get('is_admin', False) and not is_restricted_supervisor
        assigned_depts = user_ctx.get('assigned_departments', [])

        inactive_ids = get_inactive_employee_ids()

        # Build clean department mapping
        depts_map = {}
        for d in db['backend_diagnostics_Departments'].find():
            c = d.get('department_code')
            n = d.get('department_name')
            if c and n:
                depts_map[c.lower().strip()] = n.strip()
                depts_map[n.lower().strip()] = n.strip()

        # Fetch active profiles
        all_profiles = [p for p in profiles_col.find({}) if str(p.get('employeeId', '')).strip() not in inactive_ids]

        # Group profiles by department
        dept_profiles_map = {}
        for p in all_profiles:
            dept_raw = p.get('department') or p.get('department_name') or 'Admin'
            dept_name = depts_map.get(str(dept_raw).lower().strip(), dept_raw).strip()
            if not dept_name:
                dept_name = 'Admin'
            if dept_name not in dept_profiles_map:
                dept_profiles_map[dept_name] = []
            dept_profiles_map[dept_name].append(p)

        # Existing approval records for this month/period
        exist_query = {'$or': [{'month': target_month}, {'periodKey': period_key}]}
        existing_approvals = {r.get('department'): r for r in approval_col.find(exist_query) if r.get('department')}

        # Regularization map for month
        reg_records = list(reg_col.find({'month': target_month}))
        reg_map = {str(r.get('employeeId')): r for r in reg_records if r.get('employeeId')}

        department_summaries = []

        # If supervisor (HOD, AVP, INC), filter to assigned departments
        all_dept_names = sorted(list(dept_profiles_map.keys()))
        if is_restricted_supervisor:
            if assigned_depts:
                allowed_lower = {d.lower().strip() for d in assigned_depts}
                filtered_dept_names = [d for d in all_dept_names if d.lower().strip() in allowed_lower]
            else:
                filtered_dept_names = []
        else:
            filtered_dept_names = all_dept_names

        # Process each department
        for dept_name in filtered_dept_names:
            dept_profs = dept_profiles_map.get(dept_name, [])
            emp_ids = [str(p.get('employeeId', '')).strip() for p in dept_profs if p.get('employeeId')]
            existing_rec = existing_approvals.get(dept_name)

            dept_reg_count = sum(1 for eid in emp_ids if eid in reg_map)

            if existing_rec and not recalculate:
                # Use stored record
                rec_status = existing_rec.get('status', 'Draft')
                department_summaries.append({
                    'department': dept_name,
                    'status': rec_status,
                    'employeeCount': existing_rec.get('employeeCount', len(emp_ids)),
                    'totalPresent': existing_rec.get('totalPresent', 0),
                    'totalAbsent': existing_rec.get('totalAbsent', 0),
                    'totalLeaves': existing_rec.get('totalLeaves', 0),
                    'totalSinglePunch': existing_rec.get('totalSinglePunch', 0),
                    'totalLateHours': existing_rec.get('totalLateHours', 0.0),
                    'totalShortfallMinutes': existing_rec.get('totalShortfallMinutes', 0),
                    'totalShortfallHours': existing_rec.get('totalShortfallHours', '0m'),
                    'regularizedCount': existing_rec.get('regularizedCount', dept_reg_count),
                    'hodApprovedBy': existing_rec.get('hodApprovedBy'),
                    'hodApprovedAt': existing_rec.get('hodApprovedAt'),
                    'hodRemarks': existing_rec.get('hodRemarks', ''),
                    'adminApprovedBy': existing_rec.get('adminApprovedBy'),
                    'adminApprovedAt': existing_rec.get('adminApprovedAt'),
                    'adminRemarks': existing_rec.get('adminRemarks', ''),
                    'updated_at': existing_rec.get('updated_at')
                })
            else:
                # Calculate metrics on the fly using duty roster attendance
                att_map, total_month_days = calculate_attendance_metrics_from_roster(
                    target_month=target_month,
                    employee_ids=emp_ids,
                    treat_sp_as_present=True,
                    from_date=from_str,
                    to_date=to_str
                )

                tot_pres = 0.0
                tot_abs = 0.0
                tot_leaves = 0
                tot_sp = 0
                tot_late_lop = 0.0
                tot_sf_mins = 0

                for eid in emp_ids:
                    m = att_map.get(eid, {})
                    tot_sf_mins += int(m.get('total_shortfall_mins', 0) or 0)
                    reg = reg_map.get(eid)
                    if reg:
                        tot_pres += float(reg.get('regularizedPresentDays', m.get('present_days', 0)) or 0)
                        tot_abs += float(reg.get('regularizedLopDays', m.get('lop_days', 0)) or 0)
                        tot_sp += int(reg.get('regularizedSpDays', m.get('sp_days', 0)) or 0)
                    else:
                        tot_pres += float(m.get('present_days', 0) or 0)
                        tot_abs += float(m.get('lop_days', 0) or 0)
                        tot_sp += int(m.get('sp_days', 0) or 0)

                    tot_leaves += int(m.get('leave_days', 0) or 0)
                    tot_late_lop += float(m.get('late_lop_days', 0) or 0)

                tot_sf_hours_str = f"{tot_sf_mins // 60}h {tot_sf_mins % 60:02d}m" if tot_sf_mins >= 60 else (f"{tot_sf_mins}m" if tot_sf_mins > 0 else "0m")

                doc = {
                    'month': target_month,
                    'fromDate': from_str,
                    'toDate': to_str,
                    'periodKey': period_key,
                    'department': dept_name,
                    'status': existing_rec.get('status', 'Draft') if existing_rec else 'Draft',
                    'employeeCount': len(emp_ids),
                    'totalPresent': round(tot_pres, 1),
                    'totalAbsent': round(tot_abs, 1),
                    'totalLeaves': tot_leaves,
                    'totalSinglePunch': tot_sp,
                    'totalLateHours': round(tot_late_lop, 1),
                    'totalShortfallMinutes': tot_sf_mins,
                    'totalShortfallHours': tot_sf_hours_str,
                    'regularizedCount': dept_reg_count,
                    'hodApprovedBy': existing_rec.get('hodApprovedBy') if existing_rec else None,
                    'hodApprovedAt': existing_rec.get('hodApprovedAt') if existing_rec else None,
                    'hodRemarks': existing_rec.get('hodRemarks', '') if existing_rec else '',
                    'adminApprovedBy': existing_rec.get('adminApprovedBy') if existing_rec else None,
                    'adminApprovedAt': existing_rec.get('adminApprovedAt') if existing_rec else None,
                    'adminRemarks': existing_rec.get('adminRemarks', '') if existing_rec else '',
                    'updated_at': datetime.utcnow()
                }

                # Persist or update
                approval_col.update_one(
                    {'month': target_month, 'department': dept_name},
                    {'$set': doc},
                    upsert=True
                )

                department_summaries.append({
                    'department': dept_name,
                    'status': doc['status'],
                    'employeeCount': doc['employeeCount'],
                    'totalPresent': doc['totalPresent'],
                    'totalAbsent': doc['totalAbsent'],
                    'totalLeaves': doc['totalLeaves'],
                    'totalSinglePunch': doc['totalSinglePunch'],
                    'totalLateHours': doc['totalLateHours'],
                    'totalShortfallMinutes': doc['totalShortfallMinutes'],
                    'totalShortfallHours': doc['totalShortfallHours'],
                    'regularizedCount': dept_reg_count,
                    'hodApprovedBy': doc['hodApprovedBy'],
                    'hodApprovedAt': doc['hodApprovedAt'],
                    'hodRemarks': doc['hodRemarks'],
                    'adminApprovedBy': doc['adminApprovedBy'],
                    'adminApprovedAt': doc['adminApprovedAt'],
                    'adminRemarks': doc['adminRemarks'],
                    'updated_at': doc['updated_at']
                })

        # Calculate high-level stats
        total_depts = len(department_summaries)
        draft_count = sum(1 for d in department_summaries if d['status'] == 'Draft')
        hod_approved_count = sum(1 for d in department_summaries if d['status'] == 'HOD_Approved')
        admin_approved_count = sum(1 for d in department_summaries if d['status'] == 'Admin_Approved')

        return Response({
            'success': True,
            'month': target_month,
            'fromDate': from_str,
            'toDate': to_str,
            'periodKey': period_key,
            'departments': department_summaries,
            'stats': {
                'totalDepartments': total_depts,
                'draftCount': draft_count,
                'hodApprovedCount': hod_approved_count,
                'adminApprovedCount': admin_approved_count,
            },
            'userContext': {
                'isHOD': is_restricted_supervisor,
                'isAdmin': is_admin,
                'assignedDepartments': assigned_depts
            }
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("Error in get_attendance_approval_summary")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([HasRoleAndDataPermission])
def get_department_staff_attendance_summary(request):
    """
    Returns detailed staff-by-staff attendance breakdown for a department.
    Used by HOD and Admin to inspect monthly records before approving.
    Includes any regularized attendance and remarks.
    """
    try:
        db = get_mongo_db()
        profiles_col = db['backend_diagnostics_profile']
        reg_col = db['backend_diagnostics_attendance_regularization']
        from employees.views.common.utils import get_inactive_employee_ids, resolve_department_filter
        from employees.views.payroll.payroll_views import calculate_attendance_metrics_from_roster

        dept_input = request.GET.get('department')
        target_month = request.GET.get('month') or datetime.now().strftime('%Y-%m')
        from_date_in = request.GET.get('fromDate') or request.GET.get('from_date')
        to_date_in = request.GET.get('toDate') or request.GET.get('to_date')
        cycle = request.GET.get('cycle', 'hospital')

        if not dept_input:
            return Response({'error': 'Department name is required'}, status=status.HTTP_400_BAD_REQUEST)

        target_month, from_str, to_str, period_key = get_period_dates(target_month, from_date_in, to_date_in, cycle)
        inactive_ids = get_inactive_employee_ids()

        dept_ctx = resolve_department_filter(dept_input)
        
        # Build query for employees in department
        conds = [{'department': {'$regex': f"^{re.escape(str(dept_input).strip())}$", '$options': 'i'}}]
        if dept_ctx.get('target_terms'):
            for t in dept_ctx['target_terms']:
                conds.append({'department': {'$regex': f"^{re.escape(t)}$", '$options': 'i'}})

        dept_profiles = [
            p for p in profiles_col.find({'$or': conds})
            if str(p.get('employeeId', '')).strip() not in inactive_ids
        ]

        if not dept_profiles:
            # Fallback substring match
            dept_profiles = [
                p for p in profiles_col.find({'department': {'$regex': re.escape(str(dept_input).strip()), '$options': 'i'}})
                if str(p.get('employeeId', '')).strip() not in inactive_ids
            ]

        emp_ids = [str(p.get('employeeId', '')).strip() for p in dept_profiles if p.get('employeeId')]

        attendance_map, total_month_days = calculate_attendance_metrics_from_roster(
            target_month=target_month,
            employee_ids=emp_ids,
            treat_sp_as_present=True,
            from_date=from_str,
            to_date=to_str
        )

        # Build designation lookup map
        desig_map = {}
        for d in db['backend_diagnostics_Designation'].find():
            c = d.get('Designation_code')
            n = d.get('designation')
            if c and n:
                desig_map[str(c).strip()] = str(n).strip()
                desig_map[str(n).strip()] = str(n).strip()

        # Fetch regularizations for this department/month
        reg_records = list(reg_col.find({'month': target_month, 'department': dept_input}))
        reg_map = {str(r.get('employeeId')): r for r in reg_records if r.get('employeeId')}

        staff_list = []
        for prof in dept_profiles:
            eid = str(prof.get('employeeId', '')).strip()
            name = prof.get('employeeName') or prof.get('name') or prof.get('employee_name') or f"Employee {eid}"
            raw_desig = str(prof.get('designation') or '').strip()
            desig = desig_map.get(raw_desig, raw_desig) or 'Staff'
            dept_name = prof.get('department') or dept_input

            m = attendance_map.get(eid, {})
            pres = float(m.get('present_days', 0) or 0)
            lop = float(m.get('lop_days', 0) or 0)
            sp = int(m.get('sp_days', 0) or 0)
            sp_dates = m.get('sp_dates', [])
            daily_records = m.get('daily_records', [])
            leaves = int(m.get('leave_days', 0) or 0)
            offs = int(m.get('off_days', 0) or 0)
            late_lop = float(m.get('late_lop_days', 0) or 0)
            late_evts = m.get('late_events_list', [])

            reg = reg_map.get(eid)
            is_reg = bool(reg)
            orig_pres = pres
            orig_lop = lop
            orig_sp = sp

            # Strict HOD limit tracking (Max 3 regularizations per employee per month)
            hod_reg_count = int(reg.get('hodRegularizationCount', 1 if reg else 0) if reg else 0)
            hod_limit = 3
            hod_remaining = max(0, hod_limit - hod_reg_count)
            is_hod_limit_reached = hod_reg_count >= hod_limit

            if reg:
                pres = float(reg.get('regularizedPresentDays', pres))
                lop = float(reg.get('regularizedLopDays', lop))
                sp = int(reg.get('regularizedSpDays', sp))

            staff_list.append({
                'employeeId': eid,
                'employeeName': name,
                'designation': desig,
                'designationCode': raw_desig,
                'department': dept_name,
                'totalMonthDays': total_month_days,
                'presentDays': round(pres, 1),
                'lopDays': round(lop, 1),
                'spDays': sp,
                'spDates': sp_dates,
                'dailyRecords': daily_records,
                'totalShortfallMinutes': int(m.get('total_shortfall_mins', 0) or 0),
                'shortfallHoursStr': m.get('shortfall_hours_str', '0m'),
                'leaveDays': leaves,
                'offDays': offs,
                'lateLopDays': round(late_lop, 1),
                'lateOccasions': len(late_evts),
                'lateEvents': late_evts,
                'isRegularized': is_reg,
                'originalPresent': round(orig_pres, 1),
                'originalLop': round(orig_lop, 1),
                'originalSp': orig_sp,
                'regularizationReason': reg.get('reason', '') if reg else '',
                'regularizedBy': reg.get('regularizedBy', '') if reg else '',
                'regularizedAt': reg.get('regularizedAt', '') if reg else '',
                'hodRegularizationCount': hod_reg_count,
                'hodRegularizationLimit': hod_limit,
                'hodRegularizationRemaining': hod_remaining,
                'isHodLimitReached': is_hod_limit_reached
            })

        # Sort alphabetically by employee name
        staff_list.sort(key=lambda s: str(s['employeeName']).lower())

        return Response({
            'success': True,
            'department': dept_input,
            'month': target_month,
            'fromDate': from_str,
            'toDate': to_str,
            'staffCount': len(staff_list),
            'staff': staff_list
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("Error in get_department_staff_attendance_summary")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def regularize_employee_attendance(request):
    """
    Regularize attendance for a specific employee in Attendance Approvals.
    - MANDATORY reason/remarks required.
    - STRICT LIMIT: HOD can regularize at most 3 times per employee for a month.
    """
    try:
        db = get_mongo_db()
        reg_col = db['backend_diagnostics_attendance_regularization']
        approval_col = db['backend_diagnostics_attendance_approval']
        data = request.data

        month = data.get('month') or datetime.now().strftime('%Y-%m')
        from_date_in = data.get('fromDate') or data.get('from_date')
        to_date_in = data.get('toDate') or data.get('to_date')
        cycle = data.get('cycle', 'hospital')
        month, from_str, to_str, period_key = get_period_dates(month, from_date_in, to_date_in, cycle)

        emp_id = str(data.get('employeeId', '')).strip()
        dept_name = str(data.get('department', '')).strip()
        emp_name = str(data.get('employeeName', '')).strip()
        present_days = float(data.get('presentDays', 0) or 0)
        lop_days = float(data.get('lopDays', 0) or 0)
        sp_days = int(data.get('spDays', 0) or 0)
        reason = str(data.get('reason') or data.get('remarks') or '').strip()
        user_id = data.get('userId') or data.get('user_id') or 'system'
        user_name = data.get('userName') or data.get('user_name') or 'User'

        if not emp_id or not dept_name:
            return Response({'error': 'Employee ID and Department are required'}, status=status.HTTP_400_BAD_REQUEST)

        # MANDATORY REASON: User explicitly requested mandatory reason/remarks!
        if not reason:
            return Response({'error': 'Reason or remarks for regularization is mandatory.'}, status=status.HTTP_400_BAD_REQUEST)

        # Check if department attendance is already locked by Admin
        existing_appr = approval_col.find_one({
            '$or': [{'month': month, 'department': dept_name}, {'periodKey': period_key, 'department': dept_name}]
        })
        if existing_appr and existing_appr.get('status') == 'Admin_Approved':
            return Response({'error': 'Cannot regularize: Attendance for this department is already Approved & Locked by Admin.'}, status=status.HTTP_400_BAD_REQUEST)

        # HOD 3-REGULARIZATION STRICT LIMIT ENFORCEMENT
        from employees.views.common.utils import get_request_user_approval_context
        user_role_in = str(data.get('userRole') or data.get('role') or '').strip().upper()
        user_ctx = get_request_user_approval_context(request)
        is_user_hod = (
            user_role_in == 'HOD' or
            user_ctx.get('is_hod', False)
        ) and not user_ctx.get('is_admin', False) and user_role_in not in ['ADMIN', 'HR', 'HR-ADMIN']

        existing_reg = reg_col.find_one({
            '$or': [
                {'month': month, 'employeeId': emp_id},
                {'periodKey': period_key, 'employeeId': emp_id}
            ]
        })
        existing_hod_count = int(existing_reg.get('hodRegularizationCount', 0) if existing_reg else 0)

        if is_user_hod:
            if existing_hod_count >= 3:
                return Response({
                    'error': f"HOD Regularization Limit Reached: An HOD is permitted to regularize a maximum of 3 times per employee for a month. Staff member {emp_name or emp_id} has already utilized all 3 regularizations. Further regularizations require Admin approval.",
                    'limitReached': True,
                    'hodRegularizationCount': existing_hod_count,
                    'hodRegularizationLimit': 3
                }, status=status.HTTP_400_BAD_REQUEST)
            new_hod_count = existing_hod_count + 1
        else:
            new_hod_count = existing_hod_count

        editor_label = f"{user_id} - {user_name}" if user_id != 'system' else user_name
        now_iso = datetime.utcnow().isoformat()

        doc = {
            'month': month,
            'fromDate': from_str,
            'toDate': to_str,
            'periodKey': period_key,
            'department': dept_name,
            'employeeId': emp_id,
            'employeeName': emp_name,
            'regularizedPresentDays': round(present_days, 1),
            'regularizedLopDays': round(lop_days, 1),
            'regularizedSpDays': sp_days,
            'reason': reason,
            'regularizedBy': editor_label,
            'regularizedAt': now_iso,
            'hodRegularizationCount': new_hod_count,
            'lastRegularizedByRole': 'HOD' if is_user_hod else 'Admin',
            'updated_at': datetime.utcnow()
        }

        reg_col.update_one(
            {'month': month, 'employeeId': emp_id},
            {'$set': doc},
            upsert=True
        )

        # Recompute department totals in backend_diagnostics_attendance_approval
        recompute_department_attendance_totals(dept_name, month, from_str, to_str, period_key)

        return Response({
            'success': True,
            'message': f"Attendance for {emp_name or emp_id} regularized successfully with reason: '{reason}'.",
            'regularization': doc
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.exception("Error regularizing employee attendance")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def recompute_department_attendance_totals(dept_name, month, from_str, to_str, period_key):
    """
    Recomputes totalPresent, totalAbsent, totalSinglePunch for the department
    taking into account all regularized records in backend_diagnostics_attendance_regularization.
    """
    try:
        db = get_mongo_db()
        profiles_col = db['backend_diagnostics_profile']
        approval_col = db['backend_diagnostics_attendance_approval']
        reg_col = db['backend_diagnostics_attendance_regularization']
        from employees.views.common.utils import get_inactive_employee_ids, resolve_department_filter
        from employees.views.payroll.payroll_views import calculate_attendance_metrics_from_roster

        inactive_ids = get_inactive_employee_ids()
        dept_ctx = resolve_department_filter(dept_name)

        conds = [{'department': {'$regex': f"^{re.escape(str(dept_name).strip())}$", '$options': 'i'}}]
        if dept_ctx.get('target_terms'):
            for t in dept_ctx['target_terms']:
                conds.append({'department': {'$regex': f"^{re.escape(t)}$", '$options': 'i'}})

        dept_profiles = [
            p for p in profiles_col.find({'$or': conds})
            if str(p.get('employeeId', '')).strip() not in inactive_ids
        ]
        if not dept_profiles:
            dept_profiles = [
                p for p in profiles_col.find({'department': {'$regex': re.escape(str(dept_name).strip()), '$options': 'i'}})
                if str(p.get('employeeId', '')).strip() not in inactive_ids
            ]

        emp_ids = [str(p.get('employeeId', '')).strip() for p in dept_profiles if p.get('employeeId')]
        if not emp_ids:
            return

        att_map, total_month_days = calculate_attendance_metrics_from_roster(
            target_month=month,
            employee_ids=emp_ids,
            treat_sp_as_present=True,
            from_date=from_str,
            to_date=to_str
        )

        reg_records = list(reg_col.find({'month': month, 'department': dept_name}))
        reg_map = {str(r.get('employeeId')): r for r in reg_records if r.get('employeeId')}

        tot_pres = 0.0
        tot_abs = 0.0
        tot_leaves = 0
        tot_sp = 0
        tot_late_lop = 0.0
        tot_sf_mins = 0
        reg_count = 0

        for eid in emp_ids:
            m = att_map.get(eid, {})
            tot_sf_mins += int(m.get('total_shortfall_mins', 0) or 0)
            reg = reg_map.get(eid)
            if reg:
                reg_count += 1
                tot_pres += float(reg.get('regularizedPresentDays', m.get('present_days', 0)) or 0)
                tot_abs += float(reg.get('regularizedLopDays', m.get('lop_days', 0)) or 0)
                tot_sp += int(reg.get('regularizedSpDays', m.get('sp_days', 0)) or 0)
            else:
                tot_pres += float(m.get('present_days', 0) or 0)
                tot_abs += float(m.get('lop_days', 0) or 0)
                tot_sp += int(m.get('sp_days', 0) or 0)

            tot_leaves += int(m.get('leave_days', 0) or 0)
            tot_late_lop += float(m.get('late_lop_days', 0) or 0)

        tot_sf_hours_str = f"{tot_sf_mins // 60}h {tot_sf_mins % 60:02d}m" if tot_sf_mins >= 60 else (f"{tot_sf_mins}m" if tot_sf_mins > 0 else "0m")

        approval_col.update_one(
            {'$or': [{'month': month, 'department': dept_name}, {'periodKey': period_key, 'department': dept_name}]},
            {
                '$set': {
                    'totalPresent': round(tot_pres, 1),
                    'totalAbsent': round(tot_abs, 1),
                    'totalLeaves': tot_leaves,
                    'totalSinglePunch': tot_sp,
                    'totalLateHours': round(tot_late_lop, 1),
                    'totalShortfallMinutes': tot_sf_mins,
                    'totalShortfallHours': tot_sf_hours_str,
                    'regularizedCount': reg_count,
                    'updated_at': datetime.utcnow()
                }
            }
        )
    except Exception as e:
        logger.exception("Error recomputing department attendance totals")


@api_view(['POST'])
@permission_classes([HasRoleAndDataPermission])
def department_attendance_action(request):
    """
    2-Tier Attendance Action Handler:
    - hod_approve: HOD reviews department attendance -> Status becomes 'HOD_Approved' (Submitted to Admin)
    - hod_reject: HOD reverts submission back to 'Draft'
    - admin_approve: Admin gives final sign-off & locks attendance -> Status becomes 'Admin_Approved'
                     AND automatically syncs locked attendance to backend_diagnostics_payroll for salary processing.
    - admin_reject: Admin returns department to 'Draft' with revision remarks for HOD.
    """
    try:
        db = get_mongo_db()
        approval_col = db['backend_diagnostics_attendance_approval']
        data = request.data

        action = str(data.get('action', '')).strip() # 'hod_approve', 'hod_reject', 'admin_approve', 'admin_reject'
        dept_input = str(data.get('department', '')).strip()
        month = data.get('month') or datetime.now().strftime('%Y-%m')
        from_date_in = data.get('fromDate') or data.get('from_date')
        to_date_in = data.get('toDate') or data.get('to_date')
        cycle = data.get('cycle', 'hospital')
        user_id = data.get('userId') or data.get('user_id') or 'system'
        user_name = data.get('userName') or data.get('user_name') or 'User'
        remarks = str(data.get('remarks') or data.get('reason') or '').strip()

        if not dept_input or dept_input == 'All':
            return Response({'error': 'Specific department is required for this action'}, status=status.HTTP_400_BAD_REQUEST)

        month, from_str, to_str, period_key = get_period_dates(month, from_date_in, to_date_in, cycle)

        existing_record = approval_col.find_one({
            '$or': [
                {'month': month, 'department': dept_input},
                {'periodKey': period_key, 'department': dept_input}
            ]
        })

        now_iso = datetime.utcnow().isoformat()
        editor_label = f"{user_id} - {user_name}" if user_id != 'system' else user_name

        if action == 'hod_approve':
            if existing_record and existing_record.get('status') == 'Admin_Approved':
                return Response({'error': 'This department attendance has already been Approved & Locked by Admin.'}, status=status.HTTP_400_BAD_REQUEST)

            approval_col.update_one(
                {'$or': [{'month': month, 'department': dept_input}, {'periodKey': period_key, 'department': dept_input}]},
                {
                    '$set': {
                        'month': month,
                        'fromDate': from_str,
                        'toDate': to_str,
                        'periodKey': period_key,
                        'department': dept_input,
                        'status': 'HOD_Approved',
                        'hodApprovedBy': editor_label,
                        'hodApprovedAt': now_iso,
                        'hodRemarks': remarks or 'Attendance verified by Department HOD',
                        'updated_at': datetime.utcnow()
                    }
                },
                upsert=True
            )

            return Response({
                'success': True,
                'message': f"Department '{dept_input}' attendance verified & submitted to Admin successfully.",
                'department': dept_input,
                'status': 'HOD_Approved'
            }, status=status.HTTP_200_OK)

        elif action == 'hod_reject':
            if existing_record and existing_record.get('status') == 'Admin_Approved':
                return Response({'error': 'Cannot revert: Department attendance is already Approved & Locked by Admin.'}, status=status.HTTP_400_BAD_REQUEST)

            approval_col.update_one(
                {'$or': [{'month': month, 'department': dept_input}, {'periodKey': period_key, 'department': dept_input}]},
                {
                    '$set': {
                        'status': 'Draft',
                        'hodApprovedBy': None,
                        'hodApprovedAt': None,
                        'hodRemarks': remarks or 'Submission reverted by HOD',
                        'updated_at': datetime.utcnow()
                    }
                }
            )

            return Response({
                'success': True,
                'message': f"Department '{dept_input}' attendance submission reverted back to Draft.",
                'department': dept_input,
                'status': 'Draft'
            }, status=status.HTTP_200_OK)

        elif action == 'admin_approve':
            # Admin Final Approval & Lock -> Automatically syncs to payroll
            approval_col.update_one(
                {'$or': [{'month': month, 'department': dept_input}, {'periodKey': period_key, 'department': dept_input}]},
                {
                    '$set': {
                        'month': month,
                        'fromDate': from_str,
                        'toDate': to_str,
                        'periodKey': period_key,
                        'department': dept_input,
                        'status': 'Admin_Approved',
                        'adminApprovedBy': editor_label,
                        'adminApprovedAt': now_iso,
                        'adminRemarks': remarks or 'Approved and locked for monthly payroll',
                        'updated_at': datetime.utcnow()
                    }
                },
                upsert=True
            )

            # Trigger automatic sync to payroll collection for this department
            sync_res = sync_department_payroll_from_attendance(
                department=dept_input,
                month=month,
                from_date_str=from_str,
                to_date_str=to_str,
                editor_label=editor_label
            )

            return Response({
                'success': True,
                'message': f"Department '{dept_input}' attendance Approved & Locked by Admin. Payroll data is ready.",
                'department': dept_input,
                'status': 'Admin_Approved',
                'payrollSync': sync_res
            }, status=status.HTTP_200_OK)

        elif action == 'admin_reject':
            if not remarks:
                return Response({'error': 'Remarks are mandatory when rejecting or returning attendance to HOD.'}, status=status.HTTP_400_BAD_REQUEST)

            approval_col.update_one(
                {'$or': [{'month': month, 'department': dept_input}, {'periodKey': period_key, 'department': dept_input}]},
                {
                    '$set': {
                        'status': 'Draft',
                        'adminApprovedBy': None,
                        'adminApprovedAt': None,
                        'adminRemarks': f"Returned by Admin: {remarks}",
                        'hodApprovedBy': None,
                        'hodApprovedAt': None,
                        'updated_at': datetime.utcnow()
                    }
                }
            )

            # In payroll collection, mark any existing payroll for this department back to Draft / Pending Attendance
            payroll_col = db['backend_diagnostics_payroll']
            payroll_col.update_many(
                {'month': month, 'department': dept_input},
                {'$set': {'departmentStatus': 'Draft', 'status': 'Draft', 'updated_at': datetime.utcnow()}}
            )

            return Response({
                'success': True,
                'message': f"Department '{dept_input}' attendance returned to HOD with revision remarks.",
                'department': dept_input,
                'status': 'Draft'
            }, status=status.HTTP_200_OK)

        else:
            return Response({'error': f'Unsupported action: {action}'}, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.exception("Error in department_attendance_action")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def sync_department_payroll_from_attendance(department, month, from_date_str, to_date_str, editor_label):
    """
    Syncs verified attendance (including any employee regularizations) directly into
    backend_diagnostics_payroll records for this department.
    Marks departmentStatus: 'Admin_Approved' in payroll so HR/Admin can disburse salary.
    """
    try:
        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        profiles_col = db['backend_diagnostics_profile']
        reg_col = db['backend_diagnostics_attendance_regularization']
        from employees.views.common.utils import get_inactive_employee_ids, resolve_department_filter
        from employees.views.payroll.payroll_views import calculate_attendance_metrics_from_roster

        inactive_ids = get_inactive_employee_ids()
        dept_ctx = resolve_department_filter(department)

        conds = [{'department': {'$regex': f"^{re.escape(str(department).strip())}$", '$options': 'i'}}]
        if dept_ctx.get('target_terms'):
            for t in dept_ctx['target_terms']:
                conds.append({'department': {'$regex': f"^{re.escape(t)}$", '$options': 'i'}})

        dept_profiles = [
            p for p in profiles_col.find({'$or': conds})
            if str(p.get('employeeId', '')).strip() not in inactive_ids
        ]

        if not dept_profiles:
            dept_profiles = [
                p for p in profiles_col.find({'department': {'$regex': re.escape(str(department).strip()), '$options': 'i'}})
                if str(p.get('employeeId', '')).strip() not in inactive_ids
            ]

        emp_ids = [str(p.get('employeeId', '')).strip() for p in dept_profiles if p.get('employeeId')]
        if not emp_ids:
            return {'syncedCount': 0, 'status': 'No active staff in department'}

        attendance_map, total_month_days = calculate_attendance_metrics_from_roster(
            target_month=month,
            employee_ids=emp_ids,
            treat_sp_as_present=True,
            from_date=from_date_str,
            to_date=to_date_str
        )

        reg_records = list(reg_col.find({'month': month, 'department': department}))
        reg_map = {str(r.get('employeeId')): r for r in reg_records if r.get('employeeId')}

        now_iso = datetime.utcnow().isoformat()
        period_key = f"{from_date_str}_{to_date_str}"
        synced_count = 0

        for prof in dept_profiles:
            eid = str(prof.get('employeeId', '')).strip()
            name = prof.get('name') or prof.get('employee_name') or f"Employee {eid}"
            desig = prof.get('designation') or ''
            dept_name = prof.get('department') or department

            salary_info = prof.get('salaryDetails', {}) or {}
            bank_info = prof.get('bankDetails', {}) or {}

            def parse_num(val, default=0.0):
                if val is None:
                    return default
                if isinstance(val, (int, float)):
                    return float(val)
                s = str(val).strip().replace(',', '')
                if not s:
                    return default
                try:
                    return float(s)
                except Exception:
                    return default

            basic = parse_num(salary_info.get('basicSalary'))
            hra = parse_num(salary_info.get('hra'))
            allowances = parse_num(salary_info.get('otherAllowances') or salary_info.get('allowances'))
            gross = basic + hra + allowances

            # Attendance metrics (applying regularization if present)
            m = attendance_map.get(eid, {})
            pres = float(m.get('present_days', 0) or 0)
            lop = float(m.get('lop_days', 0) or 0)
            sp = int(m.get('sp_days', 0) or 0)
            late_lop = float(m.get('late_lop_days', 0) or 0)

            reg = reg_map.get(eid)
            if reg:
                pres = float(reg.get('regularizedPresentDays', pres))
                lop = float(reg.get('regularizedLopDays', lop))
                sp = int(reg.get('regularizedSpDays', sp))

            # LOP deduction
            daily_gross = (gross / total_month_days) if total_month_days > 0 else 0.0
            lop_ded = round(daily_gross * lop, 2)
            late_ded = round(daily_gross * late_lop, 2)

            pf = parse_num(salary_info.get('pf'))
            esi = parse_num(salary_info.get('esi'))
            pt = parse_num(salary_info.get('professionalTax'))
            tds = parse_num(salary_info.get('tds'))

            tot_ded = lop_ded + late_ded + pf + esi + pt + tds
            net = max(0.0, round(gross - tot_ded, 2))

            # Fetch existing payroll record to preserve any admin-entered custom fines / caution deposit / mess
            existing_pay = payroll_col.find_one({
                '$or': [
                    {'month': month, 'employeeId': eid},
                    {'periodKey': period_key, 'employeeId': eid}
                ]
            })

            if existing_pay:
                # Update attendance and lock status
                fines = float(existing_pay.get('fines', 0) or 0)
                other_ded = float(existing_pay.get('otherDeductions', 0) or 0)
                mess = float(existing_pay.get('messEb', 0) or 0)
                caution = float(existing_pay.get('cautionDeposit', 0) or 0)
                uniform = float(existing_pay.get('uniformId', 0) or 0)
                vaccine = float(existing_pay.get('vaccineDeduction', 0) or 0)

                tot_ded = lop_ded + late_ded + pf + esi + pt + tds + fines + other_ded + mess + caution + uniform + vaccine
                net = max(0.0, round(gross - tot_ded, 2))

                payroll_col.update_one(
                    {'_id': existing_pay['_id']},
                    {
                        '$set': {
                            'totalMonthDays': total_month_days,
                            'presentDays': round(pres, 1),
                            'lopDays': round(lop, 1),
                            'spDays': sp,
                            'lopDeduction': lop_ded,
                            'lateDeduction': late_ded,
                            'totalDeductions': round(tot_ded, 2),
                            'netSalary': net,
                            'departmentStatus': 'Admin_Approved',
                            'adminApprovedBy': editor_label,
                            'adminApprovedAt': now_iso,
                            'attendanceLocked': True,
                            'updated_at': datetime.utcnow()
                        }
                    }
                )
            else:
                new_doc = {
                    'month': month,
                    'fromDate': from_date_str,
                    'toDate': to_date_str,
                    'periodKey': period_key,
                    'employeeId': eid,
                    'employeeName': name,
                    'department': dept_name,
                    'designation': desig,
                    'bankName': bank_info.get('bankName', ''),
                    'accountNumber': bank_info.get('accountNumber', ''),
                    'ifscCode': bank_info.get('ifscCode', ''),
                    'panNumber': bank_info.get('panNumber', ''),
                    'basicSalary': basic,
                    'hra': hra,
                    'allowances': allowances,
                    'clEncashment': 0.0,
                    'incentives': 0.0,
                    'grossSalary': round(gross, 2),
                    'totalMonthDays': total_month_days,
                    'presentDays': round(pres, 1),
                    'lopDays': round(lop, 1),
                    'spDays': sp,
                    'lopDeduction': lop_ded,
                    'lateDeduction': late_ded,
                    'pf': pf,
                    'esi': esi,
                    'professionalTax': pt,
                    'tdsDeduction': tds,
                    'messEb': 0.0,
                    'cautionDeposit': 0.0,
                    'uniformId': 0.0,
                    'vaccineDeduction': 0.0,
                    'fines': 0.0,
                    'fineRemarks': '',
                    'otherDeductions': 0.0,
                    'otherDeductionsRemarks': '',
                    'totalDeductions': round(tot_ded, 2),
                    'netSalary': net,
                    'paymentMode': 'Bank Transfer',
                    'status': 'Draft',
                    'departmentStatus': 'Admin_Approved',
                    'adminApprovedBy': editor_label,
                    'adminApprovedAt': now_iso,
                    'attendanceLocked': True,
                    'created_at': datetime.utcnow(),
                    'updated_at': datetime.utcnow()
                }
                payroll_col.insert_one(new_doc)

            synced_count += 1

        return {'syncedCount': synced_count, 'status': 'Successfully synced to payroll'}

    except Exception as e:
        logger.exception("Error syncing department payroll from attendance")
        return {'syncedCount': 0, 'error': str(e)}
