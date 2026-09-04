import os
import io
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


def calculate_attendance_metrics_from_roster(target_month, employee_ids=None, treat_sp_as_present=True):
    """
    Computes exact Present Days, LOP (Absent) Days, and Single Punch (SP) Days
    matching the Duty Roster Attendance Report.
    Only true unapproved missed shifts count as LOP.
    Leaves (EL, CL, SL, etc.) and Week Offs/Holidays/Sundays count as Paid days (Present).
    """
    try:
        parts = target_month.split('-')
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

        metrics[eid] = {
            'total_month_days': total_days_in_month,
            'present_days': present_count,
            'lop_days': lop_count,
            'sp_days': sp_count,
            'off_days': off_count,
            'leave_days': leave_count,
        }

    return metrics, total_days_in_month


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def monthly_payroll_view(request):
    """
    GET: Retrieve payroll for a specific month (e.g. ?month=2026-07).
    POST: Generate / Regenerate payroll draft for the given month with Duty Roster attendance matching.
    """
    try:
        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        profiles_col = db['backend_diagnostics_profile']
        
        target_month = request.GET.get('month') or request.data.get('month') or datetime.now().strftime('%Y-%m')
        recalculate = str(request.GET.get('recalculate_attendance', '')).lower() in ['true', '1', 'yes'] or request.method == 'POST'
        
        # Check existing records
        existing_records = list(payroll_col.find({'month': target_month}))
        
        department_filter = request.GET.get('department') or request.data.get('department')
        from employees.views.common.utils import resolve_department_filter
        dept_ctx = resolve_department_filter(department_filter)

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
                'status': existing_records[0].get('status', 'Draft') if existing_records else 'Draft',
                'summary': {
                    'totalEmployees': len(records),
                    'totalGross': round(total_gross, 2),
                    'totalNetPayout': round(total_net, 2),
                    'totalDeductions': round(total_deductions, 2),
                },
                'records': records
            }, status=status.HTTP_200_OK)
            
        # Check if already locked / approved
        if existing_records and existing_records[0].get('status') == 'Approved' and not recalculate:
            return Response({
                'error': f'Payroll for {target_month} is Approved & Locked and cannot be regenerated.',
                'status': 'Approved'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Generate or Refresh from profiles + live Duty Roster attendance calculations
        all_profiles = list(profiles_col.find({}))
        new_records = []
        now_ts = datetime.utcnow()
        
        # Calculate attendance metrics matching Duty Roster
        all_emp_ids = [str(p.get('employeeId', '')).strip() for p in all_profiles if p.get('employeeId')]
        treat_sp = str(request.GET.get('treat_sp_as_present', request.data.get('treat_sp_as_present', 'true'))).lower() in ['true', '1', 'yes']
        attendance_map, total_month_days = calculate_attendance_metrics_from_roster(target_month, all_emp_ids, treat_sp_as_present=treat_sp)
        
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
            
            # Duty Roster Driven Present & LOP Days
            att_metric = attendance_map.get(emp_id, {
                'present_days': 0,
                'lop_days': 0.0,
            })

            present_days = att_metric.get('present_days', 0)
            lop_days = att_metric.get('lop_days', 0.0)

            # LOP deduction calculation based on gross daily rate
            daily_gross = (gross / total_month_days) if (total_month_days > 0 and gross > 0) else 0.0
            lop_deduction = round(daily_gross * lop_days, 2) if lop_days > 0 else 0.0

            tot_ded = round(pf_val + esi_val + pt_val + lop_deduction, 2)
            net = max(0.0, round(gross - tot_ded, 2))
            
            clean_dept = get_clean_dept(p.get('department'))

            pay_doc = {
                's_no': idx,
                'month': target_month,
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
                'lopDays': lop_days,
                'spDays': att_metric.get('sp_days', 0),
                
                # Earnings
                'basicSalary': basic,
                'hra': hra,
                'allowances': allowances,
                'clEncashment': 0.0,
                'incentives': 0.0,
                'grossSalary': gross,
                
                # Deductions
                'lopDeduction': lop_deduction,
                'lateDeduction': 0.0,
                'pf': pf_val,
                'esi': esi_val,
                'professionalTax': pt_val,
                'tdsDeduction': 0.0,
                'messEb': 0.0,
                'cautionDeposit': 0.0,
                'uniformId': 0.0,
                'vaccineDeduction': 0.0,
                'fines': 0.0,
                'otherDeductions': 0.0,
                'totalDeductions': tot_ded,
                
                'netSalary': net,
                'status': 'Draft',
                'created_at': now_ts,
                'updated_at': now_ts,
            }
            
            # Upsert into collection
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

        return Response({
            'message': f"Payroll generated for {target_month} matching Duty Roster",
            'month': target_month,
            'status': 'Draft',
            'summary': {
                'totalEmployees': len(new_records),
                'totalGross': round(total_gross, 2),
                'totalNetPayout': round(total_net, 2),
                'totalDeductions': round(total_deductions, 2),
            },
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
    BLOCKED IF PAYROLL IS LOCKED / APPROVED.
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
            return Response({'error': 'Payroll entry not found'}, status=status.HTTP_404_NOT_FOUND)

        # IMMUTABILITY CHECK: Reject if already Approved / Locked
        if existing.get('status') == 'Approved':
            return Response({
                'error': 'This payroll is Approved & Locked. Further edits and adjustments are strictly disabled.'
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
        other_ded = float(data.get('otherDeductions', existing.get('otherDeductions', 0)) or 0)
        
        tot_ded = (lop_ded + late_ded + pf + esi + pt + tds + mess_eb + caution + uniform + vaccine + fines + other_ded)
        net = max(0.0, gross - tot_ded)
        
        update_fields = {
            'basicSalary': basic,
            'hra': hra,
            'allowances': allowances,
            'clEncashment': cl_encash,
            'incentives': incentives,
            'grossSalary': round(gross, 2),
            
            'presentDays': float(data.get('presentDays', existing.get('presentDays', 0)) or 0),
            'lopDays': float(data.get('lopDays', existing.get('lopDays', 0)) or 0),
            'spDays': int(data.get('spDays', existing.get('spDays', 0)) or 0),
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
            'otherDeductions': round(other_ded, 2),
            'totalDeductions': round(tot_ded, 2),
            
            'netSalary': round(net, 2),
            'paymentMode': data.get('paymentMode', existing.get('paymentMode', 'Bank Transfer')),
            'updated_at': datetime.utcnow()
        }
        
        payroll_col.update_one(query, {'$set': update_fields})
        updated = payroll_col.find_one(query)
        updated['_id'] = str(updated['_id'])
        
        return Response({'message': 'Payroll entry updated successfully', 'record': updated}, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in update_payroll_entry: {str(e)}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def approve_monthly_payroll(request):
    """
    Approve & Lock monthly payroll permanently.
    """
    try:
        db = get_mongo_db()
        payroll_col = db['backend_diagnostics_payroll']
        month = request.data.get('month') or datetime.now().strftime('%Y-%m')
        
        res = payroll_col.update_many(
            {'month': month},
            {'$set': {'status': 'Approved', 'approved_at': datetime.utcnow()}}
        )
        
        return Response({
            'message': f"Payroll for {month} successfully approved and locked. Modifications are now disabled.",
            'modifiedCount': res.modified_count
        }, status=status.HTTP_200_OK)
    except Exception as e:
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
        
        records = list(payroll_col.find({'month': month}))
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
        
        records = list(payroll_col.find({'month': month, 'pf': {'$gt': 0}}))
        if not records:
            records = list(payroll_col.find({'month': month}))
            
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
        
        records = list(payroll_col.find({'month': month, 'esi': {'$gt': 0}}))
        if not records:
            records = list(payroll_col.find({'month': month, 'grossSalary': {'$lte': 21000, '$gt': 0}}))
            
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
