# SolarEdge Harvest (seh)

Download your data from SolarEdge monitoring servers and store it in a relational database.

## Features

- **Multi-database support**: SQLite (default), PostgreSQL, and MariaDB
- **Comprehensive data sync**: Sites, equipment, energy, power, batteries, meters, alerts, inventory, and inverter telemetry
- **Incremental sync**: Only fetches new data since last sync with configurable overlap buffer
- **Rate limiting**: Complies with SolarEdge API limits (3 concurrent requests, 300/day)
- **Retry with backoff**: Automatic retries with exponential backoff on transient failures
- **Data export**: Export to CSV or JSON with filtering options
- **Database views**: Pre-built views for common queries
- **Structured logging**: JSON logging with optional file rotation via structlog
- **CLI interface**: Rich terminal output with progress tables and status displays
- **Idempotent operations**: Upsert pattern ensures safe re-runs without duplicates

## Installation

```bash
# Install with uv (recommended)
uv sync

# For PostgreSQL support
uv sync --extra postgresql

# For MariaDB support (requires system libraries: libmariadb-dev)
uv sync --extra mariadb

# For all database drivers
uv sync --extra all-databases
```

### Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) package manager
- SolarEdge API key (from your monitoring portal)

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/johnzastrow/seh.git
cd seh
uv sync

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

| Variable | Description | Default |
|----------|-------------|---------|
| `SEH_API_KEY` | SolarEdge API key (**required**) | - |
| `SEH_API_BASE_URL` | API base URL | `https://monitoringapi.solaredge.com` |
| `SEH_API_TIMEOUT` | Request timeout in seconds | `10` |
| `SEH_API_MAX_CONCURRENT` | Max concurrent requests | `3` |
| `SEH_API_DAILY_LIMIT` | Max requests per day | `300` |
| `SEH_DATABASE_URL` | Database connection URL | `sqlite:///./seh.db` |
| `SEH_ENERGY_LOOKBACK_DAYS` | Days to look back for energy data on first sync | `365` |
| `SEH_POWER_LOOKBACK_DAYS` | Days to look back for power data on first sync | `7` |
| `SEH_SYNC_OVERLAP_MINUTES` | Overlap buffer for incremental syncs | `15` |
| `SEH_LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `SEH_LOG_FILE` | Log file path (logs to console if not set) | - |
| `SEH_LOG_MAX_BYTES` | Max log file size before rotation | `10485760` (10MB) |
| `SEH_LOG_BACKUP_COUNT` | Number of backup log files | `5` |

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

Create database tables. Safe to run multiple times.

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

# Sync specific site only
uv run seh sync --site 12345

# Full sync for specific site
uv run seh sync --full --site 12345
```

### `seh status`

Show sync status for all sites in the database.

```bash
uv run seh status
```

### `seh export`

Export data to CSV or JSON files.

```bash
# Export site information
uv run seh export sites
uv run seh export sites --format json -o sites.json

# Export energy readings
uv run seh export energy
uv run seh export energy --site 12345 --start 2024-01-01 --end 2024-12-31

# Export power readings
uv run seh export power --format json

# Export equipment list
uv run seh export equipment

# Export inverter telemetry
uv run seh export telemetry --site 12345 --serial ABC123

# Export inventory
uv run seh export inventory

# Export environmental benefits
uv run seh export environmental
```

**Export options:**
- `--format`, `-f`: Output format (`csv` or `json`, default: `csv`)
- `--output`, `-o`: Output file path (auto-generates if not specified)
- `--site`, `-s`: Filter by site ID
- `--start`, `--end`: Date range filtering (for time-series data)
- `--serial`: Filter by serial number (telemetry only)

### Global Options

```bash
# Use custom config file
uv run seh --config /path/to/.env sync

# Get help
uv run seh --help
uv run seh sync --help
```

## Data Model

### Database Tables

| Table | Description |
|-------|-------------|
| `sites` | Installation details (name, location, timezone, peak power, modules) |
| `equipment` | Inverters, optimizers, gateways with serial numbers and versions |
| `batteries` | Storage units with capacity, state of charge, and telemetry |
| `energy_readings` | Daily/monthly energy production in Wh |
| `power_readings` | 15-minute power measurements in W |
| `power_flows` | Current power flow snapshots (PV, grid, load, storage) |
| `meters` | Meter devices (production, consumption, etc.) |
| `meter_readings` | Meter time-series data with voltage, current, power factor |
| `alerts` | System alerts with severity, codes, and affected components |
| `environmental_benefits` | CO2/SO2/NOx savings, trees planted equivalent |
| `inventory` | Complete equipment inventory by category |
| `inverter_telemetry` | Detailed inverter data (voltage, current, temperature, mode) |
| `optimizer_telemetry` | Per-panel optimizer data (DC voltage, current, power, energy) |
| `sync_metadata` | Tracks last sync time per site and data type |

### Database Views

Pre-built views for common queries:

| View | Description |
|------|-------------|
| `v_site_summary` | Simplified site information |
| `v_daily_energy` | Daily energy with kWh conversion |
| `v_latest_power` | Most recent power reading per site |
| `v_power_flow_current` | Latest power flow snapshot per site |
| `v_sync_status` | Current sync status for all sites |
| `v_equipment_list` | Equipment with site names |
| `v_battery_status` | Current battery status |
| `v_energy_monthly` | Monthly energy totals |

See [docs/DATA_SCHEMA.md](docs/DATA_SCHEMA.md) for complete schema documentation.

### Sync Strategy

1. **First run** (`--full`): Fetches historical data
   - Energy: 365 days lookback
   - Power/Storage/Meters: 7 days lookback

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

# Run every 6 hours
0 */6 * * * cd /path/to/seh && uv run seh sync >> /var/log/seh.log 2>&1

# Run daily at 2 AM
0 2 * * * cd /path/to/seh && uv run seh sync >> /var/log/seh.log 2>&1
```

## Architecture

```
src/seh/
├── cli.py                   # Click CLI with Rich output
├── config/
│   ├── settings.py          # Pydantic Settings from env vars
│   └── logging.py           # Structlog configuration
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
- [ ] Unit and integration tests
- [ ] Grafana/dashboard integration examples

### Recently Completed

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
4. Submit a pull request

## Resources

- [SolarEdge Monitoring API Documentation](https://knowledge-center.solaredge.com/sites/kc/files/se_monitoring_api.pdf)
- [SolarEdge Monitoring Portal](https://monitoring.solaredge.com/)
