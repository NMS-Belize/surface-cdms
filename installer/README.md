# SURFACE CDMS

SURFACE CDMS is a weather and climate data management system.

This repository contains the SURFACE CDMS installer and management CLI, along with the SURFACE application source.

## Current Status

SURFACE CDMS is currently in early alpha development.

Current version: `0.2.0-alpha.3`

At this stage, this repository contains:

- The `surface-cdms` installer package
- The `surface` command-line tool
- The SURFACE application source under `surface/`
- A build process for packaging the SURFACE app into the installer wheel

## What is included right now?

The installer provides the `surface` command:

```bash
surface --version
surface info
surface doctor
surface install
```

The current installer flow uses a packaged SURFACE app artifact instead of cloning the old SURFACE repository.

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

During development, build the installer wheel and test it locally with `pipx`.

From the repository root:

```bash
./scripts/build_installer_wheel.sh
```

Then install the built wheel with `pipx`:

```bash
pipx install installer/dist/surface_cdms-0.2.0a3-py3-none-any.whl
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
pipx install installer/dist/surface_cdms-0.2.0a3-py3-none-any.whl
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

## Building the SURFACE App Artifact

The installer wheel includes a packaged SURFACE app artifact.

The artifact is built from the top-level `surface/` directory and copied into:

```text
installer/src/surface_cdms/artifacts/
```

If you modify anything inside the top-level `surface/` directory, rebuild the SURFACE app artifact before building the installer wheel:

```bash
./scripts/build_surface_artifact.sh
```

If you skip this step, the installer wheel may still contain an older SURFACE app artifact.

## Building the Installer Package

The recommended development build command is:

```bash
./scripts/build_installer_wheel.sh
```

This script does both required build steps:

1. Rebuilds the SURFACE app artifact from `surface/`
2. Builds the installer wheel from `installer/`

The installer wheel is created in:

```text
installer/dist/
```

If you want to run the steps manually:

```bash
./scripts/build_surface_artifact.sh

cd installer
rm -rf build dist *.egg-info src/*.egg-info src/surface_cdms.egg-info
python -m build
```

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
0.2.0-alpha.1
0.2.0-alpha.3
```

The root `VERSION` file controls the platform version.

The installer package version and the packaged SURFACE app artifact version should always match.

Release notes are tracked in `CHANGELOG.md`.

## Repository Layout

Current structure:

```text
surface-cdms/
├── surface/
│   ├── api/
│   ├── nginx/
│   ├── docker-compose.yml
│   └── pg_hba.custom.conf
├── installer/
│   ├── src/
│   │   └── surface_cdms/
│   │       ├── artifacts/
│   │       ├── wx_config/
│   │       └── wx_playbook/
│   ├── pyproject.toml
│   ├── MANIFEST.in
│   └── requirements.txt
├── scripts/
│   ├── build_surface_artifact.sh
│   └── build_installer_wheel.sh
├── AUTHORS.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
└── VERSION
```

## Notes

This project is still in early alpha. The installer package, artifact packaging, and release process are being stabilized before the first stable `v1.0.0` release.
