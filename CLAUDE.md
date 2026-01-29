# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SolarEdge Harvest (seh) - A Python application to download data from SolarEdge solar monitoring servers and store it in a relational database. Supports SQLite (default), PostgreSQL, and MariaDB.

**Version:** 0.2.0

## Commands

```bash
# Install dependencies
uv sync

# Run CLI
uv run seh --help
uv run seh --version
uv run seh init-db
uv run seh check-api
uv run seh sync [--full] [--sites ID1,ID2]
uv run seh status [--diagnostics]
uv run seh export sites|energy|power|equipment|telemetry|inventory|environmental|dump

# Run directly
uv run python main.py sync

# Development
uv sync --extra dev
uv run ruff check src
uv run ruff check src --fix
uv run mypy src
uv run pytest
uv run pytest -v  # verbose
uv run pytest tests/test_database_backends.py  # specific file
```

## Architecture

### Project Structure

```
src/seh/
├── __init__.py              # Package version
├── __main__.py              # Entry point for python -m seh
├── cli.py                   # Click CLI with Rich terminal output
├── config/
│   ├── settings.py          # Pydantic Settings (env vars, .env file)
│   └── logging.py           # Structlog config + SyncStats + EmailNotifier
├── api/
│   ├── client.py            # SolarEdgeClient - async httpx with all endpoints
│   ├── rate_limiter.py      # RateLimiter - semaphore + daily quota
│   └── models/responses.py  # Pydantic models for API responses
├── db/
│   ├── base.py              # Base, TimestampMixin
│   ├── engine.py            # create_engine(), get_session(), create_tables()
│   ├── views.py             # Database view definitions (8 views)
│   ├── models/              # SQLAlchemy ORM models (14 tables)
│   │   ├── site.py          # Site with relationships
│   │   ├── equipment.py     # Equipment (inverters, etc.)
│   │   ├── battery.py       # Battery/storage units
│   │   ├── energy.py        # EnergyReading (daily Wh)
│   │   ├── power.py         # PowerReading, PowerFlow
│   │   ├── meter.py         # Meter, MeterReading
│   │   ├── alert.py         # Alert notifications
│   │   ├── environmental.py # EnvironmentalBenefits
│   │   ├── inventory.py     # InventoryItem
│   │   ├── inverter_telemetry.py  # InverterTelemetry
│   │   ├── optimizer_telemetry.py # OptimizerTelemetry
│   │   └── sync_metadata.py # SyncMetadata (tracking)
│   └── repositories/        # CRUD operations with upsert
│       ├── base.py          # BaseRepository[T] generic
│       └── *.py             # Per-model repositories
├── sync/
│   ├── orchestrator.py      # SyncOrchestrator - coordinates all syncs
│   └── strategies/          # Per-data-type sync logic
│       ├── base.py          # BaseSyncStrategy ABC
│       ├── site.py          # SiteSyncStrategy
│       ├── equipment.py     # EquipmentSyncStrategy
│       ├── energy.py        # EnergySyncStrategy
│       ├── power.py         # PowerSyncStrategy
│       ├── storage.py       # StorageSyncStrategy
│       ├── meter.py         # MeterSyncStrategy
│       ├── alert.py         # AlertSyncStrategy
│       ├── environmental.py # EnvironmentalSyncStrategy
│       ├── inventory.py     # InventorySyncStrategy
│       └── telemetry.py     # TelemetrySyncStrategy
└── utils/
    ├── exceptions.py        # SEHError hierarchy
    └── retry.py             # @retry_with_backoff decorator
```

### Data Flow

1. **CLI** (`cli.py`) parses commands and loads settings
2. **SolarEdgeClient** (`api/client.py`) makes async API requests with rate limiting
3. **SyncOrchestrator** (`sync/orchestrator.py`) coordinates sync across sites
4. **SyncStrategies** (`sync/strategies/`) handle per-data-type logic
5. **Repositories** (`db/repositories/`) perform upsert operations
6. **SyncMetadata** tracks last sync timestamps for incremental syncs
7. **EmailNotifier** (`config/logging.py`) sends notifications on completion

### Key Design Patterns

- **Strategy Pattern**: Each data type has its own sync strategy
- **Repository Pattern**: Database operations abstracted behind repositories
- **Upsert Pattern**: ON CONFLICT DO UPDATE for idempotent syncs
- **Rate Limiting**: Semaphore for concurrency + rolling 24h quota tracking
- **Retry with Backoff**: Exponential backoff (2^n seconds, max 60s)

### Database Schema

14 tables with proper relationships and indexes (all prefixed with `seh_`):

| Table | Key Columns | Unique Constraint |
|-------|-------------|-------------------|
| `seh_sites` | id (PK), name, timezone, peak_power | - |
| `seh_equipment` | id, site_id (FK), serial_number | serial_number |
| `seh_batteries` | id, site_id (FK), serial_number | serial_number |
| `seh_energy_readings` | id, site_id (FK), reading_date, time_unit | (site_id, reading_date, time_unit) |
| `seh_power_readings` | id, site_id (FK), timestamp | (site_id, timestamp) |
| `seh_power_flows` | id, site_id (FK), timestamp | (site_id, timestamp) |
| `seh_meters` | id, site_id (FK), name | (site_id, name) |
| `seh_meter_readings` | id, meter_id (FK), timestamp | (meter_id, timestamp) |
| `seh_alerts` | id, site_id (FK), alert_id | (site_id, alert_id) |
| `seh_environmental_benefits` | id, site_id (FK) | (site_id) |
| `seh_inventory` | id, site_id (FK), name, serial_number | (site_id, name, serial_number) |
| `seh_inverter_telemetry` | id, site_id (FK), serial_number, timestamp | (site_id, serial_number, timestamp) |
| `seh_optimizer_telemetry` | id, site_id (FK), serial_number, timestamp | (site_id, serial_number, timestamp) |
| `seh_sync_metadata` | id, site_id (FK), data_type | (site_id, data_type) |

