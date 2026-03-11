import os
from functools import wraps
from django.http import JsonResponse
from employees.models import AllowedDevice


def get_client_ip(request):
    """
    Extract the client's local network IP.
    Prioritizes X-Real-IP and X-Forwarded-For headers which are often set by local proxies (like Nginx).
    """
    # Check for X-Real-IP (common in Nginx local setups)
    real_ip = request.META.get('HTTP_X_REAL_IP')
    if real_ip:
        return real_ip.strip()

    # Check for X-Forwarded-For
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if x_forwarded:
        # Take the first IP in the list, which is the original client
        return x_forwarded.split(',')[0].strip()

    # Fallback to REMOTE_ADDR
    return request.META.get('REMOTE_ADDR', '')


def ip_whitelist_required(view_func):
    """
    Decorator that restricts a view to IPs listed in AllowedDevice (is_active=True).
    Returns 403 if the client IP is not whitelisted.

    Usage:
        @ip_whitelist_required
        @api_view(['POST'])
        def mark_attendance(request):
            ...
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        client_ip = get_client_ip(request)
        print(client_ip)
        if not AllowedDevice.objects.filter(ip_address=client_ip, is_active=True).exists():
            return JsonResponse(
                {"error": f"Device not authorized. IP: {client_ip}"},
                status=403
            )
        return view_func(request, *args, **kwargs)
    return wrapper
