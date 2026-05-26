# SURFACE CDMS

SURFACE CDMS is a weather and climate data management system.

This repository contains the SURFACE CDMS installer and management CLI. The full SURFACE application source will be added later as the project structure matures.

## Current Status

SURFACE CDMS is currently in early alpha development.

Current version: `0.1.0-alpha.6`

At this stage, this repository focuses on the installer package and the `surface` command-line tool.

## What is included right now?

The current alpha includes the SURFACE CDMS installer package.

The installer provides the `surface` command:

```bash
surface --version
surface info
surface doctor
surface install
```

The full SURFACE application has not yet been added as a top-level `surface/` folder.

## Recommended Installation Method

The recommended way to install the SURFACE CDMS CLI is with `pipx`.

`pipx` installs Python CLI tools in isolated environments, which helps avoid dependency conflicts with other Python software on the system.

```bash
pipx install surface-cdms
```

After installation, check that the command is available:

```bash
surface --version
surface info
surface doctor
```

Then start the installer:

```bash
surface install
```

## Local Wheel Testing

During development, you can build the package and test it locally with `pipx`.

From the `installer/` directory:

```bash
python -m build
```

Then install the built wheel with `pipx`:

```bash
pipx install dist/surface_cdms-0.1.0a6-py3-none-any.whl
```

Then test:

```bash
surface --version
surface info
surface doctor
surface install
```

If you already have an older version installed with `pipx`, uninstall it first:

```bash
pipx uninstall surface-cdms
pipx install dist/surface_cdms-0.1.0a6-py3-none-any.whl
```

## Development Setup

For local development, use a virtual environment and install the package in editable mode.

```bash
cd installer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

Editable mode allows code changes in `installer/src/surface_cdms/` to take effect without reinstalling the package every time.

Test the CLI:

```bash
surface --version
surface info
surface doctor
surface install
```

## Building the Installer Package

From the `installer/` directory:

```bash
python -m build
```

This creates distribution files in:

```text
installer/dist/
```

The wheel file can then be installed locally using `pip` or `pipx`.

## Commands

### Show the version

```bash
surface --version
```

### Show installer information

```bash
surface info
```

This displays useful information such as:

- SURFACE CDMS version
- Python executable
- Python version
- Operating system
- Installer package path

### Check installer health

```bash
surface doctor
```

This checks whether the installer environment appears healthy, including required Python packages and bundled installer assets.

### Start the installer

```bash
surface install
```

This starts the SURFACE CDMS installation/configuration process.

The installer will ask for the sudo password and validate it before continuing.

## Versioning

SURFACE CDMS follows Semantic Versioning.

Early releases use alpha versions such as:

```text
0.1.0-alpha.1
0.1.0-alpha.2
0.1.0-alpha.3
```

Release notes are tracked in `CHANGELOG.md`.

## Repository Layout

Current structure:

```text
surface-cdms/
├── installer/
│   ├── src/
│   │   └── surface_cdms/
│   ├── pyproject.toml
│   ├── MANIFEST.in
│   └── requirements.txt
├── AUTHORS.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
└── VERSION
```

Future structure will include the full SURFACE application:

```text
surface-cdms/
├── surface/
├── installer/
├── docs/
├── CHANGELOG.md
├── README.md
└── VERSION
```

## Notes

This project is still in early alpha. The installer package and release process are being stabilized before the full SURFACE application is added to the repository.
