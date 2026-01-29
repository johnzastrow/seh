# Requirements & Implementation Status

## Overview

SolarEdge Harvest (seh) is a Python application to download data from the SolarEdge Monitoring API and store it in a relational database for analysis and reporting.

**Current Version:** 0.2.0

## Original Requirements

Use Python to connect to the SolarEdge API and retrieve data and load it into a relational database. Support MariaDB, PostgreSQL, and SQLite databases to store all details about a SolarEdge installation provided by the API. The objective is to harvest as many details as possible about the installation.

### Core Requirements

| Requirement | Status | Notes |
|-------------|--------|-------|
| Connect to SolarEdge API | Done | Async httpx client |
| Store data in relational database | Done | SQLAlchemy 2.0 ORM |
| Support SQLite | Done | Default database |
| Support PostgreSQL | Done | Optional dependency |
| Support MariaDB | Done | Optional dependency (requires system libs) |
| Handle API rate limiting | Done | 3 concurrent, 300/day tracking |
| Implement retries | Done | Exponential backoff |
| Log errors and timestamps | Done | Structlog with JSON output |
| Run on scheduled basis (cron) | Done | CLI suitable for cron |
| Create database tables | Done | 14 tables implemented |
| Create database views | Done | 8 views implemented |
| Incremental updates | Done | Overlap buffer for reliability |
| Email notifications | Done | SMTP support |
| Unit tests | Done | 81+ tests |
| Data export | Done | CSV, JSON, Excel, SQL dump |

## Implementation Details

### What's Implemented

#### 1. API Client (`src/seh/api/`)

- **SolarEdgeClient**: Async HTTP client using httpx
  - All major API endpoints implemented
  - Automatic retry with exponential backoff
  - Request/response logging

- **RateLimiter**: Dual rate limiting
  - Semaphore for max 3 concurrent requests
  - Rolling 24-hour window for 300/day limit
  - Raises `RateLimitError` when limits exceeded

#### 2. Database Layer (`src/seh/db/`)

**14 Tables Implemented (all prefixed with `seh_`):**

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `seh_sites` | Installation details | id, name, location, timezone, peak_power, modules |
| `seh_equipment` | Inverters, optimizers, gateways | serial_number, type, firmware versions |
| `seh_batteries` | Storage units | serial_number, capacity, state_of_charge |
| `seh_energy_readings` | Daily/monthly production | site_id, date, time_unit (DAY/MONTH), wh |
| `seh_power_readings` | 15-minute power data | site_id, timestamp, watts |
| `seh_power_flows` | Current power flow snapshot | pv, grid, load, storage power |
| `seh_meters` | Meter devices | site_id, name, type |
| `seh_meter_readings` | Meter time-series | voltage, current, power, power_factor |
| `seh_alerts` | System alerts | alert_id, severity, alert_code |
| `seh_environmental_benefits` | Environmental impact | co2_saved, trees_planted |
| `seh_inventory` | Equipment inventory | category, serial_number |
| `seh_inverter_telemetry` | Inverter time-series | serial_number, voltage, current, temp |
| `seh_optimizer_telemetry` | Optimizer time-series | serial_number, dc_voltage, dc_power |
| `seh_sync_metadata` | Sync tracking | site_id, data_type, last_sync, last_data |

**8 Views Implemented (all prefixed with `v_seh_`):**

| View | Purpose |
|------|---------|
| `v_seh_site_summary` | Simplified site information |
| `v_seh_daily_energy` | Daily energy with kWh conversion |
| `v_seh_latest_power` | Most recent power per site |
| `v_seh_power_flow_current` | Current power flow per site |
| `v_seh_sync_status` | Sync status overview |
| `v_seh_equipment_list` | Equipment with site names |
| `v_seh_battery_status` | Battery status overview |
| `v_seh_energy_monthly` | Monthly energy aggregation |

