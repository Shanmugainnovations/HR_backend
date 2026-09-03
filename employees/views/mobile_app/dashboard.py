"""
Mobile App & Web Dashboard API View
Delegates to the unified, robust PyMongo implementation in analytics_and_reports.employee_dashboard_views
"""
from employees.views.analytics_and_reports.employee_dashboard_views import today_status

__all__ = ['today_status']
