"""SURFACE CDMS Docker management helpers."""

import json
import subprocess
from pathlib import Path
import shutil

import click


METADATA_PATH = Path.home() / ".surface-cdms" / "install.json"


def sudo_remove_directory(path: Path, sudo_password: str) -> int:
    """
    Remove a directory using sudo.

    Needed because Docker-created files may be owned by root or container users.
    """

    command = [
        "sudo",
        "-S",
        "rm",
        "-rf",
        "--",
        str(path),
    ]

    result = subprocess.run(
        command,
        input=f"{sudo_password}\n",
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )

    if result.returncode != 0:
        raise click.ClickException(
            "Failed to delete SURFACE install directory.\n"
            f"Path: {path}\n"
            f"Error: {result.stderr.strip()}"
        )

    return result.returncode


def validate_surface_install_path(surface_repo_path: Path) -> None:
    """
    Make sure we are deleting what looks like a SURFACE install directory.

    This protects against accidentally deleting dangerous paths.
    """

    surface_repo_path = surface_repo_path.resolve()

    if str(surface_repo_path) in ["/", "/home", "/root", "/usr", "/var", "/opt", "/srv"]:
        raise click.ClickException(
            f"Refusing to delete unsafe path: {surface_repo_path}"
        )

    if surface_repo_path.name != "surface":
        raise click.ClickException(
            "Refusing to delete install directory because it is not named 'surface'.\n"
            f"Path: {surface_repo_path}"
        )

    if not (surface_repo_path / "docker-compose.yml").exists():
        raise click.ClickException(
            "Refusing to delete install directory because docker-compose.yml was not found.\n"
            f"Path: {surface_repo_path}"
        )

    if not (surface_repo_path / "api").exists():
        raise click.ClickException(
            "Refusing to delete install directory because api/ was not found.\n"
            f"Path: {surface_repo_path}"
        )


def uninstall_surface(sudo_password: str, remove_images: bool = True) -> int:
    """
    Uninstall SURFACE CDMS from the local machine.

    This stops/removes Docker Compose services, removes volumes and orphans,
    deletes the installed SURFACE directory, and removes install metadata.
    """

    metadata = load_install_metadata()

    surface_repo_path = Path(metadata["surface_repo_path"]).resolve()
    compose_file = Path(metadata["compose_file"]).resolve()

    if not surface_repo_path.exists():
        raise click.ClickException(
            "SURFACE install directory was not found.\n"
            f"Expected: {surface_repo_path}"
        )

    validate_surface_install_path(surface_repo_path)

    click.echo(click.style("SURFACE CDMS uninstall", fg="red", bold=True))
    click.echo("")
    click.echo("This will permanently remove SURFACE CDMS from:")
    click.echo(str(surface_repo_path))
    click.echo("")
    click.echo("This will also stop containers and remove Docker Compose volumes.")
    click.echo("")

    confirmation = click.prompt(
        "Type DELETE SURFACE to continue",
        default="",
        show_default=False,
    )

    if confirmation != "DELETE SURFACE":
        click.echo(click.style("Uninstall cancelled.", fg="yellow"))
        return 1

    compose_down_args = [
        "down",
        "--remove-orphans",
        "--volumes",
    ]

    if remove_images:
        compose_down_args.extend(["--rmi", "all"])

    command = [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "--project-directory",
        str(surface_repo_path),
        *compose_down_args,
    ]

    click.echo(click.style("Stopping and removing Docker services...", fg="yellow"))

    down_code = subprocess.call(command)

    if down_code != 0:
        raise click.ClickException(
            "Docker Compose cleanup failed. SURFACE directory was not deleted."
        )

    click.echo(click.style("Deleting SURFACE install directory...", fg="yellow"))

    sudo_remove_directory(surface_repo_path, sudo_password)

    if METADATA_PATH.exists():
        METADATA_PATH.unlink()

    click.echo(click.style("SURFACE CDMS has been uninstalled.", fg="green"))

    return 0


def load_install_metadata() -> dict:
    """
    Load SURFACE CDMS install metadata.

    The metadata file is created by the installer GUI and tells the CLI where
    the installed SURFACE Docker Compose project lives.
    """

    if not METADATA_PATH.exists():
        raise click.ClickException(
            "SURFACE CDMS install metadata was not found.\n"
            f"Expected: {METADATA_PATH}\n\n"
            "Run `surface install` first."
        )

    try:
        with METADATA_PATH.open("r", encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)

    except json.JSONDecodeError as error:
        raise click.ClickException(
            f"SURFACE CDMS install metadata is invalid JSON: {METADATA_PATH}"
        ) from error

    surface_repo_path = metadata.get("surface_repo_path")
    compose_file = metadata.get("compose_file")

    if not surface_repo_path or not compose_file:
        raise click.ClickException(
            "SURFACE CDMS install metadata is missing required fields.\n"
            f"File: {METADATA_PATH}"
        )
    
    install_status = metadata.get("install_status")

    if install_status != "installed":
        raise click.ClickException(
            "SURFACE CDMS is not ready for management commands yet.\n"
            f"Current install status: {install_status or 'unknown'}\n\n"
            "Wait for `surface install` to finish successfully before running this command."
        )

    compose_path = Path(compose_file)

    if not compose_path.exists():
        raise click.ClickException(
            "SURFACE Docker Compose file was not found.\n"
            f"Expected: {compose_path}\n\n"
            "The install metadata may be stale, or SURFACE may have been moved."
        )

    return metadata


def run_docker_compose(args: list[str]) -> int:
    """
    Run a docker compose command inside the installed SURFACE directory.
    """

    metadata = load_install_metadata()

    surface_repo_path = Path(metadata["surface_repo_path"])
    compose_file = Path(metadata["compose_file"])

    command = [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "--project-directory",
        str(surface_repo_path),
        *args,
    ]

    return subprocess.call(command)


def show_containers() -> int:
    """Show SURFACE containers."""

    return run_docker_compose(["ps"])


def show_logs(service: str | None = None, follow: bool = False, tail: int | None = None) -> int:
    """Show SURFACE Docker Compose logs."""

    args = ["logs"]

    if follow:
        args.append("-f")

    if tail is not None:
        args.extend(["--tail", str(tail)])

    if service:
        args.append(service)

    return run_docker_compose(args)


def start_services() -> int:
    """Start SURFACE services."""

    return run_docker_compose(["up", "-d"])


def stop_services() -> int:
    """Stop SURFACE services."""

    return run_docker_compose(["down"])


def restart_services() -> int:
    """Restart SURFACE services."""

    stop_code = stop_services()

    if stop_code != 0:
        return stop_code

    return start_services()