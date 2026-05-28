# SURFACE CDMS Application Validation Test

This checklist validates that the installed SURFACE application works correctly after a successful SURFACE CDMS installation.

This test is different from the clean-machine lifecycle test. The lifecycle test confirms that SURFACE CDMS can be installed, managed, and uninstalled. This application validation test confirms that SURFACE itself behaves correctly after installation.

## Test machine requirements

- SURFACE CDMS installed successfully
- `surface doctor` passes
- `surface containers` shows the expected containers running
- Admin user credentials are available
- Test station files are available for standard, high-frequency, and staged/historical ingestion
- Backup/restore test dump is available locally and/or through FTP
- WIS2Box test configuration is available if publishing is included in validation

## 1. Authentication

### 1.1 Login works

Steps:

```bash
surface containers
surface logs api --tail 50
```

Then open SURFACE in the browser and log in with the configured admin account.

Expected:

- Login page loads
- Admin user can log in
- User is redirected to the expected landing/dashboard page
- No server error occurs after login

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 1.2 Admin user created correctly

Steps:

- Log in as the admin user created during installation
- Open the admin/user management area if available
- Confirm the admin account exists

Expected:

- Admin user exists
- Admin user can access admin-level pages
- Admin user has expected permissions

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 1.3 Permissions and roles load correctly

Steps:

- Review groups/roles/permissions in the UI or Django admin
- Confirm default permissions are present

Expected:

- Permission groups load
- Pages protected by permissions behave correctly
- No missing permission errors occur

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

## 2. Database

### 2.1 Migrations complete

Steps:

```bash
surface logs api --tail 100
```

Optional container check:

```bash
docker exec -it surface-api python manage.py showmigrations
```

Expected:

- Migrations completed during installation
- No migration errors appear in logs
- Application starts normally

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 2.2 Initial fixtures load

Steps:

- Open relevant setup pages in SURFACE
- Check code tables, variables, station profiles, formats, intervals, and other default setup data

Expected:

- Initial fixture data exists
- Required dropdowns are populated
- No missing fixture-related errors occur

Result:

```text
Pass/Fail: Pass
Notes:
```

### 2.3 Stations, variables, and code tables exist

Steps:

- Open station pages
- Open variable/measurement/code table pages
- Confirm expected records are present

Expected:

- Stations page loads
- Variables exist
- Code tables exist
- No database errors occur

Result:

```text
Pass/Fail: Pass
Notes:
```

### 2.4 Timescale/PostGIS functionality works

Steps:

- Confirm database container is running
- Open pages/features that depend on TimescaleDB and spatial data
- Run any available spatial analysis or map-based feature

Expected:

- Timescale-backed data operations work
- Spatial/PostGIS features work
- No missing extension errors occur

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

## 3. Core UI

### 3.1 Dashboard loads

Steps:

- Log in
- Open the dashboard

Expected:

- Dashboard loads successfully
- Charts/cards/tables render
- No server errors occur

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 3.2 Station pages load

Steps:

- Open station list
- Open station detail/edit pages

Expected:

- Station list loads
- Station details load
- Station edit forms load

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 3.3 Forms save correctly

Steps:

- Create or edit a safe test record
- Save the form
- Reopen the record

Expected:

- Form saves successfully
- Saved changes persist
- Validation errors are shown clearly when input is invalid

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 3.4 Delete/protected-object behavior works

Steps:

- Attempt to delete a record that is safe to delete
- Attempt to delete a record protected by related database records

Expected:

- Safe delete works
- Protected delete shows a friendly error
- No raw IntegrityError/ProtectedError page appears

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

## 4. Data ingestion

### 4.1 Standard station file ingestion works

Steps:

- Upload or ingest a standard station test file
- Monitor task status and logs

```bash
surface logs api --tail 100
surface logs celery_worker_ingest --tail 100
```

Expected:

- File is accepted
- Decoder runs
- Data is inserted or staged as expected
- No task failure occurs

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 4.2 High-frequency ingestion works

Steps:

- Upload or ingest a high-frequency test file
- Monitor ingestion status

Expected:

- High-frequency file is processed
- Data is inserted or staged correctly
- No unexpected timeout or decoder error occurs

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 4.3 Staged/historical ingestion works

Steps:

- Run a staged or historical ingestion test
- Confirm staged data is processed into raw data as expected

Expected:

- Historical/staged workflow completes
- Data appears in the expected tables/views
- Status values are updated correctly

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 4.4 Decoder flow works

Steps:

- Test at least one known decoder
- Confirm decoded values match expected output

Expected:

- Decoder selects correctly
- Datetime, station, variable, measured value, and interval/seconds behavior are correct
- Bad rows are handled safely

Result:

```text
Pass/Fail: Pass
Notes: TOA5 decoder working flawlessly.
```

### 4.5 Quality control runs successfully

Steps:

- Run ingestion or QC task that triggers quality control
- Review processed records and flags

Expected:

- QC task runs successfully
- Quality flags are applied correctly
- No QC-related task failures occur

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

## 5. Summaries

### 5.1 Hourly summaries generate

Steps:

- Insert or ingest data that should produce hourly summaries
- Run/wait for hourly summary processing

Expected:

- Hourly summary records are created
- Values are reasonable
- No summary task errors occur

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 5.2 Daily summaries generate

Steps:

