"""SURFACE CDMS information command."""

import json
import platform
import sys
from pathlib import Path

import click

from surface_cdms.version import get_surface_version, normalize_surface_version


INSTALL_METADATA_PATH = Path.home() / ".surface-cdms" / "install.json"


def read_install_metadata() -> dict | None:
    """
    Read local SURFACE CDMS install metadata if it exists.

    This file is created by the installer GUI and updated after the install
    playbook finishes.
    """

    if not INSTALL_METADATA_PATH.exists():
        return None

    try:
        with INSTALL_METADATA_PATH.open("r", encoding="utf-8") as metadata_file:
            return json.load(metadata_file)

    except json.JSONDecodeError:
        return {
            "install_status": "invalid",
            "metadata_error": f"Invalid JSON in {INSTALL_METADATA_PATH}",
        }


def show_info() -> None:
    """
    Display useful information about the SURFACE CDMS installer environment.
    """

    package_dir = Path(__file__).resolve().parent
    metadata = read_install_metadata()

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
    click.echo(f"Installer version: {normalize_surface_version(get_surface_version())}")
    click.echo(f"Python executable: {sys.executable}")
    click.echo(f"Python version: {platform.python_version()}")
    click.echo(f"Operating system: {os_name} {os_version}")
    click.echo(f"Installer package path: {package_dir}")
    click.echo("")

    click.echo(click.style("Installation", fg="green", bold=True))

    if metadata is None:
        click.echo("Install status: not installed")
        click.echo(f"Metadata file: {INSTALL_METADATA_PATH} (not found)")
        return

    install_status = metadata.get("install_status", "unknown")

    click.echo(f"Install status: {install_status}")
    click.echo(f"Metadata file: {INSTALL_METADATA_PATH}")

    if metadata.get("metadata_error"):
        click.echo(click.style(metadata["metadata_error"], fg="red"))
        return

    surface_cdms_version = metadata.get("surface_cdms_version")
    surface_repo_path = metadata.get("surface_repo_path")
    compose_file = metadata.get("compose_file")
    install_started_at = metadata.get("install_started_at")
    installed_at = metadata.get("installed_at")
    failed_at = metadata.get("failed_at")
    install_duration_minutes = metadata.get("install_duration_minutes")

    if surface_cdms_version:
        click.echo(f"Installed SURFACE version: {surface_cdms_version}")

    if surface_repo_path:
        click.echo(f"SURFACE install path: {surface_repo_path}")

    if compose_file:
        click.echo(f"Docker Compose file: {compose_file}")

    if install_started_at:
        click.echo(f"Install started at: {install_started_at}")

    if installed_at:
        click.echo(f"Installed at: {installed_at}")

    if failed_at:
        click.echo(f"Failed at: {failed_at}")

    if install_duration_minutes is not None:
        click.echo(f"Install duration: {install_duration_minutes} minutes")