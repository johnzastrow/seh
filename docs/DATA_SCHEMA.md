# Data Schema Reference

This document describes all data structures in the SolarEdge Harvest (seh) database.

**Note:** All tables are prefixed with `seh_` and all views are prefixed with `v_seh_` to avoid naming conflicts.

## Entity Relationship Diagram

```
                                    +------------------+
                                    |    seh_sites     |
                                    +------------------+
                                    | id (PK)          |
                                    | name             |
                                    | status           |
                                    | peak_power       |
                                    | timezone         |
                                    | ...              |
                                    +--------+---------+
                                             |
          +----------------------------------+----------------------------------+
          |              |           |           |           |                  |
          v              v           v           v           v                  v
+------------------+ +------------------+ +------------------+ +------------------+
|  seh_equipment   | |  seh_batteries   | |seh_energy_readings| |seh_power_readings|
+------------------+ +------------------+ +------------------+ +------------------+
| id (PK)          | | id (PK)          | | id (PK)          | | id (PK)          |
| site_id (FK)     | | site_id (FK)     | | site_id (FK)     | | site_id (FK)     |
| serial_number    | | serial_number    | | reading_date     | | timestamp        |
| equipment_type   | | capacity         | | energy_wh        | | power_watts      |
| ...              | | ...              | | ...              | | ...              |
+------------------+ +------------------+ +------------------+ +------------------+

          +----------------------------------+----------------------------------+
          |              |           |           |           |                  |
          v              v           v           v           v                  v
+------------------+ +------------------+ +------------------+ +------------------+
| seh_power_flows  | |   seh_meters     | |   seh_alerts     | |  seh_inventory   |
+------------------+ +------------------+ +------------------+ +------------------+
| id (PK)          | | id (PK)          | | id (PK)          | | id (PK)          |
| site_id (FK)     | | site_id (FK)     | | site_id (FK)     | | site_id (FK)     |
| timestamp        | | name             | | alert_id         | | name             |
| pv_power         | | meter_type       | | severity         | | category         |
| grid_power       | | ...              | | ...              | | ...              |
| ...              | +--------+---------+ +------------------+ +------------------+
+------------------+          |
                              v
          +------------------+------------------+------------------+
          |                                     |                  |
          v                                     v                  v
+------------------+                 +------------------+ +------------------+
|seh_meter_readings|                 |seh_environmental_| |seh_inverter_     |
+------------------+                 |    benefits      | |   telemetry      |
| id (PK)          |                 +------------------+ +------------------+
| meter_id (FK)    |                 | id (PK)          | | id (PK)          |
| timestamp        |                 | site_id (FK)     | | site_id (FK)     |
| power            |                 | co2_saved        | | serial_number    |
| energy_lifetime  |                 | trees_planted    | | timestamp        |
| ...              |                 | ...              | | ac_voltage       |
+------------------+                 +------------------+ | ...              |
                                                         +------------------+
                              +------------------+
                              |seh_sync_metadata |
                              +------------------+
                              | id (PK)          |
                              | site_id (FK)     |
                              | data_type        |
                              | last_sync_time   |
                              | ...              |
                              +------------------+
```

---

## Tables

### seh_sites

The central entity representing a SolarEdge installation site.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | No | Primary key (SolarEdge site ID) |
| `name` | VARCHAR(255) | No | Site name |
| `account_id` | INTEGER | Yes | SolarEdge account ID |
| `status` | VARCHAR(50) | Yes | Site status (Active, Pending, etc.) |
| `peak_power` | FLOAT | Yes | Installed peak power in kWp |
| `last_update_time` | DATETIME | Yes | Last data update from SolarEdge |
| `installation_date` | DATETIME | Yes | System installation date |
| `currency` | VARCHAR(10) | Yes | Currency code |
| `notes` | TEXT | Yes | Site notes |
| `site_type` | VARCHAR(50) | Yes | Type of installation |
| `country` | VARCHAR(100) | Yes | Country |
| `state` | VARCHAR(100) | Yes | State/Province |
| `city` | VARCHAR(100) | Yes | City |
| `address` | VARCHAR(255) | Yes | Street address |
| `address2` | VARCHAR(255) | Yes | Additional address line |
| `zip_code` | VARCHAR(20) | Yes | Postal/ZIP code |
| `timezone` | VARCHAR(50) | Yes | Site timezone (e.g., "America/Denver") |
| `primary_module_manufacturer` | VARCHAR(100) | Yes | Solar panel manufacturer |
| `primary_module_model` | VARCHAR(100) | Yes | Solar panel model |
| `primary_module_power` | FLOAT | Yes | Module power rating in Watts |
| `is_public` | BOOLEAN | Yes | Whether site is publicly visible |
| `public_name` | VARCHAR(255) | Yes | Public display name |
| `created_at` | DATETIME | No | Record creation timestamp |
| `updated_at` | DATETIME | No | Record update timestamp |

