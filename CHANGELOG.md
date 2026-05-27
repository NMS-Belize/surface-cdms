# Changelog

All notable changes to SURFACE CDMS will be documented in this file.

This project follows Semantic Versioning.


## [0.8.0-beta.1] - 2026-05-27

### Changed

- Started the `0.8.0-beta` release line.
- Updated package metadata for beta release readiness.
- Updated package license metadata to GPL-3.0.
- Updated package classifiers for beta status and scientific/engineering usage.

### Verified

- Confirmed clean-machine lifecycle testing passed.
- Confirmed SURFACE application validation issues from alpha testing were fixed.
- Confirmed local dump restore works.
- Confirmed FTP dump restore works.
- Confirmed WIS2Box publishing validation is complete.
- Confirmed core CLI commands are available:
  - `surface install`
  - `surface info`
  - `surface doctor`
  - `surface up`
  - `surface down`
  - `surface restart`
  - `surface logs`
  - `surface containers`
  - `surface uninstall`

### Notes

- This is the first beta release of SURFACE CDMS.
- No major new features should be added before `v1.0.0` unless they are blocking.
- Focus after this release should be bug fixes, documentation, packaging, and release candidate preparation.
- Backup dump size and backup duration optimization are deferred to a future release.


## [0.7.0-alpha.2] - 2026-05-27

### Added

- Added install duration tracking to install metadata.
- Added install duration reporting to `surface info`.

### Fixed

- Fixed configuration page update/download/delete behavior for configuration items.
- Fixed station delete cancel redirect behavior.
- Fixed protected-object and safe-delete redirect behavior.
- Fixed standard ingestion issues found during validation.
- Fixed manually validated flag handling during ingestion.
- Fixed issues discovered during the first full SURFACE application validation run.

### Verified

- Confirmed failed validation sections from `0.7.0-alpha.1` were retested.
- Confirmed configuration item update/download/delete behavior works.
- Confirmed station delete and cancel flows return to the expected UI pages.
- Confirmed protected-object and safe-delete flows redirect correctly.
- Confirmed standard ingestion works for tested formats.
- Confirmed manually validated data behavior is respected.
- Confirmed restore from local dump works.
- Confirmed restore from FTP dump works.

### Notes

- This release fixes issues found during the first full SURFACE application validation run.
- Backup dump size and backup duration optimization are deferred to a future release.
- WIS2Box full validation is still planned for beta testing.


## [0.7.0-alpha.1] - 2026-05-26

### Added

- Added a full SURFACE application validation checklist.
- Added validation steps for authentication, admin user creation, and permissions.
- Added validation steps for database migrations, fixtures, TimescaleDB, and PostGIS functionality.
- Added validation steps for core UI pages, forms, and protected delete behavior.
- Added validation steps for standard, high-frequency, staged, and historical data ingestion.
- Added validation steps for decoder behavior and quality-control processing.
- Added validation steps for hourly, daily, and high-frequency summaries.
- Added validation steps for CSV, XLSX, and large export workflows.
- Added validation steps for Celery beat and queue-specific workers.
- Added validation steps for manual backup, scheduled backup, local restore, and FTP restore.
- Added validation steps for WIS2Box publishing configuration, publish tasks, and cleanup tasks.
- Added operational validation steps for logs, restart behavior, and container recovery after reboot.

### Changed

- Started the `0.7.0-alpha` release line for full SURFACE application validation.

### Verified

- This release is intended for validating SURFACE application behavior after a successful install.

### Notes

- This release does not add major installer or CLI features.
- The purpose of this release is to prove that SURFACE itself behaves correctly after installation.
- Issues found during this validation should be fixed in follow-up `0.7.0-alpha` releases before moving toward beta.


## [0.6.0-alpha.1] - 2026-05-26

### Added

- Added a clean-machine lifecycle test checklist.
- Added documented validation steps for installing, managing, restarting, stopping, starting, and uninstalling SURFACE CDMS.
- Added documented validation steps for reinstalling SURFACE after uninstall.

### Changed

- Started the `0.6.0-alpha` release line for clean-machine lifecycle validation.

### Verified

- This release is intended for clean-machine lifecycle testing.

### Notes

- This release does not add major installer features.
- The purpose of this release is to validate the full SURFACE CDMS lifecycle on a fresh machine.
- Full SURFACE application validation is planned for a later release.


