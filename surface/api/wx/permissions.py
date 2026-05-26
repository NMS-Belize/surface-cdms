# wx/permissions.py
from rest_framework.permissions import BasePermission
from typing import Literal
from wx.models import WxGroupPageAccess

Action = Literal["read", "write", "delete"]


class IsSuperUser(BasePermission):
    """
    Allows access only to superusers.
    """

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.is_superuser
        )

def user_can(user, url_name: str, action: Action) -> bool:
    """
    Return True if the user is allowed to perform `action` on the page identified by `url_name`.
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    field_map = {
        "read": "can_read",
        "write": "can_write",
        "delete": "can_delete",
    }
    flag_field = field_map.get(action)
    if not flag_field:
        return False

    return WxGroupPageAccess.objects.filter(
        group__in=user.groups.all(),
        page__url_name=url_name,
        **{flag_field: True},
    ).exists()