**Unique Constraints:** Primary key on `id`

---

### seh_equipment

Equipment associated with a site (inverters, optimizers, gateways).

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | No | Primary key (auto-increment) |
| `site_id` | INTEGER | No | Foreign key to seh_sites.id |
| `serial_number` | VARCHAR(100) | No | Equipment serial number (unique) |
| `name` | VARCHAR(255) | Yes | Equipment name/label |
| `manufacturer` | VARCHAR(100) | Yes | Equipment manufacturer |
| `model` | VARCHAR(100) | Yes | Equipment model |
| `equipment_type` | VARCHAR(50) | Yes | Type: Inverter, Optimizer, Gateway |
| `communication_method` | VARCHAR(50) | Yes | RS485, Ethernet, etc. |
| `cpu_version` | VARCHAR(50) | Yes | CPU firmware version |
| `connected_optimizers` | INTEGER | Yes | Number of connected optimizers |
| `dsp1_version` | VARCHAR(50) | Yes | DSP1 firmware version (inverters) |
| `dsp2_version` | VARCHAR(50) | Yes | DSP2 firmware version (inverters) |
| `inverter_serial` | VARCHAR(100) | Yes | Parent inverter (for optimizers) |
| `panel_manufacturer` | VARCHAR(100) | Yes | Panel manufacturer (for optimizers) |
| `panel_model` | VARCHAR(100) | Yes | Panel model (for optimizers) |
| `last_report_date` | DATETIME | Yes | Last telemetry report time |
| `created_at` | DATETIME | No | Record creation timestamp |
| `updated_at` | DATETIME | No | Record update timestamp |

**Unique Constraints:** `serial_number`
**Indexes:** `site_id`

---

### seh_batteries

Battery storage units associated with a site.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | No | Primary key (auto-increment) |
| `site_id` | INTEGER | No | Foreign key to seh_sites.id |
| `serial_number` | VARCHAR(100) | No | Battery serial number (unique) |
| `name` | VARCHAR(255) | Yes | Battery name/label |
| `manufacturer` | VARCHAR(100) | Yes | Battery manufacturer |
| `model` | VARCHAR(100) | Yes | Battery model |
| `firmware_version` | VARCHAR(50) | Yes | Firmware version |
| `capacity` | FLOAT | Yes | Current usable capacity in Wh |
| `nameplate_capacity` | FLOAT | Yes | Original rated capacity in Wh |
| `connected_inverter_sn` | VARCHAR(100) | Yes | Connected inverter serial |
| `last_state_of_charge` | FLOAT | Yes | Last SOC percentage (0-100) |
| `last_power` | FLOAT | Yes | Last power reading in Watts |
| `last_status` | VARCHAR(50) | Yes | Last status (Charging, Discharging, Idle) |
| `last_telemetry_time` | DATETIME | Yes | Timestamp of last telemetry |
| `lifetime_energy_charged` | FLOAT | Yes | Total energy charged in Wh |
| `lifetime_energy_discharged` | FLOAT | Yes | Total energy discharged in Wh |
| `created_at` | DATETIME | No | Record creation timestamp |
| `updated_at` | DATETIME | No | Record update timestamp |

**Unique Constraints:** `serial_number`
**Indexes:** `site_id`

---

### seh_energy_readings

Daily or monthly energy production readings.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | No | Primary key (auto-increment) |
| `site_id` | INTEGER | No | Foreign key to seh_sites.id |
| `reading_date` | DATE | No | Date of the reading |
| `time_unit` | VARCHAR(20) | No | Time unit: DAY, MONTH, YEAR |
| `energy_wh` | FLOAT | Yes | Energy produced in Watt-hours |
| `created_at` | DATETIME | No | Record creation timestamp |
| `updated_at` | DATETIME | No | Record update timestamp |

