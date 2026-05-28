# Contributing to SURFACE CDMS

Contributions are welcome.

SURFACE CDMS is currently in early alpha development. The project structure, installer, and release process are still being organized.

## Reporting issues

When reporting a bug, include:

- Your operating system and version
- Your Python version
- The SURFACE CDMS version
- The command you ran
- The full error message or traceback
- Steps to reproduce the issue


## Developer workflow

Developers should follow the detailed workflow guide when creating new features, fixing bugs, or preparing pull requests:

```text
docs/development/developer-workflow.md
```

In general:

- Do not work directly on `main`.
- Create a feature or fix branch from the latest `main`.
- Keep changes focused and easy to review.
- Test the relevant SURFACE workflow before opening a pull request.
- Rebuild the installer wheel when changes affect the packaged SURFACE app artifact.
- Do not commit secrets, runtime files, Docker data, database files, or generated environment files.

If a change modifies files inside the top-level `surface/` directory, rebuild the packaged SURFACE app artifact before building the installer wheel:

```bash
./scripts/build_installer_wheel.sh
```

Pull requests should include a clear summary, the type of change, what was tested, and any notes reviewers should pay attention to.


## Versioning

SURFACE CDMS follows Semantic Versioning.

Early releases use alpha versions such as:

```text
0.1.0-alpha.1
0.1.0-alpha.2
```

Release notes should be added to `CHANGELOG.md`.