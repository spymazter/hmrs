# HRMS — Biometric Attendance, Reports & Payroll

A Dockerized HR management system that reads punch in / punch out data from an eSSL / ZKTeco biometric device over TCP (default `192.168.20.90:4370`), converts it into attendance records, generates daily / weekly / monthly reports, processes payroll and prints salary slips. It includes an employee self-service portal and a flexible RBAC model where **multiple roles can be combined into a role group** and assigned to a user.

## Quick start

```bash
cd /Users/mohan/Documents/HRMS
cp .env.example .env
docker compose up -d --build
```

Open **http://localhost:7090**.

The API (OpenAPI docs) is available at **http://localhost:7090/api/docs**.

> The stack boots in `simulate` mode by default so you can explore the whole system immediately. Switch to the real device as described below.

The Compose file now runs **frontend and backend in a single container** named `hrms`. If you are upgrading from the previous two-container setup, run `docker compose up -d --build --remove-orphans`; the existing `hrms_hrms-data` volume is reused and no data is deleted.

## Published single-container image (Docker Hub)

The complete HRMS frontend and backend run in **one container** published as:

- `spymazter/hmrs:latest`

The image includes `linux/amd64` and `linux/arm64`, so an x64 server pulls the amd64 variant automatically while this ARM Mac stays native. To force x64 explicitly, use `docker pull --platform linux/amd64 spymazter/hmrs:latest`.

To run from the published image instead of building locally:

```bash
docker pull spymazter/hmrs:latest

docker run -d --name hrms --restart unless-stopped \
  -e SECRET_KEY='replace-with-a-long-random-string' \
  -e DATABASE_URL='sqlite:///./data/hrms.db' \
  -e TZ='Asia/Kolkata' \
  -e DEVICE_MODE='live' \
  -e DEVICE_IP='192.168.20.90' \
  -e DEVICE_PORT='4370' \
  -e DEVICE_TIMEOUT='5' \
  -e DEVICE_SYNC_INTERVAL_MINUTES='10' \
  -e LOG_RETENTION_DAYS='365' \
  -e AUTO_CREATE_DEVICE_USERS='true' \
  -e DEFAULT_SHIFT_NAME='General Shift' \
  -e PDF_DIR='./data/pdfs' \
  -v hrms_hrms-data:/app/data \
  -p 7090:80 \
  spymazter/hmrs:latest
```

Open **http://localhost:7090**. The `hrms_hrms-data` volume preserves the database and generated PDFs; the stored device mode/IP/port from **Biometric devices** takes precedence over the environment values. The older `spymazter/hmrs-backend` and `spymazter/hmrs-frontend` images remain published but are no longer required.

Source code: **https://github.com/spymazter/hmrs**. The local `docker compose up -d --build` workflow still builds natively for the host architecture.

## Default logins

| Login | Password | Access |
|---|---|---|
| `admin` | `admin123` | Everything (Admin role + Full Access group) |
| `hr` | `hr123` | Employees, shifts, attendance, reports, leave approvals |
| `payroll` | `payroll123` | Salary structures, payroll processing, salary slips |
| `manager` | `manager123` | Team attendance, reports, leave approvals |
| `employee` | `emp123` | Employee self-service portal (Aarav Sharma) |

Change these passwords after first login using the profile menu → **Change password**.

## Connecting the biometric device

1. Edit `.env`:
   ```env
   DEVICE_MODE=live
   DEVICE_IP=192.168.20.90
   DEVICE_PORT=4370
   ```
2. Rebuild / restart: `docker compose up -d --build`.
3. For an existing database, open **Biometric devices** and set the device **Mode** to `live` (the stored device mode takes precedence over `.env`). On a fresh database the seed uses `DEVICE_MODE` from `.env`.
4. In the app go to **Biometric devices → Test connection**, then **Sync punches now**. The saved IP/port from **Edit IP / settings** is used immediately by the next sync — no restart needed.

The backend uses the ZKTeco/eSSL TCP protocol via `pyzk`. It reads device users and attendance logs, deduplicates punches, and creates employees for unknown enrolment IDs when `AUTO_CREATE_DEVICE_USERS=true`. A background job re-syncs every `DEVICE_SYNC_INTERVAL_MINUTES`.

