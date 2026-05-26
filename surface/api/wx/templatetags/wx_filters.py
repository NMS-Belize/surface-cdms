from django import template

register = template.Library()


@register.filter
def has_any_feature_permission(request, features: str) -> bool:
    """
    UI gate.

    Input:
      features = "manual-data-import:read,manual-data-import:write"

    Behavior:
    - Anonymous -> False
    - Superuser -> True
    - If request.user_permissions contains "*" -> True
    - Otherwise -> check membership in request.user_permissions
    """
    if not hasattr(request, "user") or not request.user.is_authenticated:
        return False

    # Superusers see everything in the UI
    if request.user.is_superuser:
        return True

    perms = getattr(request, "user_permissions", None)
    if not perms:
        return False

    # Middleware sets "*" for superusers; keep this as a fast-path anyway
    if "*" in perms:
        return True

    feature_list = [f.strip() for f in features.split(",") if f.strip()]
    return any(f in perms for f in feature_list)