**Features:**
- TimestampMixin for created_at/updated_at
- Foreign key relationships with cascade delete
- Unique constraints for upsert support
- Indexed columns for query performance
- Multi-database upsert (ON CONFLICT / ON DUPLICATE KEY)

#### 3. Sync Logic (`src/seh/sync/`)

**Strategy Pattern Implementation:**

| Strategy | Data Type | Lookback | API Endpoint |
|----------|-----------|----------|--------------|
| SiteSyncStrategy | Site details | N/A | `/site/{id}/details` |
| EquipmentSyncStrategy | Equipment list | N/A | `/equipment/{id}/list` |
| EnergySyncStrategy | Daily energy | 365 days | `/site/{id}/energy` |
| PowerSyncStrategy | Power readings | 7 days | `/site/{id}/power` |
| StorageSyncStrategy | Battery data | 7 days | `/site/{id}/storageData` |
| MeterSyncStrategy | Meter readings | 7 days | `/site/{id}/meters` |
| AlertSyncStrategy | System alerts | N/A | `/site/{id}/alerts` |
| EnvironmentalSyncStrategy | Env benefits | N/A | `/site/{id}/envBenefits` |
| InventorySyncStrategy | Inventory | N/A | `/site/{id}/inventory` |
| TelemetrySyncStrategy | Inverter/optimizer telemetry | 7 days | `/equipment/{id}/{sn}/data` |

**Sync Behavior:**
- First run (`--full`): Fetches historical data based on lookback days
- Subsequent runs: Incremental from last sync minus overlap buffer (15 min default)
- Upsert pattern: ON CONFLICT DO UPDATE for idempotent operations
- Per-site tracking in `seh_sync_metadata` table

#### 4. CLI (`src/seh/cli.py`)

| Command | Description |
|---------|-------------|
| `seh init-db` | Create database tables and views |
| `seh check-api` | Verify API key and list sites |
| `seh sync` | Incremental sync |
| `seh sync --full` | Full historical sync |
| `seh sync --sites ID1,ID2` | Sync specific sites |
| `seh status` | Show sync status per site |
| `seh status --diagnostics` | Full system diagnostics |
| `seh export <type>` | Export data (sites, energy, power, etc.) |
| `seh export dump` | SQL database dump |

**Features:**
- Rich terminal output with tables
- Comprehensive help text with examples
- Configuration via .env file or environment variables
- Graceful error handling with helpful messages
- Excel export support (requires openpyxl)
- SQL dump export (requires sqlite3/pg_dump/mysqldump)

#### 5. Configuration (`src/seh/config/`)

All settings via environment variables with `SEH_` prefix:

