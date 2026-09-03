from .employee_management.employee import (
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
    serve_file as serve_employee_file,
    export_employees_xls
)
from .attendance_management.attendance import (
    mark_attendance,
    verify_face,
    attendance_report_with_employee_details,
    get_spoofing_attempts,
    delete_spoofing_attempts
)
from .attendance_management.shifts import (
    shift_list_create,
    shift_detail,
    department_list_create,
    department_detail,
    get_monthly_roster,
    assign_shift
)
from .authentication.auth import (
    get_device_info,
    registration,
    login,
    ip_login,
    my_ip,
    allowed_devices,
    get_global_departments,
    register_device_api,
    set_employee_password,
    get_user_profile,
    mobile_employee_check,
    mobile_create_login,
)
from .global_management import (
    get_data_entitlements,
    get_data_departments,
    get_data_designation,
    getprimaryandadditionalrole,
    get_next_department_code,
    get_next_designation_code,
    addnew_department,
    addnew_designation,
    update_department,
    update_designation,
    get_todays_birthdays,
    check_employee_id,
    create_employee,
    update_employee,
    get_employee_by_id,
    get_employees_with_labels,
    upload_file,
    serve_file,
)

from .canteen_management.canteen import (
    issue_canteen_token,
    get_canteen_today_summary,
    get_canteen_token_history,
    manage_canteen_rules
)
from .leave_management.leave_views import (
    apply_leave,
    my_leaves,
    pending_leaves,
    update_leave_status,
    leave_history,
    leave_type_list_create,
    leave_type_detail
)
from .analytics_and_reports.reports import roster_attendance_report
from .analytics_and_reports.roster_report import (
    export_roster_csv,
    export_roster_xlsx,
    import_roster_xlsx,
    preview_roster_xlsx,
    approve_roster_data
)
from .mobile_app import (
    today_status,
    my_attendance_report,
    apply_leave as mobile_apply_leave,
    my_leaves as mobile_my_leaves,
    pending_leaves as mobile_pending_leaves,
    update_leave_status as mobile_update_leave_status,
    leave_history as mobile_leave_history,
    leave_type_list_create as mobile_leave_type_list_create,
    leave_type_detail as mobile_leave_type_detail,
    get_full_employee_profile,
    serve_employee_profile_photo,
    change_employee_password
)
from .mobile_app.notifications import (
    get_employee_notifications,
    mark_notifications_read,
    clear_notifications,
    get_unread_count,
    send_admin_notification
)
from .common.utils import save_or_update_encoding
from .helpdesk.tickets import (
    get_helpdesk_tickets,
    create_helpdesk_ticket,
    update_helpdesk_ticket,
    get_helpdesk_categories
)
from .payroll.payroll_views import (
    monthly_payroll_view,
    update_payroll_entry,
    approve_monthly_payroll,
    export_bank_transfer_sheet,
    export_pf_ecr,
    export_esi_return,
    download_payslip_html,
    employee_payslip_history
)
