"""Console script for SURFACE CDMS."""

import subprocess
import sys

import click

from surface_cdms.doctor import run_doctor
from surface_cdms.info import show_info
from surface_cdms.install import wx_configuration
from surface_cdms.version import get_surface_version


def validate_sudo_password(sudo_password: str) -> bool:
    """
    Validate the sudo password before running the installer.

    This prevents the Ansible playbook from starting with an incorrect sudo
    password and hanging later on tasks that require privilege escalation.
    """

    try:
        result = subprocess.run(
            ["sudo", "-S", "-v", "-k"],
            input=f"{sudo_password}\n",
            text=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )

        return result.returncode == 0

    except subprocess.TimeoutExpired:
        return False


@click.group()
@click.version_option(version=get_surface_version(), prog_name="SURFACE CDMS")
def main(args=None):
    """SURFACE CDMS installer and management command-line interface."""
    return 0


@main.command()
def info():
    """Show information about the SURFACE CDMS installer environment."""

    show_info()


@main.command()
def doctor():
    """Check whether the SURFACE CDMS installer environment looks healthy."""

    passed = run_doctor()

    if not passed:
        raise click.ClickException("SURFACE CDMS doctor checks failed.")


@main.command()
@click.option(
    "--sudo-password",
    prompt="[sudo] password",
    hide_input=True,
    required=True,
    confirmation_prompt=True,
    help="Sudo password to install required packages.",
)
def install(sudo_password):
    """Start the SURFACE CDMS install/configuration process."""

    click.echo(click.style("Checking sudo password...", fg="yellow"))

    if not validate_sudo_password(sudo_password):
        click.echo(click.style("Invalid sudo password. Installation cancelled.", fg="red"))
        return False

    click.echo(click.style("Sudo password verified.", fg="green"))
    click.echo(click.style("Starting SURFACE CDMS installer...", fg="green"))

    wx_configuration(sudo_password)


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover