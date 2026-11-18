"""User-management APIs for SURFACE's combined Users and Permissions page.

Uses Django's default User and Group models and SURFACE's EXISTING
``wx.permissions.user_can`` helper. Group grants for ``user-management``
control ordinary read/write access; only an active Django superuser may
grant/revoke ``is_superuser`` or activate/deactivate accounts.

Non-superusers cannot edit/reset existing superuser or Django-staff accounts,
which would otherwise allow them to take control of a privileged identity.
The user's existing Change Password page is deliberately untouched.
Passwords are hashed and never returned by any endpoint.
"""

import json
import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from functools import wraps

from wx.permissions import user_can

# Use the configured authentication model rather than importing User directly.
# SURFACE currently uses Django's default User, but this is also the standard
# Django pattern for looking up the active authentication model.
User = get_user_model()
audit_logger = logging.getLogger("wx.user_management.audit")

# Limit the amount of JSON parsed from a browser request. User-account forms
# contain small fields, so a large body is unexpected and should be rejected.
MAX_JSON_BYTES = 32768

# An additional minimum for administrator-assigned credentials. Django's
# configured AUTH_PASSWORD_VALIDATORS still run below, so this is not the
# only password-strength check.
MIN_ADMIN_PASSWORD_LENGTH = 12


class AccessRevoked(Exception):
    """Access is unavailable or was revoked during an API operation."""


class InputError(Exception):
    """Invalid input that can safely be reported to the administrator."""

    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


def _error(message, status=400, field=None):
    """Use one predictable error shape for Vue form and API failures.

    ``field`` lets the frontend identify an invalid input without exposing
    internal Python exceptions or database details to the browser.
    """
    result = {"message": message}
    if field:
        result["field"] = field
    return JsonResponse(result, status=status)


