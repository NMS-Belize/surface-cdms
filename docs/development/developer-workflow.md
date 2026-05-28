# SURFACE CDMS Developer Workflow Guide

This guide explains how developers should set up SURFACE CDMS locally, develop new features, test their changes, and submit pull requests.

The goal of this document is to make development predictable and safe. SURFACE CDMS contains both the install/management tooling and the SURFACE application itself, so developers need to understand which part they are changing and which testing workflow is appropriate.

## 1. Project overview

SURFACE CDMS contains two major parts:

1. The SURFACE application source in the top-level `surface/` directory.
2. The SURFACE CDMS installer and management CLI in the `installer/` directory.

The installer package is published as:

```text
surface-cdms
```

It provides the command:

```bash
surface
```

For example:

```bash
surface install
surface doctor
surface info
surface logs
surface containers
```

## 2. Repository layout

The repository is organized roughly like this:

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
│   │       ├── wx_playbook/
│   │       ├── cli.py
│   │       ├── doctor.py
│   │       ├── info.py
│   │       ├── install.py
│   │       ├── manage.py
│   │       └── version.py
│   ├── pyproject.toml
│   ├── MANIFEST.in
│   └── README.md
├── scripts/
│   ├── build_surface_artifact.sh
│   └── build_installer_wheel.sh
├── docs/
│   ├── development/
│   └── testing/
├── AUTHORS.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
└── VERSION
```

## 3. What each major directory is for

### `surface/`

This is the actual SURFACE application.

Most application development happens here.

Examples of work in `surface/` include:

- Django model changes
- Django views
- templates and frontend pages
- station metadata features
- decoders
- data ingestion
- quality control
- Celery tasks
- exports
- backup and restore logic
- Docker Compose changes for the application

Important paths include:

```text
surface/api/
surface/api/wx/
surface/api/wx/decoders/
surface/api/wx/tasks.py
surface/api/wx/views.py
surface/api/wx/models.py
surface/api/templates/
surface/docker-compose.yml
surface/nginx/
```

### `installer/`

This contains the Python package that gets installed through `pipx`.

Examples of work in `installer/` include:

- `surface install`
- `surface info`
- `surface doctor`
- `surface logs`
- `surface containers`
- `surface up`
- `surface down`
- `surface restart`
- `surface uninstall`
- packaged Ansible playbooks
- installer GUI/configuration app
- package metadata
- PyPI/TestPyPI packaging

Important paths include:

```text
installer/src/surface_cdms/cli.py
installer/src/surface_cdms/install.py
installer/src/surface_cdms/info.py
installer/src/surface_cdms/doctor.py
installer/src/surface_cdms/manage.py
installer/src/surface_cdms/version.py
installer/src/surface_cdms/wx_config/
installer/src/surface_cdms/wx_playbook/
installer/pyproject.toml
installer/MANIFEST.in
```

### `scripts/`

This contains build helper scripts.

Important scripts:

```text
scripts/build_surface_artifact.sh
scripts/build_installer_wheel.sh
```

The most important script for release-style testing is:

```bash
./scripts/build_installer_wheel.sh
```

This script:

1. Copies the root `README.md` into `installer/README.md`.
2. Rebuilds the SURFACE app artifact from `surface/`.
3. Builds the installer wheel from `installer/`.

## 4. Clone the repository

Developers should begin by cloning the repository:

```bash
git clone https://github.com/NMS-Belize/surface-cdms.git
cd surface-cdms
```

Always start new work from an updated `main` branch:

```bash
git checkout main
git pull origin main
```

## 5. Create a feature branch

Developers should not work directly on `main`.

Create a branch for each change:

```bash
git checkout -b feature/short-description
```

Examples:

```bash
git checkout -b feature/add-new-decoder
git checkout -b fix/station-delete-redirect
git checkout -b docs/update-install-guide
git checkout -b refactor/backup-task-cleanup
```

Recommended branch prefixes:

```text
feature/   new functionality
fix/       bug fixes
docs/      documentation updates
refactor/  internal cleanup without changing behavior
test/      tests or validation updates
release/   release preparation work
```

Good branch names are short but clear.

Good examples:

```text
feature/add-davis-decoder
fix/delete-cancel-redirect
docs/add-developer-workflow
```

Avoid vague branch names:

```text
changes
updates
work
stuff
```

## 6. Installer/CLI development setup

Use this workflow when changing code inside:

```text
installer/src/surface_cdms/
```

From the repository root:

```bash
cd installer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