**Unique Constraints:** `(site_id, reading_date, time_unit)`
**Indexes:** `site_id`, `reading_date`

---

### seh_power_readings

Instantaneous power readings (typically 15-minute intervals).

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | No | Primary key (auto-increment) |
| `site_id` | INTEGER | No | Foreign key to seh_sites.id |
| `timestamp` | DATETIME | No | Reading timestamp |
| `power_watts` | FLOAT | Yes | Power in Watts |
| `created_at` | DATETIME | No | Record creation timestamp |
| `updated_at` | DATETIME | No | Record update timestamp |

**Unique Constraints:** `(site_id, timestamp)`
**Indexes:** `site_id`, `timestamp`

---

### seh_power_flows

Power flow snapshots showing energy distribution between PV, grid, load, and storage.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | No | Primary key (auto-increment) |
| `site_id` | INTEGER | No | Foreign key to seh_sites.id |
| `timestamp` | DATETIME | No | Reading timestamp |
| `unit` | VARCHAR(20) | Yes | Power unit (kW, W) |
| `grid_status` | VARCHAR(20) | Yes | Grid connection status |
| `grid_power` | FLOAT | Yes | Grid power (positive=export, negative=import) |
| `pv_status` | VARCHAR(20) | Yes | PV production status |
| `pv_power` | FLOAT | Yes | PV production power |
| `load_status` | VARCHAR(20) | Yes | Load consumption status |
| `load_power` | FLOAT | Yes | Load consumption power |
| `storage_status` | VARCHAR(20) | Yes | Storage status |
| `storage_power` | FLOAT | Yes | Storage power (positive=charging) |
| `storage_charge_level` | FLOAT | Yes | Battery charge level percentage |
| `storage_critical` | BOOLEAN | Yes | Battery in critical state |
| `created_at` | DATETIME | No | Record creation timestamp |
| `updated_at` | DATETIME | No | Record update timestamp |

**Unique Constraints:** `(site_id, timestamp)`
**Indexes:** `site_id`, `timestamp`

---

### seh_meters

Meter devices associated with a site.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | No | Primary key (auto-increment) |
| `site_id` | INTEGER | No | Foreign key to seh_sites.id |
| `name` | VARCHAR(100) | No | Meter name/label |
| `manufacturer` | VARCHAR(100) | Yes | Meter manufacturer |
| `model` | VARCHAR(100) | Yes | Meter model |
| `meter_type` | VARCHAR(50) | Yes | Type: Production, Consumption, Feed-in |
| `serial_number` | VARCHAR(100) | Yes | Meter serial number |
| `connection_type` | VARCHAR(50) | Yes | Connection type |
| `form` | VARCHAR(50) | Yes | Meter form factor |
| `created_at` | DATETIME | No | Record creation timestamp |
| `updated_at` | DATETIME | No | Record update timestamp |

**Unique Constraints:** `(site_id, name)`
**Indexes:** `site_id`

---

### seh_meter_readings

Time-series readings from meters.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | No | Primary key (auto-increment) |
| `meter_id` | INTEGER | No | Foreign key to seh_meters.id |
| `timestamp` | DATETIME | No | Reading timestamp |
| `power` | FLOAT | Yes | Power in Watts |
| `energy_lifetime` | FLOAT | Yes | Lifetime energy in Wh |
| `voltage_l1` | FLOAT | Yes | Phase 1 voltage |
| `voltage_l2` | FLOAT | Yes | Phase 2 voltage |
| `voltage_l3` | FLOAT | Yes | Phase 3 voltage |
| `current_l1` | FLOAT | Yes | Phase 1 current in Amps |
| `current_l2` | FLOAT | Yes | Phase 2 current in Amps |
| `current_l3` | FLOAT | Yes | Phase 3 current in Amps |
| `power_factor` | FLOAT | Yes | Overall power factor |
| `power_factor_l1` | FLOAT | Yes | Phase 1 power factor |
| `power_factor_l2` | FLOAT | Yes | Phase 2 power factor |
| `power_factor_l3` | FLOAT | Yes | Phase 3 power factor |
| `created_at` | DATETIME | No | Record creation timestamp |
| `updated_at` | DATETIME | No | Record update timestamp |

**Unique Constraints:** `(meter_id, timestamp)`
**Indexes:** `meter_id`, `timestamp`

---

### seh_alerts

