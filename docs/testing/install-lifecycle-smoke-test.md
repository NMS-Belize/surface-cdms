# SURFACE CDMS Install Lifecycle Smoke Test

This checklist validates that SURFACE CDMS can be installed, managed, uninstalled, and reinstalled on a test machine.

This is a smaller smoke test than the full SURFACE application validation checklist. It focuses on the installer, management CLI, Docker lifecycle, and uninstall/reinstall behavior.

## Test machine requirements

- Ubuntu supported by SURFACE CDMS
- Docker installed and running
- Docker Compose v2 available
- Python 3 available
- pipx installed
- User has sudo access

## 1. Install the CLI

Install from PyPI:

```bash
pipx install surface-cdms
```

Or, during development, install from a locally built wheel:

```bash
pipx install installer/dist/*.whl
```

Verify:

```bash
surface --version
surface info
surface doctor
```

Expected:

- `surface --version` shows the version being tested
- `surface info` works
- `surface doctor` passes installer checks
- If SURFACE is not installed yet, `surface doctor` should not fail only because install metadata is missing

Result:

```text
Pass/Fail:
Notes:
```

## 2. Run install

```bash
surface install
```

Expected:

- sudo password is validated
- configuration GUI opens
- form submits successfully
- SURFACE app artifact extracts correctly
- Docker containers start successfully
- install metadata is written
- install status becomes `installed`

Verify:

```bash
surface info
surface doctor
cat ~/.surface-cdms/install.json
```

Expected metadata should include:

```json
{
  "install_status": "installed",
  "surface_repo_path": ".../surface/",
  "compose_file": ".../surface/docker-compose.yml"
}
```

Result:

```text
Pass/Fail:
Notes:
```

## 3. Verify containers

```bash
surface containers
```

Expected:

- postgres/database container is running
- redis container is running
- cache container is running
- api container is running
- nginx container is running
- celery beat container is running
- celery worker containers are running

Result:

```text
Pass/Fail:
Notes:
```

## 4. Verify logs

```bash
surface logs --tail 50
surface logs api --tail 50
```

Expected:

- logs are readable
- no immediate crash loops
- no permission errors
- no missing environment variable interpolation warnings caused by generated secrets

Result:

```text
Pass/Fail:
Notes:
```

## 5. Verify management commands

Restart services:

```bash
surface restart
surface containers
```

Stop services:

```bash
surface down
surface containers
```

Start services again:

```bash
surface up
surface containers
```

Expected:

- restart completes
- down stops services
- up starts services again
- containers return to running state

Result:

```text
Pass/Fail:
Notes:
```

## 6. Verify uninstall cancellation

```bash
surface uninstall --keep-images
```

When prompted, type something other than:

```text
DELETE SURFACE
```

Expected:

- uninstall is cancelled
- SURFACE install directory still exists
- containers are not removed by the cancelled operation

Result:

```text
Pass/Fail:
Notes:
```

## 7. Verify uninstall

```bash
surface uninstall --keep-images
```

When prompted, type:

```text
DELETE SURFACE
```

Expected:

- Docker services are stopped
- orphan containers are removed
- Docker volumes are removed
- installed SURFACE directory is deleted
- install metadata is deleted

Verify:

```bash
surface info
surface doctor
surface containers
ls -la ~/.surface-cdms/
```

Expected:

- `surface info` shows not installed or metadata missing
- `surface doctor` still passes installer checks
- `surface containers` fails cleanly and tells the user to run `surface install` first

Result:

```text
Pass/Fail:
Notes:
```

## 8. Verify reinstall after uninstall

```bash
surface install
surface info
surface doctor
surface containers
```

Expected:

- reinstall succeeds
- metadata is recreated
- containers start successfully

Result:

```text
Pass/Fail:
Notes:
```

## 9. Record final test result

Record the following after testing:

```text
SURFACE CDMS version:
Test machine OS:
Python version:
Docker version:
Docker Compose version:
pipx version:
Install result:
Management commands result:
Uninstall result:
Reinstall result:
Known issues:
Overall result: PASS / FAIL
Tester:
Date:
```
