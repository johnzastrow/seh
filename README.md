# SolarEdge Harvest (seh)

Download your data from SolarEdge monitoring servers and store it in a relational database.

## Features

- Supports **SQLite**, **PostgreSQL**, and **MariaDB** databases
- Incremental sync with overlap buffer for reliable data capture
- Rate limiting to comply with SolarEdge API limits (3 concurrent, 300/day)
- Structured logging with file rotation
- CLI with commands for sync, status, and API verification

## Installation

```bash
# Install with uv (recommended)
uv sync

# For PostgreSQL support
uv sync --extra postgresql

# For MariaDB support (requires system libraries)
uv sync --extra mariadb
```

## Configuration

Copy the example environment file and add your SolarEdge API key:

```bash
cp .env.example .env
# Edit .env with your API key
```

Configuration options:

| Variable | Description | Default |
|----------|-------------|---------|
| `SEH_API_KEY` | SolarEdge API key (required) | - |
| `SEH_DATABASE_URL` | Database connection URL | `sqlite:///./seh.db` |
| `SEH_ENERGY_LOOKBACK_DAYS` | Days to look back for energy data | `365` |
| `SEH_POWER_LOOKBACK_DAYS` | Days to look back for power data | `7` |
| `SEH_SYNC_OVERLAP_MINUTES` | Overlap buffer for incremental syncs | `15` |
| `SEH_LOG_LEVEL` | Logging level | `INFO` |

Database URL formats:
- SQLite: `sqlite:///./seh.db`
- PostgreSQL: `postgresql+psycopg://user:password@localhost:5432/seh`
- MariaDB: `mariadb+mariadbconnector://user:password@localhost:3306/seh`

## Usage

```bash
# Initialize the database schema
uv run seh init-db

# Check API connectivity and list sites
uv run seh check-api

# Run incremental sync (for cron jobs)
uv run seh sync

# Run full sync (fetch all historical data)
uv run seh sync --full

# Sync specific site only
uv run seh sync --site 12345

# Show sync status
uv run seh status
```

Or run directly with Python:

```bash
uv run python main.py sync
```

## Data Synced

| Data Type | Description |
|-----------|-------------|
| Sites | Installation details (location, peak power, timezone) |
| Equipment | Inverters, optimizers, gateways |
| Energy | Daily energy production (Wh) |
| Power | 15-minute power readings (W) |
| Power Flow | Current PV, grid, load, storage power |
| Storage | Battery state and telemetry |
| Meters | Meter devices and readings |

## Scheduled Sync

Add to crontab for automatic daily sync:

```bash
# Run every 6 hours
0 */6 * * * cd /path/to/seh && uv run seh sync >> /var/log/seh.log 2>&1
```

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Run linter
uv run ruff check src

# Run type checker
uv run mypy src

# Run tests
uv run pytest
```

## License

MIT
