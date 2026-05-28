# SURFACE CDMS Clean Machine Lifecycle Test

This checklist validates that SURFACE CDMS can be installed, managed, and uninstalled on a clean machine.

## Test machine requirements

- Ubuntu supported by SURFACE CDMS
- Docker installed and running
- Docker Compose v2 available
- Python 3 available
- pipx installed
- User has sudo access

## 1. Install the CLI

Install from the locally built wheel:

```bash
pipx install /path/to/surface_cdms-0.6.0a1-py3-none-any.whl
```

Verify:

```bash
surface --version
surface info
surface doctor
```

Expected:

- `surface --version` shows `0.6.0-alpha.1` or `0.6.0a1`
- `surface info` works
- `surface doctor` passes installer checks
- If SURFACE is not installed yet, `surface doctor` should not fail only because install metadata is missing

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

## 4. Verify logs

```bash
surface logs --tail 50
surface logs api --tail 50
```

Expected:

- logs are readable
- no immediate crash loops
- no permission errors
- no missing env variable interpolation warnings caused by generated secrets

## 5. Verify management commands

```bash
surface restart
surface containers
surface down
surface containers
surface up
surface containers
```

Expected:

- restart completes
- down stops services
- up starts services again
- containers return to healthy/running state

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
- SURFACE directory still exists
- containers are not removed by the cancelled operation

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

## 9. Record test result

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
```