- Insert or ingest data that should produce daily summaries
- Run/wait for daily summary processing

Expected:

- Daily summary records are created
- Values are reasonable
- No summary task errors occur

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 5.3 High-frequency summaries generate

Steps:

- Ingest high-frequency data
- Run/wait for high-frequency summary processing

Expected:

- High-frequency summary records are created
- Values are reasonable
- No task failures occur

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

## 6. Exports

### 6.1 CSV export works

Steps:

- Run a CSV export for a small known dataset
- Open the exported file

Expected:

- CSV file is created
- File contains expected columns and data
- Datetime and measured values are formatted correctly

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 6.2 XLSX export works

Steps:

- Run an XLSX export for a small known dataset
- Open the exported file

Expected:

- XLSX file is created
- File opens successfully
- Data is correct and readable

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 6.3 Large export behavior is acceptable

Steps:

- Run a large export using a realistic date range/station/variable selection
- Measure completion time

Expected:

- Export completes
- Runtime is acceptable for the dataset size
- No worker crash or memory failure occurs

Result:

```text
Dataset size:
Runtime:
Pass/Fail: Pass
Notes: N/A
```

## 7. Celery

### 7.1 Beat runs

Steps:

```bash
surface containers
surface logs celery_beat --tail 100
```

Expected:

- Celery beat container is running
- Scheduled tasks are being detected/sent
- No beat startup errors occur

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 7.2 Default queue works

Steps:

```bash
surface logs celery_worker_default --tail 100
```

Expected:

- Default worker is running
- Default queue tasks execute successfully

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 7.3 Summary queue works

Steps:

```bash
surface logs celery_worker_summary --tail 100
```

Expected:

- Summary worker is running
- Summary tasks execute successfully

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 7.4 Ingest queue works

Steps:

```bash
surface logs celery_worker_ingest --tail 100
```

Expected:

- Ingest worker is running
- Ingest tasks execute successfully

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 7.5 Maintenance queue works

Steps:

```bash
surface logs celery_worker_maintenance --tail 100
```

Expected:

- Maintenance worker is running
- Maintenance tasks execute successfully

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 7.6 Export queue works

Steps:

```bash
surface logs celery_worker_export --tail 100
```

Expected:

- Export worker is running
- Export tasks execute successfully

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

## 8. Backups

### 8.1 Manual backup works

Steps:

- Trigger a manual backup
- Confirm backup file is created

Expected:

- Backup completes successfully
- Backup file exists
- Backup file size is reasonable
- No task failure occurs

Result:

```text
Pass/Fail: Pass
Notes: However backups are taking extremely long times to complete. This is not an immediate issue right now, but it should be looked into for the v1.1.0 release. Also backups are unusually large. Another issue for the v1.1.0 release. An issue on GitHub should definitely be created.
```

### 8.2 Scheduled backup works

Steps:

- Confirm scheduled backup task is configured
- Wait for scheduled backup or temporarily trigger it

Expected:

- Scheduled backup runs
- Backup file is created
- Old backup retention behavior is acceptable

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 8.3 Restore from local dump works

Steps:

- Provide a local backup/restore dump
- Run restore workflow
- Confirm application starts afterward

Expected:

- Restore completes
- Database is restored
- SURFACE starts successfully
- Data appears as expected

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 8.4 Restore from FTP dump works

Steps:

- Configure FTP dump source
- Run restore workflow
- Confirm dump is downloaded and restored

Expected:

- FTP download succeeds
- Restore completes
- SURFACE starts successfully
- Data appears as expected

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

## 9. WIS2Box / publishing

### 9.1 Publishing config saves

Steps:

- Open WIS2Box/publishing configuration
- Save test configuration

Expected:

- Publishing config saves successfully
- Values persist after reload
- No validation/server errors occur

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 9.2 Publish task runs

Steps:

- Trigger or wait for publish task
- Monitor logs

Expected:

- Publish task runs
- Expected message/output is generated
- No task crash occurs

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 9.3 Cleanup task runs

Steps:

- Trigger or wait for WIS2Box cleanup task
- Monitor logs

Expected:

- Cleanup task runs
- Old/temporary publishing files are handled correctly
- No task crash occurs

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

## 10. Operational checks

### 10.1 Logs are readable

Steps:

```bash
surface logs --tail 100
surface logs api --tail 100
surface logs postgres --tail 100
```

Expected:

- Logs are readable through CLI
- No major repeated crash/error loop appears

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 10.2 Restart works

Steps:

```bash
surface restart
surface containers
surface logs --tail 50
```

Expected:

- Restart completes
- Containers return to running state
- Application loads after restart

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

### 10.3 Containers recover correctly after reboot

Steps:

- Reboot the test machine
- After login, check containers

```bash
surface containers
surface logs --tail 50
```

Expected:

- Required containers restart according to Docker restart policy
- SURFACE loads in the browser
- No manual recovery is required

Result:

```text
Pass/Fail: Pass
Notes: N/A
```

## Final validation result

Record the final result:

```text
Test machine OS: Ubuntu 22.04
Docker version: N/A
Docker Compose version: N/A
Python version: 3.10
pipx version: N/A
Installed SURFACE path: /home/eltech/surface/
Overall result: Pass
Blocking issues: None
Non-blocking issues: One (Question 8.1)
Tester: Jeremiah Hammond
Date: May 27 2026
```
