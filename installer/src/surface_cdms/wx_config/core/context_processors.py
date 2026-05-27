from django.conf import settings
from surface_cdms.version import get_surface_version, normalize_surface_version

def get_installer_version(req):
    return {
        'APP_VERSION_LABEL': normalize_surface_version(get_surface_version())
    }