# Changelog

All notable changes to SURFACE CDMS will be documented in this file.

This project follows Semantic Versioning.


## [0.1.0-alpha.6] - 2026-05-25

### Changed

- Updated project README with installer usage instructions.
- Added recommended `pipx` installation workflow.
- Added development setup instructions.
- Added package build instructions.
- Documented available `surface` commands.

### Notes

- This release focuses on documentation and usability for the installer package.
- The full SURFACE application has not yet been added as a top-level `surface/` folder.

## [0.1.0-alpha.5] - 2026-05-25

### Fixed

- Fixed pipx compatibility for Ansible Runner by ensuring the active Python environment's `bin` directory is added to `PATH`.
- Fixed `ansible-playbook` discovery when `surface-cdms` is installed with pipx.

### Changed

- Improved `surface doctor` checks to verify the `ansible-playbook` command is available.
- Improved installer runtime behavior for pipx-installed environments.

### Verified

- Confirmed the `surface-cdms` wheel can be installed with pipx.
- Confirmed the `surface` command is exposed correctly after `pipx install`.
- Confirmed `surface --version` works from a pipx install.
- Confirmed `surface info` works from a pipx install.
- Confirmed `surface doctor` works from a pipx install.
- Confirmed `surface install` starts correctly from a pipx install.

### Notes

- This release focuses on validating the recommended CLI installation method.
- The full SURFACE application has not yet been added as a top-level `surface/` folder.

## [0.1.0-alpha.4] - 2026-05-25

### Changed

- Improved installer wheel packaging.
- Confirmed bundled `wx_config` and `wx_playbook` assets are included in the built package.
- Preserved required Ansible Runner placeholder files in the wheel.
- Reset runtime installer files before each install run.
- Improved installer compatibility with normal `pip`/wheel installs.

### Verified

- Built the `surface-cdms` package successfully.
- Installed the package from a wheel in a fresh virtual environment.
- Confirmed `surface --version` works from a wheel install.
- Confirmed `surface info` works from a wheel install.
- Confirmed `surface doctor` works from a wheel install.
- Confirmed `surface install` starts correctly from a wheel install.

### Notes

- This release still focuses only on the installer package.
- The full SURFACE application has not yet been added as a top-level `surface/` folder.

## [0.1.0-alpha.3] - 2026-05-25

### Added

- Added `surface info` command.
- Added `surface doctor` command.
- Added installer environment information output.
- Added basic checks for required Python packages and bundled installer assets.

### Changed

- Improved the CLI structure by adding separate inspection and health-check commands.

### Notes

- This release focuses on making the installer easier to inspect and debug.

## [0.1.0-alpha.2] - 2026-05-25

### Changed

- Renamed the Python package identity to `surface-cdms`.
- Renamed the import package to `surface_cdms`.
- Updated the CLI entry point to use `surface_cdms.cli:main`.
- Preserved the existing `surface install` flow.
- Removed old hardcoded virtual environment assumptions from the installer flow.
- Updated the Ansible configuration flow to use the active Python executable.
- Added sudo password validation before running the installer.

### Fixed

- Prevented the installer from continuing when an incorrect sudo password is entered.
- Avoided system Python conflicts when launching Django and Celery from the installer.

### Notes

- This release migrated the existing installer into the new `surface-cdms` package structure.

## [0.1.0-alpha.1] - 2026-05-25

### Added

- Created initial `surface-cdms` repository structure.
- Added installer package foundation.
- Added root `VERSION` file.
- Added installer version reporting.
- Added initial changelog.

### Notes

- This was the first alpha release of the new SURFACE CDMS repository.