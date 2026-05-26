from django.conf import settings

def get_installer_version(req):
    return {
        'APP_VERSION': settings.APP_VERSION,
        'APP_VERSION_STAGE': settings.APP_VERSION_STAGE,
        'APP_VERSION_LABEL': settings.APP_VERSION_LABEL
    }