# wx/middleware.py

from wx.models import WxGroupPageAccess

class AttachWxPermissionsMiddleware:
    """
    Attach a precomputed set of permission strings to request.user_permissions.

    Format:
      "<url_name>:read"
      "<url_name>:write"
      "<url_name>:delete"

    Why:
    - Templates can check permissions without extra DB hits.
    - Vue pages can read them from an endpoint (later) without recomputing.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Default for anonymous users
        request.user_permissions = set()

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return self.get_response(request)

        # Superusers get "all" in the UI
        # (We store a sentinel so template checks can short-circuit.)
        if user.is_superuser:
            request.user_permissions = {"*"}
            return self.get_response(request)

        # Fetch all WxGroupPageAccess rows for all groups the user belongs to
        access_rows = WxGroupPageAccess.objects.filter(
            group__in=user.groups.all()
        ).select_related("page")

        perms = set()

        for row in access_rows:
            url_name = row.page.url_name
            if row.can_read:
                perms.add(f"{url_name}:read")
            if row.can_write:
                perms.add(f"{url_name}:write")
            if row.can_delete:
                perms.add(f"{url_name}:delete")

        request.user_permissions = perms

        return self.get_response(request)

            