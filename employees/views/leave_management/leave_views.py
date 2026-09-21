from employees.permissions import HasRoleAndDataPermission
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from employees.models import LeaveRequest, Employee, Shift, EmployeeShiftSchedule, LeaveType, Register
from employees.serializers import LeaveTypeSerializer
from employees.views.authentication.auth import resolve_department_names
from django.utils import timezone
from datetime import datetime, timedelta

def resolve_leave_department(leave_obj, reg_map=None):
    raw_dept = getattr(leave_obj, 'department', '') or getattr(leave_obj, 'department_id', '')
    if (not raw_dept or str(raw_dept).strip() == '') and reg_map:
        raw_dept = reg_map.get(str(getattr(leave_obj, 'employee_id', '')).strip(), '')
    
    if not raw_dept:
        return "General"
    
    resolved = resolve_department_names(str(raw_dept))
    if not resolved or resolved == "Unassigned":
        return str(raw_dept) if not str(raw_dept).upper().startswith("DEPT") else "General"
    return resolved

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def leave_type_list_create(request):

    if request.method == 'GET':
        leave_types = LeaveType.objects.all().order_by('name')
        serializer = LeaveTypeSerializer(leave_types, many=True)
        return Response(serializer.data)

    elif request.method == 'POST':
        serializer = LeaveTypeSerializer(data=request.data)
        if serializer.is_valid():
            from employees.models import extract_actor_id
            actor_id = extract_actor_id(request)
            lt = serializer.save(created_by=actor_id, lastmodified_by=actor_id)
            print(f"🔑 AUDIT SAVED -> LeaveType CreatedBy: {lt.created_by}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([AllowAny])
def leave_type_detail(request, pk):
    try:
        try:
            leave_type = LeaveType.objects.get(pk=int(pk))
        except (ValueError, TypeError):
            leave_type = LeaveType.objects.get(pk=pk)
    except LeaveType.DoesNotExist:
        return Response({'error': 'Leave type not found'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = LeaveTypeSerializer(leave_type)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = LeaveTypeSerializer(leave_type, data=request.data, partial=True)
        if serializer.is_valid():
            lt = serializer.save()
            lt.save_with_audit(request)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        leave_type.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(['POST'])
@permission_classes([AllowAny])
def apply_leave(request):
    try:
        employee_id = getattr(request, 'authenticated_employee_id', None) or request.data.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee ID is required"}, status=400)
            
        reg = Register.objects.filter(employee_id=str(employee_id).strip()).first()
        emp_name = request.data.get('employee_name') or (reg.name if reg else None)
        raw_dept = request.data.get('department') or (reg.department if reg else None)
        raw_dept_id = request.data.get('department_id') or (reg.department if reg else None)

        dept_name = resolve_department_names(raw_dept) if raw_dept else ""
        if not dept_name or dept_name == "Unassigned":
            dept_name = resolve_department_names(raw_dept_id) if raw_dept_id else ""
        if not dept_name or dept_name == "Unassigned":
            dept_name = raw_dept or "General"

        LeaveRequest.objects.create(
            employee_id=employee_id,
            employee_name=emp_name,
            department=dept_name,
            department_id=raw_dept_id or raw_dept or dept_name,
            start_date=request.data.get('start_date'),
            end_date=request.data.get('end_date'),
            leave_type=request.data.get('leave_type'),
            reason=request.data.get('reason')
        )
        return Response({"message": "Leave requested successfully"}, status=201)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
@permission_classes([AllowAny])
def my_leaves(request):
    try:
        employee_id = getattr(request, 'authenticated_employee_id', None) or request.GET.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee ID is required"}, status=400)
            
        leaves = LeaveRequest.objects.filter(employee_id=employee_id).order_by('-applied_on')
        reg = Register.objects.filter(employee_id=str(employee_id).strip()).first()
        reg_map = {str(employee_id).strip(): reg.department} if reg and reg.department else {}

        data = [{
            "id": l.id,
            "employee_id": l.employee_id,
            "employee_name": l.employee_name or (reg.name if reg else "Employee"),
            "department": resolve_leave_department(l, reg_map),
            "department_code": l.department_id or l.department,
            "start_date": l.start_date,
            "end_date": l.end_date,
            "leave_type": l.leave_type,
            "reason": l.reason,
            "status": l.status,
            "applied_on": l.applied_on,
            "reviewed_by_name": l.reviewed_by_name
        } for l in leaves]
        return Response(data, status=200)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
@permission_classes([AllowAny])
def pending_leaves(request):
    try:
        department_id = request.GET.get('department_id')
        department = request.GET.get('department')
        
        leaves = LeaveRequest.objects.all().order_by('-applied_on')
        
        if department and department != 'All':
            from django.db.models import Q
            from employees.views.common.utils import resolve_department_filter
            dept_ctx = resolve_department_filter(department)
            target_terms = dept_ctx['target_terms']
            matching_emp_ids = dept_ctx['matching_employee_ids'] or set()
            
            q_dept = Q()
            if matching_emp_ids:
                q_dept |= Q(employee_id__in=matching_emp_ids)
            for t in target_terms:
                q_dept |= Q(department__icontains=t) | Q(department_id__icontains=t)
            leaves = leaves.filter(q_dept)
        emp_ids = [str(l.employee_id).strip() for l in leaves if l.employee_id]
        reg_map = {
            str(r.employee_id).strip(): (r.department or '')
            for r in Register.objects.filter(employee_id__in=emp_ids)
        }

        data = [{
            "id": l.id,
            "employee_id": l.employee_id,
            "employee_name": l.employee_name or f"Employee #{l.employee_id}",
            "department": resolve_leave_department(l, reg_map),
            "department_code": l.department_id or l.department,
            "start_date": l.start_date,
            "end_date": l.end_date,
            "leave_type": l.leave_type,
            "reason": l.reason,
            "status": l.status,
            "applied_on": l.applied_on,
            "reviewed_by_name": l.reviewed_by_name
        } for l in leaves]
        return Response(data, status=200)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(['GET'])
@permission_classes([AllowAny])
def leave_history(request):
    try:
        status_filter = request.GET.get('status')
        employee_name = request.GET.get('employee_name')
        department = request.GET.get('department')
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')
        
        leaves = LeaveRequest.objects.all()
        
        if status_filter and status_filter != 'All':
            leaves = leaves.filter(status=status_filter)
        if employee_name:
            leaves = leaves.filter(employee_name__icontains=employee_name)
        if department and department != 'All':
            from django.db.models import Q
            from employees.views.common.utils import resolve_department_filter
            dept_ctx = resolve_department_filter(department)
            target_terms = dept_ctx['target_terms']
            matching_emp_ids = dept_ctx['matching_employee_ids'] or set()
            
            q_dept = Q()
            if matching_emp_ids:
                q_dept |= Q(employee_id__in=matching_emp_ids)
            for t in target_terms:
                q_dept |= Q(department__icontains=t) | Q(department_id__icontains=t)
            leaves = leaves.filter(q_dept)
        if from_date:
            leaves = leaves.filter(end_date__gte=from_date)
        if to_date:
            leaves = leaves.filter(start_date__lte=to_date)
            
        leaves = leaves.order_by('-applied_on')
        
        hist_emp_ids = [str(l.employee_id).strip() for l in leaves if l.employee_id]
        hist_reg_map = {
            str(r.employee_id).strip(): (r.department or '')
            for r in Register.objects.filter(employee_id__in=hist_emp_ids)
        }

        data = [{
            "id": l.id,
            "employee_id": l.employee_id,
            "employee_name": l.employee_name or f"Employee #{l.employee_id}",
            "department": resolve_leave_department(l, hist_reg_map),
            "department_code": l.department_id or l.department,
            "start_date": l.start_date,
            "end_date": l.end_date,
            "leave_type": l.leave_type,
            "reason": l.reason,
            "status": l.status,
            "applied_on": l.applied_on,
            "reviewed_by_name": l.reviewed_by_name
        } for l in leaves]
        return Response(data, status=200)
    except Exception as e:
        return Response({"error": str(e)}, status=500)

@api_view(['PUT'])
@permission_classes([AllowAny])
def update_leave_status(request, leave_id):

    try:
        status_val = request.data.get('status')
        reviewer_name = request.data.get('reviewer_name')
        
        if status_val not in ['Approved', 'Rejected']:
            return Response({"error": "Invalid status"}, status=400)
            
        leave = LeaveRequest.objects.get(id=leave_id)
        prev_status = leave.status
        leave.status = status_val
        if reviewer_name:
            leave.reviewed_by_name = reviewer_name
        leave.save()
        
        # Update roster if approved
        if status_val == 'Approved':
            try:
                start_date_obj = leave.start_date
                end_date_obj = leave.end_date
                
                leave_shift = Shift.objects.filter(name__iexact=leave.leave_type).first()
                employee_obj = Employee.objects.filter(employee_id=leave.employee_id).first()
                
                if leave_shift and employee_obj:
                    current_date = start_date_obj
                    while current_date <= end_date_obj:
                        sched = EmployeeShiftSchedule.objects.filter(employee=employee_obj, date=current_date).first()
                        if sched:
                            sched.shift = leave_shift
                            sched.save()
                        else:
                            last_sched = EmployeeShiftSchedule.objects.order_by('-id').first()
                            new_id = (last_sched.id + 1) if last_sched else 1
                            EmployeeShiftSchedule.objects.create(
                                id=new_id,
                                employee=employee_obj,
                                date=current_date,
                                shift=leave_shift
                            )
                        current_date += timedelta(days=1)
            except Exception as roster_e:
                import traceback
                traceback.print_exc()
                print("Failed to update roster on leave approval:", roster_e)

        # Synchronize leave balance in Mongo
        try:
            if prev_status != status_val:
                from pymongo import MongoClient
                mongo_uri = os.environ.get('GLOBAL_DB_HOST', 'mongodb://admin:SMRFT%40prod2026@45.252.190.162:27017/')
                client = MongoClient(mongo_uri)
                global_db = client['Global']
                bal_coll = global_db['employees_leave_balance']
                
                emp_id_str = str(leave.employee_id).strip()
                bal_doc = bal_coll.find_one({'employee_id': emp_id_str})
                
                # Calculate days requested
                if leave.start_date and leave.end_date:
                    leave_days = (leave.end_date - leave.start_date).days + 1
                else:
                    leave_days = 1.0

                ltype_upper = str(leave.leave_type or '').upper().strip()
                type_key = 'EL'
                if 'NH' in ltype_upper or 'HOLIDAY' in ltype_upper or 'PH' in ltype_upper:
                    type_key = 'NH'
                elif 'SL' in ltype_upper or 'SICK' in ltype_upper or 'CL' in ltype_upper or 'CASUAL' in ltype_upper or 'C' in ltype_upper:
                    type_key = 'SL'
                elif 'EL' in ltype_upper or 'EARNED' in ltype_upper:
                    type_key = 'EL'

                if bal_doc:
                    lb = bal_doc.get('leave_balances', {})
                    current_val = float(lb.get(type_key, lb.get(type_key.lower(), 0.0)))
                    
                    if status_val == 'Approved' and prev_status != 'Approved':
                        new_val = max(0.0, current_val - leave_days)
                        lb[type_key] = new_val
                    elif prev_status == 'Approved' and status_val != 'Approved':
                        new_val = current_val + leave_days
                        lb[type_key] = new_val

                    tot_avail = sum(float(v) for k, v in lb.items() if k != 'total_available')
                    lb['total_available'] = round(tot_avail, 2)
                    
                    bal_coll.update_one({'_id': bal_doc['_id']}, {'$set': {'leave_balances': lb, 'updated_at': datetime.now()}})
        except Exception as bal_err:
            print("Error updating leave balance in Mongo:", bal_err)

        # Auto-create real-time notification for the employee
        try:
            from employees.views.mobile_app.notifications import get_notifications_collection
            col = get_notifications_collection()
            now_dt = datetime.now()
            status_icon = "✅" if status_val == 'Approved' else "❌"
            title = f"Leave Request {status_val} {status_icon}"
            start_str = leave.start_date.strftime('%d %b %Y') if hasattr(leave.start_date, 'strftime') else str(leave.start_date)
            end_str = leave.end_date.strftime('%d %b %Y') if hasattr(leave.end_date, 'strftime') else str(leave.end_date)
            
            by_str = f" by {reviewer_name}" if reviewer_name else ""
            message = f"Your request for {leave.leave_type} ({start_str} to {end_str}) has been {status_val.lower()}{by_str}."

            col.insert_one({
                "employee_id": str(leave.employee_id),
                "title": title,
                "message": message,
                "category": "leave",
                "is_read": False,
                "action_url": "",
                "created_at": now_dt.strftime('%Y-%m-%d %H:%M:%S'),
                "created_at_ts": now_dt.timestamp()
            })
        except Exception as notif_err:
            print("Error pushing leave notification", notif_err)
            
        return Response({"message": f"Leave {status_val}"}, status=200)
    except LeaveRequest.DoesNotExist:
        return Response({"error": "Leave request not found"}, status=404)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_leave_balances(request):
    """
    Retrieve employee leave balances from employees_leave_balance collection.
    Supports query params:
      - employee_id: filter by specific employee ID
      - department: filter by department name or code (or 'All')
      - search: filter by name or ID
      - balance_filter: 'all' | 'has_balance' | 'zero_balance' | 'high_balance'
      - export: 'csv'
    """
    import os
    import csv
    import re
    from pymongo import MongoClient
    from django.http import HttpResponse

    try:
        mongo_uri = os.environ.get('GLOBAL_DB_HOST', 'mongodb://admin:SMRFT%40prod2026@45.252.190.162:27017/')
        client = MongoClient(mongo_uri)
        db = client['Global']
        coll = db['employees_leave_balance']

        emp_id = request.query_params.get('employee_id')
        dept_param = request.query_params.get('department')
        search_query = request.query_params.get('search', '').strip()
        balance_filter = request.query_params.get('balance_filter', 'all')
        export_csv = request.query_params.get('export') == 'csv'

        from employees.views.common.utils import get_request_user_hod_departments
        is_hod, hod_assigned_depts = get_request_user_hod_departments(request)

        # Build mongo query
        query = {}
        if emp_id:
            query['employee_id'] = str(emp_id).strip()

        if is_hod:
            if hod_assigned_depts:
                if dept_param and dept_param.lower() != 'all':
                    dept_escaped = re.escape(dept_param.strip())
                    query['$or'] = [
                        {'department': {'$regex': f'^{dept_escaped}$', '$options': 'i'}},
                        {'department_code': {'$regex': f'^{dept_escaped}$', '$options': 'i'}},
                        {'raw_department': {'$regex': f'^{dept_escaped}$', '$options': 'i'}}
                    ]
                else:
                    dept_or_conds = []
                    for ad in hod_assigned_depts:
                        ad_escaped = re.escape(ad.strip())
                        dept_or_conds.extend([
                            {'department': {'$regex': f'^{ad_escaped}$', '$options': 'i'}},
                            {'department_code': {'$regex': f'^{ad_escaped}$', '$options': 'i'}},
                            {'raw_department': {'$regex': f'^{ad_escaped}$', '$options': 'i'}}
                        ])
                    query['$or'] = dept_or_conds
            else:
                query['employee_id'] = '__NONE__'
        elif dept_param and dept_param.lower() != 'all':
            dept_escaped = re.escape(dept_param.strip())
            query['$or'] = [
                {'department': {'$regex': f'^{dept_escaped}$', '$options': 'i'}},
                {'department_code': {'$regex': f'^{dept_escaped}$', '$options': 'i'}},
                {'raw_department': {'$regex': f'^{dept_escaped}$', '$options': 'i'}}
            ]

        if search_query:
            search_escaped = re.escape(search_query)
            search_cond = [
                {'employee_id': {'$regex': search_escaped, '$options': 'i'}},
                {'employee_name': {'$regex': search_escaped, '$options': 'i'}},
                {'designation': {'$regex': search_escaped, '$options': 'i'}}
            ]
            if '$or' in query:
                query['$and'] = [
                    {'$or': query.pop('$or')},
                    {'$or': search_cond}
                ]
            else:
                query['$or'] = search_cond

        if balance_filter == 'has_balance':
            query['leave_balances.total_available'] = {'$gt': 0}
        elif balance_filter == 'zero_balance':
            query['leave_balances.total_available'] = {'$lte': 0}
        elif balance_filter == 'high_balance':
            query['leave_balances.total_available'] = {'$gte': 10}

        include_inactive = str(request.query_params.get('include_inactive', 'false')).lower() in ['true', '1', 'yes']
        from employees.views.common.utils import get_inactive_employee_ids
        inactive_ids = get_inactive_employee_ids()
        if not include_inactive and inactive_ids:
            if 'employee_id' in query:
                if isinstance(query['employee_id'], str) and query['employee_id'] in inactive_ids:
                    return Response({'summary': {'total_employees': 0, 'total_available_leaves': 0, 'total_el': 0, 'total_nh': 0, 'total_sl': 0, 'filtered_count': 0, 'departments': []}, 'records': []}, status=200)
            else:
                query['employee_id'] = {'$nin': list(inactive_ids)}

        # Fetch records
        cursor = coll.find(query).sort([
            ('leave_balances.total_available', -1),
            ('employee_id', 1)
        ])
        raw_records = list(cursor)

        # Fallback: If querying a specific employee and no balance record exists yet, create default entry from Mongo profile
        if not raw_records and emp_id:
            try:
                prof_doc = db['backend_diagnostics_profile'].find_one({'employeeId': str(emp_id).strip()})
                if prof_doc:
                    default_doc = {
                        'employee_id': str(emp_id).strip(),
                        'employee_name': prof_doc.get('employeeName') or f"{prof_doc.get('first_name', '')} {prof_doc.get('last_name', '')}".strip() or str(emp_id),
                        'department': prof_doc.get('department_name') or prof_doc.get('department') or 'General',
                        'department_code': prof_doc.get('department') or 'DEPT001',
                        'designation': prof_doc.get('designation') or 'Staff',
                        'doj': prof_doc.get('doj') or '2024-01-01',
                        'leave_balances': {'EL': 12.0, 'NH': 9.0, 'SL': 12.0, 'total_available': 33.0},
                        'eligible_entitlement': {'EL': 12.0, 'NH': 9.0, 'SL': 12.0, 'total_eligible': 33.0},
                        'created_at': datetime.now(),
                        'updated_at': datetime.now()
                    }
                    coll.insert_one(default_doc)
                    raw_records = [default_doc]
            except Exception as fb_err:
                print("Error in fallback leave balance creation:", fb_err)

        # Format records and calculate approved leave taken
        records = []
        rec_emp_ids = [str(r.get('employee_id')).strip() for r in raw_records if r.get('employee_id')]
        taken_summary = {}
        if rec_emp_ids:
            try:
                approved_reqs = LeaveRequest.objects.filter(employee_id__in=rec_emp_ids, status='Approved')
                for req in approved_reqs:
                    eid = str(req.employee_id).strip()
                    days = (req.end_date - req.start_date).days + 1 if req.start_date and req.end_date else 1
                    ltype = str(req.leave_type or '').upper().strip()
                    
                    tkey = 'EL'
                    if 'NH' in ltype or 'HOLIDAY' in ltype or 'PH' in ltype:
                        tkey = 'NH'
                    elif 'SL' in ltype or 'SICK' in ltype or 'CL' in ltype or 'CASUAL' in ltype or 'C' in ltype:
                        tkey = 'SL'

                    if eid not in taken_summary:
                        taken_summary[eid] = {'total_taken': 0.0, 'EL': 0.0, 'NH': 0.0, 'SL': 0.0}
                    taken_summary[eid]['total_taken'] += days
                    taken_summary[eid][tkey] = taken_summary[eid].get(tkey, 0.0) + days
            except Exception as t_err:
                print("Error computing taken leaves summary:", t_err)

        for doc in raw_records:
            doc['_id'] = str(doc['_id'])
            if 'created_at' in doc and hasattr(doc['created_at'], 'isoformat'):
                doc['created_at'] = doc['created_at'].isoformat()
            if 'updated_at' in doc and hasattr(doc['updated_at'], 'isoformat'):
                doc['updated_at'] = doc['updated_at'].isoformat()
            
            eid = str(doc.get('employee_id')).strip()
            ee = doc.get('eligible_entitlement', {})
            lb = doc.get('leave_balances', {})

            el_elig = float(ee.get('EL', ee.get('el', 12.0)))
            nh_elig = float(ee.get('NH', ee.get('nh', 9.0)))
            sl_elig = float(ee.get('SL', ee.get('sl', 12.0)))
            tot_elig = float(ee.get('total_eligible', el_elig + nh_elig + sl_elig))

            # The values stored from the excel sheet represent taken leaves
            el_sheet_taken = float(lb.get('EL', lb.get('el', 0.0)))
            nh_sheet_taken = float(lb.get('NH', lb.get('nh', 0.0)))
            sl_sheet_taken = float(lb.get('SL', lb.get('sl', 0.0)))

            req_taken = taken_summary.get(eid, {'total_taken': 0.0, 'EL': 0.0, 'NH': 0.0, 'SL': 0.0})

            el_taken_tot = round(el_sheet_taken + req_taken.get('EL', 0.0), 2)
            nh_taken_tot = round(nh_sheet_taken + req_taken.get('NH', 0.0), 2)
            sl_taken_tot = round(sl_sheet_taken + req_taken.get('SL', 0.0), 2)
            total_taken_tot = round(el_taken_tot + nh_taken_tot + sl_taken_tot, 2)

            doc['leaves_taken'] = {
                'total_taken': total_taken_tot,
                'EL': el_taken_tot,
                'NH': nh_taken_tot,
                'SL': sl_taken_tot
            }

            el_rem = max(0.0, round(el_elig - el_taken_tot, 2))
            nh_rem = max(0.0, round(nh_elig - nh_taken_tot, 2))
            sl_rem = max(0.0, round(sl_elig - sl_taken_tot, 2))
            tot_rem = round(el_rem + nh_rem + sl_rem, 2)

            doc['leave_balances'] = {
                'EL': el_rem,
                'NH': nh_rem,
                'SL': sl_rem,
                'total_available': tot_rem
            }
            records.append(doc)

        # Handle CSV export
        if export_csv:
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="Employee_Leave_Balances_{datetime.now().strftime("%Y%m%d")}.csv"'
            writer = csv.writer(response)
            writer.writerow([
                'S.No', 'Employee ID', 'Employee Name', 'Department', 'Department Code',
                'Designation', 'DOJ', 'EL Balance', 'NH Balance', 'SL Balance',
                'Total Available Leaves', 'Eligible EL', 'Eligible NH', 'Eligible SL', 'Total Eligible'
            ])
            for idx, r in enumerate(records, 1):
                lb = r.get('leave_balances', {})
                ee = r.get('eligible_entitlement', {})
                writer.writerow([
                    idx,
                    r.get('employee_id', ''),
                    r.get('employee_name', ''),
                    r.get('department', ''),
                    r.get('department_code', ''),
                    r.get('designation', ''),
                    r.get('doj', ''),
                    lb.get('EL', 0),
                    lb.get('NH', 0),
                    lb.get('SL', 0),
                    lb.get('total_available', 0),
                    ee.get('EL', 0),
                    ee.get('NH', 0),
                    ee.get('SL', 0),
                    ee.get('total_eligible', 0)
                ])
            return response

        # Aggregate summary statistics across active documents in collection
        pipeline = []
        if not include_inactive and inactive_ids:
            pipeline.append({'$match': {'employee_id': {'$nin': list(inactive_ids)}}})
        if is_hod:
            if hod_assigned_depts:
                hod_match_conds = []
                for ad in hod_assigned_depts:
                    ad_escaped = re.escape(ad.strip())
                    hod_match_conds.extend([
                        {'department': {'$regex': f'^{ad_escaped}$', '$options': 'i'}},
                        {'department_code': {'$regex': f'^{ad_escaped}$', '$options': 'i'}},
                        {'raw_department': {'$regex': f'^{ad_escaped}$', '$options': 'i'}}
                    ])
                pipeline.append({'$match': {'$or': hod_match_conds}})
            else:
                pipeline.append({'$match': {'employee_id': '__NONE__'}})

        pipeline.extend([
            {'$group': {
                '_id': '$department',
                'department_code': {'$first': '$department_code'},
                'count': {'$sum': 1},
                'total_leaves': {'$sum': '$leave_balances.total_available'},
                'total_el': {'$sum': '$leave_balances.EL'},
                'total_nh': {'$sum': '$leave_balances.NH'},
                'total_sl': {'$sum': '$leave_balances.SL'}
            }},
            {'$sort': {'total_leaves': -1}}
        ])
        dept_summary_raw = list(coll.aggregate(pipeline))
        dept_summary = []
        overall_total_leaves = 0.0
        overall_total_el = 0.0
        overall_total_nh = 0.0
        overall_total_sl = 0.0
        overall_total_emps = 0

        for d in dept_summary_raw:
            d_dept = d['_id'] or 'Uncategorized'
            c = d['count']
            tot = round(d['total_leaves'], 2)
            el = round(d['total_el'], 2)
            nh = round(d['total_nh'], 2)
            sl = round(d['total_sl'], 2)

            dept_summary.append({
                'department': d_dept,
                'department_code': d.get('department_code', ''),
                'employee_count': c,
                'total_leaves': tot,
                'total_el': el,
                'total_nh': nh,
                'total_sl': sl,
                'avg_leaves_per_emp': round(tot / c, 1) if c else 0.0
            })

            overall_total_leaves += tot
            overall_total_el += el
            overall_total_nh += nh
            overall_total_sl += sl
            overall_total_emps += c

        summary = {
            'total_employees': overall_total_emps,
            'total_available_leaves': round(overall_total_leaves, 2),
            'total_el': round(overall_total_el, 2),
            'total_nh': round(overall_total_nh, 2),
            'total_sl': round(overall_total_sl, 2),
            'filtered_count': len(records),
            'departments': dept_summary
        }

        return Response({
            'isHOD': is_hod,
            'assignedDepartments': hod_assigned_depts if is_hod else [],
            'summary': summary,
            'records': records
        }, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
