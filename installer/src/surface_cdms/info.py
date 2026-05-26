"""SURFACE CDMS information command."""

import platform
import sys
from pathlib import Path

import click

from surface_cdms.version import get_surface_version


def show_info() -> None:
    """
    Display useful information about the SURFACE CDMS installer environment.
    """

    package_dir = Path(__file__).resolve().parent

    try:
        # This works on almost all modern Linux distros
        info = platform.freedesktop_os_release()
        os_name = info.get("NAME", platform.system())
        os_version = info.get("VERSION_ID", platform.release())
    except AttributeError:
        # Fallback
        os_name = platform.system()
        os_version = platform.release()

    click.echo(click.style("SURFACE CDMS", fg="green", bold=True))
    click.echo(f"Version: {get_surface_version()}")
    click.echo(f"Python executable: {sys.executable}")
    click.echo(f"Python version: {platform.python_version()}")
    click.echo(f"Operating system: {os_name} {os_version}")
    click.echo(f"Installer package path: {package_dir}")