System alerts and notifications for a site.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | No | Primary key (auto-increment) |
| `site_id` | INTEGER | No | Foreign key to seh_sites.id |
| `alert_id` | INTEGER | No | SolarEdge alert ID |
| `severity` | VARCHAR(20) | Yes | Severity: HIGH, MEDIUM, LOW |
| `alert_type` | VARCHAR(100) | Yes | Alert type classification |
| `alert_code` | INTEGER | Yes | Numeric alert code |
| `name` | VARCHAR(255) | Yes | Alert name |
| `description` | TEXT | Yes | Alert description |
| `serial_number` | VARCHAR(100) | Yes | Affected component serial |
| `alert_timestamp` | DATETIME | Yes | When alert was raised |
| `created_at` | DATETIME | No | Record creation timestamp |
| `updated_at` | DATETIME | No | Record update timestamp |

**Unique Constraints:** `(site_id, alert_id)`
**Indexes:** `site_id`

---

### seh_environmental_benefits

Environmental impact calculations for a site.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | No | Primary key (auto-increment) |
| `site_id` | INTEGER | No | Foreign key to seh_sites.id |
| `co2_saved` | FLOAT | Yes | CO2 emissions avoided |
| `so2_saved` | FLOAT | Yes | SO2 emissions avoided |
| `nox_saved` | FLOAT | Yes | NOx emissions avoided |
| `co2_units` | VARCHAR(20) | Yes | Unit for emissions (KG, LB) |
| `trees_planted` | FLOAT | Yes | Equivalent trees planted |
| `light_bulbs` | FLOAT | Yes | Equivalent light bulb hours |
| `benefits_timestamp` | DATETIME | Yes | When benefits were calculated |
| `created_at` | DATETIME | No | Record creation timestamp |
| `updated_at` | DATETIME | No | Record update timestamp |

**Unique Constraints:** `(site_id)`
**Indexes:** `site_id`

---

### seh_inventory

Complete inventory of equipment at a site.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | No | Primary key (auto-increment) |
| `site_id` | INTEGER | No | Foreign key to seh_sites.id |
| `name` | VARCHAR(255) | No | Item name |
| `manufacturer` | VARCHAR(100) | Yes | Manufacturer |
| `model` | VARCHAR(100) | Yes | Model |
| `serial_number` | VARCHAR(100) | Yes | Serial number |
| `category` | VARCHAR(50) | Yes | Category: inverters, optimizers, meters, gateways |
| `firmware_version` | VARCHAR(50) | Yes | Firmware version |
| `cpu_version` | VARCHAR(50) | Yes | CPU version |
| `connected_optimizers` | INTEGER | Yes | Number of connected optimizers |
| `connected_to` | VARCHAR(100) | Yes | Parent equipment |
| `max_power` | FLOAT | Yes | Max power rating (for panels) |
| `quantity` | INTEGER | Yes | Quantity (for panels) |
| `short_description` | TEXT | Yes | Description |
| `created_at` | DATETIME | No | Record creation timestamp |
| `updated_at` | DATETIME | No | Record update timestamp |

**Unique Constraints:** `(site_id, name, serial_number)`
**Indexes:** `site_id`

---

### seh_inverter_telemetry

Detailed inverter telemetry data at 5-minute intervals.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | No | Primary key (auto-increment) |
| `site_id` | INTEGER | No | Foreign key to seh_sites.id |
| `serial_number` | VARCHAR(50) | No | Inverter serial number |
| `timestamp` | DATETIME | No | Reading timestamp |
| `total_active_power` | FLOAT | Yes | Total AC power output in Watts |
| `total_energy` | FLOAT | Yes | Cumulative energy in Wh |
| `power_limit` | FLOAT | Yes | Power limit percentage |
| `temperature` | FLOAT | Yes | Inverter temperature in Celsius |
| `inverter_mode` | VARCHAR(50) | Yes | Mode: MPPT, FAULT, NIGHT, etc. |
| `operation_mode` | INTEGER | Yes | Operation mode code |
| `ac_current` | FLOAT | Yes | AC current in Amps |
| `ac_voltage` | FLOAT | Yes | AC voltage in Volts |
| `ac_frequency` | FLOAT | Yes | AC frequency in Hz |
| `apparent_power` | FLOAT | Yes | Apparent power in VA |
| `active_power` | FLOAT | Yes | Active power in Watts |
| `reactive_power` | FLOAT | Yes | Reactive power in VAR |
| `cos_phi` | FLOAT | Yes | Power factor (cos phi) |
| `dc_voltage` | FLOAT | Yes | DC input voltage |
| `created_at` | DATETIME | No | Record creation timestamp |
| `updated_at` | DATETIME | No | Record update timestamp |