```bash
# Required
SEH_API_KEY=your_api_key

# Database (default: SQLite)
SEH_DATABASE_URL=sqlite:///./seh.db

# Site filtering
SEH_SITE_IDS=123456,789012  # Optional

# Sync settings
SEH_ENERGY_LOOKBACK_DAYS=365
SEH_POWER_LOOKBACK_DAYS=7
SEH_SYNC_OVERLAP_MINUTES=15
SEH_POWER_TIME_UNIT=QUARTER_OF_AN_HOUR

# Error handling
SEH_ERROR_HANDLING=lenient  # strict, lenient, skip
SEH_MAX_RETRIES=3
SEH_RETRY_DELAY=2.0

# API settings
SEH_API_TIMEOUT=10
SEH_API_MAX_CONCURRENT=3
SEH_API_DAILY_LIMIT=300

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

#### 6. Logging (`src/seh/config/logging.py`)

- **SyncStats**: Track per-operation statistics
- **SyncSummary**: Aggregate stats across all operations
- **EmailNotifier**: Send SMTP notifications on sync completion
- **OperationTimer**: Context manager for timing operations
- Structured JSON logging with structlog
- File rotation support

#### 7. Testing (`tests/`)

- 81+ unit and integration tests
- pytest with pytest-asyncio
- Database backend tests (SQLite, PostgreSQL, MariaDB)
- Unique constraint verification tests
- Multi-Python version testing (3.11, 3.12, 3.13)

### What's NOT Implemented

| Feature | Description | Effort |
|---------|-------------|--------|
| Web scraping | Data not available via API | High |
| Alembic migrations | Schema version management | Medium |
| Docker support | Containerized deployment | Low |
| Grafana dashboards | Example visualization configs | Medium |

### API Endpoints Coverage

| Endpoint | Implemented | Used In |
|----------|-------------|---------|
| `GET /sites/list` | Yes | SiteSyncStrategy |
| `GET /site/{id}/details` | Yes | SiteSyncStrategy |
| `GET /site/{id}/dataPeriod` | No | - |
| `GET /site/{id}/energy` | Yes | EnergySyncStrategy |
| `GET /site/{id}/energyDetails` | Partial | EnergySyncStrategy |
| `GET /site/{id}/timeFrameEnergy` | No | - |
| `GET /site/{id}/power` | Yes | PowerSyncStrategy |
| `GET /site/{id}/powerDetails` | Partial | PowerSyncStrategy |
| `GET /site/{id}/overview` | No | - |
| `GET /site/{id}/currentPowerFlow` | Yes | PowerSyncStrategy |
| `GET /site/{id}/storageData` | Yes | StorageSyncStrategy |
| `GET /equipment/{id}/list` | Yes | EquipmentSyncStrategy |
| `GET /equipment/{id}/{sn}/data` | Yes | TelemetrySyncStrategy |
| `GET /equipment/{id}/{sn}/changeLog` | No | - |
| `GET /site/{id}/meters` | Yes | MeterSyncStrategy |
| `GET /site/{id}/envBenefits` | Yes | EnvironmentalSyncStrategy |
| `GET /site/{id}/inventory` | Yes | InventorySyncStrategy |
| `GET /site/{id}/alerts` | Yes | AlertSyncStrategy |
| `GET /site/{id}/sensors` | No | - |

## Usage

### Quick Start

```bash
# Install
git clone https://github.com/johnzastrow/seh.git
cd seh
uv sync

# Configure
cp .env.example .env
# Edit .env with your API key

# Initialize and sync
uv run seh init-db
uv run seh check-api
uv run seh sync --full
```

### Scheduled Sync

```bash
# Crontab entry for every hour
0 * * * * cd /path/to/seh && uv run seh sync >> /var/log/seh.log 2>&1
```

## Reference Resources

### SolarEdge Documentation

- [Monitoring API Documentation (PDF)](https://knowledge-center.solaredge.com/sites/kc/files/se_monitoring_api.pdf)
- [SolarEdge Monitoring Portal](https://monitoring.solaredge.com/)

### Reference Implementations

- [solaredge-interface](https://github.com/ndejong/solaredge-interface) - Python CLI
- [solaredge-go](https://github.com/elliott-davis/solaredge-go) - Go implementation
- [solaredgeoptimizers](https://github.com/ProudElm/solaredgeoptimizers) - Optimizer data

## Technical Decisions

### Why These Libraries?

| Library | Why |
|---------|-----|
| httpx | Modern async HTTP client, better than aiohttp |
| SQLAlchemy 2.0 | Type-safe ORM, multi-database support |
| pydantic-settings | Type-safe configuration from environment |
| click | Simple, composable CLI framework |
| rich | Beautiful terminal output |
| structlog | Structured logging, JSON output for production |
| openpyxl | Excel export support |

### Why Upsert Pattern?

The upsert (INSERT ... ON CONFLICT DO UPDATE) pattern ensures:
- Idempotent operations (safe to re-run)
- No duplicate data if sync runs multiple times
- Atomic updates without delete-then-insert

### Why Overlap Buffer?

The 15-minute overlap buffer when resuming syncs ensures:
- No data gaps if a sync was interrupted
- Handles clock skew between systems
- Accounts for delayed data availability in the API
