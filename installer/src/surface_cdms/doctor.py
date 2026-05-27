"""SURFACE CDMS doctor command."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import click

from surface_cdms.install import get_packaged_surface_artifact_path
from surface_cdms.version import get_surface_version, normalize_surface_version


INSTALL_METADATA_PATH = Path.home() / ".surface-cdms" / "install.json"


def ensure_current_python_bin_on_path() -> None:
    """
    Ensure commands installed in the active Python environment are available.

    This is especially important for pipx installs. The `surface` command runs
    from the pipx environment, but subprocesses may not automatically see the
    pipx venv's bin directory.

    Do not use Path.resolve() here because venv/pipx Python executables may be
    symlinks to the system Python. We want the venv/pipx bin directory itself.
    """

    python_bin_dir = Path(sys.executable).parent
    current_path = os.environ.get("PATH", "")

    if str(python_bin_dir) not in current_path.split(os.pathsep):
        os.environ["PATH"] = str(python_bin_dir) + os.pathsep + current_path


def _check_python_package(package_name: str) -> bool:
    """
    Return True if a Python package can be imported.
    """

    return importlib.util.find_spec(package_name) is not None


def _check_command(command: list[str]) -> bool:
    """
    Return True if a command runs successfully.
    """

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def _print_check(label: str, passed: bool) -> None:
    """
    Print a simple OK/FAILED check line.
    """

    if passed:
        click.echo(f"{label}: " + click.style("OK", fg="green"))
    else:
        click.echo(f"{label}: " + click.style("FAILED", fg="red"))


def _print_info(label: str, value: str) -> None:
    """
    Print an informational line.
    """

    click.echo(f"{label}: {value}")


def read_install_metadata() -> tuple[dict | None, str | None]:
    """
    Read local SURFACE CDMS install metadata.

    Returns:
        (metadata, error_message)

    If metadata does not exist, both values are None.
    """

    if not INSTALL_METADATA_PATH.exists():
        return None, None

    try:
        with INSTALL_METADATA_PATH.open("r", encoding="utf-8") as metadata_file:
            return json.load(metadata_file), None

    except json.JSONDecodeError as error:
        return None, f"Install metadata is invalid JSON: {error}"

    except OSError as error:
        return None, f"Could not read install metadata: {error}"


def run_doctor() -> bool:
    """
    Run checks for the SURFACE CDMS installer and installed SURFACE app.

    This command does not modify the system.
    """

    ensure_current_python_bin_on_path()

    package_dir = Path(__file__).resolve().parent

    wx_config_path = package_dir / "wx_config"
    wx_playbook_path = package_dir / "wx_playbook"
    ansible_playbook_path = shutil.which("ansible-playbook")

    try:
        surface_artifact_path = get_packaged_surface_artifact_path()
        artifact_exists = surface_artifact_path.exists()
    except Exception:
        surface_artifact_path = None
        artifact_exists = False

    installer_checks = {
        "SURFACE CDMS version found": get_surface_version() != "unknown",
        "Django package available": _check_python_package("django"),
        "Celery package available": _check_python_package("celery"),
        "Redis Python package available": _check_python_package("redis"),
        "Ansible package available": _check_python_package("ansible"),
        "Ansible Runner package available": _check_python_package("ansible_runner"),
        "ansible-playbook command available": ansible_playbook_path is not None,
        "docker command available": shutil.which("docker") is not None,
        "docker compose available": _check_command(["docker", "compose", "version"]),
        "wx_config directory found": wx_config_path.exists(),
        "wx_playbook directory found": wx_playbook_path.exists(),
        "Configuration playbook found": (wx_playbook_path / "project" / "wx_configuration.yml").exists(),
        "Packaged SURFACE app artifact found": artifact_exists,
    }

    metadata, metadata_error = read_install_metadata()

    installation_checks = {}

    if metadata_error:
        installation_checks["Install metadata readable"] = False

    elif metadata is None:
        # Not installed yet is not a doctor failure.
        installation_checks["Install metadata found"] = None

    else:
        surface_repo_path = Path(metadata.get("surface_repo_path", ""))
        compose_file = Path(metadata.get("compose_file", ""))
        install_status = metadata.get("install_status", "unknown")

        installation_checks = {
            "Install metadata found": True,
            "Install status is installed": install_status == "installed",
            "SURFACE install path found": surface_repo_path.exists(),
            "Docker Compose file found": compose_file.exists(),
        }

    click.echo(click.style("SURFACE CDMS Doctor", fg="green", bold=True))
    click.echo(f"Version: {normalize_surface_version(get_surface_version())}")
    click.echo(f"Python executable: {sys.executable}")

    if ansible_playbook_path:
        click.echo(f"ansible-playbook path: {ansible_playbook_path}")

    if surface_artifact_path:
        click.echo(f"SURFACE artifact path: {surface_artifact_path}")

    click.echo("")
    click.echo(click.style("Installer checks", fg="green", bold=True))

    for label, passed in installer_checks.items():
        _print_check(label, passed)

    click.echo("")
    click.echo(click.style("Installation checks", fg="green", bold=True))

    if metadata_error:
        _print_check("Install metadata readable", False)
        click.echo(click.style(metadata_error, fg="red"))

    elif metadata is None:
        _print_info("Install status", "not installed")
        _print_info("Metadata file", f"{INSTALL_METADATA_PATH} (not found)")

    else:
        _print_info("Metadata file", str(INSTALL_METADATA_PATH))
        _print_info("Install status", metadata.get("install_status", "unknown"))

        if metadata.get("surface_cdms_version"):
            _print_info("Installed SURFACE version", metadata["surface_cdms_version"])

        if metadata.get("surface_repo_path"):
            _print_info("SURFACE install path", metadata["surface_repo_path"])

        if metadata.get("compose_file"):
            _print_info("Docker Compose file", metadata["compose_file"])

        click.echo("")

        for label, passed in installation_checks.items():
            _print_check(label, passed)

    installer_passed = all(installer_checks.values())

    # If SURFACE is not installed yet, do not fail doctor.
    if metadata is None and not metadata_error:
        installation_passed = True
    else:
        installation_passed = all(
            passed is True for passed in installation_checks.values()
        )

    all_passed = installer_passed and installation_passed

    click.echo("")

    if all_passed:
        click.echo(click.style("All required checks passed.", fg="green"))
    else:
        click.echo(click.style("One or more checks failed.", fg="red"))

    return all_passed