8 database views (all prefixed with `v_seh_`):
- `v_seh_site_summary`, `v_seh_daily_energy`, `v_seh_latest_power`
- `v_seh_power_flow_current`, `v_seh_sync_status`, `v_seh_equipment_list`
- `v_seh_battery_status`, `v_seh_energy_monthly`

### API Endpoints Used

```python
# Sites
GET /sites/list              # List all sites
GET /site/{id}/details       # Site details

# Equipment
GET /equipment/{id}/list     # List inverters/equipment
GET /equipment/{id}/{sn}/data  # Inverter telemetry

# Energy
GET /site/{id}/energy        # Energy production (Wh)
GET /site/{id}/energyDetails # Detailed energy breakdown

# Power
GET /site/{id}/power         # Power production (W)
GET /site/{id}/powerDetails  # Detailed power breakdown
GET /site/{id}/currentPowerFlow  # Current power flow snapshot

# Storage
GET /site/{id}/storageData   # Battery data and telemetry

# Meters
GET /site/{id}/meters        # Meter list and readings

# Additional
GET /site/{id}/envBenefits   # Environmental benefits
GET /site/{id}/alerts        # System alerts
GET /site/{id}/inventory     # Equipment inventory
```

## Configuration

Environment variables (prefix `SEH_`):

```bash
# Required
SEH_API_KEY=xxx

# Database
SEH_DATABASE_URL=sqlite:///./seh.db

# Site filtering
SEH_SITE_IDS=123456,789012  # Optional, syncs all if not set

# Data type filtering (skip unavailable endpoints)
SEH_SKIP_DATA_TYPES=meter,alert  # Comma-separated list of data types to skip
# Valid: site, equipment, energy, power, storage, meter, environmental, alert, inventory, inverter_telemetry, optimizer_telemetry

# Sync settings
SEH_ENERGY_LOOKBACK_DAYS=365
SEH_POWER_LOOKBACK_DAYS=7
SEH_SYNC_OVERLAP_MINUTES=15
SEH_POWER_TIME_UNIT=QUARTER_OF_AN_HOUR

# Error handling
SEH_ERROR_HANDLING=lenient  # strict, lenient, skip
SEH_MAX_RETRIES=3
SEH_RETRY_DELAY=2.0

# Logging
SEH_LOG_LEVEL=INFO
SEH_LOG_FILE=/path/to/seh.log

# Email notifications
SEH_SMTP_ENABLED=false
SEH_SMTP_HOST=smtp.gmail.com
SEH_SMTP_PORT=587
SEH_SMTP_USERNAME=user
SEH_SMTP_PASSWORD=pass
SEH_SMTP_FROM_EMAIL=alerts@example.com
SEH_SMTP_TO_EMAILS=admin@example.com
SEH_NOTIFY_ON_ERROR=true
SEH_NOTIFY_ON_SUCCESS=false
```

## What's Implemented

- [x] Multi-database support (SQLite, PostgreSQL, MariaDB)
- [x] Async API client with rate limiting (3 concurrent, 300/day)
- [x] All 14 database tables with ORM models
- [x] 8 database views for common queries
- [x] Repository pattern with upsert support (ON CONFLICT / ON DUPLICATE KEY)
- [x] Sync strategies for all data types (11 strategies)
- [x] Incremental sync with overlap buffer
- [x] CLI with init-db, check-api, sync, status, export commands
- [x] Comprehensive CLI help text with examples
- [x] Structured logging with structlog
- [x] Email notifications (SMTP)
- [x] Retry with exponential backoff
- [x] Pydantic settings from environment
- [x] Data export (CSV, JSON, Excel, SQL dump)
- [x] Site filtering (--sites flag)
- [x] Diagnostics (--diagnostics flag)
- [x] Configurable error handling
- [x] 81+ unit and integration tests

## What's NOT Implemented (TODO)

- [ ] Web scraping for data not in API
- [ ] Alembic migrations
- [ ] Docker support
- [ ] Grafana dashboard examples

## Reference Resources

- [SolarEdge Monitoring API Documentation](https://knowledge-center.solaredge.com/sites/kc/files/se_monitoring_api.pdf)
- [solaredge-interface](https://github.com/ndejong/solaredge-interface) - Python reference
- [solaredge-go](https://github.com/elliott-davis/solaredge-go) - Go reference
- [solaredgeoptimizers](https://github.com/ProudElm/solaredgeoptimizers) - Optimizer data

## Code Style

- Python 3.11+ with type hints
- Ruff for linting (configured in pyproject.toml)
- SQLAlchemy 2.0 style (Mapped[], mapped_column())
- Async/await for API calls
- Pydantic v2 for data validation
