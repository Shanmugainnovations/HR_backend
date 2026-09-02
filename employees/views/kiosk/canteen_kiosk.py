"""
Canteen Kiosk Views Package
Handles Canteen Kiosk tea token issuance and daily quota rules.
"""
from employees.views.canteen_management.canteen import issue_canteen_token, get_canteen_today_summary, manage_canteen_rules

# Export canteen kiosk endpoints
__all__ = ['issue_canteen_token', 'get_canteen_today_summary', 'manage_canteen_rules']
