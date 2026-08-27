from .employee import (
    get_all_employees_with_images,
    get_employee_by_md5,
    serve_employee_image_by_md5,
    get_all_employee_from_global,
    enable_facial_recognition,
    disable_facial_recognition,
    register_employee,
    preview_face_frames,
    encode_employee_face,
    get_employee_detail,
    serve_file,
    export_employees_xls
)
from .attendance import (
    mark_attendance,
    verify_face,
    attendance_report_with_employee_details,
    get_spoofing_attempts,
    delete_spoofing_attempts
)
from .auth import (
    get_device_info,
    registration,
    login,
    ip_login,
    my_ip,
    allowed_devices,
    get_global_departments,
    register_device_api,
)

from .mobile_app import (
    today_status,
    my_attendance_report,
    apply_leave,
    my_leaves,
    pending_leaves,
    update_leave_status,
    leave_history,
    leave_type_list_create,
    leave_type_detail
)

from .utils import save_or_update_encoding
from .roster_report import export_roster_csv, export_roster_xlsx, import_roster_xlsx, preview_roster_xlsx, approve_roster_data
from .reports import roster_attendance_report

from .shifts import (
    shift_list_create, shift_detail,
    department_list_create, department_detail,
    get_monthly_roster, assign_shift
)

from .canteen import (
    issue_canteen_token,
    get_canteen_today_summary,
    get_canteen_token_history,
    manage_canteen_rules
)

from .mobile_app.notifications import (
    get_employee_notifications,
    mark_notifications_read,
    clear_notifications,
    get_unread_count,
    send_admin_notification
)




