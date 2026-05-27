"""SURFACE CDMS install/configuration logic."""
import os
import sys
import getpass
from pathlib import Path

import ansible_runner
import click

from surface_cdms.version import get_surface_version


# Package directory:
# installer/src/surface_cdms/
PACKAGE_DIR = Path(__file__).resolve().parent

# Path containing the wx configuration playbook:
# installer/src/surface_cdms/wx_playbook/
WX_PLAYBOOK_PATH = PACKAGE_DIR / "wx_playbook"

# Path to sudo password file used by the configuration playbook.
SUDO_PASSWORD_PATH = WX_PLAYBOOK_PATH / "env" / "become_password"

# Extra variables file for the wx configuration web app playbook.
PLAYBOOK_EXTRAVARS = WX_PLAYBOOK_PATH / "env" / "extravars"

# Path to wx configuration web app project folder:
# installer/src/surface_cdms/wx_config/
WEBAPP_PROJECT_PATH = PACKAGE_DIR / "wx_config"

SURFACE_APP_EXTRAVARS = (WEBAPP_PROJECT_PATH / "ansible" / "surface_app" / "env" / "extravars")

ARTIFACTS_DIR = PACKAGE_DIR / "artifacts"


def wx_configuration(sudo_password):
    """
    Start the SURFACE CDMS configuration process.

    This function prepares the local configuration files needed by the
    Ansible playbook, then runs the playbook that starts the SURFACE
    configuration web app.
    """

    try:
        # Ensure pipx/venv-installed commands like ansible-playbook are on PATH.
        ensure_current_python_bin_on_path()
        
        # Reset runtime files so old installer values are not reused.
        reset_runtime_env_files()

        # Get the path to the packaged SURFACE app artifact.
        surface_artifact_path = get_packaged_surface_artifact_path()
        
        # Write out the current Linux username for local installations.
        write_user_to_file(
            getpass.getuser(),
            WEBAPP_PROJECT_PATH / "ansible" / "surface_app" / "env" / "user",
        )

        # Configure the web app playbook with the Django configuration app path.
        with PLAYBOOK_EXTRAVARS.open("w", encoding="utf-8") as extravars_file:
            extravars_file.write(f"\ndjango_webapp_path: {WEBAPP_PROJECT_PATH}")
            extravars_file.write(f"\nsurface_python_executable: {sys.executable}")

        # Configure the SURFACE app playbook
        with SURFACE_APP_EXTRAVARS.open("a", encoding="utf-8") as extravars_file:
            extravars_file.write(f"\nsurface_artifact_path: {surface_artifact_path}")
            extravars_file.write(f"\nsurface_artifact_version: {get_surface_version()}")

        # Write sudo password required by the Ansible playbook.
        with SUDO_PASSWORD_PATH.open("w", encoding="utf-8") as sudo_password_file:
            sudo_password_file.write(sudo_password)

        # Start the local web app used to configure and install SURFACE.
        playbook_result = ansible_runner.run(
            private_data_dir=str(WX_PLAYBOOK_PATH),
            playbook="wx_configuration.yml",
        )

        if playbook_result.status == "successful":
            click.echo(
                click.style(
                    "If the installation page does not automatically launch "
                    "within 10 seconds, open http://localhost:52376/",
                    fg="green",
                )
            )
            click.launch("http://localhost:52376/")
            return True

        click.echo(
            click.style(
                "\nAn error occurred while configuring SURFACE environment variables.",
                fg="red",
            )
        )
        click.echo(
            click.style(
                "See the SURFACE CDMS project documentation for help.",
                fg="red",
            )
        )

        return False

    except Exception as error:
        click.echo(
            click.style(
                "An error occurred during SURFACE installation.",
                fg="red",
            )
        )
        click.echo(
            click.style(
                "See the SURFACE CDMS project documentation for help.",
                fg="red",
            )
        )
        click.echo(f"{error}", err=True)

        return False


def write_user_to_file(name, filename):
    """
    Write the current Linux username to a file used by the installer.
    """

    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    filename.write_text(name, encoding="utf-8")


def reset_runtime_file(file_path):
    """
    Ensure a runtime file exists and is empty before the installer writes to it.

    This prevents old values from a previous installer run from being reused.
    """

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("", encoding="utf-8")


def reset_runtime_env_files():
    """
    Reset runtime env files used by Ansible Runner and the SURFACE config app.

    These files are packaged as empty placeholders, but during an installer run
    some of them may receive machine-specific values. Reset them each time.
    """

    runtime_files = [
        # Ansible Runner env files
        WX_PLAYBOOK_PATH / "env" / "become_password",
        WX_PLAYBOOK_PATH / "env" / "extravars",

        # SURFACE app installer env files
        WEBAPP_PROJECT_PATH / "ansible" / "surface_app" / "env" / "become_password",
        WEBAPP_PROJECT_PATH / "ansible" / "surface_app" / "env" / "user",
        WEBAPP_PROJECT_PATH / "ansible" / "surface_app" / "env" / "extravars",
        WEBAPP_PROJECT_PATH / "ansible" / "surface_app" / "env" / "config_status",
        WEBAPP_PROJECT_PATH / "ansible" / "surface_app" / "env" / "install_type",
    ]

    for file_path in runtime_files:
        reset_runtime_file(file_path)


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


def python_version_to_surface_version(version: str) -> str:
    """
    Convert Python-normalized prerelease versions to SURFACE-style versions.

    Example:
        0.2.0a3 -> 0.2.0-alpha.3
        0.2.0b1 -> 0.2.0-beta.1
        0.2.0rc1 -> 0.2.0-rc.1
    """

    if "rc" in version:
        base, number = version.split("rc", 1)
        return f"{base}-rc.{number}"

    if "a" in version:
        base, number = version.split("a", 1)
        return f"{base}-alpha.{number}"

    if "b" in version:
        base, number = version.split("b", 1)
        return f"{base}-beta.{number}"
    
    return version


def get_packaged_surface_artifact_path() -> Path:
    """
    Return the packaged same-version SURFACE app artifact path.

    Expected:
        surface_cdms/artifacts/surface-app-v<version>.tar.gz

    In installed wheel/pipx mode, Python may normalize versions:
        0.2.0-alpha.3 -> 0.2.0a3

    So we check both forms.
    """

    version = get_surface_version()

    candidate_versions = [
        version,
        python_version_to_surface_version(version),
    ]

    for candidate_version in candidate_versions:
        artifact_path = ARTIFACTS_DIR / f"surface-app-v{candidate_version}.tar.gz"

        if artifact_path.exists():
            return artifact_path

    matching_artifacts = sorted(ARTIFACTS_DIR.glob("surface-app-v*.tar.gz"))

    if len(matching_artifacts) == 1:
        return matching_artifacts[0]

    if len(matching_artifacts) > 1:
        raise FileNotFoundError(
            "Multiple SURFACE app artifacts were found, but none matched "
            f"version {version}: {matching_artifacts}"
        )

    raise FileNotFoundError(
        f"SURFACE app artifact was not found in {ARTIFACTS_DIR}. "
        f"Expected one of: {candidate_versions}"
    )