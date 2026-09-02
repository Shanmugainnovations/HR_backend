from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Q
from employees.models import Shift, Department
from employees.serializers import ShiftSerializer, DepartmentSerializer
from rest_framework.permissions import AllowAny
from employees.permissions import HasRoleAndDataPermission
import os

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def shift_list_create(request):

    if request.method == 'GET':
        department = request.query_params.get('department')
        if department and department != 'All':
            from employees.views.common.utils import resolve_department_filter
            dept_ctx = resolve_department_filter(department)
            target_terms = dept_ctx['target_terms']
            
            q_objects = Q()
            for t in target_terms:
                if t.isdigit():
                    q_objects |= Q(id=int(t))
                else:
                    q_objects |= Q(name__icontains=t)
                
            depts = Department.objects.filter(q_objects)
            shift_ids = set()
            for d in depts:
                try:
                    for s in d.shifts.all():
                        shift_ids.add(s.id)
                except Exception:
                    pass
                    
            if shift_ids:
                shifts = [s for s in Shift.objects.all() if s.id in shift_ids and getattr(s, 'is_active', True)]
            else:
                shifts = [s for s in Shift.objects.all() if getattr(s, 'is_active', True)]
        else:
            shifts = [s for s in Shift.objects.all() if getattr(s, 'is_active', True)]
            
        serializer = ShiftSerializer(shifts, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        serializer = ShiftSerializer(data=request.data)
        if serializer.is_valid():
            from employees.models import extract_actor_id
            actor_id = extract_actor_id(request)
            shift = serializer.save(created_by=actor_id, lastmodified_by=actor_id)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([AllowAny])
def shift_detail(request, pk):
    try:
        shift = Shift.objects.get(pk=pk)
    except Shift.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = ShiftSerializer(shift)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = ShiftSerializer(shift, data=request.data)
        if serializer.is_valid():
            from employees.models import extract_actor_id
            actor_id = extract_actor_id(request)
            shift = serializer.save(lastmodified_by=actor_id)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        shift.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def department_list_create(request):
    if request.method == 'GET':
        dept_ids = request.query_params.get('department')
        
        # 1. Fetch Master Departments from Global MongoDB
        global_depts = []
        try:
            from employees.views.common.utils import get_mongo_client
            client = get_mongo_client()
            db_name = os.environ.get('GLOBAL_DB_NAME', 'Global')
            g_db = client[db_name]
            g_depts = list(g_db['backend_diagnostics_Departments'].find({}, {'_id': 0, 'department_name': 1, 'department_code': 1}).sort('department_name', 1))
            if g_depts:
                global_depts = g_depts
        except Exception as ge:
            pass

        # Ensure all Global departments exist in Department table with valid integer ID
        try:
            existing_depts = list(Department.objects.all())
            max_id = max([d.id for d in existing_depts if d.id and isinstance(d.id, int)], default=0)
            existing_names = {d.name for d in existing_depts if d.name}

            for gd in global_depts:
                name = gd.get('department_name')
                if name and name not in existing_names:
                    max_id += 1
                    try:
                        Department.objects.create(id=max_id, name=name)
                        existing_names.add(name)
                    except Exception:
                        pass
        except Exception:
            pass

        if dept_ids and dept_ids != 'All':
            from employees.views.common.utils import resolve_department_filter
            dept_ctx = resolve_department_filter(dept_ids)
            target_terms = dept_ctx['target_terms']
            
            q_objects = Q()
            for t in target_terms:
                if t.isdigit():
                    q_objects |= Q(id=int(t))
                else:
                    q_objects |= Q(name__icontains=t)
            
            departments = Department.objects.filter(q_objects)
        else:
            departments = Department.objects.all().order_by('name')
            
        serializer = DepartmentSerializer(departments, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        name = request.data.get('name')
        existing = Department.objects.filter(name=name).first()
        if existing:
            serializer = DepartmentSerializer(existing, data=request.data)
        else:
            serializer = DepartmentSerializer(data=request.data)
            
        if serializer.is_valid():
            from employees.models import extract_actor_id
            actor_id = extract_actor_id(request)
            dept = serializer.save(created_by=actor_id, lastmodified_by=actor_id)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([AllowAny])
def department_detail(request, pk):
    try:
        department = Department.objects.get(pk=pk)
    except Department.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = DepartmentSerializer(department)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = DepartmentSerializer(department, data=request.data)
        if serializer.is_valid():
            from employees.models import extract_actor_id
            actor_id = extract_actor_id(request)
            dept = serializer.save(lastmodified_by=actor_id)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)




@api_view(['GET'])
@permission_classes([AllowAny])
def get_monthly_roster(request):
    from_date_str = request.query_params.get('from_date')
    to_date_str = request.query_params.get('to_date')
    month_str = request.query_params.get('month') # expected format YYYY-MM
    department = request.query_params.get('department') # Optional

    import calendar
    from datetime import date, datetime

    if from_date_str and to_date_str:
        try:
            start_date = datetime.strptime(from_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(to_date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({"error": "Invalid date format. Use YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST)
    elif month_str:
        try:
            year, month = map(int, month_str.split('-'))
            _, last_day = calendar.monthrange(year, month)
            start_date = date(year, month, 1)
            end_date = date(year, month, last_day)
        except ValueError:
            return Response({"error": "Invalid month format. Use YYYY-MM"}, status=status.HTTP_400_BAD_REQUEST)
    else:
        return Response({"error": "Either from_date/to_date or month parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

    from employees.models import EmployeeShiftSchedule
    from employees.serializers import EmployeeShiftScheduleSerializer

    # Initialize query
    schedules = EmployeeShiftSchedule.objects.filter(date__gte=start_date, date__lte=end_date)

    if department and department != 'All':
        try:
            from employees.views.common.utils import get_mongo_client
            db_name = os.environ.get("GLOBAL_DB_NAME", "Global")
            client = get_mongo_client()
            db = client[db_name]

            raw_ids = [d.strip() for d in department.split(',')]
            
            # Resolve numeric IDs to names
            from employees.models import Department
            numeric_ids = [rid for rid in raw_ids if rid.isdigit()]
            resolved_names = list(Department.objects.filter(id__in=numeric_ids).values_list('name', flat=True))
            
            # Important: Add the names from raw_ids if they aren't numeric
            all_names = resolved_names + [rid for rid in raw_ids if not rid.isdigit()]

            import re
            dept_col = db['backend_diagnostics_Departments']
            resolved_codes = list(dept_col.find(
                {"$or": [
                    {"department_name": {"$in": all_names}},
                    {"department_code": {"$in": all_names}}
                ]}
            ))
            all_target_codes = set(all_names)
            for d in resolved_codes:
                if d.get("department_code"):
                    all_target_codes.add(d["department_code"])
                if d.get("department_name"):
                    all_target_codes.add(d["department_name"])

            regex_patterns = [
                {"department": {"$regex": f"(^|,){re.escape(c)}(,|$)", "$options": "i"}}
                for c in all_target_codes
            ]
            regex_patterns += [
                {"department_name": {"$regex": f"(^|,){re.escape(c)}(,|$)", "$options": "i"}}
                for c in all_target_codes
            ]

            profiles = list(db['backend_diagnostics_profile'].find({"$or": regex_patterns}))
            employee_ids = [str(p.get("employeeId")) for p in profiles if p.get("employeeId")]
            
            # Filter Schedules
            schedules = schedules.filter(employee_id__in=employee_ids)
            print(f"DEBUG: Roster Filtering - Resulting Schedule Count: {schedules.count()}")

        except Exception as e:
            print(f"Error filtering roster by department: {e}")
            # Fallback (don't fail entire request, just log error)
    from employees.models import Shift, Employee
    all_shifts = {s.id: s for s in Shift.objects.all()}
    all_emp_names = {e.employee_id: e.name for e in Employee.objects.all()}

    schedule_values = list(schedules.values('id', 'employee_id', 'shift_id', 'date', 'created_by', 'created_date', 'lastmodified_by', 'lastmodified_date'))
    data = []
    for sch in schedule_values:
        s_obj = all_shifts.get(sch['shift_id'])
        emp_id = sch['employee_id']
        data.append({
            'id': sch['id'],
            'employee': emp_id,
            'employee_name': all_emp_names.get(emp_id, emp_id),
            'shift': sch['shift_id'],
            'shift_name': s_obj.name if s_obj else '',
            'start_time': s_obj.start_time.strftime('%H:%M:%S') if s_obj else None,
            'end_time': s_obj.end_time.strftime('%H:%M:%S') if s_obj else None,
            'date': sch['date'].strftime('%Y-%m-%d'),
            'created_by': sch.get('created_by') or '',
            'created_date': sch.get('created_date').isoformat() if sch.get('created_date') else None,
            'lastmodified_by': sch.get('lastmodified_by') or '',
            'lastmodified_date': sch.get('lastmodified_date').isoformat() if sch.get('lastmodified_date') else None,
        })
    return Response(data)

@api_view(['POST'])
@permission_classes([AllowAny])
def assign_shift(request):
    from employees.models import EmployeeShiftSchedule, Employee, Shift, extract_actor_id
    from employees.serializers import EmployeeShiftScheduleSerializer
    from django.utils import timezone
    from employees.views.common.utils import get_mongo_client
    
    actor_id = extract_actor_id(request)
    db_name = os.environ.get("GLOBAL_DB_NAME", "Global")
    mongo_client = None
    try:
        mongo_client = get_mongo_client()
    except Exception:
        pass
    
    if isinstance(request.data, list):
        for item in request.data:
            employee_id = item.get('employee_id')
            shift_id = item.get('shift_id')
            date = item.get('date')
            item_actor = item.get('actor_name') or item.get('created_by') or item.get('lastmodified_by') or actor_id

            if not employee_id or not date:
                 return Response({"error": "employee_id and date are required for all items"}, status=status.HTTP_400_BAD_REQUEST)

            try:
                # 🛠 Get or Create Employee for Global/Local Roster Integrity
                employee, _ = Employee.objects.get_or_create(
                    employee_id=employee_id,
                    defaults={'name': item.get('name', employee_id)}
                )

                if not shift_id:
                    EmployeeShiftSchedule.objects.filter(employee=employee, date=date).delete()
                else:
                    shift_obj = Shift.objects.get(id=shift_id)
                    sch = EmployeeShiftSchedule.objects.filter(employee=employee, date=date).first()
                    now = timezone.now()
                    if sch:
                        sch.shift = shift_obj
                        sch.lastmodified_by = item_actor
                        sch.lastmodified_date = now
                        if not sch.created_by:
                            sch.created_by = item_actor
                        sch.save()
                    else:
                        sch = EmployeeShiftSchedule.objects.create(
                            employee=employee,
                            date=date,
                            shift=shift_obj,
                            created_by=item_actor,
                            lastmodified_by=item_actor,
                            created_date=now,
                            lastmodified_date=now
                        )
                    
                    from employees.models import generate_shiftschedule_id
                    if not getattr(sch, 'id', None):
                        sch.id = generate_shiftschedule_id()
                    
                    if mongo_client:
                        try:
                            mongo_client[db_name]['employees_employeeshiftschedule'].update_one(
                                {'id': sch.id},
                                {'$set': {
                                    'id': sch.id,
                                    'employee_id': employee.employee_id,
                                    'shift_id': shift_obj.id,
                                    'created_by': sch.created_by or item_actor,
                                    'lastmodified_by': sch.lastmodified_by or item_actor,
                                    'lastmodified_date': now
                                }},
                                upsert=True
                            )
                        except Exception:
                            pass
            except Exception as e:
                return Response({"error": f"Error with employee {employee_id}: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "Bulk assignment successful"}, status=status.HTTP_200_OK)

    employee_id = request.data.get('employee_id')
    name = request.data.get('name', employee_id)
    shift_id = request.data.get('shift_id')
    date = request.data.get('date')
    item_actor = request.data.get('actor_name') or request.data.get('created_by') or request.data.get('lastmodified_by') or actor_id

    if not employee_id or not date:
         return Response({"error": "employee_id and date are required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Get or Create local employee record
        employee, _ = Employee.objects.get_or_create(
            employee_id=employee_id,
            defaults={'name': name}
        )

        # Handle Shift Assignment
        if not shift_id:
            EmployeeShiftSchedule.objects.filter(employee=employee, date=date).delete()
            return Response({"message": "Shift assignment cleared"}, status=status.HTTP_200_OK)

        shift_obj = Shift.objects.get(id=shift_id)
        sch = EmployeeShiftSchedule.objects.filter(employee=employee, date=date).first()
        now = timezone.now()
        if sch:
            sch.shift = shift_obj
            sch.lastmodified_by = item_actor
            sch.lastmodified_date = now
            if not sch.created_by:
                sch.created_by = item_actor
            sch.save()
        else:
            sch = EmployeeShiftSchedule.objects.create(
                employee=employee,
                date=date,
                shift=shift_obj,
                created_by=item_actor,
                lastmodified_by=item_actor,
                created_date=now,
                lastmodified_date=now
            )

        from employees.models import generate_shiftschedule_id
        if not getattr(sch, 'id', None):
            sch.id = generate_shiftschedule_id()
            
        if mongo_client:
            try:
                mongo_client[db_name]['employees_employeeshiftschedule'].update_one(
                    {'id': sch.id},
                    {'$set': {
                        'id': sch.id,
                        'employee_id': employee.employee_id,
                        'shift_id': shift_obj.id,
                        'created_by': sch.created_by or item_actor,
                        'lastmodified_by': sch.lastmodified_by or item_actor,
                        'lastmodified_date': now
                    }},
                    upsert=True
                )
            except Exception:
                pass
        return Response({"message": "Shift assigned successfully"}, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
