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
    db_name = os.environ.get("GLOBAL_DB_NAME", "Global")
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
        docs = list(col.find({"employee_id": str(emp_id)}).sort("created_at_ts", -1))

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
            "employee_id": emp_id,
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
            res = col.update_many({"employee_id": str(emp_id), "is_read": False}, {"$set": {"is_read": True}})
            return Response({"message": "All notifications marked as read", "updated_count": res.modified_count})

        if notification_id:
            from bson import ObjectId
            query = {"employee_id": str(emp_id)}
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
            res = col.delete_many({"employee_id": str(emp_id)})
            return Response({"message": "All notifications cleared", "deleted_count": res.deleted_count})

        if notification_id:
            from bson import ObjectId
            query = {"employee_id": str(emp_id)}
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
        count = col.count_documents({"employee_id": str(emp_id), "is_read": False})
        return Response({"employee_id": emp_id, "unread_count": count})
    except Exception as e:
        return Response({"unread_count": 0})