**Sync progress log:** **Sync punches now** starts a background job and opens a live log window directly under the button. It polls the job every 0.7 s, shows `RUNNING / CONNECTING → FETCHED → PUNCHES → SUCCESS / DONE`, and stays visible until **Clear** is clicked. Recent runs appear in the table below. The same endpoints are available to scripts:

- `POST /api/devices/{device_id}/sync-job` → `{"job_id": 1, "message": "Sync started"}` (HTTP 202)
- `GET /api/devices/sync-jobs?limit=20`
- `GET /api/devices/sync-jobs/{job_id}`

> **Read-only and safe:** the integration only calls `get_users()` and `get_attendance()`. It never clears logs, deletes users, or changes device settings/time. The device keeps all of its own data.

> **Incremental sync:** `pyzk` reads the full attendance log each time, but the app stores a high-water mark (`device_sync_state.last_punch_time`) and only processes punches newer than the last successful sync. Re-running a sync therefore imports 0 punches and does not rewrite attendance.

> **Ping fix:** `pyzk` normally shells out to ICMP `ping` before connecting; the slim Docker image has no `ping` binary. `_zk_connection()` passes `ommit_ping=True` so the connection is validated over TCP `4370` instead.

> **Network note:** the Docker host must be able to reach `192.168.20.90:4370`. If the device is on a different subnet, add the route on the host or use `network_mode: host` for the `hrms` service.

If the device is unreachable in `live` mode, the Devices page shows the connection error and no demo data is invented.

## Features

- **Authentication & RBAC** — JWT login, permissions, roles, **role groups** (combine any roles), direct role assignment, and group assignment. Effective permissions = union of direct roles + all roles in assigned groups.
- **Employee master** — code, personal details, department, designation, location, shift, manager, device UID, optional self-service login.
- **Permanent identity rules** — employee codes and device UIDs are unique case-insensitively and reserved for life. A retired or deleted ID can never be reassigned to another employee, and an employee ID can be linked to only one user ever. Live sync skips device users whose derived `DEV-<uid>` ID is already reserved, instead of creating a duplicate.
- **People & shifts master data** — departments, designations and locations are managed in **People & shifts**; master rows in use by employees cannot be deleted until reassigned.
- **Shifts** — start/end time, late grace, early-out grace, full-day and half-day thresholds, weekly off days, plus `fixed` / `rotational` / `flexi` / `night` type, flexi target hours, reference break minutes and weekly rotation groups.
- **Shift groups** — managed under **People & shifts → Shift groups**. A group holds a set of shifts and mapped employees; mapped employees rotate through the group's shifts weekly when no explicit roster row exists. Employees can be mapped on the Shift groups page (searchable employee placeholder + mapped list) or from the Shift group field on the Employees form; shifts can be assigned from the Shifts form. This replaces the older free-text `rotation_group`, which remains supported as a fallback. API: `/api/shift-groups` (CRUD) and `PUT /api/shift-groups/{id}/employees` (bulk mapping).
- **Biometric integration** — connection test, manual sync, auto-sync, raw punch log, manual punch entry, unmapped UID detection.
- **Attendance engine** — strict in/out session pairing (or first/last mode), duplicate debounce, shift windows (including night shifts), overtime and comp-off rules, sandwich rule, late penalties, leave/OD/regularization overlays, and recomputation. Thresholds and multipliers are editable from **ATTENDANCE → Advanced reports → Engine settings**.
- **Reports** — daily, weekly (ISO) and monthly summaries with department filters and CSV export.
- **Advanced reports** — 14 time & attendance modules in the sidebar under **ATTENDANCE → Advanced reports** (below **Reports**), with date/department/location/designation/shift/employee-code filters (department, location, designation and shift support multiple selected values), KPI and chart summaries, formatted XLSX/CSV/JSON/PDF exports, a CLI, and runtime engine configuration.
- **Searchable dropdowns** — every employee, department, period and status picker can be filtered by typing; no long native select lists.
- **KPI drill-down** — clicking **Active employees**, **Present today** or **Absent today** on the dashboard opens the matching filtered employee/attendance view.
- **Payroll** — salary structures (earnings, PF, ESI, professional tax, income tax), monthly payroll periods, prorated processing from attendance, salary slip generation and printable **PDF payslips**.
- **Leave management** — leave types, applications, approvals, integration with attendance and payroll (paid leave days).
- **Employee portal** — own profile, attendance, leave applications and salary slips.
- **Audit-friendly** — raw punches are kept alongside computed records so recomputation is safe.

