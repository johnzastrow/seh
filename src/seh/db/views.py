"""Database views for simplified querying."""

from sqlalchemy import text
from sqlalchemy.engine import Engine

# View definitions for each database type
# SQLite and PostgreSQL use similar syntax, MariaDB may differ slightly

VIEWS = {
    "v_site_summary": """
        CREATE VIEW IF NOT EXISTS v_site_summary AS
        SELECT
            s.id AS site_id,
            s.name AS site_name,
            s.city,
            s.state,
            s.country,
            s.timezone,
            s.peak_power,
            s.status,
            s.installation_date,
            s.last_update_time,
            s.primary_module_manufacturer,
            s.primary_module_model,
            s.created_at,
            s.updated_at
        FROM sites s
    """,
    "v_daily_energy": """
        CREATE VIEW IF NOT EXISTS v_daily_energy AS
        SELECT
            e.id,
            e.site_id,
            s.name AS site_name,
            e.reading_date,
            e.time_unit,
            e.energy_wh,
            ROUND(e.energy_wh / 1000.0, 2) AS energy_kwh,
            e.created_at
        FROM energy_readings e
        JOIN sites s ON e.site_id = s.id
        ORDER BY e.site_id, e.reading_date DESC
    """,
    "v_latest_power": """
        CREATE VIEW IF NOT EXISTS v_latest_power AS
        SELECT
            p.id,
            p.site_id,
            s.name AS site_name,
            p.timestamp,
            p.power_watts,
            ROUND(p.power_watts / 1000.0, 2) AS power_kw,
            p.created_at
        FROM power_readings p
        JOIN sites s ON p.site_id = s.id
        WHERE p.timestamp = (
            SELECT MAX(p2.timestamp)
            FROM power_readings p2
            WHERE p2.site_id = p.site_id
        )
    """,
    "v_power_flow_current": """
        CREATE VIEW IF NOT EXISTS v_power_flow_current AS
        SELECT
            pf.id,
            pf.site_id,
            s.name AS site_name,
            pf.timestamp,
            pf.unit,
            pf.pv_status,
            pf.pv_power,
            pf.grid_status,
            pf.grid_power,
            pf.load_status,
            pf.load_power,
            pf.storage_status,
            pf.storage_power,
            pf.storage_charge_level,
            pf.created_at
        FROM power_flows pf
        JOIN sites s ON pf.site_id = s.id
        WHERE pf.timestamp = (
            SELECT MAX(pf2.timestamp)
            FROM power_flows pf2
            WHERE pf2.site_id = pf.site_id
        )
    """,
    "v_sync_status": """
        CREATE VIEW IF NOT EXISTS v_sync_status AS
        SELECT
            sm.id,
            sm.site_id,
            s.name AS site_name,
            sm.data_type,
            sm.last_sync_time,
            sm.last_data_timestamp,
            sm.records_synced,
            sm.status,
            sm.error_message,
            sm.updated_at
        FROM sync_metadata sm
        JOIN sites s ON sm.site_id = s.id
        ORDER BY sm.site_id, sm.data_type
    """,
    "v_equipment_list": """
        CREATE VIEW IF NOT EXISTS v_equipment_list AS
        SELECT
            e.id,
            e.site_id,
            s.name AS site_name,
            e.serial_number,
            e.name AS equipment_name,
            e.manufacturer,
            e.model,
            e.equipment_type,
            e.cpu_version,
            e.connected_optimizers,
            e.last_report_date,
            e.created_at
        FROM equipment e
        JOIN sites s ON e.site_id = s.id
        ORDER BY e.site_id, e.equipment_type, e.name
    """,
    "v_battery_status": """
        CREATE VIEW IF NOT EXISTS v_battery_status AS
        SELECT
            b.id,
            b.site_id,
            s.name AS site_name,
            b.serial_number,
            b.name AS battery_name,
            b.manufacturer,
            b.model,
            b.nameplate_capacity,
            b.capacity AS current_capacity,
            b.last_state_of_charge,
            b.last_power,
            b.last_status,
            b.last_telemetry_time,
            b.lifetime_energy_charged,
            b.lifetime_energy_discharged,
            b.created_at
        FROM batteries b
        JOIN sites s ON b.site_id = s.id
        ORDER BY b.site_id, b.name
    """,
    "v_energy_monthly": """
        CREATE VIEW IF NOT EXISTS v_energy_monthly AS
        SELECT
            site_id,
            strftime('%Y-%m', reading_date) AS month,
            SUM(energy_wh) AS total_wh,
            ROUND(SUM(energy_wh) / 1000.0, 2) AS total_kwh,
            COUNT(*) AS days_with_data
        FROM energy_readings
        WHERE time_unit = 'DAY'
        GROUP BY site_id, strftime('%Y-%m', reading_date)
        ORDER BY site_id, month DESC
    """,
}

