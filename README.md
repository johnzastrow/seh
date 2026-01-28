# SolarEdge Harvest (seh)

Download your data from SolarEdge monitoring servers and store it in a relational database.

## Features

- **Multi-database support**: SQLite (default), PostgreSQL, and MariaDB
- **Incremental sync**: Only fetches new data since last sync with configurable overlap buffer
- **Rate limiting**: Complies with SolarEdge API limits (3 concurrent requests, 300/day)
- **Retry with backoff**: Automatic retries with exponential backoff on transient failures
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
| `sync_metadata` | Tracks last sync time per site and data type |

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
│   ├── models/              # ORM models (9 tables)
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

- [ ] Database views for simplified querying
- [ ] Inverter telemetry data sync
- [ ] Optimizer-level data sync
- [ ] Environmental benefits data
- [ ] Alerts and notifications from API
- [ ] Web scraping for additional data not in API
- [ ] Unit and integration tests
- [ ] Data export functionality (CSV, JSON)
- [ ] Grafana/dashboard integration examples

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
