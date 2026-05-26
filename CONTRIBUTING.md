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

## Local development

Clone the repository:

```bash
git clone https://github.com/NMS-Belize/surface-cdms.git
cd surface-cdms
```

Set up the installer package:

```bash
cd installer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

Test the CLI:

```bash
surface --version
surface install
```

## Versioning

SURFACE CDMS follows Semantic Versioning.

Early releases use alpha versions such as:

```text
0.1.0-alpha.1
0.1.0-alpha.2
```

Release notes should be added to `CHANGELOG.md`.