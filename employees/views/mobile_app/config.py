"""
Mobile App Remote Configuration & System Settings Service
Manages remote feature toggles, leave policies, and mobile app customizations
stored in MongoDB Global database under 'system_settings'.
"""
import os
from datetime import datetime
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from pymongo import MongoClient
from employees.permissions import HasRoleAndDataPermission

CONFIG_KEY = 'mobile_app_config'

DEFAULT_MOBILE_CONFIG = {
    # 🍃 Leave & Permission Policies
    'allow_past_date_leaves': True,
    'max_past_leave_days': 7,          # Allow selecting up to 7 previous days
    'allow_future_leaves': True,
    'max_future_leave_days': 60,       # Up to 60 days in advance
    'require_leave_reason': True,
    'allow_past_permissions': True,
    'max_past_permission_days': 2,

    # 📱 Mobile Module Feature Toggles
    'feature_canteen': True,
    'feature_payslips': True,
    'feature_helpdesk': True,
    'feature_id_card': True,
    'feature_duty_roster': True,
    'feature_birthdays': True,
    'feature_approver_hierarchy': True,

    # 🛡️ Approvals & Security Governance
    'incharge_can_final_approve': False, # Incharge only recommends to HOD
    'block_self_approval': True,         # HODs cannot approve their own leaves
    'strict_department_live_status': True,

    # 📢 System Maintenance & Announcement Controls
    'mobile_maintenance_mode': False,
    'maintenance_notice_text': 'Scheduled system maintenance is currently in progress. Some services may be unavailable.',
    'broadcast_banner_enabled': False,
    'broadcast_banner_text': 'Welcome to Shanmuga Hospital Mobile Portal',
    'minimum_supported_version': '1.0.0'
}

_mongo_client = None

def get_settings_collection():
    global _mongo_client
    if _mongo_client is None:
        mongo_uri = os.environ.get('GLOBAL_DB_HOST') or 'mongodb://mongoAdmin:Shinovatest%402026@docker285276-env-4077430.in1.cloudlets.co.in:27017/admin?authSource=admin&directConnection=true'
        _mongo_client = MongoClient(mongo_uri)
    db_name = os.environ.get('HR_DB_NAME') or os.environ.get('GLOBAL_DB_NAME') or 'Global'
    return _mongo_client[db_name]['system_settings']

def get_active_mobile_config():
    """Returns active mobile configuration dictionary with defaults fallback."""
    try:
        col = get_settings_collection()
        doc = col.find_one({'key': CONFIG_KEY})
        if not doc:
            # Initialize default document
            col.update_one(
                {'key': CONFIG_KEY},
                {'$set': {'key': CONFIG_KEY, 'config': DEFAULT_MOBILE_CONFIG, 'updated_at': datetime.now()}},
                upsert=True
            )
            return dict(DEFAULT_MOBILE_CONFIG)
        
        cfg = doc.get('config', {})
        merged = dict(DEFAULT_MOBILE_CONFIG)
        merged.update(cfg)
        return merged
    except Exception as e:
        print("Error fetching mobile config:", e)
        return dict(DEFAULT_MOBILE_CONFIG)


@api_view(['GET'])
@permission_classes([AllowAny])
def get_mobile_config(request):
    """
    Public/App Endpoint: Returns active configuration for Mobile App launch and refresh.
    Cached locally by mobile app.
    """
    cfg = get_active_mobile_config()
    return Response({
        "success": True,
        "config": cfg,
        "timestamp": datetime.now().isoformat()
    }, status=status.HTTP_200_OK)


