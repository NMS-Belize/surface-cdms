"""SURFACE CDMS doctor command."""

import importlib.util
from pathlib import Path

import click

from surface_cdms.version import get_surface_version


def _check_python_package(package_name: str) -> bool:
    """
    Return True if a Python package can be imported.
    """

    return importlib.util.find_spec(package_name) is not None


def _print_check(label: str, passed: bool) -> None:
    """
    Print a simple OK/FAILED check line.
    """

    if passed:
        click.echo(f"{label}: " + click.style("OK", fg="green"))
    else:
        click.echo(f"{label}: " + click.style("FAILED", fg="red"))


def run_doctor() -> bool:
    """
    Run basic checks for the SURFACE CDMS installer.

    This command does not modify the system. It only checks whether the
    installer package has the expected dependencies and bundled assets.
    """

    package_dir = Path(__file__).resolve().parent

    wx_config_path = package_dir / "wx_config"
    wx_playbook_path = package_dir / "wx_playbook"

    checks = {
        "SURFACE CDMS version found": get_surface_version() != "unknown",
        "Django package available": _check_python_package("django"),
        "Celery package available": _check_python_package("celery"),
        "Redis Python package available": _check_python_package("redis"),
        "Ansible Runner package available": _check_python_package("ansible_runner"),
        "wx_config directory found": wx_config_path.exists(),
        "wx_playbook directory found": wx_playbook_path.exists(),
        "Configuration playbook found": (wx_playbook_path / "project" / "wx_configuration.yml").exists(),
    }

    click.echo(click.style("SURFACE CDMS Doctor", fg="green", bold=True))
    click.echo(f"Version: {get_surface_version()}")
    click.echo("")

    for label, passed in checks.items():
        _print_check(label, passed)

    all_passed = all(checks.values())

    click.echo("")

    if all_passed:
        click.echo(click.style("All checks passed.", fg="green"))
    else:
        click.echo(click.style("One or more checks failed.", fg="red"))

    return all_passed