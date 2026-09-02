import os
from datetime import datetime, timezone, timedelta
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient, DESCENDING
from bson import ObjectId

from employees.decorators import token_required
from employees.views.common.utils import get_mongo_client
from employees.views.mobile_app.notifications import create_in_app_notification, send_expo_push_notification

try:
    import zoneinfo
    IST = zoneinfo.ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))

HELP_CATEGORIES = [
    {
        "id": "id_card",
        "name": "ID Card Reissue",
        "icon": "🪪",
        "description": "Lost, damaged, or update details on ID card",
        "sla_days": 2
    },
    {
        "id": "uniform",
        "name": "Uniform & Scrubs",
        "icon": "👔",
        "description": "New issue, replacement, or size exchange",
        "sla_days": 3
    },
    {
        "id": "salary",
        "name": "Salary & Payslip Query",
        "icon": "💰",
        "description": "Salary breakdown, deductions, or OT clarification",
        "sla_days": 2
    },
    {
        "id": "certificate",
        "name": "Letter & Certificate",
        "icon": "📄",
        "description": "Experience letter, Bonafide, or Salary certificate",
        "sla_days": 2
    },
    {
        "id": "grievance",
        "name": "Workplace Grievance",
        "icon": "⚖️",
        "description": "Workplace concerns, shift issues, or facility requests",
        "sla_days": 3
    },
    {
        "id": "other",
        "name": "General HR Inquiry",
        "icon": "💡",
        "description": "General questions or policy inquiries",
        "sla_days": 2
    }
]


def get_helpdesk_collection():
    client = get_mongo_client()
    db_name = os.environ.get('HR_DB_NAME', 'HR')
    return client[db_name]['employees_helpdesk_tickets']


def generate_ticket_id(col):
    """Generate sequential ticket ID like TICK-1001, TICK-1002"""
    last_ticket = col.find_one({}, sort=[("ticket_sequence", DESCENDING)])
    next_seq = 1001
    if last_ticket and last_ticket.get('ticket_sequence'):
        try:
            next_seq = int(last_ticket['ticket_sequence']) + 1
        except Exception:
            next_seq = col.count_documents({}) + 1001
    return f"TICK-{next_seq}", next_seq