Then check that the CLI works:

```bash
surface --version
surface info
surface doctor
```

### What editable install means

This command:

```bash
python -m pip install -e .
```

installs the `surface-cdms` package in editable mode.

That means changes inside:

```text
installer/src/surface_cdms/
```

are reflected immediately when you run the `surface` command from that virtual environment.

For example, if you edit:

```text
installer/src/surface_cdms/cli.py
```

then rerun:

```bash
surface --help
```

your CLI changes should be visible.

If you edit:

```text
installer/src/surface_cdms/doctor.py
```

then rerun:

```bash
surface doctor
```

your doctor command changes should be visible.

### What editable install does not do

Editable install does not make changes inside:

```text
surface/
```

appear inside an installed SURFACE deployment.

That is because `surface install` installs SURFACE from a packaged artifact. It does not run directly from your repository's `surface/` folder.

So:

```text
installer/src/surface_cdms/ changes = reflected by editable install
surface/ changes = not reflected by editable install
```

This distinction is very important.

## 7. SURFACE app development workflows

There are two main ways to develop the SURFACE application itself.

### Option A: Packaged artifact workflow

This is the release-style workflow.

Use this when you want to test the exact process that users will experience.

The packaged artifact workflow is:

```bash
./scripts/build_installer_wheel.sh
pipx uninstall surface-cdms
pipx install installer/dist/*.whl
surface uninstall --keep-images
surface install
```

This workflow is slower, but it validates the real release behavior.

It tests:

- the installer wheel
- the packaged SURFACE app artifact
- artifact extraction
- generated environment/configuration files
- Ansible playbook execution
- Docker Compose startup
- install metadata
- the real user installation flow

Use this workflow before releases or when testing installer-related behavior.

### Option B: Local Docker bind mount workflow

This is the faster day-to-day SURFACE app development workflow.

In this workflow, developers run the Docker Compose project directly from:

```text
surface/
```

Example:

```bash
cd surface
docker compose up -d --build
```

The goal is to allow code changes in your local repository to be visible inside the running containers.

This is usually done with Docker bind mounts.

A bind mount maps a folder on your machine into a folder inside the container.

For example:

```yaml
volumes:
  - ./api:/app
```

This means:

```text
local machine: surface/api
container:      /app
```

So when you edit files inside:

```text
surface/api/
```

the container sees those files at:

```text
/app
```

This can make development much faster because you do not need to rebuild the installer package every time you change a Django view, template, decoder, or task.

### Important warning about bind mounts

Bind mounts are powerful, but they can also be confusing.

A bind mount can override files that were copied into the Docker image during build time.

For example, if the Docker image contains:

```text
/app
```

and you mount:

```yaml
volumes:
  - ./api:/app
```

then the container will use your local `./api` folder instead of the `/app` folder that was built into the image.

That is usually what you want during development, but developers should understand this behavior before changing Docker Compose volumes.

### When to use bind mounts

Use bind mounts when:

- you are developing SURFACE app features
- you are editing Django views, templates, or tasks
- you are working on decoders
- you need quick feedback
- you are testing UI/backend behavior locally
- you are not testing the final installer package

### When not to use bind mounts

Do not rely only on bind mounts when:

- preparing a release
- testing the installer
- testing the packaged app artifact
- testing `surface install`
- testing PyPI/TestPyPI installation
- validating that the release artifact contains the right code

