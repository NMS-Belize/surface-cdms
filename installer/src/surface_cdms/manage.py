"""SURFACE CDMS Docker management helpers."""

import json
import subprocess
from pathlib import Path

import click


METADATA_PATH = Path.home() / ".surface-cdms" / "install.json"


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