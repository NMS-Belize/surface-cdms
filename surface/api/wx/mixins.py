# wx/mixins.py

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import resolve, reverse
from wx.permissions import user_can

from wx.models import WxGroupPageAccess


class WxPermissionRequiredMixin:
    """
    Gate a Django view based on WxGroupPageAccess.

    The permission key is the Django route name (urls.py name="...").
    Example: name="manual-data-import" -> url_name="manual-data-import"

    Action is inferred from HTTP method:
    - GET/HEAD/OPTIONS -> read
    - POST/PUT/PATCH  -> write
    - DELETE          -> delete

    If unauthorized:
    - unauthenticated users go to LOGIN_URL with ?next=
    - authenticated users go to the 'not-auth' page
    """

    # Optional override: set this on a view if you want a specific page key
    # (Useful when an AJAX endpoint should inherit permission from a parent page.)
    wx_permission_page_name = None  # e.g. "spatial-analysis"

    def get_required_action(self, request):
        """Infer the required permission action from the request method."""
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return "read"
        if request.method in ("POST", "PUT", "PATCH"):
            return "write"
        if request.method == "DELETE":
            return "delete"
        return None

    def get_permission_page_name(self, request):
        """
        Decide which WxPermissionPages.url_name to check.

        Default:
        - Use the resolved Django route name (urls.py name="...")

        Override:
        - If wx_permission_page_name is set on the view, use that instead.
        """
        if self.wx_permission_page_name:
            return self.wx_permission_page_name
        return resolve(request.path_info).url_name

    def handle_no_permission(self, request):
        """
        Redirect unauthenticated users to login, and authenticated users to not-auth.
        """
        if not request.user.is_authenticated:
            login_url = getattr(settings, "LOGIN_URL", "/accounts/login/")
            return redirect(f"{login_url}?next={request.get_full_path()}")

        return redirect(reverse("not-auth"))
    
    def dispatch(self, request, *args, **kwargs):
        action = self.get_required_action(request)
        if action is None:
            return self.handle_no_permission(request)

        page_name = self.get_permission_page_name(request)

        # user_can handles the check
        if not user_can(request.user, page_name, action):
            return self.handle_no_permission(request)

        return super().dispatch(request, *args, **kwargs)