**Unique Constraints:** `(site_id, serial_number, timestamp)`
**Indexes:** `site_id`, `serial_number`, `timestamp`

---

### seh_optimizer_telemetry

Power optimizer telemetry data at 5-minute intervals.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | No | Primary key (auto-increment) |
| `site_id` | INTEGER | No | Foreign key to seh_sites.id |
| `serial_number` | VARCHAR(50) | No | Optimizer serial number |
| `inverter_serial` | VARCHAR(50) | Yes | Connected inverter serial |
| `timestamp` | DATETIME | No | Reading timestamp |
| `panel_id` | INTEGER | Yes | Panel position identifier |
| `dc_voltage` | FLOAT | Yes | DC input voltage from panel |
| `dc_current` | FLOAT | Yes | DC input current from panel |
| `dc_power` | FLOAT | Yes | DC power from panel in Watts |
| `output_voltage` | FLOAT | Yes | Output voltage to inverter |
| `output_current` | FLOAT | Yes | Output current to inverter |
| `output_power` | FLOAT | Yes | Output power to inverter in Watts |
| `energy` | FLOAT | Yes | Energy produced in Wh |
| `lifetime_energy` | FLOAT | Yes | Lifetime energy in Wh |
| `temperature` | FLOAT | Yes | Optimizer temperature in Celsius |
| `optimizer_mode` | VARCHAR(50) | Yes | Operating mode |
| `created_at` | DATETIME | No | Record creation timestamp |
| `updated_at` | DATETIME | No | Record update timestamp |

**Unique Constraints:** `(site_id, serial_number, timestamp)`
**Indexes:** `site_id`, `serial_number`, `inverter_serial`, `timestamp`

---

### seh_sync_metadata

Tracks synchronization state for each data type per site.

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `id` | INTEGER | No | Primary key (auto-increment) |
| `site_id` | INTEGER | No | Foreign key to seh_sites.id |
| `data_type` | VARCHAR(50) | No | Data type being synced |
| `last_sync_time` | DATETIME | No | When sync was last run |
| `last_data_timestamp` | DATETIME | Yes | Timestamp of most recent data |
| `records_synced` | INTEGER | Yes | Number of records synced |
| `status` | VARCHAR(20) | Yes | Status: success, partial, error |
| `error_message` | VARCHAR(500) | Yes | Error message if failed |
| `created_at` | DATETIME | No | Record creation timestamp |
| `updated_at` | DATETIME | No | Record update timestamp |

**Unique Constraints:** `(site_id, data_type)`
**Indexes:** `site_id`

**Data Types:**
- `site` - Site details
- `equipment` - Equipment list
- `energy` - Energy readings
- `power` - Power readings
- `storage` - Battery data
- `meter` - Meter data
- `environmental` - Environmental benefits
- `alert` - Alerts
- `inventory` - Inventory
- `inverter_telemetry` - Inverter telemetry
- `optimizer_telemetry` - Optimizer telemetry

---

## Database Views

Views provide simplified access to common queries.

### v_seh_site_summary

Simplified site information view.

```sql
SELECT
    id AS site_id,
    name AS site_name,
    city, state, country, timezone,
    peak_power, status,
    installation_date, last_update_time,
    primary_module_manufacturer,
    primary_module_model,
    created_at, updated_at
FROM seh_sites
```

---

### v_seh_daily_energy

Daily energy production with kWh conversion.

```sql
SELECT
    e.id, e.site_id,
    s.name AS site_name,
    e.reading_date, e.time_unit,
    e.energy_wh,
    ROUND(e.energy_wh / 1000.0, 2) AS energy_kwh,
    e.created_at
FROM seh_energy_readings e
JOIN seh_sites s ON e.site_id = s.id
ORDER BY e.site_id, e.reading_date DESC
```

---

### v_seh_latest_power

Most recent power reading per site.

```sql
SELECT
    p.id, p.site_id,
    s.name AS site_name,
    p.timestamp,
    p.power_watts,
    ROUND(p.power_watts / 1000.0, 2) AS power_kw,
    p.created_at
FROM seh_power_readings p
JOIN seh_sites s ON p.site_id = s.id
WHERE p.timestamp = (
    SELECT MAX(p2.timestamp)
    FROM seh_power_readings p2
    WHERE p2.site_id = p.site_id
)
```