# PostgreSQL-specific versions (uses different date functions)
VIEWS_POSTGRESQL = {
    "v_energy_monthly": """
        CREATE OR REPLACE VIEW v_energy_monthly AS
        SELECT
            site_id,
            TO_CHAR(reading_date, 'YYYY-MM') AS month,
            SUM(energy_wh) AS total_wh,
            ROUND(SUM(energy_wh) / 1000.0, 2) AS total_kwh,
            COUNT(*) AS days_with_data
        FROM energy_readings
        WHERE time_unit = 'DAY'
        GROUP BY site_id, TO_CHAR(reading_date, 'YYYY-MM')
        ORDER BY site_id, month DESC
    """,
}

# MariaDB/MySQL-specific versions (uses DATE_FORMAT)
VIEWS_MYSQL = {
    "v_energy_monthly": """
        CREATE VIEW v_energy_monthly AS
        SELECT
            site_id,
            DATE_FORMAT(reading_date, '%Y-%m') AS month,
            SUM(energy_wh) AS total_wh,
            ROUND(SUM(energy_wh) / 1000.0, 2) AS total_kwh,
            COUNT(*) AS days_with_data
        FROM energy_readings
        WHERE time_unit = 'DAY'
        GROUP BY site_id, DATE_FORMAT(reading_date, '%Y-%m')
        ORDER BY site_id, month DESC
    """,
}


def create_views(engine: Engine) -> None:
    """Create database views for simplified querying.

    Args:
        engine: SQLAlchemy engine.
    """
    dialect = engine.dialect.name

    with engine.connect() as conn:
        for view_name, view_sql in VIEWS.items():
            # Use database-specific version if available
            if dialect == "postgresql" and view_name in VIEWS_POSTGRESQL:
                view_sql = VIEWS_POSTGRESQL[view_name]
            elif dialect in ("mysql", "mariadb") and view_name in VIEWS_MYSQL:
                view_sql = VIEWS_MYSQL[view_name]

            # Adjust syntax for different databases
            if dialect == "postgresql":
                # PostgreSQL uses CREATE OR REPLACE VIEW
                view_sql = view_sql.replace(
                    "CREATE VIEW IF NOT EXISTS",
                    "CREATE OR REPLACE VIEW"
                )
            elif dialect in ("mysql", "mariadb"):
                # MariaDB/MySQL: drop and recreate
                drop_sql = f"DROP VIEW IF EXISTS {view_name}"
                conn.execute(text(drop_sql))
                view_sql = view_sql.replace("CREATE VIEW IF NOT EXISTS", "CREATE VIEW")

            conn.execute(text(view_sql))

        conn.commit()


def drop_views(engine: Engine) -> None:
    """Drop all database views.

    Args:
        engine: SQLAlchemy engine.
    """
    with engine.connect() as conn:
        for view_name in VIEWS:
            conn.execute(text(f"DROP VIEW IF EXISTS {view_name}"))
        conn.commit()