Before a release, always test the packaged artifact workflow.

### Quick comparison

```text
Bind mount workflow:
- Faster
- Better for day-to-day app development
- Runs from local source files
- Good for feature work and debugging

Packaged artifact workflow:
- Slower
- Better for release validation
- Runs from the built artifact
- Good for testing what users will install
```

## 8. Making SURFACE application changes

Most SURFACE app changes happen inside:

```text
surface/
```

Examples:

```text
surface/api/wx/views.py
surface/api/wx/tasks.py
surface/api/wx/models.py
surface/api/wx/decoders/
surface/api/templates/
surface/api/static/
```

If you are using the bind mount workflow, changes may be visible in the running containers depending on the Docker Compose setup.

If you are using the packaged artifact workflow, changes will not appear until you rebuild the artifact:

```bash
./scripts/build_surface_artifact.sh
```

or run the full build:

```bash
./scripts/build_installer_wheel.sh
```

Then reinstall/redeploy through the installer flow.

## 9. Making installer or CLI changes

Installer and CLI changes happen inside:

```text
installer/src/surface_cdms/
```

Examples:

```text
installer/src/surface_cdms/cli.py
installer/src/surface_cdms/install.py
installer/src/surface_cdms/info.py
installer/src/surface_cdms/doctor.py
installer/src/surface_cdms/manage.py
installer/src/surface_cdms/version.py
```

For quick testing during development:

```bash
cd installer
source .venv/bin/activate
python -m pip install -e .
surface --version
surface info
surface doctor
```

For full package testing:

```bash
cd ..
./scripts/build_installer_wheel.sh
pipx uninstall surface-cdms
pipx install installer/dist/*.whl
surface --version
surface info
surface doctor
```

## 10. Database migrations

If a developer changes Django models inside the SURFACE app, they may need to create migrations.

Model changes usually happen in:

```text
surface/api/wx/models.py
```

Developers should create and review migrations carefully.

A migration should be committed if it is needed for the application to run correctly.

Do not ignore required migrations.

Before opening a pull request involving model changes, confirm:

- migrations were created if needed
- migrations apply successfully
- the app starts after migration
- existing data is not unintentionally damaged

## 11. Celery and background tasks

SURFACE uses Celery workers for background processing.

If changing task logic, check the relevant worker logs.

Examples:

```bash
surface logs celery_worker_default --tail 100
surface logs celery_worker_ingest --tail 100
surface logs celery_worker_summary --tail 100
surface logs celery_worker_maintenance --tail 100
surface logs celery_worker_export --tail 100
```

When testing task changes, confirm:

- the task is registered
- the task runs on the expected queue
- the task does not crash the worker
- errors are logged clearly
- task status is updated correctly, if applicable

## 12. Testing changes

Before opening a pull request, developers should test the workflow affected by their change.

At minimum:

```bash
surface --version
surface info
surface doctor
```

For installer changes:

```bash
surface install
surface containers
surface logs --tail 50
surface restart
surface down
surface up
```

For uninstall changes:

```bash
surface uninstall --keep-images
```

For SURFACE application changes, test the relevant workflow.

Examples:

| Change area | Suggested testing |
|---|---|
| Station metadata | Create, edit, delete, cancel, protected delete |
| Decoders | Upload and ingest sample files |
| QC | Confirm flags are applied correctly |
| Summaries | Confirm hourly/daily summaries generate |
| Exports | Test CSV and XLSX export |
| Backups | Test manual backup and restore |
| WIS2Box | Test config save, publish task, cleanup task |
| Celery tasks | Check worker logs and task results |
| Permissions | Test pages with expected roles/users |

## 13. Validation checklists

Formal validation documents are stored in:

```text
docs/testing/
```

Important checklists:

```text
docs/testing/clean-machine-lifecycle-test.md
docs/testing/surface-application-validation-test.md
```

Use the clean-machine lifecycle test when validating:

