from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from employees.models import LeaveRequest, LeaveType
from employees.decorators import token_required
import datetime

def get_leave_type_name(lt):
    if not lt:
        return "Casual Leave"
    if hasattr(lt, 'name'):
        return lt.name
    return str(lt)

@api_view(['POST'])
@permission_classes([AllowAny])
@token_required
def apply_leave(request):

    try:
        data = request.data
        employee_id = data.get('employee_id')
        start_date = data.get('start_date') or data.get('from_date')
        end_date = data.get('end_date') or data.get('to_date')
        leave_type_input = data.get('leave_type')
        reason = data.get('reason', '')

        if not employee_id or not start_date or not end_date:
            return Response({"error": "employee_id, start_date, and end_date are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Resolve LeaveType model
        leave_type_obj = None
        if leave_type_input:
            if str(leave_type_input).isdigit():
                leave_type_obj = LeaveType.objects.filter(id=int(leave_type_input)).first()
            if not leave_type_obj:
                leave_type_obj = LeaveType.objects.filter(name__iexact=str(leave_type_input)).first()
        
        if not leave_type_obj:
            # Create or get fallback leave type
            name = str(leave_type_input) if leave_type_input else "Casual Leave"
            leave_type_obj, _ = LeaveType.objects.get_or_create(name=name)


        leave_type_str = leave_type_obj.name if hasattr(leave_type_obj, 'name') else str(leave_type_obj)

        leave = LeaveRequest(
            employee_id=employee_id,
            employee_name=data.get('employee_name', 'Employee'),
            department=data.get('department', 'General'),
            department_id=data.get('department_id', 1),
            start_date=start_date,
            end_date=end_date,
            leave_type=leave_type_str,
            reason=reason,
            status='Pending'
        )
        leave.save_with_audit(request)


        return Response({
            "message": "Leave request submitted successfully",
            "id": leave.id,
            "status": leave.status
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
@token_required
def my_leaves(request):

    try:
        employee_id = request.GET.get('employee_id')
        if not employee_id:
            return Response({"error": "employee_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        leaves = LeaveRequest.objects.filter(employee_id=employee_id).order_by('-applied_on')
        data = []
        for l in leaves:
            data.append({
                "id": l.id,
                "start_date": l.start_date.strftime('%Y-%m-%d') if l.start_date else None,
                "end_date": l.end_date.strftime('%Y-%m-%d') if l.end_date else None,
                "leave_type": get_leave_type_name(l.leave_type),
                "reason": l.reason,
                "status": l.status,
                "applied_on": l.applied_on.strftime('%Y-%m-%d %H:%M') if l.applied_on else None,
                "admin_remarks": getattr(l, 'admin_remarks', '')
            })

        return Response(data, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
@token_required
def pending_leaves(request):
    try:
        leaves = LeaveRequest.objects.filter(status='Pending').order_by('-applied_on')
        data = []
        for l in leaves:
            data.append({
                "id": l.id,
                "employee_id": l.employee_id,
                "employee_name": l.employee_name,
                "department": l.department,
                "start_date": l.start_date.strftime('%Y-%m-%d') if l.start_date else None,
                "end_date": l.end_date.strftime('%Y-%m-%d') if l.end_date else None,
                "leave_type": get_leave_type_name(l.leave_type),
                "reason": l.reason,
                "status": l.status,
                "applied_on": l.applied_on.strftime('%Y-%m-%d %H:%M') if l.applied_on else None
            })
        return Response(data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


from employees.decorators import token_required

@api_view(['PUT'])
@permission_classes([AllowAny])
@token_required
def update_leave_status(request, leave_id):
    try:
        leave = get_object_or_404(LeaveRequest, id=leave_id)
        new_status = request.data.get('status')
        remarks = request.data.get('admin_remarks', '')
        reviewer_name = request.data.get('reviewer_name', '')

        if new_status not in ['Approved', 'Rejected', 'Pending']:
            return Response({"error": "Invalid status value"}, status=status.HTTP_400_BAD_REQUEST)

        leave.status = new_status
        if hasattr(leave, 'admin_remarks'):
            leave.admin_remarks = remarks
        if reviewer_name and hasattr(leave, 'reviewed_by_name'):
            leave.reviewed_by_name = reviewer_name
        leave.save_with_audit(request)

        # Auto-create real-time notification for employee in MongoDB
        try:
            from .notifications import get_notifications_collection, send_expo_push_notification
            col = get_notifications_collection()
            now_dt = datetime.datetime.now()
            status_icon = "✅" if new_status == 'Approved' else "❌"
            title = f"Leave Request {new_status} {status_icon}"
            start_str = leave.start_date.strftime('%d %b %Y') if hasattr(leave.start_date, 'strftime') else str(leave.start_date)
            end_str = leave.end_date.strftime('%d %b %Y') if hasattr(leave.end_date, 'strftime') else str(leave.end_date)
            
            by_str = f" by {reviewer_name}" if reviewer_name else ""
            message = f"Your request for {leave.leave_type} ({start_str} to {end_str}) has been {new_status.lower()}{by_str}."

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
            send_expo_push_notification(leave.employee_id, title, message, {"category": "leave"})
            print(f"Successfully pushed leave notification for employee {leave.employee_id}")
        except Exception as notif_err:
            print("Error pushing leave notification", notif_err)


        return Response({"message": f"Leave status updated to {new_status}"}, status=status.HTTP_200_OK)

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
def leave_history(request):
    try:
        leaves = LeaveRequest.objects.exclude(status='Pending').order_by('-applied_on')
        data = []
        for l in leaves:
            data.append({
                "id": l.id,
                "employee_id": l.employee_id,
                "employee_name": l.employee_name,
                "department": l.department,
                "start_date": l.start_date.strftime('%Y-%m-%d') if l.start_date else None,
                "end_date": l.end_date.strftime('%Y-%m-%d') if l.end_date else None,
                "leave_type": get_leave_type_name(l.leave_type),
                "reason": l.reason,
                "status": l.status,
                "applied_on": l.applied_on.strftime('%Y-%m-%d %H:%M') if l.applied_on else None,
                "admin_remarks": getattr(l, 'admin_remarks', '')
            })
        return Response(data, status=status.HTTP_200_OK)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def leave_type_list_create(request):
    if request.method == 'GET':
        types = LeaveType.objects.filter(is_active__in=[True])
        data = [{
            "id": t.id,
            "name": t.name,
            "code": getattr(t, 'code', t.name[:3].upper()),
            "max_days_per_year": getattr(t, 'max_days_per_year', 12)
        } for t in types]
        return Response(data, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        name = request.data.get('name')
        code = request.data.get('code')
        max_days = request.data.get('max_days_per_year', 12)

        if not name:
            return Response({"error": "name is required"}, status=status.HTTP_400_BAD_REQUEST)

        create_kwargs = {'name': name}
        if hasattr(LeaveType, 'code') and code:
            create_kwargs['code'] = code
        if hasattr(LeaveType, 'max_days_per_year'):
            create_kwargs['max_days_per_year'] = max_days

        lt = LeaveType.objects.create(**create_kwargs)
        return Response({
            "id": lt.id,
            "name": lt.name,
            "code": getattr(lt, 'code', lt.name[:3].upper())
        }, status=status.HTTP_201_CREATED)


@api_view(['GET', 'PUT', 'DELETE'])
@permission_classes([AllowAny])
def leave_type_detail(request, pk):
    lt = get_object_or_404(LeaveType, id=pk)

    if request.method == 'GET':
        return Response({
            "id": lt.id,
            "name": lt.name,
            "code": getattr(lt, 'code', lt.name[:3].upper()),
            "max_days_per_year": getattr(lt, 'max_days_per_year', 12)
        }, status=status.HTTP_200_OK)

    elif request.method == 'PUT':
        lt.name = request.data.get('name', lt.name)
        if hasattr(lt, 'code'):
            lt.code = request.data.get('code', getattr(lt, 'code', ''))
        if hasattr(lt, 'max_days_per_year'):
            lt.max_days_per_year = request.data.get('max_days_per_year', getattr(lt, 'max_days_per_year', 12))
        lt.save()
        return Response({
            "id": lt.id,
            "name": lt.name,
            "code": getattr(lt, 'code', lt.name[:3].upper())
        }, status=status.HTTP_200_OK)

    elif request.method == 'DELETE':
        lt.is_active = False
        lt.save()
        return Response({"message": "Leave type deleted"}, status=status.HTTP_200_OK)