def user_management_api_required(action=None):
    """Authorize through SURFACE's existing group/page permission records.

    ``user_can`` reads WxGroupPageAccess for the ``user-management`` page.
    GET requires read; POST/PATCH/PUT require write. This matters because one
    URL (for example managed_users) serves both reading and account creation.
    SURFACE's URL-name-based mapping alone cannot distinguish those methods.

    This decorator protects the API even if a user bypasses the Vue interface.
    High-risk privilege and status changes add their own superuser checks.
    """
    def decorate(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return _error("Authentication is required.", status=401)

            if not request.user.is_active:
                return _error("Your account is inactive.", status=403)

            requested_action = action or ("read" if request.method == "GET" else "write")
            if not user_can(request.user, "user-management", requested_action):
                return _error("You do not have permission to perform this action.", status=403)

            return view_func(request, *args, **kwargs)
        return wrapped
    return decorate


def _assert_current_actor(actor_id, action="write", *, superuser_only=False):
    """Recheck access from the database inside account-changing transactions.

    ``request.user`` can be stale if another admin changes the actor's groups
    while the request is running. Fetching the actor again before saving avoids
    trusting only the permissions captured at the beginning of the request.
    """
    actor = User.objects.filter(pk=actor_id, is_active=True).first()
    if actor is None:
        raise AccessRevoked("Your account is no longer active.")

    if not user_can(actor, "user-management", action):
        raise AccessRevoked("Your User Management permission has been revoked.")

    if superuser_only and not actor.is_superuser:
        raise AccessRevoked("Only a superuser can perform this action.")

    return actor


def _protect_privileged_target(actor, target):
    """Prevent account takeover of privileged identities via profile/reset APIs.

    Without this guard, a non-superuser with write access could reset a Django
    superuser's password and log in as that superuser, bypassing the protected
    is_superuser toggle entirely. Django staff identities are protected too.
    """
    if not actor.is_superuser and (target.is_superuser or target.is_staff):
        raise AccessRevoked("Only a superuser can manage this privileged account.")


def _body(request, allowed_fields):
    """Parse a small JSON object and reject unexpected/mass-assignment fields."""

    # A strict allowlist prevents a client from mass-assigning arbitrary User
    # fields (especially ``is_staff``, ``password``, and ``user_permissions``).
    # The dedicated password endpoint is the only place a reset is accepted.
    if request.content_type != "application/json":
        raise InputError("Content-Type must be application/json.")

    if len(request.body) > MAX_JSON_BYTES:
        raise InputError("The request is too large.")

    try:
        data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise InputError("Invalid JSON request body.")

    if not isinstance(data, dict):
        raise InputError("Expected a JSON object.")

    extra = set(data) - set(allowed_fields)
    if extra:
        raise InputError("Unsupported field(s): {}.".format(", ".join(sorted(extra))))

    return data


def _text(data, field, max_length, required=False):
    """Normalize and length-check a plain-text field before writing it."""
    value = data.get(field, "")

    if not isinstance(value, str):
        raise InputError("Must be text.", field)

    value = value.strip()

    if required and not value:
        raise InputError("This field is required.", field)

    if len(value) > max_length:
        raise InputError("Must be at most {} characters.".format(max_length), field)

    return value


def _boolean(data, field, default=None):
    """Reject strings and numeric stand-ins for security-sensitive switches."""
    value = data.get(field, default)
    if type(value) is not bool:
        raise InputError("Must be true or false.", field)
    return value


def _validate_identity(data, current_user=None, creating=False):
    """Validate only the fields present during PATCH; all fields on create."""

    output = {}
    fields = ("username", "first_name", "last_name", "email")

    for field in fields:
        if not creating and field not in data:
            continue

        max_length = 150 if field != "email" else 254
        value = _text(data, field, max_length, required=(field == "username"))

        if field == "username":
            try:
                UnicodeUsernameValidator()(value)
            except ValidationError as exc:
                raise InputError(" ".join(exc.messages), field)

            # Django's default username uniqueness may be case-sensitive in
            # PostgreSQL. Reject case-only duplicates consistently in SURFACE.
            duplicates = User.objects.filter(username__iexact=value)
            if current_user is not None:
                duplicates = duplicates.exclude(pk=current_user.pk)

            if duplicates.exists():
                raise InputError("This username is already in use.", field)

        if field == "email" and value:
            try:
                validate_email(value)
            except ValidationError:
                raise InputError("Enter a valid email address.", field)

        output[field] = value

    return output


def _validate_groups(data):
    """Ensure every requested group exists; do not silently drop unknown IDs."""

    values = data.get("groups", [])
    if not isinstance(values, list) or len(values) > 500:
        raise InputError("Groups must be a list of up to 500 IDs.", "groups")

    if any(type(value) is not int or value < 1 for value in values):
        raise InputError("Each group ID must be a positive integer.", "groups")

    # Converting to a set prevents duplicated IDs from producing misleading
    # existence checks; a missing ID is an error, not a group silently ignored.
    ids = set(values)
    groups = list(Group.objects.filter(pk__in=ids))

    if len(groups) != len(ids):
        raise InputError("One or more selected groups do not exist.", "groups")

    return groups


def _validate_new_password(value, user):
    if not isinstance(value, str) or not value:
        raise InputError("A password is required.", "password")

    if len(value) < MIN_ADMIN_PASSWORD_LENGTH:
        raise InputError(
            "Use a password with at least {} characters.".format(MIN_ADMIN_PASSWORD_LENGTH),
            "password",
        )

    # Pass the target user so validators such as UserAttributeSimilarityValidator
    # can compare the proposed password against that user's personal details.
    try:
        validate_password(value, user=user)
    except ValidationError as exc:
        raise InputError(" ".join(exc.messages), "password")


def _serialize_user(user):
    """Expose only fields intended for the UI; never serialize password hashes."""

    return {
        "id": user.pk,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        # Read-only eligibility flag: non-superuser managers must not attempt
        # to edit or reset privileged accounts (superuser OR Django staff).
        # This is not an editable staff-access control.
        "is_restricted": user.is_superuser or user.is_staff,
        "groups": [group.pk for group in user.groups.all()],
        "date_joined": user.date_joined.isoformat() if user.date_joined else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
    }


def _lock_active_superusers():
    """Serialize sensitive account changes to protect the last active superuser.

    Locks all currently active superuser rows in PK order before locking an
    individual target account. Must be called inside transaction.atomic().
    PostgreSQL's READ COMMITTED isolation then re-checks rows after lock waits.
    """

    # Lock in a stable order to reduce deadlock risk if multiple administrators
    # edit privileged users concurrently. These locks last until commit.
    return list(
        User.objects.filter(is_active=True, is_superuser=True)
        .order_by("pk")
        .select_for_update()
        .values_list("pk", flat=True)
    )


def _assert_actor_authorized(actor_id, active_superuser_ids):
    """Recheck privileged access after locking active superuser rows."""

    if actor_id not in active_superuser_ids:
        raise AccessRevoked("Your superuser access is no longer active.")
    return _assert_current_actor(actor_id, superuser_only=True)


def _lock_target(user_id):
    """Lock the target User row inside the same atomic transaction.

    This prevents a concurrent status or privilege update from silently
    overwriting the administrator's change while it is being validated.
    """
    try:
        return User.objects.select_for_update().get(pk=user_id)
    except User.DoesNotExist:
        raise InputError("User not found.", "id")


def _protect_privileged_change(actor, target, active_superuser_ids, new_active, new_superuser):
    """Keep an administrator from locking out themselves or the installation.

    Check the *resulting* active + superuser state because deactivation and
    demotion are distinct operations that can both remove emergency access.
    """
    if target.pk == actor.pk:
        if not new_active:
            raise InputError("You cannot deactivate your own account.")
        if not new_superuser:
            raise InputError("You cannot remove your own superuser access.")

    was_active_superuser = target.is_active and target.is_superuser
    will_be_active_superuser = new_active and new_superuser

    # A last-admin check must consider both flags. A superuser who is inactive
    # cannot sign in through Django's ordinary authentication backend.
    if was_active_superuser and not will_be_active_superuser:
        if len(active_superuser_ids) <= 1:
            raise InputError("The last active superuser cannot be deactivated or demoted.")


def _audit(event, actor_id, target_id, **details):
    # No secret credentials, passwords, password hashes, or setup links here.
    audit_logger.info(
        "event=%s actor_id=%s target_id=%s details=%s",
        event,
        actor_id,
        target_id,
        details,
    )


@csrf_protect
@require_http_methods(["GET", "POST"])
@user_management_api_required()
def managed_users(request):
    """GET paginated users; POST a new account with an admin-provided password."""

    if request.method == "GET":
        # Filter and paginate in PostgreSQL, rather than loading every account
        # into the browser. This also keeps responses predictable as SURFACE grows.
        search = (request.GET.get("search") or "").strip()[:120]
        status = request.GET.get("status", "all")
        if status not in ("all", "active", "inactive"):
            return _error("Invalid status filter.", field="status")

        try:
            page = max(1, int(request.GET.get("page", "1")))
            page_size = int(request.GET.get("page_size", "20"))
        except (TypeError, ValueError):
            return _error("Invalid pagination parameters.")

        if page_size not in (10, 20, 25, 50, 100):
            return _error("Invalid page size.", field="page_size")

        queryset = User.objects.all().prefetch_related("groups")

        if search:
            # Group names are joined through a many-to-many relation. ``distinct``
            # prevents duplicate users when several groups match the search.
            queryset = queryset.filter(
                Q(username__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(email__icontains=search)
                | Q(groups__name__icontains=search)
            ).distinct()

        if status != "all":
            queryset = queryset.filter(is_active=(status == "active"))

        group_id = request.GET.get("group", "")
        if group_id:
            try:
                group_id = int(group_id)
                if group_id < 1:
                    raise ValueError
            except ValueError:
                return _error("Invalid group filter.", field="group")
            queryset = queryset.filter(groups__pk=group_id)

        # Accept only known sort fields. Never interpolate arbitrary request
        # parameters into order_by() or rely on client-provided ORM field names.
        ordering = {
            "username": "username",
            "name": "first_name",
            "email": "email",
            "status": "is_active",
            "superuser": "is_superuser",
            "last_login": "last_login",
            "date_joined": "date_joined",
        }
        sort = request.GET.get("sort", "username")
        if sort not in ordering:
            return _error("Invalid sort field.", field="sort")
        descending = request.GET.get("descending", "false")
        if descending not in ("true", "false"):
            return _error("Invalid sort direction.")
        prefix = "-" if descending == "true" else ""
        # PK is a tie-breaker for stable pagination when multiple users have
        # the same name, date, status, or other selected sort value.
        queryset = queryset.order_by(prefix + ordering[sort], "pk")

        paginator = Paginator(queryset, page_size)
        page_object = paginator.get_page(page)
        return JsonResponse({
            "results": [_serialize_user(user) for user in page_object.object_list],
            "total": paginator.count,
            "page": page_object.number,
            "page_size": page_size,
        })

    try:
        data = _body(
            request,
            {"username", "first_name", "last_name", "email", "password", "groups", "is_superuser"},
        )
        identity = _validate_identity(data, creating=True)
        groups = _validate_groups(data)
        # A group-based manager can create ordinary accounts, but must not
        # send even a false is_superuser field: they are never authorized to
        # write this sensitive flag.
        if "is_superuser" in data and not request.user.is_superuser:
            raise AccessRevoked("Only a superuser can set superuser access.")
        is_superuser = _boolean(data, "is_superuser", default=False)
        # Validate in the context of the future account before creating it.
        # No plaintext password is ever saved to the database during validation.
        pending_user = User(**identity)
        _validate_new_password(data.get("password"), pending_user)

        try:
            with transaction.atomic():
                # An ordinary creation needs only mapped write access. Only
                # privilege creation needs active-superuser locks/checks.
                if is_superuser:
                    active_superuser_ids = _lock_active_superusers()
                    _assert_actor_authorized(request.user.pk, active_superuser_ids)
                else:
                    _assert_current_actor(request.user.pk, "write")

                # create_user hashes the password and defaults is_staff to False.
                # We do not assign is_staff or expose it in the frontend.
                user = User.objects.create_user(
                    password=data["password"],
                    is_active=True,
                    is_superuser=is_superuser,
                    **identity
                )
                # Django stores membership in its built-in User.groups M2M table.
                # Keep account creation and group assignment in one transaction.
                user.groups.set(groups)
                user = User.objects.prefetch_related("groups").get(pk=user.pk)
        except IntegrityError:
            # A concurrent create can violate username uniqueness after validation.
            raise InputError("Username already exists.", "username")

        _audit("user_created", request.user.pk, user.pk, superuser=user.is_superuser)
        return JsonResponse({"user": _serialize_user(user)}, status=201)

    except AccessRevoked as exc:
        return _error(str(exc), status=403)
    except InputError as exc:
        return _error(str(exc), field=exc.field)


@csrf_protect
@require_http_methods(["PATCH"])
@user_management_api_required("write")
def managed_user_detail(request, user_id):
    """Edit personal information, groups and superuser status only."""

    try:
        data = _body(
            request,
            {"username", "first_name", "last_name", "email", "groups", "is_superuser"},
        )
        if not data:
            raise InputError("No changes supplied.")

        with transaction.atomic():
            # Ordinary account edits use mapped write permission. Editing
            # the is_superuser flag is a separate, superuser-only operation.
            # Lock privileged users *only* for that sensitive operation.
            if "is_superuser" in data:
                active_superuser_ids = _lock_active_superusers()
                actor = _assert_actor_authorized(request.user.pk, active_superuser_ids)
            else:
                active_superuser_ids = None
                actor = _assert_current_actor(request.user.pk, "write")

            target = _lock_target(user_id)
            _protect_privileged_target(actor, target)
            identity = _validate_identity(data, current_user=target)
            groups = _validate_groups(data) if "groups" in data else None
            new_superuser = (
                _boolean(data, "is_superuser")
                if "is_superuser" in data else target.is_superuser
            )

            if "is_superuser" in data:
                _protect_privileged_change(
                    actor, target, active_superuser_ids,
                    target.is_active, new_superuser,
                )
            changed_fields = list(identity)
            for field, value in identity.items():
                setattr(target, field, value)

            if "is_superuser" in data:
                target.is_superuser = new_superuser
                changed_fields.append("is_superuser")

            if changed_fields:
                target.save(update_fields=changed_fields)

            if groups is not None:
                # Only change memberships when the PATCH explicitly includes
                # ``groups``. Omitting it must preserve existing memberships.
                target.groups.set(groups)
                changed_fields.append("groups")

            response_user = User.objects.prefetch_related("groups").get(pk=target.pk)

        _audit("user_updated", request.user.pk, target.pk, fields=changed_fields)
        return JsonResponse({"user": _serialize_user(response_user)})

    except AccessRevoked as exc:
        return _error(str(exc), status=403)
    except InputError as exc:
        status = 404 if exc.field == "id" else 400
        return _error(str(exc), status=status, field=exc.field)


@csrf_protect
@require_http_methods(["POST"])
@user_management_api_required("write")
def managed_user_status(request, user_id):
    """Activate/deactivate without deleting records or touching credentials.

    Keeping the User row preserves foreign keys, historical references, and
    group assignments. ``is_active`` is the Django-supported login switch.
    """

    try:
        data = _body(request, {"is_active"})
        if "is_active" not in data:
            raise InputError("Account status is required.", "is_active")
        new_active = _boolean(data, "is_active")

        # This endpoint changes account status only: privileges and groups are
        # deliberately not modified as a side effect.
        with transaction.atomic():
            # Activation/deactivation is superuser-only even when the actor
            # has user-management:write from a regular Django group.
            active_superuser_ids = _lock_active_superusers()
            actor = _assert_actor_authorized(request.user.pk, active_superuser_ids)
            target = _lock_target(user_id)
            _protect_privileged_change(
                actor, target, active_superuser_ids,
                new_active, target.is_superuser,
            )
            target.is_active = new_active
            target.save(update_fields=["is_active"])
            response_user = User.objects.prefetch_related("groups").get(pk=target.pk)

        _audit("user_status_changed", request.user.pk, target.pk, active=new_active)
        return JsonResponse({"user": _serialize_user(response_user)})

    except AccessRevoked as exc:
        return _error(str(exc), status=403)
    except InputError as exc:
        status = 404 if exc.field == "id" else 400
        return _error(str(exc), status=status, field=exc.field)


@csrf_protect
@require_http_methods(["POST"])
@user_management_api_required("write")
def managed_user_password(request, user_id):
    """Reset another user's password without touching self-service password UI.

    Administrators provide the temporary credential via a separate secure
    channel. This endpoint does not email, return, or log that credential.
    """

    try:
        data = _body(request, {"password"})
        with transaction.atomic():
            actor = _assert_current_actor(request.user.pk, "write")
            target = _lock_target(user_id)
            _protect_privileged_target(actor, target)
            if target.pk == actor.pk:
                raise InputError("Use your existing Change Password page for your own password.")

            _validate_new_password(data.get("password"), target)
            # Never assign target.password directly: set_password() invokes
            # Django's configured password hasher and stores only its output.
            target.set_password(data["password"])
            target.save(update_fields=["password"])

        _audit("password_reset_by_admin", request.user.pk, target.pk)
        # Password deliberately not echoed back to the client.
        return JsonResponse({"message": "Password updated successfully."})

    except AccessRevoked as exc:
        return _error(str(exc), status=403)
    except InputError as exc:
        status = 404 if exc.field == "id" else 400
        return _error(str(exc), status=status, field=exc.field)