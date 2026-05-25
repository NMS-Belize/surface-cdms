import click
from rich.console import Console

from surface_cdms.version import get_surface_version


console = Console()


@click.group()
@click.version_option(version=get_surface_version(), prog_name="SURFACE CDMS")
def main():
    """
    SURFACE CDMS installer and management CLI.
    """
    pass


@main.command()
def install():
    """
    Start the SURFACE CDMS installation process.
    """

    console.print("[bold green]SURFACE CDMS installer started.[/bold green]")
    console.print(f"Platform version: [bold]{get_surface_version()}[/bold]")
    console.print("Install command placeholder is working.")