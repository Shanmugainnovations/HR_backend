"""
Attendance Push Notification Listener Service
Monitors MongoDB (employees_employeeattendance) in real time for new punch arrivals
and automatically triggers mobile push notifications and in-app alerts.
Works independently from any kiosk or biometric EXE.
"""

import os
import time
import threading
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Timezone helper
try:
    import pytz
    IST = pytz.timezone("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))

_LISTENER_THREAD = None
_LISTENER_RUNNING = False
_LOCK = threading.Lock()


_CLIENT = None

def get_db():
    global _CLIENT
    if _CLIENT is None:
        from pymongo import MongoClient
        uri = os.environ.get("GLOBAL_DB_HOST")
        _CLIENT = MongoClient(uri)
    db_name = os.environ.get("GLOBAL_DB_NAME", os.environ.get("HR_DB_NAME", "Global"))
    return _CLIENT[db_name]


def get_service_status():
    """Returns current listener status and metrics for the HR admin dashboard."""
    global _LISTENER_RUNNING
    try:
        db = get_db()
        cursor_doc = db['system_notification_cursors'].find_one({'_id': 'attendance_punch_last_id'})
        last_id = cursor_doc.get('last_id', 0) if cursor_doc else 0

        setting_doc = db['system_settings'].find_one({'key': 'attendance_push_notifications'})
        is_enabled = setting_doc.get('enabled', True) if setting_doc else True

        today_start = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
        logs_today_count = db['attendance_notification_logs'].count_documents({
            'notified_at': {'$gte': today_start}
        })
        delivered_today_count = db['attendance_notification_logs'].count_documents({
            'notified_at': {'$gte': today_start},
            'has_push_token': True
        })

        recent_logs = list(db['attendance_notification_logs'].find().sort([('_id', -1)]).limit(20))
        for log in recent_logs:
            log['_id'] = str(log['_id'])
            if isinstance(log.get('notified_at'), datetime):
                log['notified_at'] = log['notified_at'].astimezone(IST).strftime('%I:%M:%S %p')

        return {
            "is_running": _LISTENER_RUNNING,
            "is_enabled": is_enabled,
            "last_processed_id": last_id,
            "total_punches_detected_today": logs_today_count,
            "push_notifications_dispatched_today": delivered_today_count,
            "recent_logs": recent_logs
        }
    except Exception as e:
        logger.error(f"Error fetching attendance push service status: {e}")
        return {
            "is_running": _LISTENER_RUNNING,
            "is_enabled": True,
            "last_processed_id": 0,
            "total_punches_detected_today": 0,
            "push_notifications_dispatched_today": 0,
            "recent_logs": [],
            "error": str(e)
        }


def set_service_enabled(enabled: bool):
    """Allows HR Admin to toggle the automatic attendance push notification on/off."""
    try:
        db = get_db()
        db['system_settings'].update_one(
            {'key': 'attendance_push_notifications'},
            {'$set': {'key': 'attendance_push_notifications', 'enabled': bool(enabled), 'updated_at': datetime.now()}},
            upsert=True
        )
        return True
    except Exception as e:
        logger.error(f"Error setting attendance push toggle: {e}")
        return False


def _check_employee_has_token(db, employee_id):
    """Quick check if employee has registered any mobile push token."""
    emp_matches = [str(employee_id)]
    if str(employee_id).isdigit():
        emp_matches.append(int(employee_id))
    
    t1 = db['employees_push_tokens'].find_one({"employee_id": {"$in": emp_matches}, "push_token": {"$exists": True, "$ne": ""}})
    if t1:
        return True
    t2 = db['backend_diagnostics_push_tokens'].find_one({"employee_id": {"$in": emp_matches}, "expo_push_token": {"$exists": True, "$ne": ""}})
    return bool(t2)


def _get_employee_name(db, employee_id, cache):
    """Fetches employee name with local in-memory cache to minimize DB hits."""
    emp_str = str(employee_id).strip()
    if emp_str in cache:
        return cache[emp_str]

    name = None
    try:
        prof = db['backend_diagnostics_profile'].find_one({"employeeId": emp_str}, {"employeeName": 1})
        if prof and prof.get('employeeName'):
            name = prof['employeeName']
    except Exception:
        pass

    if not name:
        try:
            emp = db['employees_employee'].find_one({"employee_id": emp_str}, {"name": 1})
            if emp and emp.get('name'):
                name = emp['name']
        except Exception:
            pass

    final_name = name or emp_str
    cache[emp_str] = final_name
    return final_name


def _poll_and_dispatch(emp_name_cache):
    """Processes newly arrived attendance records in MongoDB."""
    db = get_db()
    att_col = db['employees_employeeattendance']
    cursor_col = db['system_notification_cursors']

    # 1. Check if disabled via settings
    setting_doc = db['system_settings'].find_one({'key': 'attendance_push_notifications'})
    if setting_doc and not setting_doc.get('enabled', True):
        # Service is paused by HR Admin
        return

    # 2. Checkpoint last processed ID
    cursor_doc = cursor_col.find_one({'_id': 'attendance_punch_last_id'})
    if not cursor_doc:
        # First time initialization: initialize to current max attendence_id to avoid back-notifying 80k historical records
        latest_doc = att_col.find_one(sort=[('attendence_id', -1)])
        initial_id = latest_doc.get('attendence_id', 0) if latest_doc else 0
        cursor_col.update_one(
            {'_id': 'attendance_punch_last_id'},
            {'$set': {'_id': 'attendance_punch_last_id', 'last_id': initial_id, 'initialized_at': datetime.now()}},
            upsert=True
        )
        print(f"📡 [AttendanceListener] Initialized checkpoint to latest attendence_id: {initial_id}")
        return

    last_id = cursor_doc.get('last_id', 0)

    # 3. Query new records
    new_records = list(att_col.find({'attendence_id': {'$gt': last_id}}).sort([('attendence_id', 1)]).limit(100))
    if not new_records:
        return

    from employees.views.mobile_app.notifications import create_in_app_notification, send_expo_push_notification

    current_max_id = last_id
    for rec in new_records:
        rec_id = rec.get('attendence_id') or rec.get('_id')
        if rec.get('attendence_id') and rec['attendence_id'] > current_max_id:
            current_max_id = rec['attendence_id']

        emp_id = str(rec.get('employee_id', '')).strip()
        if not emp_id:
            continue

        punch_type = str(rec.get('attendence_type', 'IN')).upper()
        device_id = rec.get('device_id') or 'Biometric'
        att_time = rec.get('attendence_time')

        if isinstance(att_time, datetime):
            try:
                ist_dt = att_time.astimezone(IST)
            except Exception:
                ist_dt = att_time
            time_str = ist_dt.strftime('%I:%M %p')
            date_str = ist_dt.strftime('%d %b %Y')
        else:
            ist_dt = datetime.now(IST)
            time_str = ist_dt.strftime('%I:%M %p')
            date_str = ist_dt.strftime('%d %b %Y')

        emp_name = _get_employee_name(db, emp_id, emp_name_cache)
        has_token = _check_employee_has_token(db, emp_id)

        # Atomic deduplication: Ensure each attendence_id is processed EXACTLY ONCE
        att_punch_id = rec.get('attendence_id')
        if att_punch_id is not None:
            try:
                claim_result = db['attendance_notification_logs'].update_one(
                    {'attendence_id': att_punch_id},
                    {'$setOnInsert': {
                        'attendence_id': att_punch_id,
                        'employee_id': emp_id,
                        'employee_name': emp_name,
                        'punch_type': punch_type,
                        'punch_time': time_str,
                        'punch_date': date_str,
                        'device_id': device_id,
                        'has_push_token': has_token,
                        'notified_at': datetime.now(IST)
                    }},
                    upsert=True
                )
                if claim_result.matched_count > 0:
                    # Already processed by another worker/thread
                    continue
            except Exception as lock_err:
                logger.error(f"[AttendanceListener] Error claiming punch {att_punch_id}: {lock_err}")

        # Build notification text
        if punch_type == 'IN':
            title = "Punch In Recorded ✅"
            body = f"Hi {emp_name}, your Punch IN was recorded at {time_str} ({device_id}). Have a productive shift!"
        else:
            title = "Punch Out Recorded 👋"
            body = f"Hi {emp_name}, your Punch OUT was recorded at {time_str} ({device_id}). Have a great evening!"

        # Create in-app notification doc (always available for the employee)
        try:
            create_in_app_notification(
                employee_id=emp_id,
                title=title,
                message=body,
                category='attendance',
                action_url='/my-attendance'
            )
        except Exception as err:
            logger.error(f"[AttendanceListener] Error creating in-app notification for {emp_id}: {err}")

        # Send Expo Push Notification if employee has active mobile app token
        if has_token:
            try:
                send_expo_push_notification(
                    employee_ids=[emp_id],
                    title=title,
                    body=body,
                    data={
                        "type": "attendance_punch",
                        "attendence_id": rec.get('attendence_id'),
                        "employee_id": emp_id,
                        "punch_type": punch_type,
                        "time": time_str,
                        "date": date_str,
                        "device_id": device_id
                    }
                )
                print(f"📱 [AttendanceListener] Dispatched {punch_type} push notification to {emp_name} ({emp_id}) at {time_str}")
            except Exception as push_err:
                logger.error(f"[AttendanceListener] Push dispatch failed for {emp_id}: {push_err}")

    # 4. Save updated checkpoint
    if current_max_id > last_id:
        cursor_col.update_one(
            {'_id': 'attendance_punch_last_id'},
            {'$set': {'last_id': current_max_id, 'updated_at': datetime.now()}},
            upsert=True
        )


def _listener_loop():
    """Background polling loop executing every 1.5 - 2 seconds."""
    global _LISTENER_RUNNING
    print("🚀 [AttendanceListener] Background polling daemon started.")
    name_cache = {}
    while _LISTENER_RUNNING:
        try:
            _poll_and_dispatch(name_cache)
        except Exception as e:
            logger.error(f"⚠️ [AttendanceListener] Unexpected error in polling loop: {e}")
        time.sleep(1.8)
    print("🛑 [AttendanceListener] Background daemon stopped.")


def start_attendance_listener():
    """Starts the attendance listener in a single daemon thread if not already active."""
    global _LISTENER_THREAD, _LISTENER_RUNNING
    with _LOCK:
        if _LISTENER_RUNNING and _LISTENER_THREAD and _LISTENER_THREAD.is_alive():
            return
        _LISTENER_RUNNING = True
        _LISTENER_THREAD = threading.Thread(target=_listener_loop, name="AttendancePushListenerThread", daemon=True)
        _LISTENER_THREAD.start()
        print("✅ [AttendanceListener] Service thread successfully spawned.")


def stop_attendance_listener():
    """Stops the attendance listener."""
    global _LISTENER_RUNNING
    _LISTENER_RUNNING = False
