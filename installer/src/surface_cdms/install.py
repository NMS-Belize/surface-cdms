"""SURFACE CDMS install/configuration logic."""
import sys
import getpass
from pathlib import Path

import ansible_runner
import click


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


def wx_configuration(sudo_password):
    """
    Start the SURFACE CDMS configuration process.

    This function prepares the local configuration files needed by the
    Ansible playbook, then runs the playbook that starts the SURFACE
    configuration web app.
    """

    try:
        # Reset runtime files so old installer values are not reused.
        reset_runtime_env_files()
        
        # Write out the current Linux username for local installations.
        write_user_to_file(
            getpass.getuser(),
            WEBAPP_PROJECT_PATH / "ansible" / "surface_app" / "env" / "user",
        )

        # Configure the web app playbook with the Django configuration app path.
        #
        # Important:
        # We no longer write venv_path or venv_activate here because the
        # installer is now intended to run through normal pip/pip editable
        # installs, not the old pipx-specific virtual environment flow.
        with PLAYBOOK_EXTRAVARS.open("w", encoding="utf-8") as extravars_file:
            extravars_file.write(f"\ndjango_webapp_path: {WEBAPP_PROJECT_PATH}")
            extravars_file.write(f"\nsurface_python_executable: {sys.executable}")

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