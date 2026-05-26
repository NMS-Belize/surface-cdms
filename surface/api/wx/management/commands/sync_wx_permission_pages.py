from django.core.management.base import BaseCommand
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver

from wx.models import WxPermissionPages


class Command(BaseCommand):
    """
    Sync WxPermissionPages with *frontend UI pages*.

    We only want "real pages" (template routes / actual user pages),
    NOT API endpoints or helper endpoints used by AJAX calls.

    Rules we apply:
    - include only paths that start with "wx/"
    - exclude "api/" routes
    - exclude helper endpoints like "/get/", "/data", "/image", "/download" etc.
    """

    help = "Sync WxPermissionPages table with named URL patterns for frontend pages only."

    # Can tune these patterns over time.
    EXCLUDE_PATH_CONTAINS = [
        "/get/",
        "/data",
        "/image",
        "/download",
        "/create/",
        "/update/",
        "/delete/",
        "/load/",
        "/calc-",
        "/records",
        "/logs",
        "/task/",
    ]

    def handle(self, *args, **options):
        resolver = get_resolver()

        created_count = 0
        updated_count = 0

        def walk(patterns, prefix=""):
            """
            Recursively walk URL patterns and yield (route_name, route_path).
            """
            for p in patterns:
                if isinstance(p, URLResolver):
                    # URLResolver comes from include(...): recurse into children
                    yield from walk(p.url_patterns, prefix + str(p.pattern))
                elif isinstance(p, URLPattern):
                    # Leaf route
                    full_path = prefix + str(p.pattern)

                    # Only process if it has a name
                    if p.name:
                        yield p.name, full_path

        routes = list(walk(resolver.url_patterns))

        # Filter only UI pages
        page_routes = []
        for name, path in routes:
            path_str = str(path)

            # Only allow wx/ paths (UI pages)
            if not path_str.startswith("wx/") and path_str != "":
                continue

            # Exclude helper endpoints commonly used by AJAX
            if any(x in path_str for x in self.EXCLUDE_PATH_CONTAINS):
                continue

            # Good candidate UI page
            page_routes.append(name)

        page_routes = sorted(set(page_routes))

        for name in page_routes:
            nice_name = name.replace("-", " ").replace("_", " ").title()

            obj, created = WxPermissionPages.objects.get_or_create(
                url_name=name,
                defaults={
                    "name": nice_name,
                    "description": "",
                }
            )

            if created:
                created_count += 1
            else:
                # Keep display name consistent
                if obj.name != nice_name:
                    obj.name = nice_name
                    obj.save(update_fields=["name"])
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Synced WxPermissionPages (frontend pages only). "
                f"Created={created_count}, Updated={updated_count}, Total={len(page_routes)}"
            )
        )