---

### v_seh_power_flow_current

Most recent power flow snapshot per site.

```sql
SELECT
    pf.id, pf.site_id,
    s.name AS site_name,
    pf.timestamp, pf.unit,
    pf.pv_status, pf.pv_power,
    pf.grid_status, pf.grid_power,
    pf.load_status, pf.load_power,
    pf.storage_status, pf.storage_power,
    pf.storage_charge_level,
    pf.created_at
FROM seh_power_flows pf
JOIN seh_sites s ON pf.site_id = s.id
WHERE pf.timestamp = (
    SELECT MAX(pf2.timestamp)
    FROM seh_power_flows pf2
    WHERE pf2.site_id = pf.site_id
)
```

---

### v_seh_sync_status

Current sync status for all sites and data types.

```sql
SELECT
    sm.id, sm.site_id,
    s.name AS site_name,
    sm.data_type,
    sm.last_sync_time,
    sm.last_data_timestamp,
    sm.records_synced,
    sm.status,
    sm.error_message,
    sm.updated_at
FROM seh_sync_metadata sm
JOIN seh_sites s ON sm.site_id = s.id
ORDER BY sm.site_id, sm.data_type
```

---

### v_seh_equipment_list

Complete equipment list with site names.

```sql
SELECT
    e.id, e.site_id,
    s.name AS site_name,
    e.serial_number,
    e.name AS equipment_name,
    e.manufacturer, e.model,
    e.equipment_type,
    e.cpu_version,
    e.connected_optimizers,
    e.last_report_date,
    e.created_at
FROM seh_equipment e
JOIN seh_sites s ON e.site_id = s.id
ORDER BY e.site_id, e.equipment_type, e.name
```

---

### v_seh_battery_status

Current battery status for all batteries.

```sql
SELECT
    b.id, b.site_id,
    s.name AS site_name,
    b.serial_number,
    b.name AS battery_name,
    b.manufacturer, b.model,
    b.nameplate_capacity,
    b.capacity AS current_capacity,
    b.last_state_of_charge,
    b.last_power,
    b.last_status,
    b.last_telemetry_time,
    b.lifetime_energy_charged,
    b.lifetime_energy_discharged,
    b.created_at
FROM seh_batteries b
JOIN seh_sites s ON b.site_id = s.id
ORDER BY b.site_id, b.name
```

---

### v_seh_energy_monthly

Monthly energy totals aggregated from daily readings.

**SQLite:**
```sql
SELECT
    site_id,
    strftime('%Y-%m', reading_date) AS month,
    SUM(energy_wh) AS total_wh,
    ROUND(SUM(energy_wh) / 1000.0, 2) AS total_kwh,
    COUNT(*) AS days_with_data
FROM seh_energy_readings
WHERE time_unit = 'DAY'
GROUP BY site_id, strftime('%Y-%m', reading_date)
ORDER BY site_id, month DESC
```

**PostgreSQL:**
```sql
SELECT
    site_id,
    TO_CHAR(reading_date, 'YYYY-MM') AS month,
    SUM(energy_wh) AS total_wh,
    ROUND(SUM(energy_wh) / 1000.0, 2) AS total_kwh,
    COUNT(*) AS days_with_data
FROM seh_energy_readings
WHERE time_unit = 'DAY'
GROUP BY site_id, TO_CHAR(reading_date, 'YYYY-MM')
ORDER BY site_id, month DESC
```

---

## Common Field Patterns

### Timestamps

All tables include audit timestamps:
- `created_at` - Record creation time (auto-set)
- `updated_at` - Last modification time (auto-updated)

### Foreign Keys

All child tables use `ON DELETE CASCADE` for the site relationship, meaning deleting a site removes all associated data.

### Units

| Measurement | Unit | Notes |
|-------------|------|-------|
| Energy | Watt-hours (Wh) | Divide by 1000 for kWh |
| Power | Watts (W) | Divide by 1000 for kW |
| Voltage | Volts (V) | |
| Current | Amperes (A) | |
| Frequency | Hertz (Hz) | |
| Temperature | Celsius (C) | |
| Charge Level | Percentage (%) | 0-100 |
| Power Factor | Ratio | -1 to 1 |
