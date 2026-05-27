# Changelog

All notable changes to SURFACE CDMS will be documented in this file.

This project follows Semantic Versioning.


## [0.2.0-alpha.3] - 2026-05-26

### Added

- Packaged the same-version SURFACE app artifact inside the `surface-cdms` wheel.
- Added installer support for locating the packaged SURFACE app artifact.
- Added `surface_artifact_path` and `surface_artifact_version` to the SURFACE install playbook variables.
- Added `SURFACE_CDMS_VERSION` to generated `production.env`.
- Added `scripts/build_installer_wheel.sh` to rebuild the SURFACE app artifact before building the installer wheel.

### Changed

- Replaced the old Git clone install flow with artifact extraction.
- Updated the SURFACE install playbook to extract the packaged app artifact.
- Updated generated secrets to avoid Docker Compose variable interpolation issues caused by `$`.
- Ensured SURFACE shell scripts are executable after artifact extraction.
- Updated README instructions for artifact-based builds.

### Fixed

- Fixed artifact version lookup when Python normalizes versions like `0.2.0-alpha.3` to `0.2.0a3`.
- Fixed Docker startup failure caused by non-executable `startup.sh`.
- Fixed Docker Compose warnings caused by generated secrets containing `$`.

### Verified

- Confirmed the SURFACE app artifact is included in the installer wheel.
- Confirmed `surface doctor` passes from a pipx install.
- Confirmed `surface install` can extract the packaged SURFACE artifact.
- Confirmed SURFACE starts successfully from the artifact-based install flow.

### Notes

- The installer now uses the bundled same-version SURFACE app artifact instead of cloning the SURFACE repository.
- If files in `surface/` are modified, the SURFACE app artifact must be rebuilt before the installer wheel is built.
- Update, backup, restore, logs, and uninstall commands are still deferred.


## [0.2.0-alpha.2] - 2026-05-26

### Added

- Added `scripts/build_surface_artifact.sh` for creating a versioned SURFACE app artifact.
- Added support for building `surface-app-v<version>.tar.gz` from the top-level `surface/` directory.
- Added artifact exclusions for runtime data, generated files, local environment files, caches, and collected static output.

### Changed

- Continued the `0.2.0-alpha` release line for installer plus SURFACE application integration.
- Kept the installer package version and SURFACE app artifact version aligned through the root `VERSION` file.

### Verified

- Confirmed the SURFACE app artifact can be built from the unified repository.
- Confirmed the artifact contains the deployable SURFACE application files.
- Confirmed runtime/generated files are excluded from the artifact.

### Notes

- This release creates the SURFACE app artifact but does not yet modify the installer GUI to consume it.
- Update, backup, restore, logs, and install directory management are still deferred.


## [0.2.0-alpha.1] - 2026-05-26

### Added

- Added the initial SURFACE application source under the top-level `surface/` directory.
- Added SURFACE Docker Compose, API, nginx, documentation, fixtures, and configuration files to the unified repository.
- Added SURFACE app-specific ignore rules for runtime data, generated files, and environment files.

### Changed

- Started the `0.2.0-alpha` release line for installer plus SURFACE application integration.
- Kept a single shared version for the installer package and SURFACE application.

### Notes

- This release focuses on bringing the SURFACE application source into the unified `surface-cdms` repository.
- The installer GUI flow is still being preserved.
- Update, backup, restore, and install directory management are intentionally deferred to a later release.


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