- install
- info
- doctor
- containers
- logs
- restart
- down/up
- uninstall
- reinstall

Use the SURFACE application validation test when validating:

- authentication
- database setup
- core UI
- ingestion
- summaries
- exports
- Celery
- backups
- restore
- WIS2Box
- operational behavior

## 14. Code style expectations

Developers should aim for:

- clear code
- readable names
- small focused commits
- simple logic where possible
- comments when behavior is not obvious
- safe error handling
- no hard-coded secrets
- no machine-specific paths unless required and documented

Before committing:

```bash
git status
```

Check that you are not committing:

- generated files
- runtime files
- local databases
- Docker volumes
- passwords
- environment files containing secrets
- local editor files

## 15. Commit guidelines

Use clear commit messages.

Good examples:

```bash
git commit -m "Fix station delete redirect"
git commit -m "Add Davis decoder validation"
git commit -m "Update install documentation"
git commit -m "Improve backup error handling"
```

Avoid vague messages:

```text
fix stuff
updates
changes
work
```

A commit should usually do one focused thing.

## 16. Pull request process

Before opening a pull request:

1. Update your local `main`.

```bash
git checkout main
git pull origin main
```

2. Return to your branch.

```bash
git checkout your-branch-name
```

3. Merge or rebase from `main`.

```bash
git merge main
```

4. Resolve conflicts if there are any.

5. Run relevant tests.

6. Build the installer wheel if your change affects packaging or the SURFACE app artifact.

```bash
./scripts/build_installer_wheel.sh
```

7. Check the package if relevant.

```bash
cd installer
python3 -m twine check dist/*
```

8. Push your branch.

```bash
git push origin your-branch-name
```

9. Open a pull request into `main`.

## 17. Pull request description template

Each pull request should include:

```md
## Summary

Describe what this pull request changes.

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation update
- [ ] Refactor
- [ ] Test/validation update
- [ ] Installer/packaging change

## What was changed?

-
-
-

## How was it tested?

- [ ] `surface --version`
- [ ] `surface info`
- [ ] `surface doctor`
- [ ] `surface install`
- [ ] Relevant UI workflow tested
- [ ] Relevant Celery task tested
- [ ] Relevant decoder/ingestion workflow tested
- [ ] Installer wheel built
- [ ] `twine check dist/*` passed

## Screenshots or logs

Add screenshots or logs if useful.

## Notes for reviewers

Mention anything reviewers should pay special attention to.
```

## 18. Review expectations

Reviewers should check:

- Does the change solve the stated problem?
- Is the code readable?
- Are edge cases handled?
- Are errors handled clearly?
- Are secrets or generated files accidentally included?
- Was the relevant workflow tested?
- Does the change affect installation, packaging, or releases?
- Does documentation need to be updated?

Review comments should be clear and actionable.

## 19. Merging

Only merge when:

- the pull request has been reviewed
- required changes have been addressed
- relevant tests/checks have passed
- the branch is up to date enough with `main`
- the change is safe to include in the next release

After merging, delete the feature branch if it is no longer needed.

## 20. Release-related changes

If a change affects the packaged SURFACE application, run:

```bash
./scripts/build_installer_wheel.sh
```

This ensures the app artifact inside the installer wheel is updated.

For releases, update:

```text
VERSION
installer/pyproject.toml
CHANGELOG.md
README.md if needed
```

Git tags should include the leading `v`:

```text
v1.0.0
```

Python package versions should not include the leading `v`:

```text
1.0.0
```

## 21. Security and secrets

Never commit:

- passwords
- tokens
- `.env` files containing secrets
- `production.env`
- database dumps with sensitive data
- local database files
- Docker volumes or runtime data
- generated password files

If a secret is accidentally committed, notify the project maintainer immediately so it can be rotated and removed properly.

## 22. Summary

A good contribution should be:

- focused
- tested
- documented when needed
- safe to review
- safe to merge
- free of secrets and generated runtime files
