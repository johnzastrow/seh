"""Integration tests for different database backends.

Run these tests with specific database URLs:

    # SQLite (default)
    uv run pytest tests/test_database_backends.py -v

    # PostgreSQL
    SEH_DATABASE_URL="postgresql+psycopg://user:pass@host:5432/db" \
        uv run pytest tests/test_database_backends.py -v -m postgresql

    # MariaDB
    SEH_DATABASE_URL="mariadb+mariadbconnector://user:pass@host:3306/db" \
        uv run pytest tests/test_database_backends.py -v -m mariadb
"""

import os
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from seh.config.settings import Settings
from seh.db.base import Base
from seh.db.models import (
    Site,
    Equipment,
    EnergyReading,
    PowerReading,
    EnvironmentalBenefits,
    Alert,
    SyncMetadata,
)
from seh.db.repositories import (
    SiteRepository,
    EquipmentRepository,
    EnergyRepository,
    PowerRepository,
    EnvironmentalBenefitsRepository,
    AlertRepository,
    SyncMetadataRepository,
)


def get_database_type(url: str) -> str:
    """Determine database type from URL."""
    if url.startswith("postgresql"):
        return "postgresql"
    elif url.startswith("mariadb"):
        return "mariadb"
    elif url.startswith("mysql"):
        return "mysql"
    else:
        return "sqlite"


@pytest.fixture(scope="module")
def database_url():
    """Get database URL from environment or use SQLite."""
    return os.environ.get("SEH_DATABASE_URL", "sqlite:///:memory:")


@pytest.fixture(scope="module")
def db_type(database_url):
    """Get database type."""
    return get_database_type(database_url)


@pytest.fixture(scope="module")
def engine(database_url):
    """Create database engine for tests."""
    engine = create_engine(database_url, echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def session(engine):
    """Create a test session."""
    with Session(engine) as session:
        yield session
        session.rollback()


class TestDatabaseConnection:
    """Test database connectivity."""

    def test_connection(self, engine):
        """Test that we can connect to the database."""
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    def test_tables_created(self, engine, db_type):
        """Test that all tables are created."""
        expected_tables = {
            "seh_sites",
            "seh_equipment",
            "seh_batteries",
            "seh_energy_readings",
            "seh_power_readings",
            "seh_power_flows",
            "seh_meters",
            "seh_meter_readings",
            "seh_alerts",
            "seh_environmental_benefits",
            "seh_inventory",
            "seh_inverter_telemetry",
            "seh_optimizer_telemetry",
            "seh_sync_metadata",
        }

        with engine.connect() as conn:
            if db_type == "postgresql":
                result = conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = current_schema()"
                    )
                )
            elif db_type in ("mariadb", "mysql"):
                result = conn.execute(text("SHOW TABLES"))
            else:  # SQLite
                result = conn.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'")
                )

            tables = {row[0] for row in result}
            assert expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}"


class TestSiteOperations:
    """Test Site model operations across backends."""

    def test_create_site(self, session, db_type):
        """Test creating a site."""
        site = Site(
            id=99901,
            name=f"Test Site {db_type}",
            status="Active",
            peak_power=10.5,
            country="United States",
            timezone="America/Los_Angeles",
        )
        session.add(site)
        session.flush()

        retrieved = session.get(Site, 99901)
        assert retrieved is not None
        assert retrieved.name == f"Test Site {db_type}"
        assert retrieved.peak_power == 10.5

    def test_upsert_site(self, session, db_type):
        """Test upserting a site."""
        repo = SiteRepository(session)

        # Create
        site_data = {
            "id": 99902,
            "name": f"Upsert Test {db_type}",
            "status": "Active",
        }
        site = repo.upsert(site_data)
        session.flush()
        assert site.name == f"Upsert Test {db_type}"

        # Update - need to expire the session cache to see updates
        session.expire_all()
        updated_data = {
            "id": 99902,
            "name": f"Updated Site {db_type}",
            "status": "Inactive",
        }
        site = repo.upsert(updated_data)
        session.flush()
        session.expire_all()

        # Refetch to verify
        site = repo.get_by_id(99902)
        assert site.name == f"Updated Site {db_type}"
        assert site.status == "Inactive"


