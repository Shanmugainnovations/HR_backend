import os
from functools import wraps
from django.http import JsonResponse
from employees.models import AllowedDevice


def get_client_ip(request):
    """
    Extract the client's local network IP.
    Prioritizes Cloudflare headers, X-Real-IP and X-Forwarded-For.
    """
    # 1. Cloudflare specific header
    cf_ip = request.META.get('HTTP_CF_CONNECTING_IP')
    
    # 2. X-Forwarded-For (standard for most proxies)
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    
    # 3. X-Real-IP (common in Nginx local setups)
    real_ip = request.META.get('HTTP_X_REAL_IP')
    
    # 4. Standard Remote Addr
    remote_addr = request.META.get('REMOTE_ADDR', '')

    # Log for debugging - this will show up in the Django server console
    print(f"--- IP Detection Debug ---")
    print(f"CF_CONNECTING_IP: {cf_ip}")
    print(f"X_FORWARDED_FOR: {x_forwarded}")
    print(f"X_REAL_IP: {real_ip}")
    print(f"REMOTE_ADDR: {remote_addr}")
    print(f"--------------------------")

    if cf_ip:
        return cf_ip.strip()

    if x_forwarded:
        # Take the first IP in the list, which is the original client
        return x_forwarded.split(',')[0].strip()

    if real_ip:
        return real_ip.strip()

    return remote_addr


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
