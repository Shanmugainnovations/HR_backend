from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
import os
from datetime import datetime
from ..utils import get_mongo_client

def get_notifications_collection():
    client = get_mongo_client()
    db_name = os.environ.get("GLOBAL_DB_NAME", "Global")
    db = client[db_name]
    return db['employees_notification']

@api_view(['GET'])
@permission_classes([AllowAny])
def get_employee_notifications(request):
    emp_id = request.query_params.get('employee_id')
    if not emp_id:
        return Response({"error": "employee_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        col = get_notifications_collection()
        docs = list(col.find({"employee_id": str(emp_id)}).sort("created_at_ts", -1))

        # Seed sample notifications if empty
        if not docs:
            now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            now_ts = datetime.now().timestamp()
            sample_alerts = [
              {
                "employee_id": str(emp_id),
                "title": "Shift Schedule Updated 📅",
                "message": "Your duty roster for this month has been published. Check your assigned shifts.",
                "category": "shift",
                "is_read": False,
                "created_at": now_str,
                "created_at_ts": now_ts,
              },
              {
                "employee_id": str(emp_id),
                "title": "Tea Token Issued ☕",
                "message": "Your daily tea token voucher was generated successfully at OPD Canteen.",
                "category": "canteen",
                "is_read": False,
                "created_at": now_str,
                "created_at_ts": now_ts - 3600,
              },
              {
                "employee_id": str(emp_id),
                "title": "Leave Request Approved ✅",
                "message": "Your recent leave request for Casual Leave has been reviewed and approved.",
                "category": "leave",
                "is_read": True,
                "created_at": now_str,
                "created_at_ts": now_ts - 86400,
              },
              {
                "employee_id": str(emp_id),
                "title": "Welcome to Shanmuga HR 📢",
                "message": "Access your attendance, leaves, duty roster, and tea tokens directly from your mobile app.",
                "category": "announcement",
                "is_read": True,
                "created_at": now_str,
                "created_at_ts": now_ts - 172800,
              }
            ]
            col.insert_many(sample_alerts)
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
def mark_notifications_read(request):
    emp_id = request.data.get('employee_id')
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

@api_view(['GET'])
@permission_classes([AllowAny])
def get_unread_count(request):
    emp_id = request.query_params.get('employee_id')
    if not emp_id:
        return Response({"error": "employee_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        col = get_notifications_collection()
        count = col.count_documents({"employee_id": str(emp_id), "is_read": False})
        return Response({"employee_id": emp_id, "unread_count": count})
    except Exception as e:
        return Response({"unread_count": 0})
