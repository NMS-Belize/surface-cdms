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

    click.echo(click.style("SURFACE CDMS", fg="green", bold=True))
    click.echo(f"Version: {get_surface_version()}")
    click.echo(f"Python executable: {sys.executable}")
    click.echo(f"Python version: {platform.python_version()}")
    click.echo(f"Operating system: {platform.system()} {platform.release()}")
    click.echo(f"Installer package path: {package_dir}")