## [0.5.0-alpha.1] - 2026-05-26

### Added

- Added additional `surface doctor` checks for Docker and Docker Compose availability.
- Added `surface doctor` checks for the packaged SURFACE app artifact.
- Added installation metadata checks to `surface doctor`.
- Added clearer reporting for installed SURFACE path, Docker Compose file, and install status.

### Changed

- Improved diagnostic output for installer and installed SURFACE environments.
- Improved `surface doctor` behavior so a missing install metadata file does not fail installer health checks.
- Improved distinction between the installed CLI package and an existing SURFACE deployment.

### Verified

- Confirmed `surface doctor` passes before SURFACE is installed.
- Confirmed `surface doctor` reports existing install metadata when SURFACE was installed previously.
- Confirmed `surface doctor` reports installer and installation health after install.


## [0.5.0-alpha.1] - 2026-05-26

### Added

- Added additional `surface doctor` checks for Docker and Docker Compose availability.
- Added `surface doctor` checks for the packaged SURFACE app artifact.
- Added installation metadata checks to `surface doctor`.
- Added clearer reporting for installed SURFACE path, Docker Compose file, and install status.

### Changed

- Improved diagnostic output for installer and installed SURFACE environments.
- Improved error messages when install metadata is missing, incomplete, or stale.
- Improved post-install and post-uninstall validation flow.

### Verified

- Confirmed `surface-cdms` installs from a locally built wheel using `pipx`.
- Confirmed `surface install` completes successfully.
- Confirmed `surface info` shows installer and installation metadata.
- Confirmed `surface doctor` reports installer and installation health.
- Confirmed `surface up`, `surface down`, `surface restart`, `surface logs`, and `surface containers` work after install.
- Confirmed `surface uninstall` removes the installed SURFACE directory and metadata.
- Confirmed SURFACE can be reinstalled after uninstall.

### Notes

- This release focuses on hardening and diagnostics.
- Backup, restore, and update commands are still deferred.


## [0.4.0-alpha.1] - 2026-05-26

### Added

- Added `surface uninstall` command.
- Added uninstall confirmation prompt requiring `DELETE SURFACE`.
- Added sudo-based removal for Docker-created files that may be owned by root or container users.
- Added install metadata status tracking with `install_status`.
- Added install status support for `installing`, `installed`, and `failed`.
- Updated `surface info` to show install metadata and install status.

### Changed

- Updated management commands to require a completed installation before running.
- Improved install metadata so commands like `surface logs`, `surface containers`, `surface up`, `surface down`, and `surface restart` do not run while installation is still in progress.
- Updated install task behavior to mark metadata as `installed` only after the SURFACE install playbook succeeds.
- Updated install task behavior to mark metadata as `failed` if the install playbook fails or times out.

### Fixed

- Fixed permission errors during uninstall caused by Docker-created folders such as `data/exported_data`.

### Verified

- Confirmed `surface info` shows installer and installation metadata.
- Confirmed management commands are blocked while install status is not `installed`.
- Confirmed `surface uninstall` can stop services and remove the installed SURFACE directory.
- Confirmed `surface --version`, `surface info`, `surface doctor`, `surface containers`, and `surface logs` work after rebuilding the wheel.

### Notes

- `surface uninstall` is destructive and requires explicit confirmation.
- Backup, restore, and update commands are still deferred.


## [0.3.0-alpha.1] - 2026-05-26

### Added

- Added local install metadata support using `~/.surface-cdms/install.json`.
- Added `surface up` command for starting SURFACE Docker services.
- Added `surface down` command for stopping SURFACE Docker services.
- Added `surface restart` command for restarting SURFACE Docker services.
- Added `surface logs` command for viewing SURFACE Docker logs.
- Added `surface containers` command for viewing SURFACE Docker containers.

### Changed

- Updated the installer GUI flow to save the installed SURFACE path for future CLI management commands.
- Added Docker Compose management helpers that use the saved install metadata.

### Verified

- Confirmed install metadata is written after the installer GUI is submitted.
- Confirmed `surface containers` can show the installed SURFACE containers.
- Confirmed `surface logs` can read Docker Compose logs.
- Confirmed `surface up`, `surface down`, and `surface restart` work using saved install metadata.

### Notes

- This release starts the `0.3.0-alpha` line for SURFACE runtime management commands.
- `surface uninstall` is still deferred because it is destructive and needs extra safety checks.


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