@api_view(['GET', 'POST'])
@permission_classes([HasRoleAndDataPermission])
def manage_mobile_settings(request):
    """
    Admin Endpoint for Web Portal:
    GET: Returns full settings with schema metadata, grouped categories, and current values.
    POST: Updates configuration values in MongoDB system_settings.
    """
    col = get_settings_collection()

    if request.method == 'GET':
        cfg = get_active_mobile_config()
        categories = [
            {
                "id": "leaves",
                "title": "Leave & Permission Policies",
                "icon": "Calendar",
                "description": "Rules for applying past and future leaves, and permission limits.",
                "fields": [
                    {
                        "key": "allow_past_date_leaves",
                        "label": "Allow Previous Day / Past Leaves",
                        "type": "boolean",
                        "value": cfg.get("allow_past_date_leaves", True),
                        "help": "If enabled, staff can apply for leaves on previous days."
                    },
                    {
                        "key": "max_past_leave_days",
                        "label": "Max Past Days Allowed (Leave)",
                        "type": "number",
                        "min": 1,
                        "max": 90,
                        "value": cfg.get("max_past_leave_days", 7),
                        "help": "How many days in the past employees can select (e.g. 7 days back)."
                    },
                    {
                        "key": "allow_future_leaves",
                        "label": "Allow Advance Future Leaves",
                        "type": "boolean",
                        "value": cfg.get("allow_future_leaves", True),
                        "help": "Allows applying for leaves in advance."
                    },
                    {
                        "key": "max_future_leave_days",
                        "label": "Max Advance Days Allowed",
                        "type": "number",
                        "min": 7,
                        "max": 180,
                        "value": cfg.get("max_future_leave_days", 60),
                        "help": "Maximum days into the future staff can apply for."
                    },
                    {
                        "key": "require_leave_reason",
                        "label": "Require Mandatory Leave Reason",
                        "type": "boolean",
                        "value": cfg.get("require_leave_reason", True),
                        "help": "Employees must enter a reason before submitting a leave request."
                    },
                    {
                        "key": "allow_past_permissions",
                        "label": "Allow Past Day 1-Hr Permissions",
                        "type": "boolean",
                        "value": cfg.get("allow_past_permissions", True),
                        "help": "Allows regularizing 1-hour permissions for yesterday or previous days."
                    },
                    {
                        "key": "max_past_permission_days",
                        "label": "Max Past Days Allowed (Permissions)",
                        "type": "number",
                        "min": 1,
                        "max": 14,
                        "value": cfg.get("max_past_permission_days", 2),
                        "help": "Maximum previous days allowed for 1-hour permission requests."
                    }
                ]
            },
            {
                "id": "modules",
                "title": "Mobile App Module Switches",
                "icon": "Smartphone",
                "description": "Show or hide specific cards and features in the mobile app.",
                "fields": [
                    {
                        "key": "feature_canteen",
                        "label": "Canteen / Meal Ordering",
                        "type": "boolean",
                        "value": cfg.get("feature_canteen", True),
                        "help": "Enables the Canteen card and food ordering kiosk in mobile app."
                    },
                    {
                        "key": "feature_payslips",
                        "label": "Salary & Payslips View",
                        "type": "boolean",
                        "value": cfg.get("feature_payslips", True),
                        "help": "Allows staff to view and download their monthly payslips."
                    },
                    {
                        "key": "feature_helpdesk",
                        "label": "HR Helpdesk & Support Tickets",
                        "type": "boolean",
                        "value": cfg.get("feature_helpdesk", True),
                        "help": "Enables raising support tickets and chatting with HR."
                    },
                    {
                        "key": "feature_id_card",
                        "label": "Digital Employee ID Card",
                        "type": "boolean",
                        "value": cfg.get("feature_id_card", True),
                        "help": "Shows digital ID card badge with QR code."
                    },
                    {
                        "key": "feature_duty_roster",
                        "label": "Staff Duty Roster View",
                        "type": "boolean",
                        "value": cfg.get("feature_duty_roster", True),
                        "help": "Allows general staff to check their monthly duty shifts."
                    },
                    {
                        "key": "feature_birthdays",
                        "label": "Birthday Wishes & Celebrations",
                        "type": "boolean",
                        "value": cfg.get("feature_birthdays", True),
                        "help": "Shows birthday celebration modal and department birthday lists."
                    },
                    {
                        "key": "feature_approver_hierarchy",
                        "label": "Organization Hierarchy Viewer",
                        "type": "boolean",
                        "value": cfg.get("feature_approver_hierarchy", True),
                        "help": "Shows the Incharge -> HOD -> AVP organizational hierarchy."
                    }
                ]
            },
            {
                "id": "governance",
                "title": "Approvals & Security Governance",
                "icon": "ShieldCheck",
                "description": "Strict role governance and approval routing restrictions.",
                "fields": [
                    {
                        "key": "block_self_approval",
                        "label": "Block Approver Self-Approval",
                        "type": "boolean",
                        "value": cfg.get("block_self_approval", True),
                        "help": "Prevents HODs from approving their own leaves (forces routing to AVP)."
                    },
                    {
                        "key": "incharge_can_final_approve",
                        "label": "Incharge Direct Final Approval",
                        "type": "boolean",
                        "value": cfg.get("incharge_can_final_approve", False),
                        "help": "If OFF, Incharge can only recommend to HOD. If ON, Incharge can directly approve."
                    },
                    {
                        "key": "strict_department_live_status",
                        "label": "Strict Department Live Punch Scope",
                        "type": "boolean",
                        "value": cfg.get("strict_department_live_status", True),
                        "help": "Restricts HODs to view only their assigned departments' live punch status."
                    }
                ]
            },
            {
                "id": "maintenance",
                "title": "Maintenance & Broadcasts",
                "icon": "AlertCircle",
                "description": "Control maintenance mode and publish hospital announcements.",
                "fields": [
                    {
                        "key": "mobile_maintenance_mode",
                        "label": "Emergency Maintenance Mode",
                        "type": "boolean",
                        "value": cfg.get("mobile_maintenance_mode", False),
                        "help": "Places the mobile app in read-only maintenance mode."
                    },
                    {
                        "key": "maintenance_notice_text",
                        "label": "Maintenance Announcement Message",
                        "type": "string",
                        "value": cfg.get("maintenance_notice_text", ""),
                        "help": "Message shown to mobile users when maintenance mode is active."
                    },
                    {
                        "key": "broadcast_banner_enabled",
                        "label": "Show Announcement Banner on Dashboard",
                        "type": "boolean",
                        "value": cfg.get("broadcast_banner_enabled", False),
                        "help": "Displays an alert ticker across all mobile user dashboards."
                    },
                    {
                        "key": "broadcast_banner_text",
                        "label": "Announcement Banner Content",
                        "type": "string",
                        "value": cfg.get("broadcast_banner_text", ""),
                        "help": "Text shown in the mobile dashboard ticker banner."
                    },
                    {
                        "key": "minimum_supported_version",
                        "label": "Minimum Supported Mobile Version",
                        "type": "string",
                        "value": cfg.get("minimum_supported_version", "1.0.0"),
                        "help": "Older app builds will be prompted to update to this version."
                    }
                ]
            }
        ]

        return Response({
            "success": True,
            "config": cfg,
            "categories": categories,
            "updated_at": datetime.now().isoformat()
        }, status=status.HTTP_200_OK)

    elif request.method == 'POST':
        updates = request.data.get('config') or request.data
        if not isinstance(updates, dict):
            return Response({"error": "Invalid payload format. Expected dict of settings."}, status=status.HTTP_400_BAD_REQUEST)

        # Merge with existing configuration
        existing = get_active_mobile_config()
        for k, v in updates.items():
            if k in DEFAULT_MOBILE_CONFIG:
                # Type sanitization
                default_val = DEFAULT_MOBILE_CONFIG[k]
                if isinstance(default_val, bool):
                    existing[k] = bool(v)
                elif isinstance(default_val, (int, float)):
                    try:
                        existing[k] = int(v)
                    except:
                        pass
                elif isinstance(default_val, str):
                    existing[k] = str(v).strip()

        col.update_one(
            {'key': CONFIG_KEY},
            {
                '$set': {
                    'key': CONFIG_KEY,
                    'config': existing,
                    'updated_at': datetime.now(),
                    'last_updated_by': getattr(request, 'user', None) and getattr(request.user, 'username', 'Admin')
                }
            },
            upsert=True
        )

        return Response({
            "success": True,
            "message": "Mobile app settings updated successfully.",
            "config": existing,
            "updated_at": datetime.now().isoformat()
        }, status=status.HTTP_200_OK)