class TestEquipmentOperations:
    """Test Equipment model operations across backends."""

    def test_create_seh_equipment(self, session, db_type):
        """Test creating seh_equipment."""
        # Create site first
        site = Site(id=99903, name="Equipment Test Site")
        session.add(site)
        session.flush()

        seh_equipment = Equipment(
            site_id=99903,
            serial_number=f"SN-{db_type}-001",
            name="Test Inverter",
            manufacturer="SolarEdge",
            model="SE10000H",
            equipment_type="Inverter",
        )
        session.add(seh_equipment)
        session.flush()

        retrieved = session.query(Equipment).filter_by(
            serial_number=f"SN-{db_type}-001"
        ).first()
        assert retrieved is not None
        assert retrieved.name == "Test Inverter"

    def test_upsert_seh_equipment(self, session, db_type):
        """Test upserting seh_equipment."""
        site = Site(id=99904, name="Equipment Upsert Site")
        session.add(site)
        session.flush()

        repo = EquipmentRepository(session)

        # Create
        seh_equipment_data = {
            "site_id": 99904,
            "serial_number": f"SN-{db_type}-002",
            "name": "Original Name",
            "manufacturer": "SolarEdge",
        }
        seh_equipment = repo.upsert(seh_equipment_data)
        session.flush()
        assert seh_equipment.name == "Original Name"

        # Update - need to expire session cache
        session.expire_all()
        updated_data = {
            "site_id": 99904,
            "serial_number": f"SN-{db_type}-002",
            "name": "Updated Name",
            "manufacturer": "SolarEdge",
        }
        repo.upsert(updated_data)
        session.flush()
        session.expire_all()

        # Refetch to verify
        seh_equipment = repo.get_by_serial(f"SN-{db_type}-002")
        assert seh_equipment.name == "Updated Name"


class TestEnergyOperations:
    """Test EnergyReading operations across backends."""

    def test_upsert_batch_energy(self, session, db_type):
        """Test batch upserting energy readings."""
        site = Site(id=99905, name="Energy Test Site")
        session.add(site)
        session.flush()

        repo = EnergyRepository(session)

        readings = [
            {
                "site_id": 99905,
                "reading_date": date(2024, 1, i),
                "time_unit": "DAY",
                "energy_wh": 1000.0 * i,
            }
            for i in range(1, 6)
        ]

        count = repo.upsert_batch(readings)
        assert count == 5

        # Verify data
        result = repo.get_by_site_id(99905)
        assert len(result) == 5

        # Test idempotency - upsert again
        count = repo.upsert_batch(readings)
        assert count == 5

        result = repo.get_by_site_id(99905)
        assert len(result) == 5  # Still 5, not 10


class TestPowerOperations:
    """Test PowerReading operations across backends."""

    def test_upsert_batch_power(self, session, db_type):
        """Test batch upserting power readings."""
        site = Site(id=99906, name="Power Test Site")
        session.add(site)
        session.flush()

        repo = PowerRepository(session)

        readings = [
            {
                "site_id": 99906,
                "timestamp": datetime(2024, 1, 15, i, 0, 0),
                "power_watts": 5000.0 + i * 100,
            }
            for i in range(12)
        ]

        count = repo.upsert_batch(readings)
        assert count == 12

        result = repo.get_by_site_id(99906)
        assert len(result) == 12


class TestAlertOperations:
    """Test Alert operations across backends."""

    def test_upsert_alert(self, session, db_type):
        """Test upserting seh_alerts."""
        site = Site(id=99907, name="Alert Test Site")
        session.add(site)
        session.flush()

        repo = AlertRepository(session)

        alert_data = {
            "site_id": 99907,
            "alert_id": 1001,
            "severity": "HIGH",
            "alert_code": 100,
            "description": "Test alert",
            "alert_timestamp": datetime(2024, 1, 15, 12, 0, 0),
        }

        alert = repo.upsert(alert_data)
        session.flush()
        assert alert.severity == "HIGH"

        # Update - expire cache first
        session.expire_all()
        updated_data = {
            "site_id": 99907,
            "alert_id": 1001,
            "severity": "MEDIUM",
            "alert_code": 100,
            "description": "Updated alert",
            "alert_timestamp": datetime(2024, 1, 15, 12, 0, 0),
        }

        repo.upsert(updated_data)
        session.flush()
        session.expire_all()

        # Refetch to verify
        alert = repo.get_by_alert_id(99907, 1001)
        assert alert.severity == "MEDIUM"
        assert alert.description == "Updated alert"


