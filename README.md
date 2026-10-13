# SolarEdge Harvest (seh)

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub release](https://img.shields.io/github/v/release/johnzastrow/seh)](https://github.com/johnzastrow/seh/releases)
[![Code style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

![seh logo](docs/images/logo.png)

Download your data from SolarEdge monitoring servers and store it in a relational database.

> **v0.3.0 uses the SolarEdge Monitoring API V2.** SolarEdge retired the V1 API (static
> API keys) on 2026-11-01. V2 requires a free developer app and a one-time OAuth
> sign-in; see the [migration guide](docs/MIGRATING_TO_API_V2.md).

**See the outputs on [this page](https://northredoubt.com/weather/) near the bottom where it says "Residential Solar"**

## Features

- **Multi-database support**: SQLite (default), PostgreSQL, and MariaDB
- **Comprehensive data sync**: Sites, equipment, energy, 15-minute power and power breakdown, power flow, batteries, meters, alerts, inventory (including optimizers), and inverter telemetry
- **Incremental sync**: Only fetches new data since last sync with configurable overlap buffer
- **SolarEdge API V2 with OAuth**: One-time browser sign-in (`seh auth login`), automatic token refresh
- **Rate limiting**: Paces requests to 10/minute and tracks the 2,000-credit monthly budget
- **Retry with backoff**: Automatic retries with exponential backoff on transient failures
- **Data export**: Export to CSV, JSON, Excel (.xlsx), or SQL dump
- **Database views**: Pre-built views for common queries (8 views with `v_seh_` prefix)
- **Structured logging**: JSON logging with optional file rotation via structlog
- **Email notifications**: SMTP email alerts on sync errors or completion
- **CLI interface**: Rich terminal output with progress tables, status displays, and comprehensive help
- **Idempotent operations**: Upsert pattern ensures safe re-runs without duplicates
- **Configurable error handling**: Strict, lenient, or skip modes for error handling
- **Site filtering**: Sync specific sites by ID

### Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- A free app at [developer.solaredge.com](https://developer.solaredge.com/) with **Site Access**
  and the redirect URI `http://127.0.0.1:8765/callback`
- Your SolarEdge site ID (shown in the monitoring portal URL)
- Relational database (SQLite, PostgreSQL, or MariaDB)


## Installation and Quick Start

Run through these in order to see the app working. Then  setup your cron job to run regularly.

```bash
# 1. Clone and install
git clone https://github.com/johnzastrow/seh.git
cd seh

# Install with uv (recommended)
uv sync
# For PostgreSQL support
uv sync --extra postgresql

# For MariaDB support (requires system libraries: libmariadb-dev. First try `sudo apt install libmariadb3 libmariadb-dev` for ubuntu)
uv sync --extra mariadb

# For all database drivers
uv sync --extra all-databases

# For Excel export support
uv pip install openpyxl

# 2. Configure
cp .env.example .env
# Edit .env: SEH_OAUTH_CLIENT_ID, SEH_OAUTH_CLIENT_SECRET, SEH_SITE_IDS and other items
chmod 600 .env

# 3. Sign in to SolarEdge once (opens a browser; see 'seh auth --help' for servers)
uv run seh auth login

# 4. Initialize database and verify API access
uv run seh init-db
uv run seh check-api

# 5. Run initial full sync
uv run seh sync

# then do a --full to see the differences
uv run seh sync --full

# 6. Check status
uv run seh status

# Full diagnostics (API health, DB status, rate limits)
uv run seh status --diagnostics

# Incremental sync - the command to setup with a cron job. Maybe hourly
# cd /home/user/seh && /home/user/.local/bin/uv run seh sync for the full cron entry
uv run seh sync
```

## Configuration

Configuration is via environment variables or a `.env` file:

### Required Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `SEH_OAUTH_CLIENT_ID` | Client ID of your developer.solaredge.com app (**required**) | - |
| `SEH_OAUTH_CLIENT_SECRET` | Client secret of that app (**required**) | - |
| `SEH_SITE_IDS` | Comma-separated site IDs to sync (**required**; V2 cannot list sites) | - |

### Sign-in Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `SEH_TOKEN_FILE` | OAuth token file, written with owner-only permissions | `~/.config/seh/tokens.json` |
| `SEH_OAUTH_REDIRECT_PORT` | Loopback port of the registered redirect URI | `8765` |

### API Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `SEH_API_BASE_URL` | API base URL (must be https) | `https://monitoringapi.solaredge.com/v2` |
| `SEH_API_TIMEOUT` | Request timeout in seconds | `10` |
| `SEH_API_MAX_CONCURRENT` | Max concurrent requests | `3` |
| `SEH_API_PER_MINUTE_LIMIT` | Max requests per minute | `10` |
| `SEH_API_MONTHLY_CREDITS` | Monthly API credit budget (1 credit per request) | `2000` |
| `SEH_USAGE_FILE` | Monthly credit ledger shared by all seh processes | `~/.config/seh/usage.json` |

### Database Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `SEH_DATABASE_URL` | Database connection URL | `sqlite:///./seh.db` |

### Sync Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `SEH_ENERGY_LOOKBACK_DAYS` | Days to look back for energy data on first sync | `365` |
| `SEH_POWER_LOOKBACK_DAYS` | Days to look back for power data on first sync | `7` |
| `SEH_POWER_DETAILS_LOOKBACK_DAYS` | Days to look back for the power breakdown on first sync | `25` |
| `SEH_SYNC_OVERLAP_MINUTES` | Overlap buffer for incremental syncs | `15` |
| `SEH_POWER_TIME_UNIT` | Power data resolution (QUARTER_HOUR, HOUR, DAY, WEEK, MONTH, YEAR; V1's QUARTER_OF_AN_HOUR is accepted) | `QUARTER_HOUR` |

### Error Handling Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `SEH_ERROR_HANDLING` | Error mode: strict, lenient, skip | `lenient` |
| `SEH_MAX_RETRIES` | Max retry attempts for failed API requests | `3` |
| `SEH_RETRY_DELAY` | Base delay in seconds between retries | `2.0` |

### Logging Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `SEH_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `SEH_LOG_FILE` | Log file path (logs to console if not set) | - |
| `SEH_LOG_MAX_BYTES` | Max log file size before rotation | `10485760` (10MB) |
| `SEH_LOG_BACKUP_COUNT` | Number of backup log files | `5` |

### Email Notification Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `SEH_SMTP_ENABLED` | Enable email notifications | `false` |
| `SEH_SMTP_HOST` | SMTP server hostname | `smtp.gmail.com` |
| `SEH_SMTP_PORT` | SMTP server port | `587` |
| `SEH_SMTP_USE_TLS` | Use TLS for SMTP | `true` |
| `SEH_SMTP_USERNAME` | SMTP authentication username | - |
| `SEH_SMTP_PASSWORD` | SMTP authentication password | - |
| `SEH_SMTP_FROM_EMAIL` | From email address | - |
| `SEH_SMTP_TO_EMAILS` | Comma-separated recipient emails | - |
| `SEH_NOTIFY_ON_ERROR` | Send email on sync errors | `true` |
| `SEH_NOTIFY_ON_SUCCESS` | Send email on successful sync | `false` |

### Database URL Formats

```bash
# SQLite (default)
SEH_DATABASE_URL=sqlite:///./seh.db

# PostgreSQL
SEH_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/seh

# PostgreSQL with custom schema (note: '=' is URL-encoded as '%3D')
SEH_DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/seh?options=-csearch_path%3Dmy_schema

# MariaDB
SEH_DATABASE_URL=mariadb+mariadbconnector://user:password@localhost:3306/seh
```

## CLI Commands

### `seh init-db`

Create database tables and views. Safe to run multiple times.

```bash
uv run seh init-db
```

### `seh auth`

Sign in to SolarEdge (OAuth, API V2). Needed once; seh renews the sign-in automatically.

```bash
# Browser sign-in (on a server: run `ssh -L 8765:127.0.0.1:8765 user@server` first)
uv run seh auth login

# Paste the redirect address instead of using the local listener
uv run seh auth login --paste

# Show sign-in state (no API credits); --refresh proves renewal works
uv run seh auth status --refresh

# Revoke at SolarEdge and delete the token file
uv run seh auth logout
```

### `seh check-api`

Verify the sign-in, show the configured sites, and probe each V2 endpoint once (about 10 API
credits; `--no-probe` uses 1). `--update-config` adds unavailable data types to
`SEH_SKIP_DATA_TYPES`.

```bash
uv run seh check-api
```

### `seh api get`

Fetch one raw API V2 response, for diagnostics (1 credit per request; uses seh's sign-in,
so run it on the machine that syncs). `{site}` is replaced with the first `SEH_SITE_IDS`.

```bash
uv run seh api get /sites/{site}
uv run seh api get /sites/{site}/alerts -p alerts-in-page=100
uv run seh api get /sites/{site}/devices -p types=BATTERY -o devices.json
```

### `seh sync`

Synchronize data from SolarEdge to the database.

```bash
# Incremental sync (recommended for cron)
uv run seh sync

# Full sync (re-fetch the configured lookback periods; about 30 credits with defaults)
uv run seh sync --full

# Sync specific sites only
uv run seh sync --sites 12345,67890

# Verbose output
uv run seh sync -v
```

### `seh status`

Show sync status for all sites in the database. `--diagnostics` adds configuration and the
month's API credit usage.

```bash
# Basic status
uv run seh status

# Full diagnostics (DB, API settings, credits used this month)
uv run seh status --diagnostics

# Status for specific sites
uv run seh status --sites 12345,67890
```

### `seh export`

Export data to CSV, JSON, Excel, or SQL dump files.

```bash
# Export site information
uv run seh export sites
uv run seh export sites --format json -o sites.json
uv run seh export sites --format xlsx -o sites.xlsx

# Export energy readings
uv run seh export energy
uv run seh export energy --sites 12345 --start 2024-01-01 --end 2024-12-31

# Export power readings
uv run seh export power --format json

# Export equipment list
uv run seh export equipment

# Export inverter telemetry
uv run seh export telemetry --sites 12345 --serial ABC123

# Export inventory
uv run seh export inventory

# Export environmental benefits
uv run seh export environmental

# SQL dump of entire database
uv run seh export dump -o backup.sql
```

**Export options:**
- `--format`, `-f`: Output format (`csv`, `json`, or `xlsx`, default: `csv`)
- `--output`, `-o`: Output file path (auto-generates if not specified)
- `--sites`, `-s`: Comma-separated site IDs to filter
- `--start`, `--end`: Date range filtering (for time-series data)
- `--serial`: Filter by serial number (telemetry only)

### Global Options

```bash
# Use custom config file
uv run seh --config /path/to/.env sync

# Enable verbose output
uv run seh -v sync

# Get help
uv run seh --help
uv run seh sync --help

# Show version
uv run seh --version
```

## Data Model

### Database Tables

All tables are prefixed with `seh_` to avoid naming conflicts. Column-level detail, including which
columns API V2 fills, is in [docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md):

| Table | Description |
|-------|-------------|
| `seh_sites` | Installation details (name, location, timezone, peak power) |
| `seh_equipment` | Inverters with model, firmware and optimizer count |
| `seh_batteries` | Storage units with latest power and state of charge |
| `seh_energy_readings` | Daily energy production in Wh |
| `seh_power_readings` | 15-minute average power in W |
| `seh_power_flows` | Real-time power flow snapshots (PV, grid, load, storage) — one record per sync |
| `seh_power_details` | 15-minute production, consumption, self-consumption, feed-in and purchased power in W (from meter telemetry) |
| `seh_meters` | Meter devices (production, consumption, etc.) |
| `seh_meter_readings` | 15-minute power per meter (production, import, export) |
| `seh_alerts` | System alerts with impact, type, and affected component |
| `seh_environmental_benefits` | CO2 avoided (older equivalents kept from V1) |
| `seh_inventory` | All devices: inverters, meters, batteries, optimizers |
| `seh_inverter_telemetry` | 15-minute inverter AC power, voltage, current, frequency (V1 rows also have temperature and mode) |
| `seh_optimizer_telemetry` | Per-panel optimizer data; not available in API V2 (stays empty) |
| `seh_sync_metadata` | Tracks last sync time per site and data type |

### Database Views

Pre-built views for common queries (all prefixed with `v_seh_`):

| View | Description |
|------|-------------|
| `v_seh_site_summary` | Simplified site information |
| `v_seh_daily_energy` | Daily energy with kWh conversion |
| `v_seh_latest_power` | Most recent power reading per site |
| `v_seh_power_flow_current` | Latest power flow snapshot per site |
| `v_seh_sync_status` | Current sync status for all sites |
| `v_seh_equipment_list` | Equipment with site names |
| `v_seh_battery_status` | Current battery status |
| `v_seh_energy_monthly` | Monthly energy totals |

See [docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md) for complete schema documentation.

### Sync Strategy

1. **First run** (`--full`): Fetches historical data
   - Energy: 365 days lookback (configurable)
   - Power, meters, inverter telemetry: 7 days lookback (configurable)
   - Power details: 25 days lookback (configurable; V2 has no maximum)
   - Long ranges are split into SolarEdge's maximum windows (1 week for 15-minute data,
     1 month for daily data); each request costs 1 API credit

2. **Subsequent runs**: Incremental sync
   - Starts from the newest stored reading minus 15 minutes (configurable overlap), aligned to
     the interval start, so the interval that was in progress last time is completed
   - Uses upsert (ON CONFLICT DO UPDATE) for idempotent operations

3. **Data types synced** (in order):
   - Site details
   - Equipment list
   - Energy readings
   - Power readings + current power flow
   - Power details (15-minute breakdown derived from meter telemetry)
   - Storage/battery data
   - Meter devices and readings
   - Environmental benefits
   - Alerts
   - Inventory
   - Inverter telemetry
   - Optimizer telemetry (not available in V2; recorded as `skipped`)

## Scheduled Sync

Add to crontab for automatic updates. Run it as the user who ran `seh auth login` (the token
file is in that user's home directory).

```bash
# Edit crontab
crontab -e

# Once a day (~300 credits/month)
49 13 * * * cd /path/to/seh && /home/user/.local/bin/uv run seh sync >> /var/log/seh.log 2>&1

# Every 6 hours (~1,200 credits/month)
0 */6 * * * cd /path/to/seh && /home/user/.local/bin/uv run seh sync >> /var/log/seh.log 2>&1
```

Each incremental sync costs about 8-10 API credits, and the Free tier allows 2,000 per month.
Hourly or more frequent schedules exceed the budget; seh stops before it is exceeded and
resumes on the 1st (UTC).

## Architecture

```
src/seh/
├── cli.py                   # Click CLI with Rich output
├── config/
│   ├── settings.py          # Pydantic Settings from env vars
│   └── logging.py           # Structlog + email notifications
├── api/
│   ├── client.py            # Async httpx client for the API V2 endpoints
│   ├── auth.py              # OAuth token store and refresh (rotating tokens)
│   ├── oauth_login.py       # Interactive sign-in for `seh auth login`
│   └── rate_limiter.py      # Per-minute limit + monthly credit ledger
├── db/
│   ├── base.py              # SQLAlchemy DeclarativeBase
│   ├── engine.py            # Engine factory for SQLite/PG/MariaDB
│   ├── views.py             # Database view definitions
│   ├── models/              # ORM models (15 tables)
│   └── repositories/        # CRUD with upsert support
├── sync/
│   ├── orchestrator.py      # Coordinates sync across sites
│   ├── v2_fields.py         # V2 field and timestamp conversion helpers
│   └── strategies/          # Per-data-type sync logic
└── utils/
    ├── exceptions.py        # Custom exception hierarchy
    ├── filelock.py          # Cross-process file locks (tokens, credit ledger)
    └── retry.py             # Exponential backoff decorator
```

### Key Libraries

| Library | Purpose |
|---------|---------|
| httpx | Async HTTP client |
| SQLAlchemy 2.0 | ORM with modern typing |
| pydantic-settings | Configuration from environment |
| click | CLI framework |
| rich | Terminal tables and formatting |
| structlog | Structured JSON logging |
| openpyxl | Excel export (optional) |

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Run linter
uv run ruff check src

# Auto-fix linting issues
uv run ruff check src --fix

# Run type checker
uv run mypy src

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=src/seh

# Run tests for specific database backend
SEH_DATABASE_URL="postgresql+psycopg://user:pass@localhost/seh" uv run pytest -m postgresql
```

## Testing

The project includes 230+ unit and integration tests:

```bash
# Run all tests
uv run pytest

# Run with verbose output
uv run pytest -v

# Run specific test file
uv run pytest tests/test_database_backends.py

# Test with different Python versions
./scripts/test_python_versions.sh
```

## Troubleshooting

### Sign-in Issues

```
Not signed in (no token file at ...). Run 'seh auth login'.
Token refresh rejected by SolarEdge ... Run 'seh auth login' to sign in again.
```

Run `seh auth login`. A sign-in lapses if seh does not run for 30 days or after the
24-month grant. `seh auth status --refresh` checks the stored sign-in without using
API credits. If `SEH_API_KEY` is still set, seh reports that V1 keys no longer work.

### Credit Budget Used

```
RateLimitError: Monthly API credit budget used (2000/2000 for 2026-10) ...
```

The Free tier allows 2,000 requests per calendar month (UTC) with no overage. A daily
incremental sync uses about 10; a `--full` sync with the default 365-day energy lookback
about 30. `seh status --diagnostics` shows the month's usage.

### Database Connection Errors

For PostgreSQL, ensure `psycopg` is installed:
```bash
uv sync --extra postgresql
```

For MariaDB, ensure system libraries are installed:
```bash
# Debian/Ubuntu
sudo apt-get install libmariadb-dev

# Then install Python driver
uv sync --extra mariadb
```

### Known issues

For Mariadb this error is thrown when setting up the database:


```bash
❯ uv run seh init-db
Initializing database...
  Database: localhost:3306/solar
/home/jcz/seh/seh/.venv/lib/python3.12/site-packages/mariadb/connectionpool.py:30: SyntaxWarning: invalid escape sequence '\*'
  """
  Tables created
  Views created
```

This warning is coming from the mariadb connector library itself, not from your code. The database initialization
  actually completed successfully (you can see "Tables created" and "Views created" at the end). The warning is a known issue in the mariadb Python package where they have an unescaped \* in a docstring at line 30
  of connectionpool.py. This is a bug in the third-party library that should be \\* or use a raw string. You can verify the issue is with the library by checking their source:
  head -35 .venv/lib/python3.12/site-packages/mariadb/connectionpool.py

  The fix would need to come from the mariadb package maintainers.
  

## What's Not Yet Implemented

See [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) for the full roadmap. Key items remaining:

- [ ] Web scraping for additional data not in API
- [ ] Grafana/dashboard integration examples
- [ ] Alembic database migrations
- [ ] Docker support

### Recently Completed (v0.3.0)

- [x] SolarEdge Monitoring API V2 with OAuth sign-in (`seh auth`)
- [x] Monthly credit budget and per-minute rate limiting
- [x] Power details from meter telemetry; history backfill back to installation
- [x] 230+ unit and integration tests

### Completed in v0.2.0

- [x] Comprehensive unit tests (81+ tests)
- [x] Multi-database backend testing (SQLite, PostgreSQL, MariaDB)
- [x] Comprehensive CLI help text with examples
- [x] Email notifications (SMTP)
- [x] Excel export format (.xlsx)
- [x] SQL dump export
- [x] Multiple site filtering (--sites flag)
- [x] Full diagnostics (--diagnostics flag)
- [x] Configurable error handling
- [x] Power data granularity configuration

### Previously Completed (v0.1.0)

- [x] Database views for simplified querying (8 views)
- [x] Inverter telemetry data sync
- [x] Optimizer telemetry data sync (V1 only; not available in API V2)
- [x] Environmental benefits data
- [x] Alerts sync (with graceful handling for restricted API access)
- [x] Inventory sync
- [x] Data export functionality (CSV, JSON)

## Upgrading from v0.2 (API V1)

The full step-by-step guide, including headless servers, backfilling history, the credit budget,
and troubleshooting, is in **[docs/MIGRATING_TO_API_V2.md](docs/MIGRATING_TO_API_V2.md)**. Summary:

1. Create an app at [developer.solaredge.com](https://developer.solaredge.com/) (Free tier,
   Site Access, redirect URI `http://127.0.0.1:8765/callback`).
2. In `.env`, remove `SEH_API_KEY`, `SEH_API_DAILY_LIMIT`, and add `SEH_OAUTH_CLIENT_ID`,
   `SEH_OAUTH_CLIENT_SECRET`, `SEH_SITE_IDS`. Run `chmod 600 .env`.
3. Run `uv sync`, then `seh auth login`. On a server without a browser, first run
   `ssh -L 8765:127.0.0.1:8765 user@server` from your desktop and open the printed URL there.
4. Run `seh sync`. Existing tables are reused; no database migration is needed.

**Data differences in V2:**

| Table | Change |
|-------|--------|
| `seh_power_details` | Same columns and 15-minute resolution; built from meter telemetry (consumption = production + import - export) |
| `seh_inverter_telemetry` | 15-minute (was ~5-minute); no temperature, modes, DC voltage, power limit, or reactive power |
| `seh_optimizer_telemetry` | No V2 endpoint; not collected |
| `seh_environmental_benefits` | CO2 only; trees, light bulbs, SO2, NOx keep their last V1 values |
| `seh_inventory` | Now includes optimizers (`category = 'optimizers'`) |
| `seh_sites`, `seh_equipment` | V1-only fields (currency, primary module, DSP versions) keep their last V1 values |

## Changelog

### v0.3.0 (2026-10-13)
- Migrated to the SolarEdge Monitoring API V2 (V1 retired 2026-11-01)
- OAuth2 Site Access: `seh auth login|status|logout`, rotating refresh tokens stored with owner-only permissions
- Rate limiting by minute (10) and monthly credit budget (2,000) with a persistent ledger
- Power details derived from meter telemetry; power flow, energy, power, inventory (now with optimizers) on V2
- Incremental syncs resume from the newest stored reading, fixing partial last intervals left by V1
- Endpoints a plan does not include (HTTP 400/403/404) are recorded as skipped
- Removed `SEH_API_KEY` and `SEH_API_DAILY_LIMIT`
- Security: `seh export dump` no longer passes the database password on the command line (uses a temporary
  owner-only credentials file), never prints it in errors, and writes the dump file owner-only (0600)
- Added `seh api get` for raw API responses; removed the throwaway `scripts/probe_v2.py`
- Fixed: the global `-c/--config` option now loads the given `.env` file (it was silently ignored); `check-api --update-config` writes to that file

### v0.2.0 (2026-03-13)
- Added `seh_power_details` table: historical 15-minute power breakdown (production, consumption, self-consumption, feed-in, purchased) from the `powerDetails` API endpoint
- Added `PowerDetailsSyncStrategy` (12th sync strategy)
- Added `SEH_POWER_DETAILS_LOOKBACK_DAYS` setting (default 25; API enforces < 1 calendar month)
- Updated `seh_weekly_power_chart.py` to use `seh_power_details` as primary data source for accurate grid consumption display

### v0.1.x
- Initial release with 14 tables and 11 sync strategies
- Multi-database support (SQLite, PostgreSQL, MariaDB)
- Email notifications on sync failure

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run linting: `uv run ruff check src`
4. Run tests: `uv run pytest`
5. Submit a pull request

## Resources

- [SolarEdge API V2 Documentation](https://api-docs.solaredge.com/)
- [SolarEdge Developer Platform](https://developer.solaredge.com/)
- [SolarEdge Monitoring Portal](https://monitoring.solaredge.com/)

- 





