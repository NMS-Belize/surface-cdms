"""
permissions_map.py

This module documents and centralizes the SURFACE Wx permissions system.

Why this file exists
--------------------
- Document how permissions work for current/future developers.
- Provide a single place to map helper/AJAX endpoints to their parent UI pages.
- Reduce duplication and mistakes (parent/action copied incorrectly across many views).

Core idea
---------
We treat permissions as "page access" with three actions:

    read   -> view the page + fetch data used by the page
    write  -> create/update/upload/process data used by the page
    delete -> delete records/files belonging to the page

Permissions are stored in WxGroupPageAccess:
- Each row links a Django Group -> a WxPermissionPages entry (url_name) with can_read/can_write/can_delete flags.
- Rules enforced:
    * write/delete requires read
    * at least one permission must be True (no all-false rows)

-------------------------------------------------------------------------------
1) UI PAGES ("Pages")
-------------------------------------------------------------------------------
Definition:
- A "page" is a route that renders a full HTML template / screen.
- Typically a class-based view using .as_view() and a named URL pattern.

How it is secured:
- Pages use WxPermissionRequiredMixin.
- The mixin auto-detects the current route name (url_name) and enforces permissions.
- Pages require at least "read" to view (simply by nature of the call).

Example:
    # Important: the mixin must come first in the inheritance list.
    class SpatialAnalysisView(WxPermissionRequiredMixin, LoginRequiredMixin, TemplateView):
        template_name = "wx/spatial_analysis.html"

-------------------------------------------------------------------------------
2) HELPER / AJAX ENDPOINTS ("Helpers")
-------------------------------------------------------------------------------
Definition:
- A helper endpoint is NOT a page.
- It returns JSON/files or performs actions called by a page (Axios/fetch).
- These endpoints are often function views and may be CSRF exempt.

How it is secured:
We support two styles:

A) MAPPED (preferred default)
- Use @wx_mapped_permission_required for fxn based views
- Or for CBV's use: @method_decorator(wx_mapped_permission_required, name="dispatch")
- The decorator resolves the endpoint url_name and looks it up in ENDPOINT_PARENT_PAGE
- This forces developers to keep ENDPOINT_PARENT_PAGE updated

B) MANUAL OVERRIDE (exceptions)
- Use @wx_permission_required("<parent_page>", "<action>")
- Bypasses ENDPOINT_PARENT_PAGE
- Use when an endpoint is shared or has special rules

-------------------------------------------------------------------------------
ACTION RULES (how we decide read/write/delete)
-------------------------------------------------------------------------------
Typical mapping by HTTP method:
- GET / HEAD / OPTIONS -> read
- POST / PUT / PATCH   -> write
- DELETE               -> delete

Note:
- Many Django apps do not use HTTP DELETE.
- Endpoints that "delete things" should still be treated as action="delete"
  even if the request method is POST/GET.

-------------------------------------------------------------------------------
FRONTEND HIDING (UI/UX layer)
-------------------------------------------------------------------------------
Backend enforcement is the security layer (required).
Frontend hiding is UX polish.

Note: Remember to load the filters

In Django templates we hide buttons/menus based on "page:action" permissions.

Format:
    "<url_name>:<action>"

Examples:
    {% if request|has_any_feature_permission:"manual-data-import:write" %}
        <button>Upload</button>
    {% endif %}

    {% if request|has_any_feature_permission:"manual-data-import:delete" %}
        <button>Delete</button>
    {% endif %}

Superuser-only UI:
    {% if request.user.is_superuser %}
        <button>Admin Only</button>
    {% endif %}

-------------------------------------------------------------------------------
ROLL-OUT ORDER (important)
-------------------------------------------------------------------------------
Apply permissions in this order to avoid breaking pages:

1) Secure the page view (mixin) first
2) Secure helper endpoints used by the page (decorators)
3) Hide UI buttons/options for that page
4) Move on to the next page

-------------------------------------------------------------------------------
GOTCHAS / REMINDERS
-------------------------------------------------------------------------------
- Some pages call endpoints located in other modules — secure those too.
- If an endpoint is shared by multiple pages:
    * choose a primary parent page permission OR
    * split the endpoint into specific endpoints for each page
- Downloads:
    * use read for safe exports
    * use write if the export is sensitive or "generates" data
- manage-permissions should remain superuser-only unless explicitly designed otherwise.

-------------------------------------------------------------------------------
ENDPOINT → PARENT PAGE PERMISSION MAP
-------------------------------------------------------------------------------
This mapping documents which permission each helper endpoint inherits.

Format:
    "<endpoint_url_name>": ("<parent_page_url_name>", "<action>")

Strict mode:
- If settings.WX_PERMISSIONS_STRICT_MAP is True, missing entries should raise loudly
  so developers are forced to update this file.
"""






