# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SolarEdge Harvest (seh) - A Python application to download data from SolarEdge solar monitoring servers and store it in a relational database. Supports SQLite (default), PostgreSQL, and MariaDB.

## Commands

```bash
# Install dependencies
uv sync

# Run CLI
uv run seh --help
uv run seh init-db
uv run seh check-api
uv run seh sync [--full] [--site ID]
uv run seh status

# Run directly
uv run python main.py sync

# Development
uv sync --extra dev
uv run ruff check src
uv run ruff check src --fix
uv run mypy src
uv run pytest
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
│   └── logging.py           # Structlog configuration (JSON/console)
├── api/
│   ├── client.py            # SolarEdgeClient - async httpx with all endpoints
│   ├── rate_limiter.py      # RateLimiter - semaphore + daily quota
│   └── models/responses.py  # Pydantic models for API responses
├── db/
│   ├── base.py              # Base, TimestampMixin
│   ├── engine.py            # create_engine(), get_session(), create_tables()
│   ├── models/              # SQLAlchemy ORM models
│   │   ├── site.py          # Site with relationships
│   │   ├── equipment.py     # Equipment (inverters, etc.)
│   │   ├── battery.py       # Battery/storage units
│   │   ├── energy.py        # EnergyReading (daily Wh)
│   │   ├── power.py         # PowerReading, PowerFlow
│   │   ├── meter.py         # Meter, MeterReading
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
│       └── meter.py         # MeterSyncStrategy
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

### Key Design Patterns

- **Strategy Pattern**: Each data type has its own sync strategy
- **Repository Pattern**: Database operations abstracted behind repositories
- **Upsert Pattern**: ON CONFLICT DO UPDATE for idempotent syncs
- **Rate Limiting**: Semaphore for concurrency + rolling 24h quota tracking
- **Retry with Backoff**: Exponential backoff (2^n seconds, max 60s)

### Database Schema

9 tables with proper relationships and indexes:

| Table | Key Columns | Unique Constraint |
|-------|-------------|-------------------|
| `sites` | id (PK), name, timezone, peak_power | - |
| `equipment` | id, site_id (FK), serial_number | serial_number |
| `batteries` | id, site_id (FK), serial_number | serial_number |
| `energy_readings` | id, site_id (FK), reading_date, time_unit | (site_id, reading_date, time_unit) |
| `power_readings` | id, site_id (FK), timestamp | (site_id, timestamp) |
| `power_flows` | id, site_id (FK), timestamp | (site_id, timestamp) |
| `meters` | id, site_id (FK), name | (site_id, name) |
| `meter_readings` | id, meter_id (FK), timestamp | (meter_id, timestamp) |
| `sync_metadata` | id, site_id (FK), data_type | (site_id, data_type) |

### API Endpoints Used

```python
# Sites
GET /sites/list              # List all sites
GET /site/{id}/details       # Site details

# Equipment
GET /equipment/{id}/list     # List inverters/equipment
GET /equipment/{id}/{sn}/data  # Inverter telemetry (not yet implemented)

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
```

## Configuration

Environment variables (prefix `SEH_`):

```bash
SEH_API_KEY=xxx              # Required
SEH_DATABASE_URL=sqlite:///./seh.db
SEH_ENERGY_LOOKBACK_DAYS=365
SEH_POWER_LOOKBACK_DAYS=7
SEH_SYNC_OVERLAP_MINUTES=15
SEH_LOG_LEVEL=INFO
```

## What's Implemented

- [x] Multi-database support (SQLite, PostgreSQL, MariaDB)
- [x] Async API client with rate limiting (3 concurrent, 300/day)
- [x] All 9 database tables with ORM models
- [x] Repository pattern with upsert support
- [x] Sync strategies for all data types
- [x] Incremental sync with overlap buffer
- [x] CLI with init-db, check-api, sync, status commands
- [x] Structured logging with structlog
- [x] Retry with exponential backoff
- [x] Pydantic settings from environment

## What's NOT Implemented (TODO)

- [ ] Database views for simplified querying
- [ ] Inverter telemetry data sync (`/equipment/{id}/{sn}/data`)
- [ ] Optimizer-level data
- [ ] Environmental benefits data (`/site/{id}/envBenefits`)
- [ ] Alerts from API (`/site/{id}/alerts`)
- [ ] Inventory data (`/site/{id}/inventory`)
- [ ] Sensors data (`/site/{id}/sensors`)
- [ ] Web scraping for data not in API
- [ ] Unit tests
- [ ] Integration tests with mocked API
- [ ] Data export (CSV, JSON)
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