class TestSyncMetadata:
    """Test SyncMetadata operations across backends."""

    def test_seh_sync_metadata_tracking(self, session, db_type):
        """Test sync metadata tracking."""
        site = Site(id=99908, name="Metadata Test Site")
        session.add(site)
        session.flush()

        repo = SyncMetadataRepository(session)

        # Record sync
        repo.upsert(
            site_id=99908,
            data_type="energy",
            last_sync_time=datetime(2024, 1, 15, 12, 0, 0),
            records_synced=100,
        )
        session.flush()

        metadata = repo.get_by_site_and_type(99908, "energy")
        assert metadata is not None
        assert metadata.records_synced == 100

        # Update sync - expire cache first
        session.expire_all()
        repo.upsert(
            site_id=99908,
            data_type="energy",
            last_sync_time=datetime(2024, 1, 16, 12, 0, 0),
            records_synced=200,
        )
        session.flush()
        session.expire_all()

        # Refetch to verify
        metadata = repo.get_by_site_and_type(99908, "energy")
        assert metadata.records_synced == 200


@pytest.mark.postgresql
class TestPostgreSQLSpecific:
    """Tests specific to PostgreSQL."""

    @pytest.fixture(autouse=True)
    def skip_if_not_postgresql(self, db_type):
        if db_type != "postgresql":
            pytest.skip("PostgreSQL-specific test")

    def test_schema_support(self, engine):
        """Test PostgreSQL schema support."""
        with engine.connect() as conn:
            result = conn.execute(text("SELECT current_schema()"))
            schema = result.scalar()
            assert schema is not None


@pytest.mark.mariadb
class TestMariaDBSpecific:
    """Tests specific to MariaDB."""

    @pytest.fixture(autouse=True)
    def skip_if_not_mariadb(self, db_type):
        if db_type not in ("mariadb", "mysql"):
            pytest.skip("MariaDB-specific test")

    def test_engine_version(self, engine):
        """Test MariaDB version."""
        with engine.connect() as conn:
            result = conn.execute(text("SELECT VERSION()"))
            version = result.scalar()
            assert version is not None


@pytest.mark.sqlite
class TestSQLiteSpecific:
    """Tests specific to SQLite."""

    @pytest.fixture(autouse=True)
    def skip_if_not_sqlite(self, db_type):
        if db_type != "sqlite":
            pytest.skip("SQLite-specific test")

    def test_sqlite_version(self, engine):
        """Test SQLite version."""
        with engine.connect() as conn:
            result = conn.execute(text("SELECT sqlite_version()"))
            version = result.scalar()
            assert version is not None


