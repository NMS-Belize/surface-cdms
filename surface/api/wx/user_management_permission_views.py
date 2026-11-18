"""Group page-access APIs for the combined SURFACE User Management page.

Security policy:
- GET requires user-management:read; PUT requires user-management:write.
- Superusers automatically pass SURFACE's existing user_can() checks.
- Permission writes are full replacements, matching the old endpoint contract.
- Missing rows mean "no access". Read is required for Write or Delete.

Keep the URL names and response shapes of the old permission APIs so that the
existing Vue permission editor's behavior remains compatible.
"""

import json

from django.contrib.auth.models import Group
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from wx.models import WxGroupPageAccess, WxPermissionPages
from wx.user_management_views import user_management_api_required


MAX_PERMISSION_PAYLOAD_BYTES = 262144


def _permission_error(message, http_status=400):
    """Use an error format already supported by SURFACE's wxFetch frontend."""
    return JsonResponse({"message": message}, status=http_status)


@require_http_methods(["GET"])
@user_management_api_required()
def managed_groups_info(request):
    """Keep GET /api/groups/ compatible: a plain list of {id, name}."""
    groups = list(Group.objects.order_by("id").values("id", "name"))
    return JsonResponse(groups, safe=False)


@require_http_methods(["GET"])
@user_management_api_required()
def managed_permission_pages_info(request):
    """Return the same category metadata consumed by the old permission matrix."""
    pages = (
        WxPermissionPages.objects
        .select_related("category")
        .order_by("category__sort_order", "category__name", "name")
    )

    output = []
    for page in pages:
        output.append({
            "id": page.pk,
            "name": page.name,
            "url_name": page.url_name,
            "description": page.description,
            "category": {
                "id": page.category_id,
                "name": page.category.name if page.category_id else None,
            },
        })

    return JsonResponse(output, safe=False)


@csrf_protect
@require_http_methods(["GET", "PUT"])
@user_management_api_required()
def managed_group_page_access(request, group_id):
    """Read or fully replace the access matrix for a Django group.

    GET returns a dict keyed by page URL names, containing only existing rows.
    PUT accepts a dict with every page key and read/write/delete booleans.

    The old endpoint also used PUT as a full replacement. We additionally
    require *all* current pages in the payload: if a new page appears while
    an administrator is editing, a stale save must not silently revoke its
    access (or overwrite a concurrently updated set of page definitions).
    """
    if not Group.objects.filter(pk=group_id).exists():
        return _permission_error("Group not found.", http_status=404)

    if request.method == "GET":
        rows = (
            WxGroupPageAccess.objects
            .filter(group_id=group_id)
            .select_related("page")
        )
        data = {
            row.page.url_name: {
                "can_read": row.can_read,
                "can_write": row.can_write,
                "can_delete": row.can_delete,
            }
            for row in rows
        }
        return JsonResponse(data)

    if request.content_type != "application/json":
        return _permission_error("Content-Type must be application/json.")

    if len(request.body) > MAX_PERMISSION_PAYLOAD_BYTES:
        return _permission_error("Permission data is too large.")

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _permission_error("Invalid JSON request body.")

    if not isinstance(payload, dict):
        return _permission_error("Expected an object keyed by page URL names.")

    # Serialize writes to the same group. The original implementation deletes
    # and recreates all rows, so transactions are essential to avoid partial
    # changes if a database constraint fails.
    with transaction.atomic():
        group = Group.objects.select_for_update().filter(pk=group_id).first()
        if group is None:
            return _permission_error("Group not found.", http_status=404)

        # Recheck the actor's latest membership/permissions inside the same
        # transaction rather than relying only on the initial HTTP check.
        from wx.user_management_views import AccessRevoked, _assert_current_actor
        try:
            _assert_current_actor(request.user.pk, "write")
        except AccessRevoked as exc:
            return _permission_error(str(exc), http_status=403)

        pages = {
            page.url_name: page
            for page in WxPermissionPages.objects.all()
        }
        submitted = set(payload)
        expected = set(pages)

        unknown = submitted - expected
        if unknown:
            return _permission_error("Unknown page: {}.".format(sorted(unknown)[0]))

        # Reject incomplete submissions rather than accidentally deleting
        # permissions for hidden/unloaded pages during a full PUT replacement.
        missing = expected - submitted
        if missing:
            return _permission_error(
                "Permission pages have changed. Refresh and try again.",
                http_status=409,
            )

        replacements = []
        for url_name, flags in payload.items():
            if not isinstance(flags, dict):
                return _permission_error("{}: expected permission flags.".format(url_name))

            permitted_fields = {"can_read", "can_write", "can_delete"}
            if set(flags) != permitted_fields:
                return _permission_error("{}: expected Read, Write and Delete flags.".format(url_name))

            # bool("false") is True in Python. Require JSON booleans exactly to
            # prevent unexpectedly granting permissions on malformed requests.
            if any(type(flags[field]) is not bool for field in permitted_fields):
                return _permission_error("{}: permission flags must be booleans.".format(url_name))

            can_read = flags["can_read"]
            can_write = flags["can_write"]
            can_delete = flags["can_delete"]

            if (can_write or can_delete) and not can_read:
                return _permission_error(
                    "{}: Read must be enabled for Write or Delete.".format(url_name)
                )

            # The absence of a record means no access. Do not create all-false
            # rows: this matches the existing WxGroupPageAccess storage rules.
            if not (can_read or can_write or can_delete):
                continue

            replacements.append(WxGroupPageAccess(
                group=group,
                page=pages[url_name],
                can_read=can_read,
                can_write=can_write,
                can_delete=can_delete,
            ))

        WxGroupPageAccess.objects.filter(group=group).delete()
        if replacements:
            WxGroupPageAccess.objects.bulk_create(replacements)

    return JsonResponse({"message": "ok"})