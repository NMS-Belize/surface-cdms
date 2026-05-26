from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def get_surface_version() -> str:
    """
    Return the SURFACE CDMS platform version.

    During development, the VERSION file lives at the root of the repository.

    When installed from a wheel, the root VERSION file may not exist, so we
    fall back to the installed Python package metadata.
    """

    current_file = Path(__file__).resolve()

    # Development/editable install case:
    for parent in current_file.parents:
        version_file = parent / "VERSION"

        if version_file.exists():
            return version_file.read_text(encoding="utf-8").strip()

    # Wheel/normal install case:
    try:
        return version("surface-cdms")
    except PackageNotFoundError:
        return "unknown"