## Advanced Time & Attendance reporting engine

Open **ATTENDANCE → Advanced reports** in the sidebar, directly below **Reports** (requires `report.view`; exports require `report.export`). The page loads all 14 reports from the same filtered, recomputed attendance records used by the rest of the app:

| Category | Reports |
|---|---|
| Daily operational | `daily_basic`, `daily_detailed`, `punch_pairs`, `live_headcount` |
| Monthly & payroll | `monthly_payroll_summary`, `muster_roll`, `ot_compoff` |
| Exception & compliance | `late_early`, `missed_single`, `continuous_absence`, `shift_deviation` |
| Audit & raw logs | `raw_punch_log`, `regularization_audit`, `leave_od_balance` |

- **Filters** — from/to date (max 366 days), employee code, department, location, designation and shift. Every picker is searchable; muster-roll output includes every employee in scope, including employees with no punches.
- **Statistics** — row counts, final-status distribution and net-hours trend charts are rendered above the table.
- **Exports** — Excel (styled XLSX with headers, totals and summary), CSV (UTF-8 with BOM), JSON and PDF (paginated tables with summary) from the **Excel / CSV / JSON / PDF** buttons. Every report also includes a summary section in its API response.
- **Engine settings** — **Engine settings** opens the runtime calculation config (pairing mode, debounce, half/full-day hours, OT thresholds, multipliers, comp-off hours, sandwich rule, late penalties, authorized device serials). Saving persists to `app_settings` under `advanced_engine_config`; **Recalculate** rebuilds the selected date range with the current settings.
- **Overlay data** — approved regularizations, on-duty requests and comp-offs feed the engine. They are available from `GET/POST /api/attendance/advanced/regularizations`, `/on-duty` and `/comp-offs`; creating one recomputes the affected employee/date.
- **API aliases** — all advanced endpoints are mounted at both `/api/attendance/advanced/*` (the UI location) and `/api/reports/advanced/*`:
  - `GET /meta` — report catalogue and filter options
  - `GET /report?report=daily_basic&from_date=…&to_date=…` — rows, columns, summary and charts
  - `GET /export?report=…&format=xlsx|csv|json|pdf` — formatted download
  - `GET/PUT /config`, `POST /recompute`
- **CLI** — runs against the same SQLite database inside the single HRMS container:

  ```bash
  docker compose exec hrms python -m cli.advanced_reports --list-reports

  docker compose exec hrms python -m cli.advanced_reports \
    --report muster_roll --from 2026-11-01 --to 2026-11-30 \
    --dept "IT department" --format xlsx --output /tmp/muster.xlsx

  docker compose exec hrms python -m cli.advanced_reports \
    --report monthly_payroll_summary --from 2026-11-01 --to 2026-11-30 \
    --employee-code DEV-111 --format table
  ```

  `--location`, `--designation`, `--shift` and `--format table|xlsx|csv|json|pdf` are also supported. `--output` writes bytes to a file; without it, formatted output goes to stdout.

- **Tests** — `docker compose run --rm hrms python -m pytest -q` runs the engine, report-builder, overlay and export-formatter suite (21 tests).

## Architecture

Docker Compose builds one image from the root `Dockerfile` and runs a single container named `hrms`:

```
HRMS/
├── Dockerfile                  # single image: Vite build + Python API + nginx + supervisor
├── docker-compose.yml          # one service on port 7090
├── nginx-single.conf           # /api → 127.0.0.1:8000, SPA fallback
├── supervisord.conf            # runs uvicorn and nginx inside the container
├── .env.example
├── backend/                    # FastAPI app, CLI, scripts and pytest suite
└── frontend/                   # React/Vite source
```

Inside the container, supervisor starts `uvicorn` on `127.0.0.1:8000` and nginx on port `80`; nginx serves the built React app and proxies `/api` to uvicorn. Compose publishes host port `7090` to container port `80`.

## Common commands

