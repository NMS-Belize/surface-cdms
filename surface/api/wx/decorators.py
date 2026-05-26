from functools import wraps
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse, resolve

from wx.permissions import user_can
from wx.permissions_map import get_parent_permission

import logging

logger = logging.getLogger('surface.urls')

VALID_ACTIONS = {"read", "write", "delete"}


def _wants_json(request) -> bool:
    # Always treat API routes as JSON
    if request.path.startswith("/api/"):
        return True
    
    # If frontend sends this header (many setups do)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True

    # If client explicitly accepts JSON
    accept = request.headers.get("Accept", "")
    if "application/json" in accept:
        return True

    return False


def wx_permission_required(page_url_name: str, action: str):
    """
    Manual override decorator for Wx permissions. This bypasses permissions_map.

    Args:
        page_url_name: Parent page url_name (e.g. "spatial-analysis")
        action: One of "read" | "write" | "delete"

    Use this when:
    - an endpoint should not use the mapped (auto-resolved) behavior
    - an endpoint is shared by multiple pages and you want an explicit parent/action
    - you want a custom rule that doesn't fit the mapping system
    """

    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action '{action}'. Must be one of {VALID_ACTIONS}.")

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):

            # Not logged in
            if not request.user.is_authenticated:
                if _wants_json(request):
                    return JsonResponse({"detail": "Authentication required."}, status=401)
                login_url = getattr(settings, "LOGIN_URL", "/accounts/login/")
                return redirect(f"{login_url}?next={request.get_full_path()}")

            # Not authorized
            if not user_can(request.user, page_url_name, action):
                if _wants_json(request):
                    return JsonResponse({"detail": "Not authorized."}, status=403)
                return redirect(reverse("not-auth"))

            return view_func(request, *args, **kwargs)

        return _wrapped
    
    return decorator


def wx_mapped_permission_required(view_func):
    """
    Enforce permissions using ENDPOINT_PARENT_PAGE from permissions_map.py.

    This decorator:
    - auto-resolves the endpoint url_name from the current request
    - looks up (parent_page, action) from ENDPOINT_PARENT_PAGE
    - enforces that permission
    - if missing mapping and strict mode enabled -> raises KeyError

    Use this on helper/AJAX endpoints to force developers to keep the map updated.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        # ==============================
        # DEBUG CHECK — Soft Fail
        # ==============================
        # if not hasattr(request, "path_info"):
        #     logger.error(
        #         "wx_mapped_permission_required was applied to NON-VIEW function '%s'. "
        #         "First argument type = %s",
        #         view_func.__name__,
        #         type(request).__name__,
        #     )
        #     # Let execution continue so you can see full stack trace
        #     return view_func(request, *args, **kwargs)
        
        # ==============================
        # DEBUG CHECK — Hard Fail
        # ==============================
        # Hard guard: must be a real Django request
        if not hasattr(request, "path_info"):
            raise TypeError(
                f"@wx_mapped_permission_required can only decorate Django views "
                f"(first argument must be request). "
                f"{view_func.__name__} received {type(request).__name__} instead."
            )
        
        endpoint_url_name = resolve(request.path_info).url_name

        # This will raise KeyError in strict mode if missing
        mapping = get_parent_permission(endpoint_url_name)

        # If strict mode is off and mapping missing, decide behavior:
        if mapping is None:
            # Safer default is to deny access (fail closed)
            if _wants_json(request):
                return JsonResponse({"detail": "Permission mapping missing."}, status=500)
            return redirect(reverse("not-auth"))

        parent_page, action = mapping

        # Authentication check
        if not request.user.is_authenticated:
            if _wants_json(request):
                return JsonResponse({"detail": "Authentication required."}, status=401)
            login_url = getattr(settings, "LOGIN_URL", "/accounts/login/")
            return redirect(f"{login_url}?next={request.get_full_path()}")

        # Authorization check
        if not user_can(request.user, parent_page, action):
            if _wants_json(request):
                return JsonResponse({"detail": "Not authorized."}, status=403)
            return redirect(reverse("not-auth"))

        return view_func(request, *args, **kwargs)

    return _wrapped

