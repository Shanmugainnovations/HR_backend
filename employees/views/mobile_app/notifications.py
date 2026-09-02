from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
import os
from datetime import datetime
from employees.views.common.utils import get_mongo_client

from employees.decorators import token_required

def get_notifications_collection():
    client = get_mongo_client()
    db_name = os.environ.get("HR_DB_NAME", "HR")
    db = client[db_name]
    return db['employees_notification']


def create_in_app_notification(employee_id, title, message, category='general', action_url=''):
    """Helper to insert an in-app notification for a given employee"""
    try:
        col = get_notifications_collection()
        now_dt = datetime.now()
        doc = {
            "employee_id": str(employee_id),
            "title": title,
            "message": message,
            "category": category,
            "is_read": False,
            "action_url": action_url,
            "created_at": now_dt.strftime('%Y-%m-%d %H:%M:%S'),
            "created_at_ts": now_dt.timestamp()
        }
        return col.insert_one(doc)
    except Exception as e:
        print("Error creating in-app notification:", e)
        return None


def send_expo_push_notification(employee_ids, title, body, data=None):
    """
    Sends real-time Expo system push notifications to mobile devices via Expo HTTP Push API.
    """
    if isinstance(employee_ids, (str, int)):
        employee_ids = [str(employee_ids)]
    else:
        employee_ids = [str(eid) for eid in employee_ids if eid]

    if not employee_ids:
        return

    try:
        import requests
        col = get_notifications_collection().database['employees_push_tokens']
        
        emp_matches = []
        for eid in employee_ids:
            emp_matches.append(str(eid))
            if str(eid).isdigit():
                emp_matches.append(int(eid))

        tokens_docs = list(col.find({"employee_id": {"$in": emp_matches}}, {"push_token": 1}))
        push_tokens = list(set([doc['push_token'] for doc in tokens_docs if doc.get('push_token')]))

        if not push_tokens:
            print(f"No active Expo push tokens found for employees {employee_ids}")
            return

        messages = []
        for token in push_tokens:
            messages.append({
                "to": token,
                "sound": "default",
                "title": title,
                "body": body,
                "data": data or {},
                "badge": 1
            })

        response = requests.post(
            "https://exp.host/--/api/v2/push/send",
            json=messages,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip, deflate",
                "Content-Type": "application/json",
            },
            timeout=8
        )
        print(f"Expo push notification sent to {len(push_tokens)} token(s). Status: {response.status_code}")
    except Exception as err:
        print("Error sending Expo push notification:", err)


@api_view(['POST'])
@permission_classes([AllowAny])
@token_required
def register_push_token(request):
    emp_id = getattr(request, 'authenticated_employee_id', None) or request.data.get('employee_id')
    push_token = request.data.get('push_token')
    platform_name = request.data.get('platform', 'android')
    device_name = request.data.get('device_name', '')

    if not emp_id or not push_token:
        return Response({"error": "employee_id and push_token are required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        col = get_notifications_collection().database['employees_push_tokens']
        now_dt = datetime.now()

        col.update_one(
            {"employee_id": str(emp_id), "push_token": push_token},
            {"$set": {
                "employee_id": str(emp_id),
                "push_token": push_token,
                "platform": platform_name,
                "device_name": device_name,
                "updated_at": now_dt.strftime('%Y-%m-%d %H:%M:%S'),
                "updated_at_ts": now_dt.timestamp()
            }},
            upsert=True
        )
        return Response({"success": True, "message": "Push token registered successfully"})
    except Exception as e:
        print("Error registering push token:", e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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

        is_popup = request.data.get('is_popup', False)
        documents = []
        for eid in set(emp_ids):
            documents.append({
                "employee_id": str(eid),
                "title": title,
                "message": message,
                "category": category,
                "is_read": False,
                "is_popup": bool(is_popup),
                "action_url": "",
                "created_at": now_str,
                "created_at_ts": now_ts,
                "sent_by": request.data.get('sent_by', 'Admin')
            })

        if documents:
            col.insert_many(documents)

        # Trigger real-time mobile push notifications
        try:
            send_expo_push_notification(emp_ids, title, message, {"category": category})
        except Exception as push_err:
            print("Failed to dispatch push notification", push_err)

        return Response({
            "success": True,
            "message": f"Notification successfully sent to {len(documents)} employee(s).",
            "sent_count": len(documents)
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        print("Error sending admin notification", e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([AllowAny])
@token_required
def get_active_popup_announcement(request):
    """
    Returns the latest unread Flash News / Emergency Announcement popup targeting this employee.
    """
    emp_id = getattr(request, 'authenticated_employee_id', None) or request.query_params.get('employee_id')

    if not emp_id:
        return Response({"error": "employee_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        col = get_notifications_collection()
        emp_match = [str(emp_id)]
        if str(emp_id).isdigit():
            emp_match.append(int(emp_id))

        doc = col.find_one(
            {"employee_id": {"$in": emp_match}, "is_popup": True, "is_read": False},
            sort=[("_id", -1)]
        )

        if not doc:
            return Response({"active_popup": None})

        return Response({
            "active_popup": {
                "id": str(doc.get('_id')),
                "title": doc.get('title', ''),
                "message": doc.get('message', ''),
                "category": doc.get('category', 'announcement'),
                "created_at": doc.get('created_at', ''),
                "sent_by": doc.get('sent_by', 'Admin')
            }
        })
    except Exception as e:
        print("Error fetching active popup announcement", e)
        return Response({"active_popup": None})