```bash
docker compose logs -f hrms       # watch sync/startup logs
docker compose restart hrms       # restart the single container
docker compose down              # stop (data stays in hrms_hrms-data volume)
docker compose down -v            # stop and delete all data

docker compose run --rm hrms python -m pytest -q          # run tests
docker compose exec hrms python -m cli.advanced_reports --list-reports
```

## Notes

- Data is stored in the named Docker volume `hrms-data` (`data/hrms.db` and generated PDFs).
- Payroll working days are Monday–Friday minus configured holidays.
- Payroll processing defaults to **`scope=device`**: only live biometric employees (`DEV-*`) are paid, using their device attendance; demo `EMP-*` slips for that period are replaced. Salary structures must be imported first — processing fails with a clear message instead of generating zero-pay slips. Use `{"scope":"all","replace_existing":false}` via the API if you intentionally want the old behaviour.
- The Salary structures and Salary slips lists also default to live `DEV-*` records only. Add `?include_demo=true` to either endpoint to inspect seeded demo data; self-service users always retain access to their own slip.
- Salary structures can be imported/exported from **Payroll → Salary structures** using CSV or XLSX. Download the template for accepted columns; rows are matched by `Employee Code` (`DEV-111` or `111`) or employee ID. `POST /api/payroll/structures/import` accepts `replace_existing=true` to clear live rows first; exports support `?format=xlsx`.
- Administrators can manage departments, designations and locations from **People & shifts → Departments / Designations / Locations** (or **People & shifts → Locations**). Rows in use by employees cannot be deleted until those employees are reassigned. Employee records have a `location_id`, and the advanced report location filter uses the same master list.
- Shift metadata (`shift_type`, `rotation_group`, `target_hours`, `break_minutes`) is editable from **People & shifts → Shifts**. Explicit `ShiftRoster` rows override default shifts; without a roster row, shifts in the same `rotation_group` rotate weekly. Comp-off earned on a weekly off/holiday keeps the WO/HL status and contributes OT instead of replacing it.
- Employee logins see only their own salary slips in **Payroll & slips**, with no period/structure/processing controls, no “mark paid”, and no manual punch/recompute/delete controls in **Attendance**. Multi-month slips can be downloaded as a ZIP from the slips page or **My portal → Download all slips**.
- Employee-linked users created through **Roles & access → Users** or **Employees → Enable self-service login** must complete a first-login onboarding step: confirm personal details (DOB, first/last name, contact and emergency contact details) and set a new password. Their username cannot be changed. Existing accounts are treated as already complete.
- Employees can later update their own personal details from **My portal → Edit personal details** (`PUT /api/employees/me`). Employment fields such as employee code, status, device UID, department, designation, shift and manager remain admin-only.
- Punches are paired into every completed in/out segment of the day and the segment durations are added together, so multiple sessions (morning + evening) no longer count the gap as working time. Historical records are rebuilt automatically once after upgrading; `POST /api/attendance/recompute-all` can rebuild them again at any time.
- **Attendance → Daily records** status picker includes **Late arrivals** (`?status=late`): it matches every record with late minutes above the shift grace, regardless of whether the final status is present or half day. The dashboard’s “late arrivals” count uses the same rule.
- The **Attendance** page header of both tables has **Excel** and **PDF** buttons that download the current view (same tab, date range, employee and status filters) via `GET /api/attendance/export?view=records|logs&format=xlsx|pdf`. Exports include all matching rows up to 10,000 and respect each user's attendance scoping.
- Daily, weekly and monthly reports list **all employees in the selected department**, including those with no punches in that period, and show status breakdown charts, top-hours charts, department comparisons and KPI statistics. Export to CSV or a PDF report (with tables and charts) from the Reports page: `GET /api/reports/pdf?type=monthly&year=2026&month=8&department_id=25`.
- Attendance/punch history is retained for at least **365 days** (`LOG_RETENTION_DAYS`) and is never purged by normal sync/recompute flows. `GET /api/system/log-coverage` reports the stored date range and counts; the Reports page displays this coverage banner. The device currently supplies history from May 2026 onward.
- For production: set a strong `SECRET_KEY`, put the app behind TLS, and consider PostgreSQL by changing `DATABASE_URL`.
