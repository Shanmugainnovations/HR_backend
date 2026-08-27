from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from employees.models import LeaveRequest, Employee, Shift, EmployeeShiftSchedule, LeaveType
from employees.serializers import LeaveTypeSerializer
from django.utils import timezone
from datetime import datetime, timedelta

from employees.decorators import token_required

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
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([AllowAny])
def leave_type_detail(request, pk):
    try:
        leave_type = LeaveType.objects.get(pk=pk)
    except LeaveType.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = LeaveTypeSerializer(leave_type)
        return Response(serializer.data)

    elif request.method == 'PUT':
        serializer = LeaveTypeSerializer(leave_type, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    elif request.method == 'DELETE':
        leave_type.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

@api_view(['POST'])
@permission_classes([AllowAny])
@token_required
def apply_leave(request):
    try:
        employee_id = getattr(request, 'authenticated_employee_id', None) or request.data.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee ID is required"}, status=400)
            
        LeaveRequest.objects.create(
            employee_id=employee_id,
            employee_name=request.data.get('employee_name'),
            department=request.data.get('department'),
            department_id=request.data.get('department_id'),
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
@token_required
def my_leaves(request):
    try:
        employee_id = getattr(request, 'authenticated_employee_id', None) or request.GET.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee ID is required"}, status=400)
            
        leaves = LeaveRequest.objects.filter(employee_id=employee_id).order_by('-applied_on')
        data = [{
            "id": l.id,
            "employee_name": l.employee_name,
            "department": l.department,
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
@token_required
def pending_leaves(request):
    try:
        department_id = request.GET.get('department_id')
        department = request.GET.get('department')
        
        leaves = LeaveRequest.objects.all().order_by('-applied_on')
        
        if department:
            leaves = leaves.filter(department=department)
        elif department_id:
            leaves = leaves.filter(department_id=department_id)
            
        data = [{
            "id": l.id,
            "employee_id": l.employee_id,
            "employee_name": l.employee_name,
            "department": l.department,
            "department_id": l.department_id,
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
@token_required
def leave_history(request):
    try:
        status_filter = request.GET.get('status')
        employee_name = request.GET.get('employee_name')
        department = request.GET.get('department')
        from_date = request.GET.get('from_date')
        to_date = request.GET.get('to_date')
        
        leaves = LeaveRequest.objects.exclude(status='Pending')
        
        if status_filter:
            leaves = leaves.filter(status=status_filter)
        if employee_name:
            leaves = leaves.filter(employee_name__icontains=employee_name)
        if department:
            leaves = leaves.filter(department__icontains=department)
        if from_date:
            leaves = leaves.filter(start_date__gte=from_date)
        if to_date:
            leaves = leaves.filter(end_date__lte=to_date)
            
        leaves = leaves.order_by('-applied_on')
        
        data = [{
            "id": l.id,
            "employee_id": l.employee_id,
            "employee_name": l.employee_name,
            "department": l.department,
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
@token_required
def update_leave_status(request, leave_id):

    try:
        status_val = request.data.get('status')
        reviewer_name = request.data.get('reviewer_name')
        
        if status_val not in ['Approved', 'Rejected']:
            return Response({"error": "Invalid status"}, status=400)
            
        leave = LeaveRequest.objects.get(id=leave_id)
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

        # Auto-create real-time notification for the employee
        try:
            from .mobile_app.notifications import get_notifications_collection
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
