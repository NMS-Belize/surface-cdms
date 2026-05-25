from pathlib import Path


def get_surface_version() -> str:
    """
    Return the SURFACE CDMS platform version.

    During development, the VERSION file lives at the root of the repository:

        surface-cdms/VERSION

    This keeps the installer version and platform version aligned.
    """

    current_file = Path(__file__).resolve()

    for parent in current_file.parents:
        version_file = parent / "VERSION"

        if version_file.exists():
            return version_file.read_text(encoding="utf-8").strip()

    return "unknown"