from functools import wraps
from rest_framework.response import Response
from rest_framework import status
from .token_utils import decode_employee_token

def token_required(view_func):
    """
    Decorator that enforces JWT Bearer Token authentication on Django REST view functions.
    Inspects HTTP Authorization header, verifies signature, and attaches request.token_payload.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # 1. Extract token from Authorization header
        auth_header = request.headers.get('Authorization') or request.META.get('HTTP_AUTHORIZATION')
        token = None

        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() in ['bearer', 'token']:
                token = parts[1]
            elif len(parts) == 1:
                token = parts[0]

        # 2. Fallback to query param or request body
        if not token:
            token = request.GET.get('token') or (request.data.get('token') if hasattr(request, 'data') else None)

        if not token:
            return Response(
                {"error": "Authentication required. Bearer Token missing in Authorization header."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # 3. Decode & verify token
        payload = decode_employee_token(token)
        if not payload:
            return Response(
                {"error": "Unauthorized. Token is invalid or expired."},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # 4. Attach verified employee payload to request
        request.token_payload = payload
        request.authenticated_employee_id = (
            payload.get('employee_id') or
            payload.get('employeeId') or
            payload.get('aud') or
            payload.get('sub')
        )

        return view_func(request, *args, **kwargs)

    return _wrapped_view
