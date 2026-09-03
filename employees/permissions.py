"""
DRF Permission Classes Module
Integrates pyauth role-based and data-entitlement permission classes with robust header handling.
"""
import logging
from pyauth.jwt_check import isSecurityDisabled, checkAccess
from pyauth.auth import _set_auth_data, HasRolePermission
from rest_framework import permissions
from rest_framework.permissions import AllowAny, IsAuthenticated

logger = logging.getLogger(__name__)


class HasRoleAndDataPermission(permissions.BasePermission):
    def has_permission(self, request, view) -> bool:
        if isSecurityDisabled():
            return True
        try:
            token = (
                request.headers.get("Authorization")
                or request.META.get("HTTP_AUTHORIZATION")
                or ""
            )
            if token.startswith("Bearer "):
                token = token[7:].strip()
            elif token.startswith("bearer "):
                token = token[7:].strip()

            if not token:
                print("HasRoleAndDataPermission: Access not allowed. Reason: Missing Authorization token")
                return False

            branch_code = (
                request.headers.get("Branch-Code")
                or request.headers.get("branch-code")
                or request.META.get("HTTP_BRANCH_CODE")
                or "SHB001"
            )
            page_path = request.get_full_path()
            http_method = request.method

            vjson = checkAccess(token, branch_code, page_path, http_method)
            _set_auth_data(request, vjson, branch_code)
            print(f"HasRoleAndDataPermission: Access allowed for {page_path}")
            return True
        except ValueError as e:
            print(f"HasRoleAndDataPermission: Access not allowed. Reason: {e}\n")
            return False
        except Exception as e:
            import traceback
            print(f"HasRoleAndDataPermission: Error in access validation: {type(e).__name__}: {e}")
            traceback.print_exc()
            return False


__all__ = [
    'HasRolePermission',
    'HasRoleAndDataPermission',
    'AllowAny',
    'IsAuthenticated'
]

