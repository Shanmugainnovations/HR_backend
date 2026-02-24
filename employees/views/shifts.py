from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from ..models import Shift, Department
from ..serializers import ShiftSerializer, DepartmentSerializer
import os
from pymongo import MongoClient

@api_view(['GET', 'POST'])
def shift_list_create(request):
    if request.method == 'GET':
        department = request.query_params.get('department')
        if department and department != 'All':
            # Assuming Department Name is passed. 
            # Note: Department model name field is `name`.
            # If backend uses codes, we might need mapping, but Department model seems to stick to names here.
            shifts = Shift.objects.filter(departments__name=department)
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
        dept_name = request.query_params.get('department')
        if dept_name and dept_name != 'All':
            departments = Department.objects.filter(name=dept_name)
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

            # 1. Get Dept Code
            dept_doc = db['backend_diagnostics_Departments'].find_one({"department_name": department})
            if dept_doc:
                dept_code = dept_doc.get("department_code")
                # 2. Get Employees in Dept
                profiles = db['backend_diagnostics_profile'].find({"department": dept_code})
                employee_ids = [str(p.get("employeeId")) for p in profiles]
                
                # Filter Schedules
                schedules = schedules.filter(employee_id__in=employee_ids)
            else:
                 # If department name not found directly, maybe code was passed? Or invalid.
                 # Try filtering by assuming `department` param IS the code
                 profiles = db['backend_diagnostics_profile'].find({"department": department})
                 employee_ids = [str(p.get("employeeId")) for p in profiles]
                 if employee_ids:
                    schedules = schedules.filter(employee_id__in=employee_ids)
                 else:
                    return Response([], status=200) # No match

        except Exception as e:
            print(f"Error filtering roster by department: {e}")
            # Fallback (don't fail entire request, just log error)

    serializer = EmployeeShiftScheduleSerializer(schedules, many=True)
    return Response(serializer.data)

@api_view(['POST'])
def assign_shift(request):
    from ..models import EmployeeShiftSchedule, Employee, Shift
    from ..serializers import EmployeeShiftScheduleSerializer
    
    employee_id = request.data.get('employee_id')
    shift_id = request.data.get('shift_id')
    date = request.data.get('date')

    if not employee_id or not date:
         return Response({"error": "employee_id and date are required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        # If shift_id is None or empty, delete the assignment (Clear/Off)
        if not shift_id:
            EmployeeShiftSchedule.objects.filter(employee_id=employee_id, date=date).delete()
            return Response({"message": "Shift assignment cleared"}, status=status.HTTP_200_OK)

        # Otherwise update or create
        schedule, created = EmployeeShiftSchedule.objects.update_or_create(
            employee_id=employee_id,
            date=date,
            defaults={'shift_id': shift_id}
        )
        serializer = EmployeeShiftScheduleSerializer(schedule)
        return Response(serializer.data, status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

