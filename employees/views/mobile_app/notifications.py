from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
import os
from datetime import datetime
from ..utils import get_mongo_client

from employees.decorators import token_required

def get_notifications_collection():
    client = get_mongo_client()
    db_name = os.environ.get("HR_DB_NAME", "HR")
    db = client[db_name]
    return db['employees_notification']


@api_view(['GET'])
@permission_classes([AllowAny])
@token_required
def get_employee_notifications(request):
    emp_id = getattr(request, 'authenticated_employee_id', None) or request.query_params.get('employee_id')

    if not emp_id:
        return Response({"error": "employee_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        col = get_notifications_collection()
        emp_match = [str(emp_id)]
        if str(emp_id).isdigit():
            emp_match.append(int(emp_id))

        docs = list(col.find({"employee_id": {"$in": emp_match}}).sort([("_id", -1)]))

        data = []
        unread_count = 0
        for doc in docs:
            if not doc.get('is_read', False):
                unread_count += 1
            data.append({
                "id": str(doc.get('_id')),
                "title": doc.get('title', ''),
                "message": doc.get('message', ''),
                "category": doc.get('category', 'general'),
                "is_read": doc.get('is_read', False),
                "action_url": doc.get('action_url', ''),
                "created_at": doc.get('created_at', ''),
            })

        return Response({
            "employee_id": str(emp_id),
            "unread_count": unread_count,
            "notifications": data
        })
    except Exception as e:
        print("Error fetching notifications via PyMongo", e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
@token_required
def mark_notifications_read(request):
    emp_id = getattr(request, 'authenticated_employee_id', None) or request.data.get('employee_id')
    notification_id = request.data.get('notification_id')
    mark_all = request.data.get('mark_all', False)

    if not emp_id:
        return Response({"error": "employee_id is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        col = get_notifications_collection()
        if mark_all:
            emp_match = [str(emp_id)]
            if str(emp_id).isdigit(): emp_match.append(int(emp_id))
            res = col.update_many({"employee_id": {"$in": emp_match}, "is_read": False}, {"$set": {"is_read": True}})
            return Response({"message": "All notifications marked as read", "updated_count": res.modified_count})

        if notification_id:
            from bson import ObjectId
            query = {}
            try:
                query["_id"] = ObjectId(notification_id)
            except Exception:
                query["_id"] = notification_id

            col.update_one(query, {"$set": {"is_read": True}})
            return Response({"message": "Notification marked as read", "notification_id": notification_id})

        return Response({"error": "Either notification_id or mark_all parameter is required"}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
@token_required
def clear_notifications(request):
    emp_id = getattr(request, 'authenticated_employee_id', None) or request.data.get('employee_id')
    notification_id = request.data.get('notification_id')
    clear_all = request.data.get('clear_all', False)

    if not emp_id:
        return Response({"error": "employee_id is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        col = get_notifications_collection()
        if clear_all:
            emp_match = [str(emp_id)]
            if str(emp_id).isdigit(): emp_match.append(int(emp_id))
            res = col.delete_many({"employee_id": {"$in": emp_match}})
            return Response({"message": "All notifications cleared", "deleted_count": res.deleted_count})

        if notification_id:
            from bson import ObjectId
            query = {}
            try:
                query["_id"] = ObjectId(notification_id)
            except Exception:
                query["_id"] = notification_id

            col.delete_one(query)
            return Response({"message": "Notification cleared", "notification_id": notification_id})

        return Response({"error": "Either notification_id or clear_all parameter is required"}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
@token_required
def get_unread_count(request):
    emp_id = getattr(request, 'authenticated_employee_id', None) or request.query_params.get('employee_id')

    if not emp_id:
        return Response({"error": "employee_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        col = get_notifications_collection()
        emp_match = [str(emp_id)]
        if str(emp_id).isdigit(): emp_match.append(int(emp_id))

        count = col.count_documents({"employee_id": {"$in": emp_match}, "is_read": False})
        return Response({"employee_id": str(emp_id), "unread_count": count})
    except Exception as e:
        return Response({"unread_count": 0})


@api_view(['POST'])
@permission_classes([AllowAny])
@token_required
def send_admin_notification(request):
    """
    Admin Broadcast Notification API: Sends targeted or broadcast notifications
    to all employees, specific department, or single employee.
    """
    target_type = request.data.get('target_type', 'all')  # 'all', 'department', 'employee'
    target_dept = request.data.get('department_name') or request.data.get('department')
    target_emp = request.data.get('employee_id')
    title = request.data.get('title')
    message = request.data.get('message')
    category = request.data.get('category', 'announcement')

    if not title or not message:
        return Response({"error": "Title and Message are required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        col = get_notifications_collection()
        now_dt = datetime.now()
        now_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')
        now_ts = now_dt.timestamp()

        emp_ids = []

        if target_type == 'employee':
            if not target_emp:
                return Response({"error": "Target employee_id is required"}, status=status.HTTP_400_BAD_REQUEST)
            emp_ids = [str(target_emp)]

        elif target_type == 'department':
            if not target_dept:
                return Response({"error": "Target department is required"}, status=status.HTTP_400_BAD_REQUEST)
            from employees.models import Register
            users = Register.objects.filter(department__icontains=target_dept).values_list('employee_id', flat=True)
            emp_ids = [str(eid) for eid in users if eid]

        else:  # 'all'
            from employees.models import Register
            users = Register.objects.all().values_list('employee_id', flat=True)
            emp_ids = [str(eid) for eid in users if eid]

        if not emp_ids:
            return Response({"error": "No matching employees found for target selection"}, status=status.HTTP_404_NOT_FOUND)

        documents = []
        for eid in set(emp_ids):
            documents.append({
                "employee_id": str(eid),
                "title": title,
                "message": message,
                "category": category,
                "is_read": False,
                "action_url": "",
                "created_at": now_str,
                "created_at_ts": now_ts,
                "sent_by": request.data.get('sent_by', 'Admin')
            })

        if documents:
            col.insert_many(documents)

        return Response({
            "success": True,
            "message": f"Notification successfully sent to {len(documents)} employee(s).",
            "sent_count": len(documents)
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        print("Error sending admin notification", e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
