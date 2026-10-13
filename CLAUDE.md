# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SolarEdge Harvest (seh) - A Python application to download data from SolarEdge solar monitoring servers and store it in a relational database. Supports SQLite (default), PostgreSQL, and MariaDB.

**Version:** 0.3.0 (SolarEdge Monitoring API V2)

## Commands

```bash
# Install dependencies
uv sync

# Run CLI
uv run seh --help
uv run seh --version
uv run seh init-db
uv run seh auth login|status|logout
uv run seh api get /sites/{site}/alerts -p alerts-in-page=100   # raw V2 JSON, 1 credit
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
│   ├── client.py            # SolarEdgeClient - async httpx, API V2 endpoints
│   ├── auth.py              # OAuth token store + refresh (rotating tokens)
│   ├── oauth_login.py       # Interactive sign-in (seh auth login)
│   ├── rate_limiter.py      # RateLimiter - per-minute + monthly credit ledger
├── db/
│   ├── base.py              # Base, TimestampMixin
│   ├── engine.py            # create_engine(), get_session(), create_tables()
│   ├── views.py             # Database view definitions (8 views)
│   ├── models/              # SQLAlchemy ORM models (15 tables)
│   │   ├── site.py          # Site with relationships
│   │   ├── equipment.py     # Equipment (inverters, etc.)
│   │   ├── battery.py       # Battery/storage units
│   │   ├── energy.py        # EnergyReading (daily Wh)
│   │   ├── power.py         # PowerReading, PowerFlow, PowerDetails
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
│       ├── power_details.py # PowerDetailsSyncStrategy
│       ├── storage.py       # StorageSyncStrategy
│       ├── meter.py         # MeterSyncStrategy
│       ├── alert.py         # AlertSyncStrategy
│       ├── environmental.py # EnvironmentalSyncStrategy
│       ├── inventory.py     # InventorySyncStrategy
│       ├── inverter_telemetry.py  # InverterTelemetrySyncStrategy
│       └── optimizer_telemetry.py # No-op: no optimizer data in API V2
│   (sync/v2_fields.py: V2 timestamp/field conversion helpers)
└── utils/
    ├── exceptions.py        # SEHError hierarchy (incl. AuthenticationError)
    ├── filelock.py          # Cross-process locks (token file, credit ledger)
    └── retry.py             # @retry_with_backoff decorator
```

### Data Flow

1. **CLI** (`cli.py`) parses commands and loads settings
2. **SolarEdgeClient** (`api/client.py`) makes async API V2 requests with an OAuth bearer token
   from **OAuthTokenManager** (`api/auth.py`), rate limiting, and window splitting
3. **SyncOrchestrator** (`sync/orchestrator.py`) coordinates sync across sites
4. **SyncStrategies** (`sync/strategies/`) handle per-data-type logic
5. **Repositories** (`db/repositories/`) perform upsert operations
6. **SyncMetadata** tracks last sync timestamps for incremental syncs
7. **EmailNotifier** (`config/logging.py`) sends notifications on completion

### Key Design Patterns

- **Strategy Pattern**: Each data type has its own sync strategy
- **Repository Pattern**: Database operations abstracted behind repositories
- **Upsert Pattern**: ON CONFLICT DO UPDATE for idempotent syncs
- **Rate Limiting**: Semaphore for concurrency, rolling 60 s limit (10/min), persistent monthly
  credit ledger (`~/.config/seh/usage.json`, 2000/month) shared across processes
- **OAuth tokens**: Rotating refresh tokens persisted atomically (0600) before use, under an
  asyncio lock and a cross-process file lock
- **V1 column preservation**: Strategies only upsert columns V2 provides; V1-only columns keep values
- **Timestamps**: Naive site-local (V2 offset dropped); request ranges are UTC instants aligned to
  interval starts
- **Retry with Backoff**: Exponential backoff (2^n seconds, max 60s)

### Database Schema

15 tables with proper relationships and indexes (all prefixed with `seh_`):

| Table | Key Columns | Unique Constraint |
|-------|-------------|-------------------|
| `seh_sites` | id (PK), name, timezone, peak_power | - |
| `seh_equipment` | id, site_id (FK), serial_number | serial_number |
| `seh_batteries` | id, site_id (FK), serial_number | serial_number |
| `seh_energy_readings` | id, site_id (FK), reading_date, time_unit | (site_id, reading_date, time_unit) |
| `seh_power_readings` | id, site_id (FK), timestamp | (site_id, timestamp) |
| `seh_power_flows` | id, site_id (FK), timestamp | (site_id, timestamp) |
| `seh_power_details` | id, site_id (FK), timestamp, production_w, consumption_w, self_consumption_w, feed_in_w, purchased_w | (site_id, timestamp) |
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