class TestUniqueConstraints:
    """Test that unique constraints prevent duplicates."""

    def test_energy_reading_unique_constraint(self, session, db_type):
        """Test that duplicate energy readings are rejected."""
        from sqlalchemy.exc import IntegrityError

        site = Site(id=99950, name="Unique Constraint Test Site")
        session.add(site)
        session.flush()

        # Insert first reading
        reading1 = EnergyReading(
            site_id=99950,
            reading_date=date(2024, 1, 1),
            time_unit="DAY",
            energy_wh=1000.0,
        )
        session.add(reading1)
        session.flush()

        # Try to insert duplicate (same site_id, reading_date, time_unit)
        reading2 = EnergyReading(
            site_id=99950,
            reading_date=date(2024, 1, 1),
            time_unit="DAY",
            energy_wh=2000.0,
        )
        session.add(reading2)

        with pytest.raises(IntegrityError):
            session.flush()

        session.rollback()

    def test_power_reading_unique_constraint(self, session, db_type):
        """Test that duplicate power readings are rejected."""
        from sqlalchemy.exc import IntegrityError

        site = Site(id=99951, name="Power Unique Test Site")
        session.add(site)
        session.flush()

        ts = datetime(2024, 1, 15, 12, 0, 0)

        # Insert first reading
        reading1 = PowerReading(
            site_id=99951,
            timestamp=ts,
            power_watts=5000.0,
        )
        session.add(reading1)
        session.flush()

        # Try to insert duplicate (same site_id, timestamp)
        reading2 = PowerReading(
            site_id=99951,
            timestamp=ts,
            power_watts=6000.0,
        )
        session.add(reading2)

        with pytest.raises(IntegrityError):
            session.flush()

        session.rollback()

    def test_alert_unique_constraint(self, session, db_type):
        """Test that duplicate alerts are rejected."""
        from sqlalchemy.exc import IntegrityError

        site = Site(id=99952, name="Alert Unique Test Site")
        session.add(site)
        session.flush()

        # Insert first alert
        alert1 = Alert(
            site_id=99952,
            alert_id=5001,
            severity="HIGH",
        )
        session.add(alert1)
        session.flush()

        # Try to insert duplicate (same site_id, alert_id)
        alert2 = Alert(
            site_id=99952,
            alert_id=5001,
            severity="LOW",
        )
        session.add(alert2)

        with pytest.raises(IntegrityError):
            session.flush()

        session.rollback()

    def test_equipment_serial_unique_constraint(self, session, db_type):
        """Test that duplicate equipment serial numbers are rejected."""
        from sqlalchemy.exc import IntegrityError

        site = Site(id=99953, name="Equipment Unique Test Site")
        session.add(site)
        session.flush()

        # Insert first equipment
        eq1 = Equipment(
            site_id=99953,
            serial_number="UNIQUE-SN-001",
            name="First Inverter",
        )
        session.add(eq1)
        session.flush()

        # Try to insert duplicate serial number
        eq2 = Equipment(
            site_id=99953,
            serial_number="UNIQUE-SN-001",
            name="Second Inverter",
        )
        session.add(eq2)

        with pytest.raises(IntegrityError):
            session.flush()

        session.rollback()

    def test_sync_metadata_unique_constraint(self, session, db_type):
        """Test that duplicate sync metadata entries are rejected."""
        from sqlalchemy.exc import IntegrityError

        site = Site(id=99954, name="Sync Unique Test Site")
        session.add(site)
        session.flush()

        # Insert first metadata
        meta1 = SyncMetadata(
            site_id=99954,
            data_type="energy",
            last_sync_time=datetime(2024, 1, 15, 12, 0, 0),
        )
        session.add(meta1)
        session.flush()

        # Try to insert duplicate (same site_id, data_type)
        meta2 = SyncMetadata(
            site_id=99954,
            data_type="energy",
            last_sync_time=datetime(2024, 1, 16, 12, 0, 0),
        )
        session.add(meta2)

        with pytest.raises(IntegrityError):
            session.flush()

        session.rollback()


class TestCascadeDeletes:
    """Test cascade delete behavior across backends."""

    def test_site_cascade_delete(self, session, db_type):
        """Test that deleting a site cascades to related data."""
        # Create site with related data
        site = Site(id=99999, name="Cascade Delete Test")
        session.add(site)
        session.flush()

        seh_equipment = Equipment(
            site_id=99999,
            serial_number=f"CASCADE-{db_type}",
            name="Cascade Test Inverter",
        )
        reading = EnergyReading(
            site_id=99999,
            reading_date=date(2024, 1, 1),
            time_unit="DAY",
            energy_wh=1000.0,
        )
        session.add_all([seh_equipment, reading])
        session.flush()

        # Delete site
        session.delete(site)
        session.flush()

        # Verify cascade
        assert session.query(Equipment).filter_by(site_id=99999).first() is None
        assert session.query(EnergyReading).filter_by(site_id=99999).first() is None
