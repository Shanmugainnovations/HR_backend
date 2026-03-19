from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Q
from ..models import Shift, Department
from ..serializers import ShiftSerializer, DepartmentSerializer
import os
from pymongo import MongoClient

@api_view(['GET', 'POST'])
def shift_list_create(request):
    if request.method == 'GET':
        department = request.query_params.get('department')
        if department and department != 'All':
            dept_keys = [d.strip() for d in department.split(',')]
            numeric_ids = [k for k in dept_keys if k.isdigit()]
            names = [k for k in dept_keys if not k.isdigit()]
            
            q_objects = Q()
            if numeric_ids:
                q_objects |= Q(departments__id__in=numeric_ids)
            if names:
                q_objects |= Q(departments__name__in=names)
                
            shifts = Shift.objects.filter(q_objects).distinct()
        else:
            shifts = Shift.objects.all()
            
        serializer = ShiftSerializer(shifts, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        serializer = ShiftSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'DELETE'])
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
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        shift.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(['GET', 'POST'])
def department_list_create(request):
    if request.method == 'GET':
        dept_ids = request.query_params.get('department')
        if dept_ids and dept_ids != 'All':
            id_list = [d.strip() for d in dept_ids.split(',')]
            numeric_ids = [i for i in id_list if i.isdigit()]
            names = [i for i in id_list if not i.isdigit()]
            
            q_objects = Q()
            if numeric_ids:
                q_objects |= Q(id__in=numeric_ids)
            if names:
                q_objects |= Q(name__in=names)
            
            departments = Department.objects.filter(q_objects)
        else:
            departments = Department.objects.all()
        serializer = DepartmentSerializer(departments, many=True)
        return Response(serializer.data)
    
    elif request.method == 'POST':
        serializer = DepartmentSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'DELETE'])
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
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
def get_monthly_roster(request):
    month_str = request.query_params.get('month') # expected format YYYY-MM
    department = request.query_params.get('department') # Optional

    if not month_str:
        return Response({"error": "Month parameter (YYYY-MM) is required"}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        year, month = map(int, month_str.split('-'))
    except ValueError:
        return Response({"error": "Invalid format. Use YYYY-MM"}, status=status.HTTP_400_BAD_REQUEST)

    import calendar
    from datetime import date
    
    _, last_day = calendar.monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)

    from ..models import EmployeeShiftSchedule
    from ..serializers import EmployeeShiftScheduleSerializer

    # Initialize query
    schedules = EmployeeShiftSchedule.objects.filter(date__gte=start_date, date__lte=end_date)

    # Filter by Department if provided
    if department and department != 'All':
        try:
            mongo_uri = os.environ.get("GLOBAL_DB_HOST")
            db_name = os.environ.get("GLOBAL_DB_NAME", "Global")
            client = MongoClient(mongo_uri)
            db = client[db_name]

            raw_ids = [d.strip() for d in department.split(',')]
            
            # Resolve numeric IDs to names
            from ..models import Department
            numeric_ids = [rid for rid in raw_ids if rid.isdigit()]
            resolved_names = list(Department.objects.filter(id__in=numeric_ids).values_list('name', flat=True))
            
            # Important: Add the names from raw_ids if they aren't numeric
            all_names = resolved_names + [rid for rid in raw_ids if not rid.isdigit()]

            # 1. Resolve Names to Codes via Mongo
            dept_col = db['backend_diagnostics_Departments']
            resolved_codes = list(dept_col.find(
                {"department_name": {"$in": all_names}},
                {"department_code": 1}
            ))
            codes = [c.get("department_code") for c in resolved_codes]

            # Combine names, codes, and IDs for the profile search
            search_values = all_names + codes + raw_ids
            print(f"DEBUG: Roster Filtering - Department Filter: {department}")
            print(f"DEBUG: Roster Filtering - Resolved Names: {all_names}")
            print(f"DEBUG: Roster Filtering - Resolved Codes: {codes}")
            print(f"DEBUG: Roster Filtering - Search Values: {search_values}")

            # 2. Get Employees in these Depts
            profiles = list(db['backend_diagnostics_profile'].find({
                "$or": [
                    {"department": {"$in": search_values}},
                    {"department_id": {"$in": search_values}},
                    {"department_name": {"$in": search_values}}
                ]
            }))
            employee_ids = [str(p.get("employeeId")) for p in profiles]
            print(f"DEBUG: Roster Filtering - Found {len(employee_ids)} Employees: {employee_ids}")
            
            # Filter Schedules
            schedules = schedules.filter(employee_id__in=employee_ids)
            print(f"DEBUG: Roster Filtering - Resulting Schedule Count: {schedules.count()}")

        except Exception as e:
            print(f"Error filtering roster by department: {e}")
            # Fallback (don't fail entire request, just log error)

    serializer = EmployeeShiftScheduleSerializer(schedules, many=True)
    return Response(serializer.data)

@api_view(['POST'])
def assign_shift(request):
    from ..models import EmployeeShiftSchedule, Employee, Shift
    from ..serializers import EmployeeShiftScheduleSerializer
    
    if isinstance(request.data, list):
        for item in request.data:
            employee_id = item.get('employee_id')
            shift_id = item.get('shift_id')
            date = item.get('date')

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
                    EmployeeShiftSchedule.objects.update_or_create(
                        employee=employee,
                        date=date,
                        defaults={'shift': Shift.objects.get(id=shift_id)}
                    )
            except Exception as e:
                return Response({"error": f"Error with employee {employee_id}: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"message": "Bulk assignment successful"}, status=status.HTTP_200_OK)

    employee_id = request.data.get('employee_id')
    name = request.data.get('name', employee_id)
    shift_id = request.data.get('shift_id')
    date = request.data.get('date')

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

        schedule, created = EmployeeShiftSchedule.objects.update_or_create(
            employee=employee,
            date=date,
            defaults={'shift': Shift.objects.get(id=shift_id)}
        )
        serializer = EmployeeShiftScheduleSerializer(schedule)
        return Response(serializer.data, status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

