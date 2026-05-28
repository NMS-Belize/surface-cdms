# SURFACE CDMS

SURFACE CDMS is a weather and climate data management system.

This repository contains the SURFACE CDMS installer and management CLI, along with the SURFACE application source.

## Current Status

SURFACE CDMS is currently in its first stable release.

Current version: `1.0.0`

This repository contains:

- The `surface-cdms` installer package
- The `surface` command-line tool
- The SURFACE application source under `surface/`
- A build process for packaging the SURFACE app into the installer wheel
- CLI commands for installing, managing, inspecting, and uninstalling SURFACE

## What is included?

The installer provides the `surface` command:

```bash
surface --version
surface info
surface doctor
surface install
surface up
surface down
surface restart
surface logs
surface containers
surface uninstall
```

The installer uses a packaged same-version SURFACE app artifact instead of cloning the SURFACE application from a separate repository.

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

## Basic Usage

### Start the installer

```bash
surface install
```

This starts the SURFACE CDMS installation/configuration process.

The installer asks for the sudo password and validates it before continuing.

### Show version

```bash
surface --version
```

### Show installer and installation information

```bash
surface info
```

This displays useful information such as:

- Installer version
- Python executable
- Python version
- Operating system
- Installer package path
- Install status
- Installed SURFACE path
- Docker Compose file
- Install duration, when available

### Check installer and installation health

```bash
surface doctor
```

This checks whether the installer environment appears healthy, including required Python packages, bundled installer assets, Docker availability, Docker Compose availability, and installation metadata when available.

### Show containers

```bash
surface containers
```

This shows the Docker Compose containers for the installed SURFACE deployment.

### View logs

```bash
surface logs --tail 50
surface logs api --tail 50
surface logs api --follow
```

### Start services

```bash
surface up
```

### Stop services

```bash
surface down
```

### Restart services

```bash
surface restart
```

### Uninstall SURFACE CDMS

```bash
surface uninstall
```

This stops SURFACE containers, removes Docker resources used by the installation, deletes the installed SURFACE directory, and removes local install metadata.

This command is destructive and requires explicit confirmation.

To keep Docker images during uninstall:

```bash
surface uninstall --keep-images
```

## Local Wheel Testing

During development, build the installer wheel and test it locally with `pipx`.

From the repository root:

```bash
./scripts/build_installer_wheel.sh
```

Then install the built wheel with `pipx`:

```bash
pipx install installer/dist/surface_cdms-1.0.0-py3-none-any.whl
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
pipx install installer/dist/surface_cdms-1.0.0-py3-none-any.whl
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

This script does three required build steps:

1. Copies the root `README.md` into `installer/README.md`
2. Rebuilds the SURFACE app artifact from `surface/`
3. Builds the installer wheel from `installer/`

The installer wheel is created in:

```text
installer/dist/
```

If you want to run the steps manually:

```bash
cp README.md installer/README.md

./scripts/build_surface_artifact.sh

cd installer
rm -rf build dist *.egg-info src/*.egg-info src/surface_cdms.egg-info
python -m build
```

## Testing

Testing documents are available under:

```text
docs/testing/
```

Important validation checklists include:

```text
docs/testing/install-lifecycle-smoke-test.md
docs/testing/surface-application-validation-test.md
```

The install lifecycle smoke test validates that SURFACE CDMS can be installed, managed, uninstalled, and reinstalled on a clean machine.

The SURFACE application validation test validates that the installed SURFACE application itself works correctly after installation.

## Versioning

SURFACE CDMS follows Semantic Versioning.

Example versions:

```text
0.7.0-alpha.2
0.8.0-beta.1
1.0.0-rc.1
1.0.0
```

The root `VERSION` file controls the platform version.

The installer package version and the packaged SURFACE app artifact version should always match.

Git tags include the leading `v`, for example:

```text
v1.0.0
```

Python package versions do not include the leading `v`, for example:

```text
1.0.0
```

Python packaging may normalize prerelease versions. For example:

```text
1.0.0-rc.1
```

may appear as:

```text
1.0.0rc1
```

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
├── docs/
│   └── testing/
├── AUTHORS.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
└── VERSION
```

## License

SURFACE CDMS is licensed under the GNU General Public License v3.0.

See `LICENSE` for details.

## Notes

This is the first stable SURFACE CDMS release.

Future feature work, including backup optimization and additional management commands, should continue in later releases.
