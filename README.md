# SolarEdge Harvest (seh)

Download your data from SolarEdge monitoring servers and store it in a relational database.

## Features

- **Multi-database support**: SQLite (default), PostgreSQL, and MariaDB
- **Comprehensive data sync**: Sites, equipment, energy, power, batteries, meters, alerts, inventory, and telemetry
- **Incremental sync**: Only fetches new data since last sync with configurable overlap buffer
- **Rate limiting**: Complies with SolarEdge API limits (3 concurrent requests, 300/day)
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
- SolarEdge API key (from your monitoring portal)
- Relational database (SQLite, PostgreSQL, or MariaDB)


## Installation and Quick Start


```bash
# 1. Clone and install
git clone https://github.com/johnzastrow/seh.git
cd seh

# Install with uv (recommended)
uv sync
# For PostgreSQL support
uv sync --extra postgresql

# For MariaDB support (requires system libraries: libmariadb-dev)
uv sync --extra mariadb

# For all database drivers
uv sync --extra all-databases

# For Excel export support
uv pip install openpyxl


# 2. Configure
cp .env.example .env
# Edit .env and add your SEH_API_KEY

# 3. Initialize database and verify API access
uv run seh init-db
uv run seh check-api

# 4. Run initial full sync
uv run seh sync --full

# 5. Check status
uv run seh status
```

## Configuration

Configuration is via environment variables or a `.env` file:

### Required Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `SEH_API_KEY` | SolarEdge API key (**required**) | - |

### API Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `SEH_API_BASE_URL` | API base URL | `https://monitoringapi.solaredge.com` |
| `SEH_API_TIMEOUT` | Request timeout in seconds | `10` |
| `SEH_API_MAX_CONCURRENT` | Max concurrent requests | `3` |
| `SEH_API_DAILY_LIMIT` | Max requests per day | `300` |

### Database Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `SEH_DATABASE_URL` | Database connection URL | `sqlite:///./seh.db` |

### Sync Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `SEH_SITE_IDS` | Comma-separated site IDs to sync (syncs all if not set) | - |
| `SEH_ENERGY_LOOKBACK_DAYS` | Days to look back for energy data on first sync | `365` |
| `SEH_POWER_LOOKBACK_DAYS` | Days to look back for power data on first sync | `7` |
| `SEH_SYNC_OVERLAP_MINUTES` | Overlap buffer for incremental syncs | `15` |
| `SEH_POWER_TIME_UNIT` | Power data granularity (QUARTER_OF_AN_HOUR, HOUR, DAY, WEEK, MONTH, YEAR) | `QUARTER_OF_AN_HOUR` |

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

### `seh check-api`

Verify API connectivity and list available sites.

```bash
uv run seh check-api
```

### `seh sync`

Synchronize data from SolarEdge to the database.

```bash
# Incremental sync (recommended for cron)
uv run seh sync

# Full sync (fetch all historical data)
uv run seh sync --full

# Sync specific sites only
uv run seh sync --sites 12345,67890

# Verbose output
uv run seh sync -v
```

### `seh status`

Show sync status for all sites in the database.

```bash
# Basic status
uv run seh status

# Full diagnostics (API health, DB status, rate limits)
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

All tables are prefixed with `seh_` to avoid naming conflicts:

| Table | Description |
|-------|-------------|
| `seh_sites` | Installation details (name, location, timezone, peak power, modules) |
| `seh_equipment` | Inverters, optimizers, gateways with serial numbers and versions |
| `seh_batteries` | Storage units with capacity, state of charge, and telemetry |
| `seh_energy_readings` | Daily/monthly energy production in Wh |
| `seh_power_readings` | 15-minute power measurements in W |
| `seh_power_flows` | Current power flow snapshots (PV, grid, load, storage) |
| `seh_meters` | Meter devices (production, consumption, etc.) |
| `seh_meter_readings` | Meter time-series data with voltage, current, power factor |
| `seh_alerts` | System alerts with severity, codes, and affected components |
| `seh_environmental_benefits` | CO2/SO2/NOx savings, trees planted equivalent |
| `seh_inventory` | Complete equipment inventory by category |
| `seh_inverter_telemetry` | Detailed inverter data (voltage, current, temperature, mode) |
| `seh_optimizer_telemetry` | Per-panel optimizer data (DC voltage, current, power, energy) |
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
   - Power/Storage/Meters: 7 days lookback (configurable)

2. **Subsequent runs**: Incremental sync
   - Starts from `last_data_timestamp - 15 minutes` (configurable overlap)
   - Uses upsert (ON CONFLICT DO UPDATE) for idempotent operations

3. **Data types synced** (in order):
   - Site details
   - Equipment list
   - Energy readings
   - Power readings + current power flow
   - Storage/battery data
   - Meter devices and readings
   - Environmental benefits
   - Alerts
   - Inventory
   - Inverter telemetry
   - Optimizer telemetry

## Scheduled Sync

Add to crontab for automatic updates:

```bash
# Edit crontab
crontab -e

# Run every hour
0 * * * * cd /path/to/seh && uv run seh sync >> /var/log/seh.log 2>&1

# Run every 6 hours
0 */6 * * * cd /path/to/seh && uv run seh sync >> /var/log/seh.log 2>&1

# Run every 15 minutes during daylight hours
*/15 6-20 * * * cd /path/to/seh && uv run seh sync
```

## Architecture

```
src/seh/
├── cli.py                   # Click CLI with Rich output
├── config/
│   ├── settings.py          # Pydantic Settings from env vars
│   └── logging.py           # Structlog + email notifications
├── api/
│   ├── client.py            # Async httpx client for all API endpoints
│   ├── rate_limiter.py      # Semaphore + daily quota tracking
│   └── models/responses.py  # Pydantic models for API responses
├── db/
│   ├── base.py              # SQLAlchemy DeclarativeBase
│   ├── engine.py            # Engine factory for SQLite/PG/MariaDB
│   ├── views.py             # Database view definitions
│   ├── models/              # ORM models (14 tables)
│   └── repositories/        # CRUD with upsert support
├── sync/
│   ├── orchestrator.py      # Coordinates sync across sites
│   └── strategies/          # Per-data-type sync logic
└── utils/
    ├── exceptions.py        # Custom exception hierarchy
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

The project includes 81+ unit and integration tests:

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

### API Key Issues

```
Configuration error: api_key - Field required
```

Ensure `SEH_API_KEY` is set in your `.env` file or environment.

### Rate Limit Exceeded

```
RateLimitError: Daily API limit (300) reached
```

Wait until the next day or reduce sync frequency. The rate limiter tracks requests over a rolling 24-hour window.

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

## What's Not Yet Implemented

See [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md) for the full roadmap. Key items remaining:

- [ ] Web scraping for additional data not in API
- [ ] Grafana/dashboard integration examples
- [ ] Alembic database migrations
- [ ] Docker support

### Recently Completed (v0.2.0)

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
- [x] Optimizer telemetry data sync
- [x] Environmental benefits data
- [x] Alerts sync (with graceful handling for restricted API access)
- [x] Inventory sync
- [x] Data export functionality (CSV, JSON)

## License

MIT

## Contributing

1. Fork the repository
2. Create a feature branch
3. Run linting: `uv run ruff check src`
4. Run tests: `uv run pytest`
5. Submit a pull request

## Resources

- [SolarEdge Monitoring API Documentation](https://knowledge-center.solaredge.com/sites/kc/files/se_monitoring_api.pdf)
- [SolarEdge Monitoring Portal](https://monitoring.solaredge.com/)