# NOTE:
# Only endpoints protected with @wx_mapped_permission_required must appear here.
# If an endpoint uses manual @wx_permission_required(...) it does not need mapping.

ENDPOINT_PARENT_PAGE = {
    # -------------------------------------------------------------------------
    # Manual Data Import Page (manual-data-import)
    # -------------------------------------------------------------------------
    # Page:
    #   manual-data-import (GET page)
    # Helpers:
    #   list uploaded files, validate imports, upload imports, remove/delete files
    "manual-data-files": ("manual-data-import", "read"),
    "check-manual-import": ("manual-data-import", "write"),
    "upload-manual-data-file": ("manual-data-import", "write"),
    "remove-manual-data-file": ("manual-data-import", "read"),
    "data-import-manual-delete": ("manual-data-import", "delete"),


    # -------------------------------------------------------------------------
    # Monthly Capture Page (monthly-form)
    # -------------------------------------------------------------------------
    # Page:
    #   monthly-form (GET page)
    # Helpers:
    #   load form, update form, update empty cols, delete monthly form
    "load-monthly-form": ("monthly-form", "read"),
    "update-monthly-form": ("monthly-form", "write"),
    "update-empty-col-monthly-capture-form": ("monthly-form", "write"),
    "delete-monthly-form-row": ("monthly-form", "delete"),


    # -------------------------------------------------------------------------
    # Synop Capture Page (synop-capture-form)
    # -------------------------------------------------------------------------
    # Page:
    #   synop-capture-form (GET page)
    # Helpers:
    #   load form, update form
    "load-synop-report": ("synop-capture-form", "read"),
    "update-synop-report": ("synop-capture-form", "write"),
    "calculate-pressure-difference": ("synop-capture-form", "write"),
    "calculate-24-hr-precipitation": ("synop-capture-form", "write"),
    "update-empty-col-synop-capture-report": ("synop-capture-form", "write"),
    "synop-push-to-wis2box": ("synop-capture-form", "write"),
    "delete-synop-report-row": ("synop-capture-form", "delete"),


    # -------------------------------------------------------------------------
    # Data Inventory (data-inventory)
    # -------------------------------------------------------------------------
    # Page:
    #   data-inventory (GET page)
    # Helpers:
    #   Uses various api endpoint to retrieve and display data


    # -------------------------------------------------------------------------
    # Data Export Page (data-export)
    # -------------------------------------------------------------------------
    # Page:
    #   data-export (GET page)
    # Helpers:
    #   fetch export files (csv), download exports (csv), download exports (xlsx),
    #   Combine csv files, combine xlsx files, delete export files
    #   Schedule data export, fetch export files (xlsx)
    "data-export-files": ("data-export", "read"),
    "data-export-download": ("data-export", "read"),
    "data-export-download-xlsx": ("data-export", "read"),
    "combine-xlsx": ("data-export", "read"),
    "data-export-delete": ("data-export", "delete"),
    "data-export-schedule": ("data-export", "read"),
    "combine-files": ("data-export", "read"),


    # -------------------------------------------------------------------------
    # Maintenance Report Page (maintenance-reports)
    # -------------------------------------------------------------------------
    # Page:
    #   maintenance-reports (GET page)
    "get-maint-report-list": ("maintenance-reports", "read"),
    "delete-maint-report": ("maintenance-reports", "delete"),
    "update-maint-report": ("maintenance-reports", "write"),
    "view-maintenance-report": ("maintenance-reports", "read"),
    "approve-maint-report": ("maintenance-reports", "write"),
    "create-maint-report": ("maintenance-reports", "write"),
    "update-maint-report-equip-type": ("maintenance-reports", "write"),
    "update-maint-report-condition": ("maintenance-reports", "write"),
    "update-maint-report-contacts": ("maintenance-reports", "write"),
    "update-maint-report-datalogger": ("maintenance-reports", "write"),
    "update-maint-report-summary": ("maintenance-reports", "write"),
    "get-maint-report": ("maintenance-reports", "read"),
    "new-maintenance-report": ("maintenance-reports", "write"),


    # -------------------------------------------------------------------------
    # Equipment Inventory Page (equipment-inventory)
    # -------------------------------------------------------------------------
    # Page:
    #   equipment-inventory (GET page)
    "get-equipment-inventory": ("equipment-inventory", "read"),
    "create-equipment-inventory": ("equipment-inventory", "write"),
    "delete-equipment-inventory": ("equipment-inventory", "delete"),
    "update-equipment-inventory": ("equipment-inventory", "write"),


    # -------------------------------------------------------------------------
    # Station Pages (stations-list)
    # -------------------------------------------------------------------------
    # Page:
    #   stations-list (GET page)
    "station-create": ("stations-list", "write"),
    "station-detail": ("stations-list", "read"),
    "station-metadata": ("stations-list", "read"),
    "station-update": ("stations-list", "write"),
    "station-delete": ("stations-list", "delete"),
    "stationfiles-list": ("stations-list", "read"),
    "stationfile-create": ("stations-list", "write"),
    "stationfile-delete": ("stations-list", "delete"),
    "stationvariable-list": ("stations-list", "read"),
    "stationvariable-create": ("stations-list", "write"),
    "stationvariable-delete": ("stations-list", "delete"),


    # -------------------------------------------------------------------------
    # Station Oscar Export Page (station-oscar-export)
    # -------------------------------------------------------------------------
    # Page:
    #   station-oscar-export (GET page)
    # Notes:
    #   write is required to see the export buttons


    # -------------------------------------------------------------------------
    # Station Monitoring Page (stations-monitoring)
    # -------------------------------------------------------------------------
    # Page:
    #   stations-monitoring (GET page)
    "monitoring-map-data": ("stations-monitoring", "read"),
    "monitoring-station-data": ("stations-monitoring", "read"),
    "monitoring-chart-data": ("stations-monitoring", "read"),


    # -------------------------------------------------------------------------
    # WIS2 Dashboard Page (wis2-dashboard)
    # -------------------------------------------------------------------------
    # Page:
    #   wis2-dashboard (GET page)
    "wis2dashboard_records_list": ("wis2-dashboard", "read"),
    "wis2-publishing-logs": ("wis2-dashboard", "read"),
    "wis2-download-logs": ("wis2-dashboard", "read"),
    "wis2-download-Message": ("wis2-dashboard", "read"),
    "push-to-wis2box": ("wis2-dashboard", "write"),
    "wis2box-publish-list": ("wis2-dashboard", "read"),
    "local-wis-credentials": ("wis2-dashboard", "write"),
    "regional-wis-credentials": ("wis2-dashboard", "write"),
    "config-wis-stations": ("wis2-dashboard", "write"),


    # -------------------------------------------------------------------------
    # Data Validation Page (quality-control)
    # -------------------------------------------------------------------------
    # Page:
    #   quality-control (GET page)
    "get-qc-description": ("quality-control", "read"),
    "get-update-quality-control": ("quality-control", "write"),
    "bulk-update-quality-control": ("quality-control", "write"),
    "update-threshold-reference-station": ("quality-control", "write"),
    "update-global-threshold": ("quality-control", "write"),


    # -------------------------------------------------------------------------
    # Reference Station Page (reference-station)
    # -------------------------------------------------------------------------
    # Page:
    #   reference-station (GET page)
    "load-reference-stations": ("reference-station", "read"),
    "load-reference-station-variables": ("reference-station", "read"),
    "load-reference-station-thresholds": ("reference-station", "read"),
    "create-reference-station": ("reference-station", "write"),
    "modify-reference-station": ("reference-station", "write"),
    "toggle-reference-station-active": ("reference-station", "write"),
    "save-reference-station-thresholds": ("reference-station", "write"),
    "delete-reference-station": ("reference-station", "delete"),


    # -------------------------------------------------------------------------
    # Range Threshold Page (range-threshold)
    # -------------------------------------------------------------------------
    # Page:
    #   range-threshold (GET page)
    "range-threshold-get": ("range-threshold", "read"),
    "range-threshold-update": ("range-threshold", "write"),
    "range-threshold-delete": ("range-threshold", "delete"),


    # -------------------------------------------------------------------------
    # Step Threshold Page (step-threshold)
    # -------------------------------------------------------------------------
    # Page:
    #   step-threshold (GET page)
    "step-threshold-get": ("step-threshold", "read"),
    "step-threshold-update": ("step-threshold", "write"),
    "step-threshold-delete": ("step-threshold", "delete"),


    # -------------------------------------------------------------------------
    # Persist Threshold Page (persist-threshold)
    # -------------------------------------------------------------------------
    # Page:
    #   persist-threshold (GET page)
    "persist-threshold-get": ("persist-threshold", "read"),
    "persist-threshold-update": ("persist-threshold", "write"),
    "persist-threshold-delete": ("persist-threshold", "delete"),


    # -------------------------------------------------------------------------
    # Station Report Page (station-report)
    # -------------------------------------------------------------------------
    # Page:
    #   station-report (GET page)
    # Notes:
    #   write is required to see the export to CSV button


    # -------------------------------------------------------------------------
    # Variable Report Page (variable-report)
    # -------------------------------------------------------------------------
    # Page:
    #   variable-report (GET page)
    # Notes:
    #   write is required to see the export to CSV button


    # -------------------------------------------------------------------------
    # Product Compare Page (product-compare)
    # -------------------------------------------------------------------------
    # Page:
    #   product-compare (GET page)
    # Notes:
    #   Export is hidden behind write permissions and the delete btn behid delete permissions
   
   
    # -------------------------------------------------------------------------
    # Yearly Average Page (yearly-average)
    # -------------------------------------------------------------------------
    # Page:
    #   yearly-average (GET page)
    # Notes:
    #   ....
    "get-yearly-average": ("yearly-average", "read"),
   
   
    # -------------------------------------------------------------------------
    # Spatial Analysis Page (spatial-analysis)
    # -------------------------------------------------------------------------
    # Page:
    #   spatial-analysis (GET page)
    # Notes:
    #   ....
    "spatial-analysis-image": ("spatial-analysis", "read"),
    "spatial-analysis-data": ("spatial-analysis", "read"),
    "spatial-analysis-interpolate-data": ("spatial-analysis", "write"),
    "spatial-analysis-color-bar": ("spatial-analysis", "read"),


    # -------------------------------------------------------------------------
    # Extremes and Means Page (extremes-means)
    # -------------------------------------------------------------------------
    # Page:
    #   extremes-means (GET page)


    # -------------------------------------------------------------------------
    # Wave Data Analysis Page (wave-data)
    # -------------------------------------------------------------------------
    # Page:
    #   wave-data (GET page)
    "get-wave-data": ("wave-data", "read"),


    # -------------------------------------------------------------------------
    # Agrometeorology: Monthly & Seasonal Page (agromet-summaries)
    # -------------------------------------------------------------------------
    # Page:
    #   agromet-summaries (GET page)
    "get-agromet-summaries-data": ("agromet-summaries", "read"),


    # -------------------------------------------------------------------------
    # Agrometeorology: Calculated Products Page (agromet-products)
    # -------------------------------------------------------------------------
    # Page:
    #   agromet-products (GET page)
    "get-agromet-products-data": ("agromet-products", "read"),


    # -------------------------------------------------------------------------
    # Manage Permissions Page (manage-permissions)
    # -------------------------------------------------------------------------
    # Page:
    #   manage-permissions (GET page)
    "groups-info": ("manage-permissions", "read"),
    "users-groups-info": ("manage-permissions", "read"),
    "users-groups-update": ("manage-permissions", "write"),
    "permission-pages-info": ("manage-permissions", "read"),
    "group-page-access": ("manage-permissions", "write"),  # saving perms is write


    # -------------------------------------------------------------------------
    # Configuration Settings Page (configuration-settings)
    # -------------------------------------------------------------------------
    # Page:
    #   configuration-settings (GET page)
    "upload-document": ("configuration-settings", "write"),
    "download-document": ("configuration-settings", "write"),
    "organization_logo_details": ("configuration-settings", "write"),
    "upload_or_delete_organization_logo": ("configuration-settings", "write"),
    "download_organization_logo": ("configuration-settings", "write"),


    # # Add more mappings below...
}

from django.conf import settings

def get_parent_permission(endpoint_url_name: str):
    """
    Return (parent_page, action) for the endpoint url_name if defined.

    If WX_PERMISSIONS_STRICT_MAP is True:
    - raise an error when an endpoint is missing from the map
      (helps catch omissions during development)
    """
    perm = ENDPOINT_PARENT_PAGE.get(endpoint_url_name)

    if perm is None and getattr(settings, "WX_PERMISSIONS_STRICT_MAP", False):
        raise KeyError(
            f"Endpoint '{endpoint_url_name}' missing from ENDPOINT_PARENT_PAGE in permissions_map.py"
        )

    return perm