### API Endpoints Used (Monitoring API V2)

Base URL `https://monitoringapi.solaredge.com/v2`, OAuth2 bearer token. Time ranges are UTC
ISO-8601 instants; max window per request: QUARTER_HOUR 1 week, HOUR 24 h, DAY 1 month.

```python
GET /sites/{id}                      # Site details (sites list is Fleet-only: 403 for OAuth)
GET /sites/{id}/devices?types=...    # Inverters, meters, batteries, optimizers
GET /sites/{id}/energy               # Energy (Wh), resolution DAY
GET /sites/{id}/power                # Power (W), resolution QUARTER_HOUR
GET /sites/{id}/power-flow           # Current power flow snapshot (kW)
GET /sites/{id}/meters/telemetry     # Production/import/export -> seh_power_details, meters
GET /sites/{id}/inverters/telemetry  # Inverter power/voltage/current/frequency
GET /sites/{id}/storage/telemetry    # Battery telemetry
GET /sites/{id}/environmental-benefits
GET /sites/{id}/alerts
POST /oauth2/token, /oauth2/revoke-token   # OAuth (sign-in at connect.solaredge.com/authorize)
```

## Configuration

Environment variables (prefix `SEH_`):

```bash
# Required
SEH_OAUTH_CLIENT_ID=xxx
SEH_OAUTH_CLIENT_SECRET=xxx
SEH_SITE_IDS=123456  # required: V2 cannot list sites

# Sign-in state and API budget
SEH_TOKEN_FILE=~/.config/seh/tokens.json
SEH_USAGE_FILE=~/.config/seh/usage.json
SEH_API_MONTHLY_CREDITS=2000
SEH_API_PER_MINUTE_LIMIT=10

# Database
SEH_DATABASE_URL=sqlite:///./seh.db

# Data type filtering (skip unavailable endpoints)
SEH_SKIP_DATA_TYPES=meter,alert  # Comma-separated list of data types to skip
# Valid: site, equipment, energy, power, power_details, storage, meter, environmental, alert, inventory, inverter_telemetry, optimizer_telemetry

# Sync settings
SEH_ENERGY_LOOKBACK_DAYS=365
SEH_POWER_LOOKBACK_DAYS=7
SEH_POWER_DETAILS_LOOKBACK_DAYS=25
SEH_SYNC_OVERLAP_MINUTES=15
SEH_POWER_TIME_UNIT=QUARTER_HOUR

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
- [x] Async API V2 client with OAuth2 and rate limiting (10/min, 2000 credits/month)
- [x] All 15 database tables with ORM models
- [x] 8 database views for common queries
- [x] Repository pattern with upsert support (ON CONFLICT / ON DUPLICATE KEY)
- [x] Sync strategies for all data types (12 strategies)
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
- [x] SolarEdge API V2 with OAuth (`seh auth`), migration guide in docs/MIGRATING_TO_API_V2.md
- [x] 230+ unit and integration tests

## What's NOT Implemented (TODO)

- [ ] Web scraping for data not in API
- [ ] Alembic migrations
- [ ] Docker support
- [ ] Grafana dashboard examples

## Reference Resources

- [SolarEdge API V2 documentation](https://api-docs.solaredge.com/) and
  [developer platform](https://developer.solaredge.com/)
- docs/V2_MIGRATION_HANDOFF.md - verified V2 behaviour, limits, deployment state
- docs/MIGRATING_TO_API_V2.md - user upgrade guide
- [ha_int_solaredge](https://github.com/trooperthorn/ha_int_solaredge) - community V2 client (reference)
- V1-era references (historical): [V1 API PDF](https://knowledge-center.solaredge.com/sites/kc/files/se_monitoring_api.pdf),
  [solaredge-interface](https://github.com/ndejong/solaredge-interface)

## Code Style

- Python 3.11+ with type hints
- Ruff for linting (configured in pyproject.toml)
- SQLAlchemy 2.0 style (Mapped[], mapped_column())
- Async/await for API calls
- Pydantic v2 for data validation
