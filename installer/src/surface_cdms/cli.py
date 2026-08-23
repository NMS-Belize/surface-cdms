"""Console script for SURFACE CDMS."""

import subprocess
import sys

import click

from surface_cdms.doctor import run_doctor
from surface_cdms.info import show_info
from surface_cdms.install import wx_configuration
from surface_cdms.version import get_surface_version

from surface_cdms.manage import (
    restart_services,
    show_containers,
    show_logs,
    start_services,
    stop_services,
    uninstall_surface,
)


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


# surface info
@main.command()
def info():
    """Show information about the SURFACE CDMS installer environment."""

    show_info()


# surface doctor
@main.command()
def doctor():
    """Check whether the SURFACE CDMS installer environment looks healthy."""

    passed = run_doctor()

    if not passed:
        raise click.ClickException("SURFACE CDMS doctor checks failed.")
    

# surface up
@main.command()
@click.option(
    "--sudo",
    prompt="[sudo] password",
    prompt_required=False,
    hide_input=True,
    required=False,
    help="Run `surface up` with escalated privileges.",
)
def up(sudo):
    """Start SURFACE Docker services."""

    if sudo and not validate_sudo_password(sudo):
        click.echo(click.style("Invalid sudo password.", fg="red"))
        return False

    raise SystemExit(start_services(sudo))


# surface down
@main.command()
@click.option(
    "--sudo",
    prompt="[sudo] password",
    prompt_required=False,
    hide_input=True,
    required=False,
    help="Run `surface down` with escalated privileges.",
)
def down(sudo):
    """Bring down SURFACE Docker services."""

    if sudo and not validate_sudo_password(sudo):
        click.echo(click.style("Invalid sudo password.", fg="red"))
        return False

    raise SystemExit(stop_services(sudo))


# surface restart
@main.command()
@click.option(
    "--sudo",
    prompt="[sudo] password",
    prompt_required=False,
    hide_input=True,
    required=False,
    help="Run `surface restart` with escalated privileges.",
)
def restart(sudo):
    """Restart SURFACE Docker services."""

    if sudo and not validate_sudo_password(sudo):
        click.echo(click.style("Invalid sudo password.", fg="red"))
        return False

    raise SystemExit(restart_services(sudo))


# surface logs
@main.command()
@click.argument("service", required=False)
@click.option(
    "--sudo",
    prompt="[sudo] password",
    prompt_required=False,
    hide_input=True,
    required=False,
    help="Run `surface logs` with escalated privileges.",
)
@click.option("-f", "--follow", is_flag=True, help="Follow log output.")
@click.option("--tail", type=int, default=None, help="Number of lines to show from the end of logs.")
def logs(service, follow, tail, sudo):
    """Show SURFACE Docker logs."""

    if sudo and not validate_sudo_password(sudo):
        click.echo(click.style("Invalid sudo password.", fg="red"))
        return False

    raise SystemExit(show_logs(service=service, follow=follow, tail=tail, sudo=sudo))


# surface containers
@main.command()
@click.option(
    "--sudo",
    prompt="[sudo] password",
    prompt_required=False,
    hide_input=True,
    required=False,
    help="Run `surface containers` with escalated privileges.",
)
def containers(sudo):
    """Show SURFACE Docker containers."""

    if sudo and not validate_sudo_password(sudo):
        click.echo(click.style("Invalid sudo password.", fg="red"))
        return False

    raise SystemExit(show_containers(sudo))


# surface install
@main.command()
@click.option(
    "--sudo-password",
    prompt="[sudo] password",
    prompt_required=True,
    hide_input=True,
    required=True,
    confirmation_prompt=True,
    help="Sudo password to install required packages.",
)
def install(sudo_password):
    """Start the SURFACE CDMS install/configuration process."""

    if sudo_password and not validate_sudo_password(sudo_password):
        click.echo(click.style("Invalid sudo password. Installation cancelled.", fg="red"))
        return False

    click.echo(click.style("Starting SURFACE CDMS installer...", fg="green"))

    wx_configuration(sudo_password)


# surface uninstall
@main.command()
@click.option(
    "--sudo-password",
    prompt="[sudo] password",
    prompt_required=True,
    hide_input=True,
    required=True,
    confirmation_prompt=True,
    help="Sudo password to uninstall SURFACE.",
)
@click.option(
    "--keep-images",
    is_flag=True,
    help="Do not remove Docker images during uninstall.",
)
def uninstall(keep_images, sudo_password):
    """Uninstall SURFACE CDMS from this machine."""

    if sudo_password and not validate_sudo_password(sudo_password):
        click.echo(click.style("Invalid sudo password. Uninstall cancelled.", fg="red"))
        raise SystemExit(1)

    raise SystemExit(
        uninstall_surface(
            sudo=sudo_password,
            remove_images=not keep_images,
        )
    )









if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover