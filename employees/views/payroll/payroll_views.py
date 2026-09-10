import os
import io
import re
import csv
import json
import logging
import calendar
from datetime import datetime, date, time, timedelta
from bson import ObjectId
import pytz
from django.http import HttpResponse, JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient

logger = logging.getLogger(__name__)
IST = pytz.timezone('Asia/Kolkata')

def to_ist(dt):
    if not dt:
        return None
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except:
            return None
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(IST)

def get_mongo_db():
    mongo_uri = os.environ.get('GLOBAL_DB_HOST', 'mongodb://localhost:27017')
    db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
    client = MongoClient(mongo_uri)
    return client[db_name]


def calculate_late_hours_lop(late_minutes_list):
    """
    Implements the August 2026 Late Hours New Formula:
    1. 0 to 10 mins: Free grace period (0 penalty).
    2. 11 to 30 mins: Occasions rule.
       - 0 to 3 occasions: 0 LOP
       - 4 to 5 occasions: 0.5 LOP
       - 6 to 8 occasions: 1.0 LOP
       - 9 to 11 occasions: 1.5 LOP
       - 12 to 14 occasions: 2.0 LOP
       - 15 to 17 occasions: 2.5 LOP
       - 18 to 20 occasions: 3.0 LOP
       - 21 to 23 occasions: 3.5 LOP
       - 24+ occasions: 4.0 LOP
    3. Heavy late hours:
       - 31 to 60 mins (0.5 to 1 hr): 0.5 Day LOP per occurrence
       - Above 60 mins (> 1 hr): 1.0 Day LOP per occurrence
    Returns dict with breakdown and total late LOP days.
    """
    occ_count = sum(1 for m in late_minutes_list if 10 < m <= 30)
    
    occ_slabs = [
        (24, 4.0), (21, 3.5), (18, 3.0), (15, 2.5),
        (12, 2.0), (9, 1.5), (6, 1.0), (4, 0.5), (0, 0.0)
    ]
    occ_lop = 0.0
    for threshold, lop in occ_slabs:
        if occ_count >= threshold:
            occ_lop = lop
            break
            
    heavy_half = sum(1 for m in late_minutes_list if 30 < m <= 60)
    heavy_full = sum(1 for m in late_minutes_list if m > 60)
    heavy_lop = (heavy_half * 0.5) + (heavy_full * 1.0)
    
    total_late_lop = round(occ_lop + heavy_lop, 2)
    return {
        'occ_count': occ_count,
        'occ_lop': occ_lop,
        'heavy_half_count': heavy_half,
        'heavy_full_count': heavy_full,
        'heavy_lop': heavy_lop,
        'total_late_lop_days': total_late_lop
    }


def calculate_attendance_metrics_from_roster(target_month=None, employee_ids=None, treat_sp_as_present=True, from_date=None, to_date=None):
    """
    Computes exact Present Days, LOP (Absent) Days, and Single Punch (SP) Days
    matching the Duty Roster Attendance Report for a target month or custom date range.
    Only true unapproved missed shifts count as LOP.
    Leaves (EL, CL, SL, etc.) and Week Offs/Holidays/Sundays count as Paid days (Present).
    """
    if from_date and to_date:
        if isinstance(from_date, str):
            start_date = datetime.strptime(str(from_date).strip(), '%Y-%m-%d').date()
        elif isinstance(from_date, datetime):
            start_date = from_date.date()
        else:
            start_date = from_date

        if isinstance(to_date, str):
            end_date = datetime.strptime(str(to_date).strip(), '%Y-%m-%d').date()
        elif isinstance(to_date, datetime):
            end_date = to_date.date()
        else:
            end_date = to_date
        target_month = f"{start_date.year:04d}-{start_date.month:02d}"
    else:
        try:
            parts = str(target_month).split('-')
            year = int(parts[0])
            month = int(parts[1])
        except Exception:
            now = datetime.now()
            year = now.year
            month = now.month
            target_month = f"{year:04d}-{month:02d}"

        _, last_day = calendar.monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, last_day)

    report_dates = []
    curr = start_date
    while curr <= end_date:
        report_dates.append(curr)
        curr += timedelta(days=1)

    total_days_in_month = len(report_dates)

    db = get_mongo_db()

    # 1. Fetch All Shifts & Shift Schedules from MongoDB Global directly
    from employees.models import Shift, LeaveRequest
    all_shifts = {s.id: s for s in Shift.objects.all()}

    start_dt_sch = datetime.combine(start_date, datetime.min.time())
    end_dt_sch = datetime.combine(end_date, datetime.max.time())
    sch_query = {
        'date': {'$gte': start_dt_sch, '$lte': end_dt_sch}
    }
    if employee_ids:
        sch_query['employee_id'] = {'$in': [str(eid) for eid in employee_ids]}

    schedules_raw = list(db['employees_employeeshiftschedule'].find(
        sch_query, 
        {'_id': 0, 'employee_id': 1, 'shift_id': 1, 'date': 1}
    ))
    schedule_map = {}
    for sch in schedules_raw:
        sch_date = sch['date'].date() if isinstance(sch.get('date'), datetime) else sch.get('date')
        schedule_map[(str(sch.get('employee_id', '')), sch_date)] = all_shifts.get(sch.get('shift_id'))

    # 2. Fetch Attendance Punches from MongoDB Global directly
    start_dt = datetime.combine(start_date - timedelta(days=1), datetime.min.time())
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.max.time())

    att_query = {
        'attendence_time': {'$gte': start_dt, '$lte': end_dt}
    }
    if employee_ids:
        att_query['employee_id'] = {'$in': [str(eid) for eid in employee_ids]}

    attendance_records = list(db['employees_employeeattendance'].find(
        att_query,
        {'_id': 0, 'employee_id': 1, 'attendence_time': 1, 'attendence_type': 1}
    ).sort([('employee_id', 1), ('attendence_time', 1)]))

    # Process attendance into date-assigned punches matching Roster Report
    attendance_map = {}
    current_emp_id = None
    current_shift_date = None
    last_in_time = None
    noon_time = time(12, 0)

    for att in attendance_records:
        att_time = att.get('attendence_time')
        if not att_time:
            continue
        ist_time = to_ist(att_time)
        if not ist_time:
            continue
        punch_date = ist_time.date()
        
        eid = str(att.get('employee_id', ''))
        if current_emp_id != eid:
            current_emp_id = eid
            current_shift_date = None
            last_in_time = None
            
        punch_type = att.get('attendence_type')
        assigned_date = punch_date
        
        if punch_type == 'IN':
            current_shift_date = punch_date
            last_in_time = ist_time
            assigned_date = current_shift_date
        elif punch_type == 'OUT':
            if current_shift_date and last_in_time:
                if (ist_time - last_in_time).total_seconds() <= 16 * 3600:
                    assigned_date = current_shift_date
                else:
                    if ist_time.time() < noon_time:
                        assigned_date = punch_date - timedelta(days=1)
            else:
                if ist_time.time() < noon_time:
                    assigned_date = punch_date - timedelta(days=1)

        key = (eid, assigned_date)
        if key not in attendance_map:
            attendance_map[key] = []
        attendance_map[key].append({'time': ist_time, 'type': punch_type})

    # 3. Fetch Approved Leaves
    approved_leave_map = {}
    try:
        leaves = LeaveRequest.objects.filter(
            status='Approved',
            start_date__lte=end_date,
            end_date__gte=start_date
        )
        for l in leaves:
            eid = str(l.employee_id)
            c = max(l.start_date, start_date)
            e = min(l.end_date, end_date)
            while c <= e:
                approved_leave_map[(eid, c)] = l.leave_type or 'Leave'
                c += timedelta(days=1)
    except Exception as e:
        logger.warning(f"Error querying leaves for payroll: {e}")

    # 3b. Fetch granted permissions from backend_diagnostics_permissions
    permissions_map = {}
    try:
        perm_col = db['backend_diagnostics_permissions']
        date_strs = [d.strftime('%Y-%m-%d') for d in report_dates]
        perm_query = {'date': {'$in': date_strs}}
        if employee_ids:
            perm_query['employeeId'] = {'$in': [str(eid) for eid in employee_ids]}
        for p in perm_col.find(perm_query):
            permissions_map[(str(p.get('employeeId', '')), str(p.get('date', '')))] = p
    except Exception as e:
        logger.warning(f"Error querying permissions for payroll: {e}")

    # 4. Evaluate each employee per day
    all_emp_ids = set()
    if employee_ids:
        all_emp_ids.update([str(e) for e in employee_ids])
    for (eid, _) in schedule_map.keys():
        all_emp_ids.add(eid)
    for (eid, _) in attendance_map.keys():
        all_emp_ids.add(eid)

    metrics = {}

    for eid in all_emp_ids:
        present_count = 0.0
        lop_count = 0.0
        off_count = 0
        leave_count = 0
        sp_count = 0
        late_minutes_list = []
        late_events_list = []

        for current_date in report_dates:
            shift_obj = schedule_map.get((eid, current_date))
            punches = attendance_map.get((eid, current_date), [])
            is_approved_leave = (eid, current_date) in approved_leave_map

            shift_name = shift_obj.name.upper() if shift_obj else ""
            is_leave_shift = False
            if shift_obj:
                is_leave_shift = (
                    (shift_obj.start_time.strftime('%H:%M') == '00:00' and shift_obj.end_time.strftime('%H:%M') == '00:00')
                    or shift_name in ['OFF', 'EL', 'CL', 'SL', 'ML', 'COFF', 'LEAVE', 'WEEK OFF', 'PH', 'COL', 'PL', 'OD']
                )

            in_punches = [p for p in punches if p.get('type') == 'IN']
            out_punches = [p for p in punches if p.get('type') == 'OUT']

            # Calculate Roster Time Shortfall (Expected Shift Duration vs Actual Worked Hours)
            if in_punches and out_punches and shift_obj and not is_leave_shift:
                first_in = min([p['time'] for p in in_punches])
                last_out = max([p['time'] for p in out_punches])
                if last_out > first_in:
                    act_mins = int((last_out - first_in).total_seconds() // 60)
                    st = shift_obj.start_time
                    et = shift_obj.end_time
                    st_mins = st.hour * 60 + st.minute
                    et_mins = et.hour * 60 + et.minute
                    if et_mins < st_mins:
                        et_mins += 24 * 60  # Overnight shift
                    exp_mins = et_mins - st_mins
                    shortfall = exp_mins - act_mins

                    # Check for granted 1-hour permission on this date
                    date_str = current_date.strftime('%Y-%m-%d')
                    perm_doc = permissions_map.get((eid, date_str))
                    perm_mins = int(perm_doc.get('durationMins', 60)) if perm_doc else 0
                    effective_shortfall = max(0, shortfall - perm_mins)
                    grace_period = 10

                    if effective_shortfall > grace_period:
                        net_shortfall = effective_shortfall - grace_period
                        if net_shortfall > 0:
                            late_minutes_list.append(net_shortfall)
                            late_events_list.append({
                                'date': date_str,
                                'day_name': current_date.strftime('%a'),
                                'shift_name': shift_name,
                                'shift_timing': f"{st.strftime('%H:%M')} - {et.strftime('%H:%M')}",
                                'expected_mins': exp_mins,
                                'expected_hours_str': f"{exp_mins // 60}h {exp_mins % 60:02d}m",
                                'actual_mins': act_mins,
                                'actual_hours_str': f"{act_mins // 60}h {act_mins % 60:02d}m",
                                'check_in': first_in.strftime('%H:%M:%S'),
                                'check_out': last_out.strftime('%H:%M:%S'),
                                'raw_shortfall_mins': shortfall,
                                'permission_mins': perm_mins,
                                'permission_applied': bool(perm_doc),
                                'permission_reason': perm_doc.get('reason') if perm_doc else '',
                                'permission_approved_by': perm_doc.get('approvedBy') if perm_doc else '',
                                'effective_shortfall_mins': effective_shortfall,
                                'grace_mins': grace_period,
                                'net_shortfall_mins': net_shortfall,
                                'shortfall_str': f"{net_shortfall // 60}h {net_shortfall % 60:02d}m" if net_shortfall >= 60 else f"{net_shortfall}m",
                                'is_heavy': net_shortfall >= 60,
                                'penalty_type': 'Heavy Delay (1.0 Day LOP)' if net_shortfall >= 120 else ('Heavy Delay (0.5 Day LOP)' if net_shortfall >= 60 else 'Occasion Shortfall')
                            })
                    elif perm_doc and shortfall > 0:
                        # Shortfall was fully waived by permission!
                        late_events_list.append({
                            'date': date_str,
                            'day_name': current_date.strftime('%a'),
                            'shift_name': shift_name,
                            'shift_timing': f"{st.strftime('%H:%M')} - {et.strftime('%H:%M')}",
                            'expected_mins': exp_mins,
                            'expected_hours_str': f"{exp_mins // 60}h {exp_mins % 60:02d}m",
                            'actual_mins': act_mins,
                            'actual_hours_str': f"{act_mins // 60}h {act_mins % 60:02d}m",
                            'check_in': first_in.strftime('%H:%M:%S'),
                            'check_out': last_out.strftime('%H:%M:%S'),
                            'raw_shortfall_mins': shortfall,
                            'permission_mins': perm_mins,
                            'permission_applied': True,
                            'permission_reason': perm_doc.get('reason', ''),
                            'permission_approved_by': perm_doc.get('approvedBy', ''),
                            'effective_shortfall_mins': 0,
                            'grace_mins': grace_period,
                            'net_shortfall_mins': 0,
                            'shortfall_str': 'Waived by 1h Permission',
                            'is_heavy': False,
                            'penalty_type': 'Waived by 1h Permission'
                        })

            if current_date > date.today():
                # Future date in the current month: not an absent day!
                off_count += 1
                present_count += 1
            elif in_punches and out_punches:
                # Both IN and OUT punches -> Full Present
                present_count += 1
            elif in_punches or out_punches:
                # Single punch
                sp_count += 1
                if treat_sp_as_present:
                    present_count += 1
                else:
                    present_count += 0.5
                    lop_count += 0.5
            elif is_approved_leave or is_leave_shift:
                # Approved leave shift or formal leave -> Paid day (0 LOP)
                leave_count += 1
                present_count += 1
            elif not shift_obj or current_date.weekday() == 6:
                # Week Off / Sunday / Unassigned -> Paid day (0 LOP)
                off_count += 1
                present_count += 1
            else:
                # Past/today shift was assigned, but employee has no punches and no approved leave -> True Absent / LOP
                lop_count += 1

        late_lop_info = calculate_late_hours_lop(late_minutes_list)

        metrics[eid] = {
            'total_month_days': total_days_in_month,
            'present_days': present_count,
            'lop_days': lop_count,
            'sp_days': sp_count,
            'off_days': off_count,
            'leave_days': leave_count,
            'late_minutes_list': late_minutes_list,
            'late_events_list': late_events_list,
            'late_lop_days': late_lop_info['total_late_lop_days'],
            'late_lop_info': late_lop_info
        }

    return metrics, total_days_in_month


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def monthly_payroll_view(request):
    """
    GET: Retrieve payroll for a specific month or date range (?fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD or ?month=YYYY-MM).
    POST: Generate / Regenerate payroll draft with Duty Roster attendance matching for the specified date range.
    """
    try:
        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        profiles_col = db['backend_diagnostics_profile']
        
        from_date_in = request.GET.get('fromDate') or request.GET.get('from_date') or request.data.get('fromDate') or request.data.get('from_date')
        to_date_in = request.GET.get('toDate') or request.GET.get('to_date') or request.data.get('toDate') or request.data.get('to_date')
        target_month = request.GET.get('month') or request.data.get('month')

        if from_date_in and to_date_in:
            from_date_str = str(from_date_in).strip()
            to_date_str = str(to_date_in).strip()
            if not target_month:
                target_month = to_date_str[:7]
            period_key = f"{from_date_str}_{to_date_str}"
        else:
            if not target_month:
                target_month = datetime.now().strftime('%Y-%m')
            try:
                parts = target_month.split('-')
                y, m = int(parts[0]), int(parts[1])
            except:
                now = datetime.now()
                y, m = now.year, now.month
                target_month = f"{y:04d}-{m:02d}"

            cycle = str(request.GET.get('cycle', request.data.get('cycle', 'hospital'))).lower().strip()
            if cycle in ['hospital', '26-25']:
                if m == 1:
                    prev_y, prev_m = y - 1, 12
                else:
                    prev_y, prev_m = y, m - 1
                from_date_str = f"{prev_y:04d}-{prev_m:02d}-26"
                to_date_str = f"{y:04d}-{m:02d}-25"
                period_key = f"{from_date_str}_{to_date_str}"
            else:
                _, last_d = calendar.monthrange(y, m)
                from_date_str = f"{y:04d}-{m:02d}-01"
                to_date_str = f"{y:04d}-{m:02d}-{last_d:02d}"
                period_key = target_month

        recalculate = str(request.GET.get('recalculate_attendance', '')).lower() in ['true', '1', 'yes'] or request.method == 'POST'
        
        # Check existing records
        from employees.views.common.utils import get_inactive_employee_ids, resolve_department_filter
        inactive_ids = get_inactive_employee_ids()

        exist_query = {'$or': [{'month': target_month}, {'periodKey': period_key}]}
        if from_date_in and to_date_in:
            exist_query = {'$or': [{'fromDate': from_date_str, 'toDate': to_date_str}, {'periodKey': period_key}, {'month': target_month}]}
        
        # Exclude disabled/inactive employees from existing payroll records
        existing_records = [r for r in payroll_col.find(exist_query) if str(r.get('employeeId', '')).strip() not in inactive_ids]
        existing_map = {str(r.get('employeeId')): r for r in existing_records if r.get('employeeId')}

        # Clean up any lingering draft payroll records for disabled employees
        if inactive_ids:
            try:
                payroll_col.delete_many({
                    'month': target_month,
                    'employeeId': {'$in': list(inactive_ids)},
                    'status': 'Draft'
                })
            except Exception:
                pass
        
        from employees.views.common.utils import get_request_user_hod_departments
        is_hod, hod_assigned_depts = get_request_user_hod_departments(request)

        # If requester is HOD, scope existing records strictly to their assigned departments
        if is_hod:
            if hod_assigned_depts:
                hod_allowed_lower = {d.lower().strip() for d in hod_assigned_depts}
                existing_records = [r for r in existing_records if str(r.get('department') or '').strip().lower() in hod_allowed_lower]
            else:
                existing_records = []

        department_filter = request.GET.get('department') or request.data.get('department')
        dept_ctx = resolve_department_filter(department_filter)

        # Build Department Summary across all existing records
        departments_summary = {}
        for r in existing_records:
            d_name = r.get('department') or 'Admin'
            if d_name not in departments_summary:
                departments_summary[d_name] = {
                    'department': d_name,
                    'totalEmployees': 0,
                    'totalGross': 0.0,
                    'totalNet': 0.0,
                    'status': r.get('departmentStatus', r.get('status', 'Draft')),
                    'hasHodEdits': False,
                    'hodApprovedBy': r.get('hodApprovedBy'),
                    'hodApprovedAt': r.get('hodApprovedAt'),
                    'adminApprovedBy': r.get('adminApprovedBy'),
                    'adminApprovedAt': r.get('adminApprovedAt'),
                }
            departments_summary[d_name]['totalEmployees'] += 1
            departments_summary[d_name]['totalGross'] += float(r.get('grossSalary', 0) or 0)
            departments_summary[d_name]['totalNet'] += float(r.get('netSalary', 0) or 0)
            if r.get('hasHodEdits') or (r.get('auditTrail') and len(r.get('auditTrail')) > 0):
                departments_summary[d_name]['hasHodEdits'] = True

        if request.method == 'GET' and existing_records and not recalculate:
            records = []
            total_gross = 0.0
            total_net = 0.0
            total_deductions = 0.0
            
            for r in existing_records:
                r['_id'] = str(r['_id'])
                if dept_ctx['is_filtered'] and not dept_ctx['is_match'](r.get('department')):
                    continue
                records.append(r)
                total_gross += float(r.get('grossSalary', 0) or 0)
                total_net += float(r.get('netSalary', 0) or 0)
                total_deductions += float(r.get('totalDeductions', 0) or 0)
                
            return Response({
                'month': target_month,
                'fromDate': from_date_str,
                'toDate': to_date_str,
                'periodKey': period_key,
                'status': existing_records[0].get('status', 'Draft') if existing_records else 'Draft',
                'isHOD': is_hod,
                'assignedDepartments': hod_assigned_depts if is_hod else [],
                'summary': {
                    'totalEmployees': len(records),
                    'totalGross': round(total_gross, 2),
                    'totalNetPayout': round(total_net, 2),
                    'totalDeductions': round(total_deductions, 2),
                    'departments': list(departments_summary.values())
                },
                'departmentsSummary': departments_summary,
                'records': records
            }, status=status.HTTP_200_OK)
            
        # Check if already locked / approved globally
        if existing_records and existing_records[0].get('status') == 'Approved' and not recalculate:
            return Response({
                'error': f'Payroll for {target_month} is Approved & Locked and cannot be regenerated.',
                'status': 'Approved'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Generate or Refresh from profiles + live Duty Roster attendance calculations
        from employees.views.common.utils import get_inactive_employee_ids
        inactive_ids = get_inactive_employee_ids()

        profile_query = {}
        if dept_ctx['is_filtered']:
            profile_query = dict(dept_ctx['mongo_query'])
        all_profiles = [p for p in profiles_col.find(profile_query) if str(p.get('employeeId', '')).strip() not in inactive_ids]
        new_records = []
        now_ts = datetime.utcnow()
        
        # Calculate attendance metrics matching Duty Roster
        all_emp_ids = [str(p.get('employeeId', '')).strip() for p in all_profiles if p.get('employeeId')]
        treat_sp = str(request.GET.get('treat_sp_as_present', request.data.get('treat_sp_as_present', 'true'))).lower() in ['true', '1', 'yes']
        attendance_map, total_month_days = calculate_attendance_metrics_from_roster(
            target_month=target_month,
            employee_ids=all_emp_ids,
            treat_sp_as_present=treat_sp,
            from_date=from_date_str,
            to_date=to_date_str
        )
        
        total_gross = 0.0
        total_net = 0.0
        total_deductions = 0.0
        
        # Build canonical department lookup map
        depts_map = {}
        for d in db['backend_diagnostics_Departments'].find():
            c = d.get('department_code')
            n = d.get('department_name')
            if c and n:
                depts_map[str(c).strip()] = n.strip()
            if n:
                depts_map[n.strip().lower()] = n.strip()

        def get_clean_dept(raw_val):
            if not raw_val:
                return 'Admin'
            raw_s = str(raw_val).strip()
            if raw_s in depts_map:
                return depts_map[raw_s]
            if raw_s.lower() in depts_map:
                return depts_map[raw_s.lower()]
            return raw_s

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
            except:
                return default

        for idx, p in enumerate(all_profiles, 1):
            emp_id = str(p.get('employeeId', '')).strip()
            if not emp_id:
                continue
                
            salary_info = p.get('salaryDetails', {}) or {}
            bank_info = p.get('bankDetails', {}) or {}
            
            basic = parse_num(salary_info.get('basicSalary'))
            hra = parse_num(salary_info.get('hra'), round(basic * 0.20, 2) if basic > 0 else 0.0)
            allowances = parse_num(salary_info.get('allowances'), round(basic * 0.10, 2) if basic > 0 else 0.0)
            gross = parse_num(salary_info.get('grossSalary'), basic + hra + allowances)
            if gross == 0.0:
                gross = basic
                
            # Statutory Contributions
            pf_val = parse_num(salary_info.get('pfEmployee'))
            if pf_val == 0.0 and basic > 0 and salary_info.get('pfApplicable', True):
                pf_val = 1800.0 if basic >= 15000 else round(basic * 0.12, 2)
                
            esi_val = round(gross * 0.0075, 2) if (gross <= 21000 and gross > 0 and salary_info.get('esiApplicable', True)) else 0.0
            pt_val = parse_num(salary_info.get('professionalTax'), 0.0)
            
            # Duty Roster Driven Present, LOP & Late Hours Metrics
            att_metric = attendance_map.get(emp_id, {
                'present_days': 0,
                'lop_days': 0.0,
                'late_lop_days': 0.0,
                'late_lop_info': {}
            })

            present_days = att_metric.get('present_days', 0)
            absent_lop_days = att_metric.get('lop_days', 0.0)
            late_lop_days = att_metric.get('late_lop_days', 0.0)
            total_lop_days = round(absent_lop_days + late_lop_days, 2)

            # LOP deduction calculation based on gross daily rate
            daily_gross = (gross / total_month_days) if (total_month_days > 0 and gross > 0) else 0.0
            absent_lop_ded = round(daily_gross * absent_lop_days, 2) if absent_lop_days > 0 else 0.0

            # Preserve any existing adjustments / approval status if recalculating
            existing_doc = existing_map.get(emp_id)
            cl_encash = existing_doc.get('clEncashment', 0.0) if existing_doc else 0.0
            incentives = existing_doc.get('incentives', 0.0) if existing_doc else 0.0
            
            # Auto-calculate late penalty in rupees from late_lop_days (Roster Shortfall matrix)
            auto_late_ded = round(daily_gross * late_lop_days, 2) if late_lop_days > 0 else 0.0
            late_ded = existing_doc.get('lateDeduction', auto_late_ded) if existing_doc else auto_late_ded
            lop_deduction = absent_lop_ded  # Absent LOP only, late deduction is tracked separately in lateDeduction

            tds_ded = existing_doc.get('tdsDeduction', 0.0) if existing_doc else 0.0
            mess_eb = existing_doc.get('messEb', 0.0) if existing_doc else 0.0
            caution_dep = existing_doc.get('cautionDeposit', 0.0) if existing_doc else 0.0
            uniform_id = existing_doc.get('uniformId', 0.0) if existing_doc else 0.0
            vaccine_ded = existing_doc.get('vaccineDeduction', 0.0) if existing_doc else 0.0
            fines = existing_doc.get('fines', 0.0) if existing_doc else 0.0
            fine_remarks = existing_doc.get('fineRemarks', '') if existing_doc else ''
            other_ded = existing_doc.get('otherDeductions', 0.0) if existing_doc else 0.0
            other_ded_remarks = existing_doc.get('otherDeductionsRemarks', '') if existing_doc else ''

            dept_status = existing_doc.get('departmentStatus', 'Draft') if existing_doc else 'Draft'
            rec_status = existing_doc.get('status', 'Draft') if existing_doc else 'Draft'
            audit_trail = existing_doc.get('auditTrail', []) if existing_doc else []
            has_hod_edits = existing_doc.get('hasHodEdits', False) if existing_doc else False
            hod_by = existing_doc.get('hodApprovedBy') if existing_doc else None
            hod_at = existing_doc.get('hodApprovedAt') if existing_doc else None
            adm_by = existing_doc.get('adminApprovedBy') if existing_doc else None
            adm_at = existing_doc.get('adminApprovedAt') if existing_doc else None

            # Total deductions = Statutory (PF, ESI, PT) + Absent LOP + Late LOP + Other deductions
            tot_ded = round(pf_val + esi_val + pt_val + lop_deduction + late_ded + tds_ded + mess_eb + caution_dep + uniform_id + vaccine_ded + fines + other_ded, 2)
            net = max(0.0, round((gross + cl_encash + incentives) - tot_ded, 2))
            
            clean_dept = get_clean_dept(p.get('department'))

            pay_doc = {
                's_no': idx,
                'month': target_month,
                'fromDate': from_date_str,
                'toDate': to_date_str,
                'periodKey': period_key,
                'employeeId': emp_id,
                'employeeName': p.get('employeeName', '') or p.get('name', 'N/A'),
                'department': clean_dept,
                'designation': p.get('designation', 'Employee'),
                'paymentMode': bank_info.get('paymentMode', 'Bank Transfer'),
                'bankName': bank_info.get('bankName', ''),
                'accountNumber': bank_info.get('accountNumber', ''),
                'ifscCode': bank_info.get('ifscCode', ''),
                
                # Attendance
                'totalMonthDays': total_month_days,
                'presentDays': present_days,
                'lopDays': total_lop_days,
                'absentLopDays': absent_lop_days,
                'lateLopDays': late_lop_days,
                'lateLopInfo': att_metric.get('late_lop_info', {}),
                'lateEventsList': att_metric.get('late_events_list', []),
                'spDays': att_metric.get('sp_days', 0),
                
                # Earnings
                'basicSalary': basic,
                'hra': hra,
                'allowances': allowances,
                'clEncashment': cl_encash,
                'incentives': incentives,
                'grossSalary': gross,
                
                # Deductions
                'lopDeduction': lop_deduction,
                'lateDeduction': late_ded,
                'pf': pf_val,
                'esi': esi_val,
                'professionalTax': pt_val,
                'tdsDeduction': tds_ded,
                'messEb': mess_eb,
                'cautionDeposit': caution_dep,
                'uniformId': uniform_id,
                'vaccineDeduction': vaccine_ded,
                'fines': fines,
                'fineRemarks': fine_remarks,
                'otherDeductions': other_ded,
                'otherDeductionsRemarks': other_ded_remarks,
                'totalDeductions': tot_ded,
                
                'netSalary': net,
                'status': rec_status,
                'departmentStatus': dept_status,
                'hasHodEdits': has_hod_edits,
                'auditTrail': audit_trail,
                'hodApprovedBy': hod_by,
                'hodApprovedAt': hod_at,
                'adminApprovedBy': adm_by,
                'adminApprovedAt': adm_at,
                'created_at': now_ts,
                'updated_at': now_ts,
            }
            
            # Only persist to collection on explicit POST/PUT recalculation or approval
            if request.method in ['POST', 'PUT'] or recalculate:
                payroll_col.update_one(
                    {'month': target_month, 'employeeId': emp_id},
                    {'$set': pay_doc},
                    upsert=True
                )
            
            # For JSON serialization
            pay_doc['_id'] = str(pay_doc.get('_id', f"{target_month}_{emp_id}"))
            new_records.append(pay_doc)
            
            total_gross += gross
            total_net += net
            total_deductions += tot_ded

        # Recalculate department summary for newly generated records
        new_dept_summary = {}
        for r in new_records:
            d_name = r.get('department') or 'Admin'
            if d_name not in new_dept_summary:
                new_dept_summary[d_name] = {
                    'department': d_name,
                    'totalEmployees': 0,
                    'totalGross': 0.0,
                    'totalNet': 0.0,
                    'status': r.get('departmentStatus', 'Draft'),
                    'hasHodEdits': r.get('hasHodEdits', False),
                    'hodApprovedBy': r.get('hodApprovedBy'),
                    'hodApprovedAt': r.get('hodApprovedAt'),
                    'adminApprovedBy': r.get('adminApprovedBy'),
                    'adminApprovedAt': r.get('adminApprovedAt'),
                }
            new_dept_summary[d_name]['totalEmployees'] += 1
            new_dept_summary[d_name]['totalGross'] += float(r.get('grossSalary', 0) or 0)
            new_dept_summary[d_name]['totalNet'] += float(r.get('netSalary', 0) or 0)

        # Strictly scope records and summary to HOD assigned departments if requester is HOD
        if is_hod and hod_assigned_depts:
            hod_allowed_lower = {d.lower().strip() for d in hod_assigned_depts}
            new_records = [r for r in new_records if str(r.get('department') or '').strip().lower() in hod_allowed_lower]
            new_dept_summary = {k: v for k, v in new_dept_summary.items() if str(k).strip().lower() in hod_allowed_lower}
            total_gross = sum(float(r.get('grossSalary', 0) or 0) for r in new_records)
            total_net = sum(float(r.get('netSalary', 0) or 0) for r in new_records)
            total_deductions = sum(float(r.get('totalDeductions', 0) or 0) for r in new_records)

        return Response({
            'message': f"Payroll generated for {target_month} ({from_date_str} to {to_date_str}) matching Duty Roster",
            'month': target_month,
            'fromDate': from_date_str,
            'toDate': to_date_str,
            'periodKey': period_key,
            'status': 'Draft',
            'isHOD': is_hod,
            'assignedDepartments': hod_assigned_depts if is_hod else [],
            'summary': {
                'totalEmployees': len(new_records),
                'totalGross': round(total_gross, 2),
                'totalNetPayout': round(total_net, 2),
                'totalDeductions': round(total_deductions, 2),
                'departments': list(new_dept_summary.values())
            },
            'departmentsSummary': new_dept_summary,
            'records': new_records
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in monthly_payroll_view: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PUT', 'POST'])
@permission_classes([AllowAny])
def update_payroll_entry(request):
    """
    Update adjustments for an employee in the monthly payroll.
    BLOCKED IF PAYROLL IS LOCKED / APPROVED BY ADMIN.
    Automatically captures audit trail / diff of changes made by HOD or Admin.
    """
    try:
        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        data = request.data
        
        entry_id = data.get('_id')
        month = data.get('month')
        emp_id = data.get('employeeId')
        
        query = {}
        if entry_id and ObjectId.is_valid(entry_id):
            query = {'_id': ObjectId(entry_id)}
        elif month and emp_id:
            query = {'month': month, 'employeeId': str(emp_id)}
        else:
            return Response({'error': 'Missing _id or (month, employeeId)'}, status=status.HTTP_400_BAD_REQUEST)
            
        existing = payroll_col.find_one(query)
        if not existing:
            existing = {'month': month, 'employeeId': str(emp_id), 'status': 'Draft', 'departmentStatus': 'Draft'}

        # IMMUTABILITY CHECK: Reject if already Approved / Locked by Admin
        if existing.get('status') == 'Approved' or existing.get('departmentStatus') == 'Admin_Approved':
            return Response({
                'error': 'This payroll is Approved & Locked by Admin. Further edits and adjustments are strictly disabled.'
            }, status=status.HTTP_403_FORBIDDEN)

        editor_role = str(data.get('editorRole') or data.get('editor_role') or data.get('role') or '').strip()
        editor_id = str(data.get('editorId') or data.get('editor_id') or '').strip()
        editor_name = str(data.get('editorName') or data.get('editor_name') or '').strip()
        edit_reason = str(data.get('editReason') or data.get('edit_reason') or data.get('reason') or '').strip()

        # If HOD has already submitted approval for this department, prevent HOD from editing unless Admin returned it to Draft
        if 'HOD' in editor_role.upper() and existing.get('departmentStatus') == 'HOD_Approved':
            return Response({
                'error': 'You have already verified & approved this department. To make further adjustments, request Admin to return it for revision.'
            }, status=status.HTTP_403_FORBIDDEN)
            
        # Extract editable fields
        basic = float(data.get('basicSalary', existing.get('basicSalary', 0)) or 0)
        hra = float(data.get('hra', existing.get('hra', 0)) or 0)
        allowances = float(data.get('allowances', existing.get('allowances', 0)) or 0)
        cl_encash = float(data.get('clEncashment', existing.get('clEncashment', 0)) or 0)
        incentives = float(data.get('incentives', existing.get('incentives', 0)) or 0)
        
        gross = basic + hra + allowances + cl_encash + incentives
        
        # Deductions
        lop_ded = float(data.get('lopDeduction', existing.get('lopDeduction', 0)) or 0)
        late_ded = float(data.get('lateDeduction', existing.get('lateDeduction', 0)) or 0)
        pf = float(data.get('pf', existing.get('pf', 0)) or 0)
        esi = float(data.get('esi', existing.get('esi', 0)) or 0)
        pt = float(data.get('professionalTax', existing.get('professionalTax', 0)) or 0)
        tds = float(data.get('tdsDeduction', existing.get('tdsDeduction', 0)) or 0)
        mess_eb = float(data.get('messEb', existing.get('messEb', 0)) or 0)
        caution = float(data.get('cautionDeposit', existing.get('cautionDeposit', 0)) or 0)
        uniform = float(data.get('uniformId', existing.get('uniformId', 0)) or 0)
        vaccine = float(data.get('vaccineDeduction', existing.get('vaccineDeduction', 0)) or 0)

        fines = float(data.get('fines', existing.get('fines', 0)) or 0)
        fine_remarks = str(data.get('fineRemarks', existing.get('fineRemarks', '')) or '').strip()
        other_ded = float(data.get('otherDeductions', existing.get('otherDeductions', 0)) or 0)
        other_ded_remarks = str(data.get('otherDeductionsRemarks', existing.get('otherDeductionsRemarks', '')) or '').strip()

        # Enforcement: HOD CANNOT add or edit fines or otherDeductions
        if 'HOD' in editor_role.upper():
            if fines > 0 or other_ded > 0 or fine_remarks or other_ded_remarks:
                return Response({
                    'error': 'Fines and Other Deductions can only be added or modified by Admin with mandatory remarks.'
                }, status=status.HTTP_403_FORBIDDEN)

        # Mandatory remarks when adding Fine
        if fines > 0 and not fine_remarks:
            return Response({
                'error': 'Remarks are mandatory when adding a fine / penalty.'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Mandatory remarks when adding Other Deductions
        if other_ded > 0 and not other_ded_remarks:
            return Response({
                'error': 'Remarks are mandatory when adding other deductions.'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        tot_ded = (lop_ded + late_ded + pf + esi + pt + tds + mess_eb + caution + uniform + vaccine + fines + other_ded)
        net = max(0.0, gross - tot_ded)

        pres_days = float(data.get('presentDays', existing.get('presentDays', 0)) or 0)
        lop_days = float(data.get('lopDays', existing.get('lopDays', 0)) or 0)
        sp_days = int(data.get('spDays', existing.get('spDays', 0)) or 0)
        pay_mode = data.get('paymentMode', existing.get('paymentMode', 'Bank Transfer'))
        
        update_fields = {
            'basicSalary': basic,
            'hra': hra,
            'allowances': allowances,
            'clEncashment': cl_encash,
            'incentives': incentives,
            'grossSalary': round(gross, 2),
            
            'presentDays': pres_days,
            'lopDays': lop_days,
            'spDays': sp_days,
            'lopDeduction': round(lop_ded, 2),
            'lateDeduction': round(late_ded, 2),
            'pf': round(pf, 2),
            'esi': round(esi, 2),
            'professionalTax': round(pt, 2),
            'tdsDeduction': round(tds, 2),
            'messEb': round(mess_eb, 2),
            'cautionDeposit': round(caution, 2),
            'uniformId': round(uniform, 2),
            'vaccineDeduction': round(vaccine, 2),
            'fines': round(fines, 2),
            'fineRemarks': fine_remarks,
            'otherDeductions': round(other_ded, 2),
            'otherDeductionsRemarks': other_ded_remarks,
            'totalDeductions': round(tot_ded, 2),
            
            'netSalary': round(net, 2),
            'paymentMode': pay_mode,
            'updated_at': datetime.utcnow()
        }

        # Track changes for Audit Trail
        fields_to_check = [
            ('basicSalary', 'Basic Salary', basic),
            ('hra', 'HRA', hra),
            ('allowances', 'Allowances', allowances),
            ('clEncashment', 'CL Encashment', cl_encash),
            ('incentives', 'Incentives', incentives),
            ('presentDays', 'Present Days', pres_days),
            ('lopDays', 'LOP (Absent) Days', lop_days),
            ('spDays', 'Single Punch Days', sp_days),
            ('lopDeduction', 'LOP Deduction', round(lop_ded, 2)),
            ('lateDeduction', 'Late Deduction', round(late_ded, 2)),
            ('pf', 'PF Contribution', round(pf, 2)),
            ('esi', 'ESI Contribution', round(esi, 2)),
            ('professionalTax', 'Professional Tax', round(pt, 2)),
            ('tdsDeduction', 'TDS Deduction', round(tds, 2)),
            ('messEb', 'Mess/EB Deduction', round(mess_eb, 2)),
            ('cautionDeposit', 'Caution Deposit', round(caution, 2)),
            ('uniformId', 'Uniform Deduction', round(uniform, 2)),
            ('vaccineDeduction', 'Vaccine Deduction', round(vaccine, 2)),
            ('fines', 'Fines / Penalties', round(fines, 2)),
            ('fineRemarks', 'Fine Remarks', fine_remarks),
            ('otherDeductions', 'Other Deductions', round(other_ded, 2)),
            ('otherDeductionsRemarks', 'Other Deductions Remarks', other_ded_remarks),
            ('netSalary', 'Net Salary Payable', round(net, 2)),
            ('paymentMode', 'Payment Mode', pay_mode),
        ]

        field_diffs = []
        for f_key, f_label, new_val in fields_to_check:
            old_val = existing.get(f_key)
            if isinstance(new_val, (int, float)):
                old_num = float(old_val or 0)
                new_num = float(new_val or 0)
                if abs(old_num - new_num) > 0.001:
                    field_diffs.append({
                        'field': f_key,
                        'label': f_label,
                        'oldValue': old_num,
                        'newValue': new_num
                    })
            else:
                old_str = str(old_val or '').strip()
                new_str = str(new_val or '').strip()
                if old_str != new_str:
                    field_diffs.append({
                        'field': f_key,
                        'label': f_label,
                        'oldValue': old_str,
                        'newValue': new_str
                    })

        mongo_update = {'$set': update_fields}
        if field_diffs:
            audit_item = {
                'auditId': str(ObjectId()),
                'timestamp': datetime.utcnow().isoformat(),
                'editedBy': f"{editor_id} - {editor_name}" if (editor_id and editor_name) else (editor_name or editor_id or 'HOD'),
                'editorRole': editor_role or 'HOD',
                'reason': edit_reason or 'Adjustment made by HOD/Admin',
                'changes': field_diffs
            }
            mongo_update['$push'] = {'auditTrail': audit_item}
            if 'HOD' in editor_role.upper() or not editor_role:
                update_fields['hasHodEdits'] = True
                mongo_update['$set']['hasHodEdits'] = True
        
        payroll_col.update_one(query, mongo_update, upsert=True)
        updated = payroll_col.find_one(query)
        if updated:
            updated['_id'] = str(updated['_id'])
        
        return Response({
            'message': 'Payroll entry updated successfully',
            'record': updated,
            'changesLogged': len(field_diffs)
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in update_payroll_entry: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def approve_monthly_payroll(request):
    """
    Approve & Lock monthly payroll globally or department-wise.
    """
    try:
        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        month = request.data.get('month') or datetime.now().strftime('%Y-%m')
        dept_filter = request.data.get('department')

        update_query = {'month': month}
        if dept_filter and dept_filter != 'All':
            update_query['department'] = dept_filter

        res = payroll_col.update_many(
            update_query,
            {'$set': {
                'status': 'Approved',
                'departmentStatus': 'Admin_Approved',
                'approved_at': datetime.utcnow(),
                'adminApprovedAt': datetime.utcnow().isoformat(),
                'adminApprovedBy': request.data.get('adminName', 'Admin')
            }}
        )
        
        return Response({
            'message': f"Payroll for {month} successfully approved and locked. Modifications are now disabled.",
            'modifiedCount': res.modified_count
        }, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def populate_month_payroll_if_missing(month):
    """
    Ensures draft payroll records exist in backend_diagnostics_payroll for the specified month.
    If no records exist, generates them from profiles and duty roster attendance.
    """
    db = get_mongo_db()
    payroll_col = db['backend_diagnostics_payroll']
    if payroll_col.count_documents({'month': month}) > 10:
        return
        
    profiles_col = db['backend_diagnostics_profile']
    from employees.views.common.utils import get_inactive_employee_ids
    inactive_ids = get_inactive_employee_ids()
    all_profiles = [p for p in profiles_col.find({}) if str(p.get('employeeId', '')).strip() not in inactive_ids]
    if not all_profiles:
        return

    try:
        parts = month.split('-')
        y, m = int(parts[0]), int(parts[1])
    except Exception:
        now = datetime.now()
        y, m = now.year, now.month
        month = f"{y:04d}-{m:02d}"
    _, last_d = calendar.monthrange(y, m)
    from_date_str = f"{y:04d}-{m:02d}-01"
    to_date_str = f"{y:04d}-{m:02d}-{last_d:02d}"

    all_emp_ids = [str(p.get('employeeId', '')).strip() for p in all_profiles if p.get('employeeId')]
    attendance_map, total_month_days = calculate_attendance_metrics_from_roster(
        target_month=month,
        employee_ids=all_emp_ids,
        treat_sp_as_present=True,
        from_date=from_date_str,
        to_date=to_date_str
    )

    depts_map = {}
    for d in db['backend_diagnostics_Departments'].find():
        c = d.get('department_code')
        n = d.get('department_name')
        if c and n:
            depts_map[c.lower().strip()] = n.strip()
            depts_map[n.lower().strip()] = n.strip()

    now_ts = datetime.utcnow()
    for prof in all_profiles:
        emp_id = str(prof.get('employeeId', '')).strip()
        if not emp_id or emp_id in inactive_ids:
            continue
        emp_name = prof.get('name') or prof.get('employee_name') or f"Employee {emp_id}"
        dept_raw = prof.get('department') or prof.get('department_name') or 'Admin'
        dept_clean = depts_map.get(str(dept_raw).lower().strip(), dept_raw)

        salary_info = prof.get('salaryDetails', {}) or {}
        bank_info = prof.get('bankDetails', {}) or {}

        def parse_n(val, default=0.0):
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

        basic = parse_n(salary_info.get('basicSalary'))
        hra = parse_n(salary_info.get('hra'), round(basic * 0.20, 2) if basic > 0 else 0.0)
        allowances = parse_n(salary_info.get('allowances'), round(basic * 0.10, 2) if basic > 0 else 0.0)
        gross = parse_n(salary_info.get('grossSalary'), basic + hra + allowances)
        if gross == 0.0:
            gross = basic

        pf = parse_n(salary_info.get('pfEmployee'))
        if pf == 0.0 and basic > 0 and salary_info.get('pfApplicable', True):
            pf = 1800.0 if basic >= 15000 else round(basic * 0.12, 2)

        esi = round(gross * 0.0075, 2) if (gross <= 21000 and gross > 0 and salary_info.get('esiApplicable', True)) else 0.0
        pt = parse_n(salary_info.get('professionalTax'), 0.0)

        att = attendance_map.get(emp_id, {
            'present_days': total_month_days,
            'lop_days': 0.0,
            'sp_days': 0,
            'late_lop_days': 0.0,
            'late_lop_info': {}
        })

        pres = float(att.get('present_days', total_month_days))
        lop = float(att.get('lop_days', 0.0))
        sp = int(att.get('sp_days', 0))
        late_lop = float(att.get('late_lop_days', 0.0))
        late_lop_info = att.get('late_lop_info', {})

        daily_rate = (gross / total_month_days) if total_month_days > 0 else 0.0
        lop_ded = round(daily_rate * lop, 2)
        tot_ded = round(lop_ded + pf + esi + pt, 2)
        net = max(0.0, round(gross - tot_ded, 2))

        doc = {
            'month': month,
            'fromDate': from_date_str,
            'toDate': to_date_str,
            'periodKey': month,
            'employeeId': emp_id,
            'employeeName': emp_name,
            'department': dept_clean,
            'designation': prof.get('designation', ''),
            'basicSalary': basic,
            'hra': hra,
            'allowances': allowances,
            'clEncashment': 0.0,
            'incentives': 0.0,
            'grossSalary': gross,
            'totalMonthDays': total_month_days,
            'presentDays': pres,
            'lopDays': lop,
            'spDays': sp,
            'lateLopDays': late_lop,
            'lateLopInfo': late_lop_info,
            'lopDeduction': lop_ded,
            'lateDeduction': 0.0,
            'pf': pf,
            'esi': esi,
            'professionalTax': pt,
            'tdsDeduction': 0.0,
            'messEb': 0.0,
            'cautionDeposit': 0.0,
            'uniformId': 0.0,
            'vaccineDeduction': 0.0,
            'fines': 0.0,
            'fineRemarks': '',
            'otherDeductions': 0.0,
            'otherDeductionsRemarks': '',
            'totalDeductions': tot_ded,
            'netSalary': net,
            'status': 'Draft',
            'departmentStatus': 'Draft',
            'hasHodEdits': False,
            'auditTrail': [],
            'created_at': now_ts,
            'updated_at': now_ts,
        }
        payroll_col.update_one(
            {'month': month, 'employeeId': emp_id},
            {'$setOnInsert': doc},
            upsert=True
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def department_payroll_action(request):
    """
    Multi-Tier Approval Action for Payroll:
    - hod_approve: HOD verifies & approves their department payroll. Department status -> 'HOD_Approved'
    - hod_reject: HOD cancels approval / returns to draft.
    - admin_approve: Admin final approval & lock. Strictly blocked if not yet HOD_Approved (unless force override).
    - admin_reject: Admin returns department to Draft with remarks for HOD to correct.
    """
    try:
        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        data = request.data
        
        action = data.get('action')  # 'hod_approve', 'hod_reject', 'admin_approve', 'admin_reject'
        dept_input = data.get('department')
        month = data.get('month') or data.get('periodKey') or datetime.now().strftime('%Y-%m')
        from_date = data.get('fromDate') or data.get('from_date')
        to_date = data.get('toDate') or data.get('to_date')
        user_id = data.get('userId') or data.get('user_id') or 'system'
        user_name = data.get('userName') or data.get('user_name') or 'User'
        reason = data.get('reason') or ''
        override = data.get('override', False)

        if not dept_input or dept_input == 'All':
            return Response({'error': 'Specific department is required for department action'}, status=status.HTTP_400_BAD_REQUEST)

        # Ensure draft payroll records exist in MongoDB collection
        populate_month_payroll_if_missing(month)

        from employees.views.common.utils import resolve_department_filter, get_inactive_employee_ids
        dept_ctx = resolve_department_filter(dept_input)
        inactive_ids = get_inactive_employee_ids()
        
        query = {'month': month}
        if from_date and to_date:
            query = {'$or': [
                {'fromDate': str(from_date), 'toDate': str(to_date)},
                {'month': month},
                {'periodKey': f"{from_date}_{to_date}"}
            ]}

        dept_cond = {'$regex': f"^{re.escape(str(dept_input).strip())}$", '$options': 'i'}
        
        # Build comprehensive match criteria (exact name/code, target terms, employee IDs)
        conds = [{'department': dept_cond}]
        if dept_ctx.get('target_terms'):
            for t in dept_ctx['target_terms']:
                conds.append({'department': {'$regex': f"^{re.escape(t)}$", '$options': 'i'}})
        if dept_ctx.get('matching_employee_ids'):
            conds.append({'employeeId': {'$in': list(dept_ctx['matching_employee_ids'])}})
        
        dept_query = {'$and': [query, {'$or': conds}]}
        records = [r for r in payroll_col.find(dept_query) if str(r.get('employeeId', '')).strip() not in inactive_ids]
        
        # Fallback: substring match if still not found
        if not records:
            sub_cond = {'department': {'$regex': re.escape(str(dept_input).strip()), '$options': 'i'}}
            records = [r for r in payroll_col.find({'$and': [query, sub_cond]}) if str(r.get('employeeId', '')).strip() not in inactive_ids]

        if not records:
            return Response({'error': f'No payroll records found for department "{dept_input}" in {month}'}, status=status.HTTP_404_NOT_FOUND)

        matched_ids = [str(r.get('employeeId')).strip() for r in records if r.get('employeeId')]
        now_iso = datetime.utcnow().isoformat()
        editor_label = f"{user_id} - {user_name}" if user_id != 'system' else user_name

        update_filter = {'month': month, 'employeeId': {'$in': matched_ids}}

        if action == 'hod_approve':
            # Verify not already Admin_Approved
            if any(r.get('status') == 'Approved' or r.get('departmentStatus') == 'Admin_Approved' for r in records):
                return Response({'error': 'This department is already Approved & Locked by Admin.'}, status=status.HTTP_400_BAD_REQUEST)

            res = payroll_col.update_many(
                update_filter,
                {'$set': {
                    'departmentStatus': 'HOD_Approved',
                    'hodApprovedBy': editor_label,
                    'hodApprovedAt': now_iso,
                    'hodRemarks': reason,
                    'updated_at': datetime.utcnow()
                }}
            )
            return Response({
                'message': f"Department '{dept_input}' verified & approved by HOD successfully. Ready for Admin approval.",
                'department': dept_input,
                'status': 'HOD_Approved',
                'modifiedCount': res.modified_count
            }, status=status.HTTP_200_OK)

        elif action == 'hod_reject':
            # HOD reverts their approval back to draft
            if any(r.get('status') == 'Approved' or r.get('departmentStatus') == 'Admin_Approved' for r in records):
                return Response({'error': 'Cannot revert: Department is already Approved & Locked by Admin.'}, status=status.HTTP_400_BAD_REQUEST)

            res = payroll_col.update_many(
                update_filter,
                {'$set': {
                    'departmentStatus': 'Draft',
                    'hodApprovedBy': None,
                    'hodApprovedAt': None,
                    'updated_at': datetime.utcnow()
                }}
            )
            return Response({
                'message': f"Department '{dept_input}' status reverted to Draft by HOD.",
                'department': dept_input,
                'status': 'Draft',
                'modifiedCount': res.modified_count
            }, status=status.HTTP_200_OK)

        elif action == 'admin_approve':
            # STRICT REQUIREMENT: HOD must have verified & approved first!
            unapproved = [r for r in records if r.get('departmentStatus') != 'HOD_Approved']
            if unapproved and not override:
                return Response({
                    'error': f"Cannot approve department '{dept_input}'. HOD approval has not been completed yet (Current Status: {records[0].get('departmentStatus', 'Draft')}). HOD must verify & approve first.",
                    'requiresHodApproval': True,
                    'currentStatus': records[0].get('departmentStatus', 'Draft')
                }, status=status.HTTP_400_BAD_REQUEST)

            res = payroll_col.update_many(
                update_filter,
                {'$set': {
                    'departmentStatus': 'Admin_Approved',
                    'status': 'Approved',
                    'adminApprovedBy': editor_label,
                    'adminApprovedAt': now_iso,
                    'adminRemarks': reason,
                    'approved_at': datetime.utcnow(),
                    'updated_at': datetime.utcnow()
                }}
            )
            return Response({
                'message': f"Department '{dept_input}' Final Approved & Locked by Admin.",
                'department': dept_input,
                'status': 'Admin_Approved',
                'modifiedCount': res.modified_count
            }, status=status.HTTP_200_OK)

        elif action == 'admin_reject':
            # Admin returns department back to HOD for revision
            res = payroll_col.update_many(
                update_filter,
                {'$set': {
                    'departmentStatus': 'Draft',
                    'status': 'Draft',
                    'adminRejectionReason': reason,
                    'rejectedBy': editor_label,
                    'rejectedAt': now_iso,
                    'updated_at': datetime.utcnow()
                }}
            )
            return Response({
                'message': f"Department '{dept_input}' returned to HOD for revision.",
                'department': dept_input,
                'status': 'Draft',
                'modifiedCount': res.modified_count
            }, status=status.HTTP_200_OK)

        else:
            return Response({'error': f"Unknown action '{action}'"}, status=status.HTTP_400_BAD_REQUEST)

    except Exception as e:
        logger.error(f"Error in department_payroll_action: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def payroll_audit_trail_view(request):
    """
    Retrieve audit trail and HOD modifications for payroll.
    """
    try:
        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        
        month = request.GET.get('month')
        from_date = request.GET.get('fromDate') or request.GET.get('from_date')
        to_date = request.GET.get('toDate') or request.GET.get('to_date')
        department = request.GET.get('department')
        emp_id = request.GET.get('employeeId')
        
        query = {}
        if month:
            query['month'] = month
        if from_date and to_date:
            query['fromDate'] = from_date
            query['toDate'] = to_date
        if emp_id:
            query['employeeId'] = str(emp_id)
        if department and department != 'All':
            from employees.views.common.utils import resolve_department_filter
            dept_ctx = resolve_department_filter(department)
            if dept_ctx['is_filtered']:
                query.update(dept_ctx['mongo_query'])

        # Only fetch records that have had edits
        query['$or'] = [
            {'hasHodEdits': True},
            {'auditTrail.0': {'$exists': True}}
        ]

        records = list(payroll_col.find(query, {
            '_id': 1,
            'employeeId': 1,
            'employeeName': 1,
            'department': 1,
            'designation': 1,
            'month': 1,
            'fromDate': 1,
            'toDate': 1,
            'departmentStatus': 1,
            'status': 1,
            'hasHodEdits': 1,
            'auditTrail': 1,
            'grossSalary': 1,
            'netSalary': 1,
            'lopDays': 1,
        }))

        for r in records:
            r['_id'] = str(r['_id'])

        return Response({
            'totalModifiedEmployees': len(records),
            'records': records
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in payroll_audit_trail_view: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def export_bank_transfer_sheet(request):
    """
    Generate CSV file for Bank Transfer (NEFT/RTGS Batch).
    """
    try:
        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        month = request.GET.get('month') or datetime.now().strftime('%Y-%m')
        
        from employees.views.common.utils import get_inactive_employee_ids
        inactive_ids = get_inactive_employee_ids()
        records = [r for r in payroll_col.find({'month': month}) if str(r.get('employeeId', '')).strip() not in inactive_ids]
        if not records:
            return Response({'error': f'No payroll records found for {month}'}, status=status.HTTP_404_NOT_FOUND)
            
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            'S.No', 'Employee ID', 'Beneficiary Name', 'Bank Name', 
            'Account Number', 'IFSC Code', 'Payment Mode', 'Net Amount (INR)', 'Month'
        ])
        
        for idx, r in enumerate(records, 1):
            writer.writerow([
                idx,
                r.get('employeeId', ''),
                r.get('employeeName', ''),
                r.get('bankName', 'N/A'),
                r.get('accountNumber', 'N/A'),
                r.get('ifscCode', 'N/A'),
                r.get('paymentMode', 'Bank Transfer'),
                f"{float(r.get('netSalary', 0)):.2f}",
                month
            ])
            
        response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="Shanmuga_Hospital_Bank_Payout_{month}.csv"'
        return response

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def export_pf_ecr(request):
    """
    Generate Statutory EPFO ECR (Electronic Challan cum Return) CSV / Text file.
    Columns: UAN, Member Name, Gross Wages, EPF Wages, EPS Wages, EDLI Wages, 
             EE EPF Share (12%), ER EPS Share (8.33%), ER EPF Share (3.67%), NCP Days, Refund
    """
    try:
        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        profiles_col = db['backend_diagnostics_profile']
        month = request.GET.get('month') or datetime.now().strftime('%Y-%m')
        
        from employees.views.common.utils import get_inactive_employee_ids
        inactive_ids = get_inactive_employee_ids()

        records = list(payroll_col.find({'month': month, 'pf': {'$gt': 0}}))
        if not records:
            records = list(payroll_col.find({'month': month}))
        records = [r for r in records if str(r.get('employeeId', '')).strip() not in inactive_ids]
            
        if not records:
            return Response({'error': f'No payroll records found for {month}'}, status=status.HTTP_404_NOT_FOUND)

        # UAN Mapping from profile KYC
        profile_map = {
            str(p.get('employeeId', '')): p.get('kycDetails', {})
            for p in profiles_col.find({}, {'employeeId': 1, 'kycDetails': 1})
        }

        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            'UAN', 'Member Name', 'Gross Wages', 'EPF Wages', 'EPS Wages', 'EDLI Wages',
            'EE Share (12%)', 'ER EPS Share (8.33%)', 'ER EPF Share (3.67%)', 'NCP Days', 'Refund of Advances'
        ])

        for r in records:
            emp_id = str(r.get('employeeId', '')).strip()
            kyc = profile_map.get(emp_id, {}) or {}
            uan = kyc.get('uanNumber') or f"100{emp_id.zfill(9)}"
            name = r.get('employeeName', 'N/A')
            gross = float(r.get('grossSalary', 0) or 0)
            basic = float(r.get('basicSalary', 0) or 0)
            
            # Statutory Capping at 15000
            epf_wages = min(basic, 15000.0) if basic > 0 else 0.0
            eps_wages = min(basic, 15000.0) if basic > 0 else 0.0
            edli_wages = min(basic, 15000.0) if basic > 0 else 0.0
            
            ee_pf = round(epf_wages * 0.12)
            er_eps = round(eps_wages * 0.0833)
            er_epf = max(0, ee_pf - er_eps)
            ncp_days = int(r.get('lopDays', 0) or 0)

            writer.writerow([
                uan,
                name,
                f"{gross:.2f}",
                f"{epf_wages:.2f}",
                f"{eps_wages:.2f}",
                f"{edli_wages:.2f}",
                ee_pf,
                er_eps,
                er_epf,
                ncp_days,
                0
            ])

        response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="Shanmuga_Hospital_PF_ECR_{month}.csv"'
        return response

    except Exception as e:
        logger.error(f"Error in export_pf_ecr: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def export_esi_return(request):
    """
    Generate Statutory ESIC Monthly Contribution Return CSV.
    Columns: IP Number, IP Name, No of Days Worked, Total Monthly Wages, 
             Employee Contribution (0.75%), Employer Contribution (3.25%), Reason Code
    """
    try:
        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        profiles_col = db['backend_diagnostics_profile']
        month = request.GET.get('month') or datetime.now().strftime('%Y-%m')
        
        from employees.views.common.utils import get_inactive_employee_ids
        inactive_ids = get_inactive_employee_ids()

        records = list(payroll_col.find({'month': month, 'esi': {'$gt': 0}}))
        if not records:
            records = list(payroll_col.find({'month': month, 'grossSalary': {'$lte': 21000, '$gt': 0}}))
        records = [r for r in records if str(r.get('employeeId', '')).strip() not in inactive_ids]
            
        if not records:
            return Response({'error': f'No ESI applicable records found for {month}'}, status=status.HTTP_404_NOT_FOUND)

        # Profile Insurance Mapping
        profile_map = {
            str(p.get('employeeId', '')): p.get('kycDetails', {})
            for p in profiles_col.find({}, {'employeeId': 1, 'kycDetails': 1})
        }

        output = io.StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow([
            'IP Number (ESI No)', 'IP Name', 'No of Days Worked', 'Total Monthly Wages',
            'Employee Contribution (0.75%)', 'Employer Contribution (3.25%)', 'Total ESI Remittance', 'Reason Code'
        ])

        for r in records:
            emp_id = str(r.get('employeeId', '')).strip()
            kyc = profile_map.get(emp_id, {}) or {}
            ip_num = kyc.get('esiNumber') or kyc.get('insuranceNumber') or f"5200{emp_id.zfill(6)}"
            name = r.get('employeeName', 'N/A')
            
            total_days = int(r.get('totalMonthDays', 30) or 30)
            lop_days = int(r.get('lopDays', 0) or 0)
            working_days = max(0, total_days - lop_days)
            
            gross = float(r.get('grossSalary', 0) or 0)
            ee_esi = round(gross * 0.0075, 2)
            er_esi = round(gross * 0.0325, 2)
            total_esi = round(ee_esi + er_esi, 2)
            reason_code = 0 if working_days > 0 else 1

            writer.writerow([
                ip_num,
                name,
                working_days,
                f"{gross:.2f}",
                f"{ee_esi:.2f}",
                f"{er_esi:.2f}",
                f"{total_esi:.2f}",
                reason_code
            ])

        response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="Shanmuga_Hospital_ESI_Monthly_Return_{month}.csv"'
        return response

    except Exception as e:
        logger.error(f"Error in export_esi_return: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def download_payslip_html(request, employee_id):
    """
    Returns printable hospital payslip HTML.
    """
    try:
        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        month = request.GET.get('month') or datetime.now().strftime('%Y-%m')
        
        record = payroll_col.find_one({'employeeId': str(employee_id), 'month': month})
        if not record:
            record = payroll_col.find_one({'employeeId': str(employee_id)})
            
        if not record:
            return Response({'error': 'Payslip not found'}, status=status.HTTP_404_NOT_FOUND)
            
        emp_name = record.get('employeeName', 'N/A')
        dept = record.get('department', 'N/A')
        desig = record.get('designation', 'N/A')
        basic = float(record.get('basicSalary', 0))
        hra = float(record.get('hra', 0))
        allowances = float(record.get('allowances', 0))
        cl = float(record.get('clEncashment', 0))
        gross = float(record.get('grossSalary', basic))
        
        present_days = record.get('presentDays', 0)
        lop_days = record.get('lopDays', 0)
        
        lop = float(record.get('lopDeduction', 0))
        pf = float(record.get('pf', 0))
        esi = float(record.get('esi', 0))
        pt = float(record.get('professionalTax', 0))
        tds = float(record.get('tdsDeduction', 0))
        mess = float(record.get('messEb', 0))
        other_ded = float(record.get('otherDeductions', 0)) + float(record.get('fines', 0)) + float(record.get('uniformId', 0))
        total_ded = float(record.get('totalDeductions', 0))
        net = float(record.get('netSalary', gross - total_ded))
        
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Payslip - {emp_name} ({month})</title>
    <style>
        body {{ font-family: 'Helvetica Neue', Arial, sans-serif; margin: 20px; color: #1e293b; background: #fff; }}
        .payslip-box {{ max-width: 800px; margin: auto; border: 2px solid #0f172a; padding: 25px; border-radius: 8px; }}
        .header {{ text-align: center; border-bottom: 2px solid #0f172a; padding-bottom: 15px; margin-bottom: 15px; }}
        .header h1 {{ margin: 0; font-size: 24px; color: #0284c7; text-transform: uppercase; }}
        .header p {{ margin: 3px 0; font-size: 13px; color: #64748b; }}
        .payslip-title {{ font-size: 16px; font-weight: bold; margin-top: 10px; color: #0f172a; background: #f1f5f9; padding: 6px; }}
        .info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 20px; font-size: 13px; }}
        .info-item {{ display: flex; justify-content: space-between; border-bottom: 1px dashed #cbd5e1; padding-bottom: 4px; }}
        .table-section {{ display: flex; gap: 20px; margin-bottom: 20px; }}
        .table-col {{ flex: 1; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th {{ background: #0f172a; color: #fff; padding: 8px; text-align: left; }}
        td {{ padding: 8px; border-bottom: 1px solid #e2e8f0; }}
        .amount-col {{ text-align: right; }}
        .total-row {{ font-weight: bold; background: #f8fafc; }}
        .net-pay-banner {{ background: #ecfdf5; border: 2px solid #10b981; border-radius: 6px; padding: 15px; text-align: center; margin-top: 20px; }}
        .net-pay-banner h2 {{ margin: 0; color: #065f46; font-size: 22px; }}
        .footer {{ margin-top: 30px; display: flex; justify-content: space-between; font-size: 12px; color: #64748b; }}
        @media print {{
            .no-print {{ display: none; }}
            body {{ margin: 0; }}
        }}
    </style>
</head>
<body>
    <div class="payslip-box">
        <div class="no-print" style="text-align: right; margin-bottom: 10px;">
            <button onclick="window.print()" style="background: #0284c7; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; font-weight: bold;">🖨️ Print / Save as PDF</button>
        </div>
        <div class="header">
            <h1>SHANMUGA HOSPITAL LTD</h1>
            <p>Salem, Tamil Nadu, India | Multi-Speciality Healthcare</p>
            <div class="payslip-title">PAYSLIP FOR THE MONTH OF {month}</div>
        </div>
        
        <div class="info-grid">
            <div class="info-item"><span>Employee ID:</span> <strong>{employee_id}</strong></div>
            <div class="info-item"><span>Employee Name:</span> <strong>{emp_name}</strong></div>
            <div class="info-item"><span>Department:</span> <strong>{dept}</strong></div>
            <div class="info-item"><span>Designation:</span> <strong>{desig}</strong></div>
            <div class="info-item"><span>Present Days:</span> <strong>{present_days}</strong></div>
            <div class="info-item"><span>LOP Days:</span> <strong>{lop_days}</strong></div>
            <div class="info-item"><span>Payment Mode:</span> <strong>{record.get('paymentMode', 'Bank Transfer')}</strong></div>
            <div class="info-item"><span>Status:</span> <strong style="color: #10b981;">{record.get('status', 'Processed')}</strong></div>
        </div>

        <div class="table-section">
            <div class="table-col">
                <table>
                    <thead>
                        <tr><th>Earnings</th><th class="amount-col">Amount (₹)</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>Basic Salary</td><td class="amount-col">{basic:,.2f}</td></tr>
                        <tr><td>HRA</td><td class="amount-col">{hra:,.2f}</td></tr>
                        <tr><td>Allowances</td><td class="amount-col">{allowances:,.2f}</td></tr>
                        <tr><td>CL Encashment</td><td class="amount-col">{cl:,.2f}</td></tr>
                        <tr class="total-row"><td>Gross Earnings</td><td class="amount-col">{gross:,.2f}</td></tr>
                    </tbody>
                </table>
            </div>
            <div class="table-col">
                <table>
                    <thead>
                        <tr><th>Deductions</th><th class="amount-col">Amount (₹)</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>PF Contribution</td><td class="amount-col">{pf:,.2f}</td></tr>
                        <tr><td>ESI Contribution</td><td class="amount-col">{esi:,.2f}</td></tr>
                        <tr><td>Professional Tax</td><td class="amount-col">{pt:,.2f}</td></tr>
                        <tr><td>Loss of Pay (LOP)</td><td class="amount-col">{lop:,.2f}</td></tr>
                        <tr><td>TDS Deduction</td><td class="amount-col">{tds:,.2f}</td></tr>
                        <tr><td>Mess / EB / Other</td><td class="amount-col">{(mess + other_ded):,.2f}</td></tr>
                        <tr class="total-row"><td>Total Deductions</td><td class="amount-col">{total_ded:,.2f}</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <div class="net-pay-banner">
            <div>NET SALARY PAYABLE</div>
            <h2>₹{net:,.2f}</h2>
        </div>

        <div class="footer">
            <div>This is a computer generated document and does not require a physical signature.</div>
            <div>Generated on: {datetime.now().strftime('%d-%m-%Y')}</div>
        </div>
    </div>
</body>
</html>
"""
        return HttpResponse(html_content, content_type='text/html')

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def employee_payslip_history(request, employee_id):
    """
    Endpoint for Mobile App: Return all monthly payslips for an employee.
    """
    try:
        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        
        records = list(payroll_col.find({'employeeId': str(employee_id)}).sort('month', -1))
        for r in records:
            r['_id'] = str(r['_id'])
            
        return Response({'employeeId': str(employee_id), 'payslips': records}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_late_hours_deductions_report(request):
    """
    Specialized report & deduction review endpoint for Late Hours (August 2026 New Formula).
    Query Params:
    - month: YYYY-MM (default: current month)
    - department: 'All' or specific department
    - search: string filter
    - filter: 'all' | 'has_late' | 'penalty_only' | 'grace_only'
    - export: 'csv'
    """
    try:
        target_month = request.GET.get('month') or datetime.now().strftime('%Y-%m')
        dept_param = request.GET.get('department')
        search_query = str(request.GET.get('search', '')).strip().lower()
        filter_type = request.GET.get('filter', 'all')
        export_csv = request.GET.get('export') == 'csv'

        from employees.views.common.utils import resolve_department_filter, get_inactive_employee_ids, get_request_user_hod_departments
        inactive_ids = get_inactive_employee_ids()
        is_hod, hod_assigned_depts = get_request_user_hod_departments(request)
        dept_ctx = resolve_department_filter(dept_param if dept_param and dept_param != 'All' else None)

        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        profiles_col = db['backend_diagnostics_profile']

        # 1. Fetch live or recorded payroll data (excluding inactive/disabled employees)
        records = [r for r in payroll_col.find({'month': target_month}) if str(r.get('employeeId', '')).strip() not in inactive_ids]

        # Scope strictly for HOD
        if is_hod:
            if hod_assigned_depts:
                hod_allowed_lower = {d.lower().strip() for d in hod_assigned_depts}
                records = [r for r in records if str(r.get('department') or '').strip().lower() in hod_allowed_lower]
            else:
                records = []

        # If no payroll records exist yet for this month, calculate on the fly
        if not records:
            attendance_map, total_month_days = calculate_attendance_metrics_from_roster(
                target_month=target_month,
                treat_sp_as_present=True
            )
            # Fetch active profiles
            profile_query = {}
            if dept_ctx['is_filtered']:
                profile_query = dict(dept_ctx['mongo_query'])
            all_profiles = [p for p in profiles_col.find(profile_query) if str(p.get('employeeId', '')).strip() not in inactive_ids]

            records = []
            for p in all_profiles:
                emp_id = str(p.get('employeeId', '')).strip()
                if not emp_id:
                    continue
                att = attendance_map.get(emp_id, {})
                salary_info = p.get('salaryDetails', {}) or {}
                basic = float(salary_info.get('basicSalary', 0) or 0)
                hra = float(salary_info.get('hra', 0) or 0)
                allowances = float(salary_info.get('allowances', 0) or 0)
                gross = float(salary_info.get('grossSalary', basic + hra + allowances) or basic)

                daily_gross = (gross / total_month_days) if (total_month_days > 0 and gross > 0) else 0.0
                late_lop_days = att.get('late_lop_days', 0.0)
                late_ded = round(daily_gross * late_lop_days, 2) if late_lop_days > 0 else 0.0

                records.append({
                    'employeeId': emp_id,
                    'employeeName': p.get('employeeName', ''),
                    'department': p.get('department', 'General'),
                    'designation': p.get('designation', 'Employee'),
                    'grossSalary': gross,
                    'dailyGross': round(daily_gross, 2),
                    'totalMonthDays': total_month_days,
                    'presentDays': att.get('present_days', 0),
                    'lopDays': att.get('lop_days', 0.0) + late_lop_days,
                    'absentLopDays': att.get('lop_days', 0.0),
                    'lateLopDays': late_lop_days,
                    'lateLopInfo': att.get('late_lop_info', {}),
                    'lateMinutesList': att.get('late_minutes_list', []),
                    'lateDeduction': late_ded,
                    'departmentStatus': 'Draft',
                    'status': 'Draft'
                })

        # Process and filter records
        filtered_records = []
        summary = {
            'totalEmployees': 0,
            'employeesWithLate': 0,
            'employeesWithPenalty': 0,
            'totalLateLopDays': 0.0,
            'totalLateDeductions': 0.0,
            'totalOccasions': 0,
            'totalHeavyLates': 0,
            'departments': {}
        }

        for r in records:
            eid = str(r.get('employeeId', '')).strip()
            if eid in inactive_ids:
                continue

            dept_name = str(r.get('department') or 'General').strip()
            if dept_ctx['is_filtered'] and not dept_ctx['is_match'](dept_name):
                continue

            emp_name = str(r.get('employeeName') or '').strip()
            desig = str(r.get('designation') or '').strip()

            if search_query:
                if search_query not in eid.lower() and search_query not in emp_name.lower() and search_query not in desig.lower():
                    continue

            late_lop_days = float(r.get('lateLopDays', 0) or 0)
            late_info = r.get('lateLopInfo', {}) or {}
            occ_count = late_info.get('occ_count', 0)
            occ_lop = float(late_info.get('occ_lop', 0) or 0)
            heavy_half = late_info.get('heavy_half_count', 0)
            heavy_full = late_info.get('heavy_full_count', 0)
            heavy_lop = float(late_info.get('heavy_lop', 0) or 0)
            gross = float(r.get('grossSalary', 0) or 0)
            total_days = int(r.get('totalMonthDays', 30) or 30)
            daily_rate = round(gross / total_days, 2) if (total_days > 0 and gross > 0) else 0.0
            late_ded = float(r.get('lateDeduction', 0) or 0)
            if late_ded == 0.0 and late_lop_days > 0:
                late_ded = round(daily_rate * late_lop_days, 2)

            total_late_events = occ_count + heavy_half + heavy_full

            # Apply Filter Type
            if filter_type == 'has_late' and total_late_events == 0:
                continue
            elif filter_type == 'penalty_only' and late_lop_days == 0:
                continue
            elif filter_type == 'grace_only' and (total_late_events == 0 or late_lop_days > 0):
                continue

            formatted_row = {
                'employeeId': eid,
                'employeeName': emp_name,
                'department': dept_name,
                'designation': desig,
                'grossSalary': gross,
                'dailyRate': daily_rate,
                'presentDays': r.get('presentDays', 0),
                'totalLopDays': r.get('lopDays', 0),
                'absentLopDays': r.get('absentLopDays', 0),
                'lateLopDays': late_lop_days,
                'lateDeduction': late_ded,
                'occCount': occ_count,
                'occLop': occ_lop,
                'heavyHalfCount': heavy_half,
                'heavyFullCount': heavy_full,
                'heavyLop': heavy_lop,
                'totalLateEvents': total_late_events,
                'lateEventsList': r.get('lateEventsList', []),
                'status': r.get('departmentStatus', r.get('status', 'Draft'))
            }
            filtered_records.append(formatted_row)

            # Accumulate Summary
            summary['totalEmployees'] += 1
            if total_late_events > 0:
                summary['employeesWithLate'] += 1
            if late_lop_days > 0:
                summary['employeesWithPenalty'] += 1
            summary['totalLateLopDays'] = round(summary['totalLateLopDays'] + late_lop_days, 2)
            summary['totalLateDeductions'] = round(summary['totalLateDeductions'] + late_ded, 2)
            summary['totalOccasions'] += occ_count
            summary['totalHeavyLates'] += (heavy_half + heavy_full)

            if dept_name not in summary['departments']:
                summary['departments'][dept_name] = {
                    'department': dept_name,
                    'employees': 0,
                    'withPenalty': 0,
                    'totalLateLop': 0.0,
                    'totalDeductions': 0.0
                }
            d_sum = summary['departments'][dept_name]
            d_sum['employees'] += 1
            if late_lop_days > 0:
                d_sum['withPenalty'] += 1
            d_sum['totalLateLop'] = round(d_sum['totalLateLop'] + late_lop_days, 2)
            d_sum['totalDeductions'] = round(d_sum['totalDeductions'] + late_ded, 2)

        summary['departmentsList'] = sorted(list(summary['departments'].values()), key=lambda x: x['totalDeductions'], reverse=True)

        # Handle CSV Export
        if export_csv:
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="Late_Hours_Deductions_{target_month}.csv"'
            writer = csv.writer(response)
            writer.writerow([
                'S.No', 'Employee ID', 'Employee Name', 'Department', 'Designation',
                'Monthly Gross (₹)', 'Daily Rate (₹)',
                '11-30m Occasions', 'Occasion LOP (Days)',
                '31-60m Lates (0.5d)', '>60m Lates (1.0d)', 'Heavy Late LOP (Days)',
                'Total Late LOP (Days)', 'Late Deduction Amount (₹)', 'Status'
            ])
            for idx, item in enumerate(filtered_records, 1):
                writer.writerow([
                    idx,
                    item['employeeId'],
                    item['employeeName'],
                    item['department'],
                    item['designation'],
                    item['grossSalary'],
                    item['dailyRate'],
                    item['occCount'],
                    item['occLop'],
                    item['heavyHalfCount'],
                    item['heavyFullCount'],
                    item['heavyLop'],
                    item['lateLopDays'],
                    item['lateDeduction'],
                    item['status']
                ])
            return response

        return Response({
            'month': target_month,
            'isHOD': is_hod,
            'assignedDepartments': hod_assigned_depts if is_hod else [],
            'summary': summary,
            'records': filtered_records
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in get_late_hours_deductions_report: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_employee_late_events_breakdown(request):
    """
    Returns the exact date-wise Roster Time Shortfall events for a specific employee and month.
    Used by the Late Hours Deductions Date-Breakdown Modal in frontend.
    """
    try:
        emp_id = str(request.GET.get('employee_id', '')).strip()
        month_str = str(request.GET.get('month', '')).strip() or datetime.now().strftime('%Y-%m')

        if not emp_id:
            return Response({'error': 'employee_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        # 1. First check if stored in backend_diagnostics_payroll
        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        p_rec = payroll_col.find_one({'month': month_str, 'employeeId': emp_id})

        late_events = []
        if p_rec and p_rec.get('lateEventsList'):
            late_events = p_rec.get('lateEventsList', [])
        else:
            # Calculate live from roster
            metrics, _ = calculate_attendance_metrics_from_roster(
                target_month=month_str,
                employee_ids=[emp_id],
                treat_sp_as_present=True
            )
            emp_metric = metrics.get(emp_id, {})
            late_events = emp_metric.get('late_events_list', [])

        # Fetch profile info for rich modal header
        profiles_col = db['backend_diagnostics_profile']
        profile = profiles_col.find_one({'employeeId': emp_id}) or {}

        gross = float(p_rec.get('grossSalary', 0)) if p_rec else 0.0
        daily_rate = round(float(p_rec.get('grossSalary', 0) / (p_rec.get('totalMonthDays', 30) or 30)), 2) if (p_rec and p_rec.get('grossSalary')) else 0.0
        late_lop_days = float(p_rec.get('lateLopDays', 0)) if p_rec else 0.0
        late_deduction = float(p_rec.get('lateDeduction', 0)) if p_rec else 0.0
        late_lop_info = p_rec.get('lateLopInfo', {}) if p_rec else {}

        if not p_rec:
            salary_info = profile.get('salaryDetails', {}) or {}
            basic = float(salary_info.get('basicSalary', 0) or 0)
            hra = float(salary_info.get('hra', 0) or 0)
            allowances = float(salary_info.get('allowances', 0) or 0)
            gross = float(salary_info.get('grossSalary', basic + hra + allowances) or basic)
            daily_rate = round(gross / 30, 2) if gross > 0 else 0.0

        return Response({
            'employeeId': emp_id,
            'employeeName': profile.get('employeeName') or (p_rec.get('employeeName') if p_rec else 'N/A'),
            'department': profile.get('department') or (p_rec.get('department') if p_rec else 'General'),
            'designation': profile.get('designation') or (p_rec.get('designation') if p_rec else 'Employee'),
            'month': month_str,
            'grossSalary': round(gross, 2),
            'dailyRate': round(daily_rate, 2),
            'lateLopDays': late_lop_days,
            'lateDeduction': late_deduction,
            'lateLopInfo': late_lop_info,
            'totalEvents': len(late_events),
            'events': late_events,
            'permissionsUsed': len(list(db['backend_diagnostics_permissions'].find({
                'employeeId': emp_id,
                '$or': [{'month': month_str}, {'date': {'$regex': f'^{month_str}'}}]
            }))),
            'permissionsRemaining': max(0, 2 - len(list(db['backend_diagnostics_permissions'].find({
                'employeeId': emp_id,
                '$or': [{'month': month_str}, {'date': {'$regex': f'^{month_str}'}}]
            }))))
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in get_employee_late_events_breakdown: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def apply_employee_permission(request):
    """
    Applies a 1-hour Permission to an employee for a specific shortfall date.
    Policy:
    - Monthly max: 2 hours per employee (2 occasions x 1 hour).
    - Session max: 1 hour per day/occasion.
    - Authorized: HOD (for assigned departments) or Admin.
    - Effect: Deducts 60 mins from shortfall, automatically recalculates Late LOP & deduction.
    """
    try:
        emp_id = str(request.data.get('employee_id') or request.data.get('employeeId', '')).strip()
        date_str = str(request.data.get('date', '')).strip()
        month_str = str(request.data.get('month', '')).strip()
        reason = str(request.data.get('reason', '')).strip()
        duration_hours = float(request.data.get('duration_hours', 1.0) or 1.0)

        if not emp_id or not date_str:
            return Response({'error': 'employee_id and date are required.'}, status=status.HTTP_400_BAD_REQUEST)

        if not reason:
            return Response({'error': 'Reason for permission is mandatory.'}, status=status.HTTP_400_BAD_REQUEST)

        # Enforce 1-hour max per occasion
        if duration_hours > 1.0:
            return Response({'error': 'Permission limit exceeded: Maximum 1 hour per occasion is allowed.'}, status=status.HTTP_400_BAD_REQUEST)

        if not month_str:
            month_str = date_str[:7]

        # Authenticate & check HOD role/scoping
        from employees.views.common.utils import get_request_user_hod_departments
        is_hod, hod_assigned_depts = get_request_user_hod_departments(request)

        db = get_mongo_db()
        profiles_col = db['backend_diagnostics_profile']
        profile = profiles_col.find_one({'employeeId': emp_id}) or {}
        emp_dept = profile.get('department') or 'General'
        emp_name = profile.get('employeeName') or emp_id

        if is_hod and hod_assigned_depts:
            hod_allowed_lower = {d.lower().strip() for d in hod_assigned_depts}
            if emp_dept.lower().strip() not in hod_allowed_lower:
                return Response({'error': f'Permission denied: Employee {emp_id} belongs to {emp_dept}, which is outside your assigned departments.'}, status=status.HTTP_403_FORBIDDEN)

        perm_col = db['backend_diagnostics_permissions']

        # 1. Check if permission already exists for this employee on this date
        existing_on_date = perm_col.find_one({'employeeId': emp_id, 'date': date_str})
        if existing_on_date:
            return Response({'error': f'Permission already granted for {emp_name} on {date_str}. (Max 1 hour per day).'}, status=status.HTTP_400_BAD_REQUEST)

        # 2. Check monthly quota: maximum 2 occasions (2 hours) per month
        month_perms = list(perm_col.find({
            'employeeId': emp_id,
            '$or': [{'month': month_str}, {'date': {'$regex': f'^{month_str}'}}]
        }))
        if len(month_perms) >= 2:
            return Response({'error': f'Monthly limit reached: {emp_name} has already used all 2 hours of permission for {month_str}.'}, status=status.HTTP_400_BAD_REQUEST)

        user_name = request.data.get('approvedBy') or getattr(request.user, 'username', None) or ('HOD' if is_hod else 'Admin')

        perm_doc = {
            'employeeId': emp_id,
            'employeeName': emp_name,
            'department': emp_dept,
            'month': month_str,
            'date': date_str,
            'durationHours': 1.0,
            'durationMins': 60,
            'reason': reason,
            'approvedBy': user_name,
            'approvedRole': 'HOD' if is_hod else 'ADMIN',
            'createdAt': datetime.utcnow()
        }
        res = perm_col.insert_one(perm_doc)

        # Recalculate attendance metrics with updated permissions
        metrics, total_month_days = calculate_attendance_metrics_from_roster(
            target_month=month_str,
            employee_ids=[emp_id],
            treat_sp_as_present=True
        )
        emp_metric = metrics.get(emp_id, {})
        new_late_lop = emp_metric.get('late_lop_days', 0.0)
        new_events = emp_metric.get('late_events_list', [])

        # Update backend_diagnostics_payroll record if exists
        payroll_col = db['backend_diagnostics_payroll']
        p_rec = payroll_col.find_one({'month': month_str, 'employeeId': emp_id})
        updated_deduction = 0.0
        if p_rec:
            gross = float(p_rec.get('grossSalary', 0) or 0)
            daily_gross = (gross / total_month_days) if (total_month_days > 0 and gross > 0) else 0.0
            updated_deduction = round(daily_gross * new_late_lop, 2)
            absent_lop = float(p_rec.get('absentLopDays', 0) or 0)
            total_lop = absent_lop + new_late_lop
            lop_ded = round(daily_gross * total_lop, 2)

            pf = float(p_rec.get('pfDeduction', 0) or 0)
            esi = float(p_rec.get('esiDeduction', 0) or 0)
            pt = float(p_rec.get('professionalTax', 0) or 0)
            manual_ded = float(p_rec.get('manualDeduction', 0) or 0)
            other_ded = float(p_rec.get('otherDeductions', 0) or 0)

            total_deductions = round(pf + esi + pt + lop_ded + manual_ded + other_ded, 2)
            net_salary = round(max(0.0, gross - total_deductions), 2)

            payroll_col.update_one(
                {'_id': p_rec['_id']},
                {'$set': {
                    'lateLopDays': new_late_lop,
                    'lateDeduction': updated_deduction,
                    'lateEventsList': new_events,
                    'lateLopInfo': emp_metric.get('late_lop_info', {}),
                    'lopDays': total_lop,
                    'lopDeduction': lop_ded,
                    'totalDeductions': total_deductions,
                    'netSalary': net_salary,
                    'hasHodEdits': True if is_hod else p_rec.get('hasHodEdits', False),
                    'updatedAt': datetime.utcnow()
                }}
            )

        return Response({
            'message': f'1-Hour Permission granted successfully for {emp_name} on {date_str}.',
            'permissionId': str(res.inserted_id),
            'employeeId': emp_id,
            'date': date_str,
            'lateLopDays': new_late_lop,
            'lateDeduction': updated_deduction,
            'permissionsUsed': len(month_perms) + 1,
            'permissionsRemaining': max(0, 2 - (len(month_perms) + 1)),
            'events': new_events
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        logger.error(f"Error in apply_employee_permission: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def revoke_employee_permission(request):
    """
    Revokes a previously granted 1-hour Permission and recalculates late hours LOP.
    """
    try:
        emp_id = str(request.data.get('employee_id') or request.data.get('employeeId', '')).strip()
        date_str = str(request.data.get('date', '')).strip()
        month_str = str(request.data.get('month', '')).strip() or date_str[:7]

        if not emp_id or not date_str:
            return Response({'error': 'employee_id and date are required.'}, status=status.HTTP_400_BAD_REQUEST)

        db = get_mongo_db()
        perm_col = db['backend_diagnostics_permissions']
        del_res = perm_col.delete_one({'employeeId': emp_id, 'date': date_str})

        # Recalculate attendance metrics without that permission
        metrics, total_month_days = calculate_attendance_metrics_from_roster(
            target_month=month_str,
            employee_ids=[emp_id],
            treat_sp_as_present=True
        )
        emp_metric = metrics.get(emp_id, {})
        new_late_lop = emp_metric.get('late_lop_days', 0.0)
        new_events = emp_metric.get('late_events_list', [])

        payroll_col = db['backend_diagnostics_payroll']
        p_rec = payroll_col.find_one({'month': month_str, 'employeeId': emp_id})
        updated_deduction = 0.0
        if p_rec:
            gross = float(p_rec.get('grossSalary', 0) or 0)
            daily_gross = (gross / total_month_days) if (total_month_days > 0 and gross > 0) else 0.0
            updated_deduction = round(daily_gross * new_late_lop, 2)
            absent_lop = float(p_rec.get('absentLopDays', 0) or 0)
            total_lop = absent_lop + new_late_lop
            lop_ded = round(daily_gross * total_lop, 2)

            pf = float(p_rec.get('pfDeduction', 0) or 0)
            esi = float(p_rec.get('esiDeduction', 0) or 0)
            pt = float(p_rec.get('professionalTax', 0) or 0)
            manual_ded = float(p_rec.get('manualDeduction', 0) or 0)
            other_ded = float(p_rec.get('otherDeductions', 0) or 0)

            total_deductions = round(pf + esi + pt + lop_ded + manual_ded + other_ded, 2)
            net_salary = round(max(0.0, gross - total_deductions), 2)

            payroll_col.update_one(
                {'_id': p_rec['_id']},
                {'$set': {
                    'lateLopDays': new_late_lop,
                    'lateDeduction': updated_deduction,
                    'lateEventsList': new_events,
                    'lateLopInfo': emp_metric.get('late_lop_info', {}),
                    'lopDays': total_lop,
                    'lopDeduction': lop_ded,
                    'totalDeductions': total_deductions,
                    'netSalary': net_salary,
                    'updatedAt': datetime.utcnow()
                }}
            )

        month_perms = list(perm_col.find({
            'employeeId': emp_id,
            '$or': [{'month': month_str}, {'date': {'$regex': f'^{month_str}'}}]
        }))

        return Response({
            'message': f'Permission revoked for employee {emp_id} on {date_str}.',
            'deletedCount': del_res.deleted_count,
            'lateLopDays': new_late_lop,
            'lateDeduction': updated_deduction,
            'permissionsUsed': len(month_perms),
            'permissionsRemaining': max(0, 2 - len(month_perms)),
            'events': new_events
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in revoke_employee_permission: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_employee_monthly_permissions(request):
    """
    Returns the permissions granted to an employee in a given month.
    """
    try:
        emp_id = str(request.GET.get('employee_id', '')).strip()
        month_str = str(request.GET.get('month', '')).strip() or datetime.now().strftime('%Y-%m')

        if not emp_id:
            return Response({'error': 'employee_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        db = get_mongo_db()
        perm_col = db['backend_diagnostics_permissions']
        perms = list(perm_col.find({
            'employeeId': emp_id,
            '$or': [{'month': month_str}, {'date': {'$regex': f'^{month_str}'}}]
        }))

        perm_count = len(perms)
        perm_hours = sum(float(p.get('durationHours', 1.0)) for p in perms)

        return Response({
            'employeeId': emp_id,
            'month': month_str,
            'permissionsUsed': perm_count,
            'permissionsUsedHours': perm_hours,
            'permissionsRemaining': max(0, 2 - perm_count),
            'permissionsRemainingHours': max(0.0, 2.0 - perm_hours),
            'permissions': [{
                'id': str(p.get('_id')),
                'date': p.get('date'),
                'durationHours': p.get('durationHours', 1.0),
                'reason': p.get('reason'),
                'approvedBy': p.get('approvedBy'),
                'approvedRole': p.get('approvedRole')
            } for p in perms]
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in get_employee_monthly_permissions: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def manual_deduction_action(request):
    """
    Allows Admin to manually add, adjust, or override a deduction for an employee.
    Used on the Deductions page for exceptional deductions, fine penalties, or custom adjustments.
    """
    try:
        emp_id = str(request.data.get('employee_id') or request.data.get('employeeId', '')).strip()
        month_str = str(request.data.get('month', '')).strip() or datetime.now().strftime('%Y-%m')
        amount = float(request.data.get('amount', 0) or 0)
        deduction_type = str(request.data.get('deduction_type', 'Manual Penalty')).strip()
        reason = str(request.data.get('reason', '')).strip()
        admin_name = str(request.data.get('admin_name') or getattr(request.user, 'username', 'Admin')).strip()

        if not emp_id:
            return Response({'error': 'employee_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if not reason:
            return Response({'error': 'Reason / remarks are mandatory for manual deduction.'}, status=status.HTTP_400_BAD_REQUEST)

        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        profiles_col = db['backend_diagnostics_profile']

        p_rec = payroll_col.find_one({'month': month_str, 'employeeId': emp_id})
        if not p_rec:
            profile = profiles_col.find_one({'employeeId': emp_id}) or {}
            salary_info = profile.get('salaryDetails', {}) or {}
            gross = float(salary_info.get('grossSalary', 0) or 0)
            p_rec = {
                'employeeId': emp_id,
                'employeeName': profile.get('employeeName', emp_id),
                'department': profile.get('department', 'General'),
                'designation': profile.get('designation', 'Employee'),
                'month': month_str,
                'grossSalary': gross,
                'presentDays': 30,
                'lopDays': 0,
                'pfDeduction': 0,
                'esiDeduction': 0,
                'professionalTax': 0,
                'lopDeduction': 0,
                'status': 'Draft',
                'createdAt': datetime.utcnow()
            }
            payroll_col.insert_one(p_rec)
            p_rec = payroll_col.find_one({'month': month_str, 'employeeId': emp_id})

        gross = float(p_rec.get('grossSalary', 0) or 0)
        lop_ded = float(p_rec.get('lopDeduction', 0) or 0)
        pf = float(p_rec.get('pfDeduction', 0) or 0)
        esi = float(p_rec.get('esiDeduction', 0) or 0)
        pt = float(p_rec.get('professionalTax', 0) or 0)
        other_ded = float(p_rec.get('otherDeductions', 0) or 0)

        total_deductions = round(pf + esi + pt + lop_ded + amount + other_ded, 2)
        net_salary = round(max(0.0, gross - total_deductions), 2)

        payroll_col.update_one(
            {'_id': p_rec['_id']},
            {'$set': {
                'manualDeduction': amount,
                'manualDeductionType': deduction_type,
                'manualDeductionReason': reason,
                'manualDeductionBy': admin_name,
                'manualDeductionAt': datetime.utcnow(),
                'totalDeductions': total_deductions,
                'netSalary': net_salary,
                'updatedAt': datetime.utcnow()
            }}
        )

        return Response({
            'message': f'Manual deduction of ₹{amount:,.2f} recorded for {p_rec.get("employeeName", emp_id)}.',
            'employeeId': emp_id,
            'manualDeduction': amount,
            'manualDeductionType': deduction_type,
            'totalDeductions': total_deductions,
            'netSalary': net_salary
        }, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in manual_deduction_action: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