@api_view(['GET'])
@permission_classes([AllowAny])
def get_helpdesk_categories(request):
    """Return list of supported helpdesk categories with SLAs"""
    return Response({
        "categories": HELP_CATEGORIES
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_helpdesk_tickets(request):
    """
    Fetch tickets.
    If employee_id query param is supplied, filters for that employee (for mobile app).
    Otherwise returns all tickets with optional status, category, priority, and department filters (for Admin).
    """
    try:
        col = get_helpdesk_collection()
        query = {}

        emp_id = request.GET.get('employee_id')
        status_filter = request.GET.get('status')
        category_filter = request.GET.get('category')
        priority_filter = request.GET.get('priority')
        department_filter = request.GET.get('department')
        search = request.GET.get('search', '').strip().lower()

        if emp_id:
            emp_match = [str(emp_id).strip()]
            if str(emp_id).isdigit():
                emp_match.append(int(emp_id))
            query["employee_id"] = {"$in": emp_match}

        if status_filter and status_filter != 'All':
            query["status"] = status_filter

        if category_filter and category_filter != 'All':
            query["category"] = category_filter

        if priority_filter and priority_filter != 'All':
            query["priority"] = priority_filter

        if department_filter and department_filter != 'All':
            query["department"] = {"$regex": department_filter, "$options": "i"}

        if search:
            query["$or"] = [
                {"ticket_id": {"$regex": search, "$options": "i"}},
                {"title": {"$regex": search, "$options": "i"}},
                {"employee_name": {"$regex": search, "$options": "i"}},
                {"employee_id": {"$regex": search, "$options": "i"}},
                {"description": {"$regex": search, "$options": "i"}},
            ]

        # Fetch tickets
        docs = list(col.find(query).sort([("created_at_ts", DESCENDING)]).limit(300))

        tickets = []
        for d in docs:
            tickets.append({
                "id": str(d.get('_id')),
                "ticket_id": d.get('ticket_id', f"TICK-{d.get('ticket_sequence', 1000)}"),
                "employee_id": str(d.get('employee_id', '')),
                "employee_name": d.get('employee_name', 'Employee'),
                "department": d.get('department', 'General'),
                "designation": d.get('designation', ''),
                "category": d.get('category', 'general'),
                "category_name": d.get('category_name', d.get('category', 'General')),
                "category_icon": d.get('category_icon', '🎫'),
                "title": d.get('title', ''),
                "description": d.get('description', ''),
                "priority": d.get('priority', 'Medium'),
                "status": d.get('status', 'Open'),
                "attachment_url": d.get('attachment_url', ''),
                "admin_response": d.get('admin_response', ''),
                "resolved_by": d.get('resolved_by', ''),
                "resolved_at": d.get('resolved_at', ''),
                "created_at": d.get('created_at', ''),
                "updated_at": d.get('updated_at', ''),
            })

        # Calculate counts for quick stats
        all_emp_query = {}
        if emp_id:
            emp_match = [str(emp_id).strip()]
            if str(emp_id).isdigit():
                emp_match.append(int(emp_id))
            all_emp_query["employee_id"] = {"$in": emp_match}

        total_count = col.count_documents(all_emp_query)
        open_count = col.count_documents({**all_emp_query, "status": "Open"})
        in_progress_count = col.count_documents({**all_emp_query, "status": "In Progress"})
        resolved_count = col.count_documents({**all_emp_query, "status": {"$in": ["Resolved", "Closed"]}})
        urgent_count = col.count_documents({**all_emp_query, "priority": "Urgent", "status": {"$in": ["Open", "In Progress"]}})

        return Response({
            "tickets": tickets,
            "stats": {
                "total": total_count,
                "open": open_count,
                "in_progress": in_progress_count,
                "resolved": resolved_count,
                "urgent": urgent_count
            }
        }, status=status.HTTP_200_OK)
    except Exception as e:
        print("Error fetching helpdesk tickets:", e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def create_helpdesk_ticket(request):
    """Create a new helpdesk ticket from Employee Mobile App or Web"""
    try:
        col = get_helpdesk_collection()
        data = request.data

        emp_id = str(data.get('employee_id') or getattr(request, 'authenticated_employee_id', '') or '').strip()
        title = (data.get('title') or '').strip()
        description = (data.get('description') or '').strip()
        category = data.get('category', 'other')
        priority = data.get('priority', 'Medium')
        attachment_url = data.get('attachment_url', '')

        if not emp_id or not title or not description:
            return Response(
                {"error": "employee_id, title, and description are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Lookup employee profile to attach details
        client = get_mongo_client()
        global_db = client[os.environ.get('GLOBAL_DB_NAME', 'Global')]
        emp_profile = global_db['backend_diagnostics_profile'].find_one(
            {"employeeId": str(emp_id)},
            {"employeeName": 1, "department": 1, "designation": 1, "_id": 0}
        )

        emp_name = data.get('employee_name') or (emp_profile.get('employeeName') if emp_profile else emp_id)
        emp_dept = data.get('department') or (emp_profile.get('department') if emp_profile else 'General')
        emp_desig = data.get('designation') or (emp_profile.get('designation') if emp_profile else '')

        # Resolve category metadata
        cat_info = next((c for c in HELP_CATEGORIES if c['id'] == category), None)
        category_name = cat_info['name'] if cat_info else category.replace('_', ' ').title()
        category_icon = cat_info['icon'] if cat_info else '🎫'

        ticket_id_str, seq_num = generate_ticket_id(col)
        now_dt = datetime.now(IST)
        created_str = now_dt.strftime('%d %b %Y, %I:%M %p')

        ticket_doc = {
            "ticket_id": ticket_id_str,
            "ticket_sequence": seq_num,
            "employee_id": str(emp_id),
            "employee_name": emp_name,
            "department": str(emp_dept),
            "designation": str(emp_desig),
            "category": category,
            "category_name": category_name,
            "category_icon": category_icon,
            "title": title,
            "description": description,
            "priority": priority,
            "status": "Open",
            "attachment_url": attachment_url,
            "admin_response": "",
            "resolved_by": "",
            "resolved_at": "",
            "created_at": created_str,
            "created_at_ts": now_dt.timestamp(),
            "updated_at": created_str,
            "updated_at_ts": now_dt.timestamp(),
        }

        result = col.insert_one(ticket_doc)

        # Notify employee that ticket is received
        try:
            create_in_app_notification(
                employee_id=str(emp_id),
                title=f"Ticket #{ticket_id_str} Submitted 🎫",
                message=f"Your request for '{title}' has been submitted to HR. We'll update you shortly.",
                category="helpdesk",
                action_url="helpdesk"
            )
        except Exception as notif_err:
            print("Notice: could not emit notification:", notif_err)

        return Response({
            "success": True,
            "message": "Ticket created successfully",
            "ticket_id": ticket_id_str,
            "id": str(result.inserted_id)
        }, status=status.HTTP_201_CREATED)

    except Exception as e:
        print("Error creating helpdesk ticket:", e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['PUT', 'POST'])
@permission_classes([AllowAny])
def update_helpdesk_ticket(request, ticket_id):
    """
    Update ticket status and response from HR Admin.
    Can match by MongoDB ObjectId or ticket_id (e.g. TICK-1001).
    """
    try:
        col = get_helpdesk_collection()
        data = request.data

        # Search by ticket_id or _id
        query = {"ticket_id": ticket_id}
        if ObjectId.is_valid(ticket_id):
            query = {"$or": [{"ticket_id": ticket_id}, {"_id": ObjectId(ticket_id)}]}

        existing = col.find_one(query)
        if not existing:
            return Response({"error": f"Ticket '{ticket_id}' not found"}, status=status.HTTP_404_NOT_FOUND)

        now_dt = datetime.now(IST)
        updated_str = now_dt.strftime('%d %b %Y, %I:%M %p')

        new_status = data.get('status', existing.get('status', 'Open'))
        admin_response = data.get('admin_response', existing.get('admin_response', ''))
        resolved_by = data.get('resolved_by', 'HR Administrator')
        priority = data.get('priority', existing.get('priority', 'Medium'))

        update_fields = {
            "status": new_status,
            "admin_response": admin_response,
            "priority": priority,
            "updated_at": updated_str,
            "updated_at_ts": now_dt.timestamp(),
        }

        if new_status in ['Resolved', 'Closed', 'Rejected']:
            update_fields["resolved_by"] = resolved_by
            update_fields["resolved_at"] = updated_str

        col.update_one(query, {"$set": update_fields})

        # Send notification to the employee about the status change
        emp_id = existing.get('employee_id')
        t_id = existing.get('ticket_id')
        t_title = existing.get('title', 'Helpdesk Ticket')

        status_emojis = {
            "In Progress": "🔄 In Progress",
            "Resolved": "✅ Resolved",
            "Closed": "🔒 Closed",
            "Rejected": "❌ Rejected",
            "Open": "📬 Open"
        }
        status_label = status_emojis.get(new_status, new_status)

        notif_msg = f"Ticket #{t_id} status updated to {status_label}."
        if admin_response:
            notif_msg += f" HR Note: {admin_response[:80]}..." if len(admin_response) > 80 else f" HR Note: {admin_response}"

        try:
            create_in_app_notification(
                employee_id=str(emp_id),
                title=f"Ticket #{t_id} {status_label}",
                message=notif_msg,
                category="helpdesk",
                action_url="helpdesk"
            )
            send_expo_push_notification(
                employee_ids=[str(emp_id)],
                title=f"HR Helpdesk: #{t_id} {status_label}",
                body=notif_msg,
                data={"type": "helpdesk", "ticket_id": t_id}
            )
        except Exception as notif_err:
            print("Notice: could not push ticket update notification:", notif_err)

        return Response({
            "success": True,
            "message": f"Ticket #{t_id} updated successfully to '{new_status}'",
            "ticket_id": t_id,
            "status": new_status
        }, status=status.HTTP_200_OK)

    except Exception as e:
        print("Error updating helpdesk ticket:", e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
