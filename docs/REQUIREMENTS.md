# Requirements & Implementation Status

## Overview

SolarEdge Harvest (seh) is a Python application to download data from the SolarEdge Monitoring API and store it in a relational database for analysis and reporting.

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
| Create database tables | Done | 9 tables implemented |
| Create database views | **Not Done** | Planned for future |
| Incremental updates | Done | Overlap buffer for reliability |

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

**9 Tables Implemented:**

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `sites` | Installation details | id, name, location, timezone, peak_power, modules |
| `equipment` | Inverters, optimizers, gateways | serial_number, type, firmware versions |
| `batteries` | Storage units | serial_number, capacity, state_of_charge |
| `energy_readings` | Daily/monthly production | site_id, date, time_unit (DAY/MONTH), wh |
| `power_readings` | 15-minute power data | site_id, timestamp, watts |
| `power_flows` | Current power flow snapshot | pv, grid, load, storage power |
| `meters` | Meter devices | site_id, name, type |
| `meter_readings` | Meter time-series | voltage, current, power, power_factor |
| `sync_metadata` | Sync tracking | site_id, data_type, last_sync, last_data |

**Features:**
- TimestampMixin for created_at/updated_at
- Foreign key relationships with cascade delete
- Unique constraints for upsert support
- Indexed columns for query performance

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

**Sync Behavior:**
- First run (`--full`): Fetches historical data based on lookback days
- Subsequent runs: Incremental from last sync minus overlap buffer (15 min default)
- Upsert pattern: ON CONFLICT DO UPDATE for idempotent operations
- Per-site tracking in `sync_metadata` table

#### 4. CLI (`src/seh/cli.py`)

| Command | Description |
|---------|-------------|
| `seh init-db` | Create database tables |
| `seh check-api` | Verify API key and list sites |
| `seh sync` | Incremental sync |
| `seh sync --full` | Full historical sync |
| `seh sync --site ID` | Sync specific site |
| `seh status` | Show sync status per site |

**Features:**
- Rich terminal output with tables
- Configuration via .env file or environment variables
- Graceful error handling with helpful messages

#### 5. Configuration (`src/seh/config/`)

All settings via environment variables with `SEH_` prefix:

```bash
# Required
SEH_API_KEY=your_api_key

# Database (default: SQLite)
SEH_DATABASE_URL=sqlite:///./seh.db

# Sync settings
SEH_ENERGY_LOOKBACK_DAYS=365
SEH_POWER_LOOKBACK_DAYS=7
SEH_SYNC_OVERLAP_MINUTES=15

# API settings
SEH_API_TIMEOUT=10
SEH_API_MAX_CONCURRENT=3
SEH_API_DAILY_LIMIT=300

# Logging
SEH_LOG_LEVEL=INFO
SEH_LOG_FILE=/path/to/seh.log
```

### What's NOT Implemented

#### High Priority

| Feature | Description | Effort |
|---------|-------------|--------|
| Database views | Simplified queries for common reports | Low |
| Unit tests | pytest tests for core logic | Medium |
| Integration tests | Tests with mocked API responses | Medium |
| Inverter telemetry | Per-inverter time-series data | Medium |

#### Medium Priority

| Feature | Description | Effort |
|---------|-------------|--------|
| Optimizer data | Panel-level optimizer metrics | Medium |
| Environmental benefits | CO2 savings, trees planted | Low |
| Alerts sync | System alerts and notifications | Low |
| Inventory data | Detailed component inventory | Low |
| Sensors data | Temperature, irradiance sensors | Low |
| Data export | CSV/JSON export commands | Medium |

#### Lower Priority

| Feature | Description | Effort |
|---------|-------------|--------|
| Web scraping | Data not available via API | High |
| Alembic migrations | Schema version management | Medium |
| Docker support | Containerized deployment | Low |
| Grafana dashboards | Example visualization configs | Medium |
| Multi-account support | Multiple API keys | Medium |

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
| `GET /equipment/{id}/{sn}/data` | No | - |
| `GET /equipment/{id}/{sn}/changeLog` | No | - |
| `GET /site/{id}/meters` | Yes | MeterSyncStrategy |
| `GET /site/{id}/envBenefits` | No | - |
| `GET /site/{id}/inventory` | No | - |
| `GET /site/{id}/alerts` | No | - |
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
# Crontab entry for every 6 hours
0 */6 * * * cd /path/to/seh && uv run seh sync >> /var/log/seh.log 2>&1
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
