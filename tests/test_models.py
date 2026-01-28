"""Tests for ORM models."""

from datetime import datetime, date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from seh.db.base import Base
from seh.db.models import (
    Site,
    Equipment,
    Battery,
    EnergyReading,
    PowerReading,
    PowerFlow,
    Meter,
    MeterReading,
    Alert,
    EnvironmentalBenefits,
    InventoryItem,
    InverterTelemetry,
    OptimizerTelemetry,
    SyncMetadata,
)


class TestSiteModel:
    """Test Site model."""

    def test_create_site(self, test_session):
        """Test creating a site."""
        site = Site(
            id=12345,
            name="Test Site",
            status="Active",
            peak_power=10.5,
            country="United States",
            timezone="America/Los_Angeles",
        )
        test_session.add(site)
        test_session.commit()

        retrieved = test_session.get(Site, 12345)
        assert retrieved is not None
        assert retrieved.name == "Test Site"
        assert retrieved.status == "Active"
        assert retrieved.peak_power == 10.5

    def test_site_timestamps(self, test_session):
        """Test that timestamps are set automatically."""
        site = Site(id=12346, name="Timestamp Test")
        test_session.add(site)
        test_session.commit()

        retrieved = test_session.get(Site, 12346)
        assert retrieved.created_at is not None
        assert retrieved.updated_at is not None

    def test_site_repr(self, test_session):
        """Test site string representation."""
        site = Site(id=12347, name="Repr Test")
        assert "12347" in repr(site)
        assert "Repr Test" in repr(site)


class TestEquipmentModel:
    """Test Equipment model."""

    def test_create_equipment(self, test_session):
        """Test creating equipment."""
        # First create a site
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        equipment = Equipment(
            site_id=12345,
            serial_number="SN123456",
            name="Inverter 1",
            manufacturer="SolarEdge",
            model="SE10000H",
            equipment_type="Inverter",
        )
        test_session.add(equipment)
        test_session.commit()

        retrieved = test_session.query(Equipment).filter_by(serial_number="SN123456").first()
        assert retrieved is not None
        assert retrieved.name == "Inverter 1"
        assert retrieved.equipment_type == "Inverter"

    def test_equipment_site_relationship(self, test_session):
        """Test equipment-site relationship."""
        site = Site(id=12348, name="Relationship Test")
        test_session.add(site)
        test_session.commit()

        equipment = Equipment(
            site_id=12348,
            serial_number="SN789",
            name="Test Inverter",
            equipment_type="Inverter",
        )
        test_session.add(equipment)
        test_session.commit()

        # Check relationship from equipment to site
        assert equipment.site.name == "Relationship Test"

        # Check relationship from site to equipment
        site = test_session.get(Site, 12348)
        assert len(site.equipment) == 1
        assert site.equipment[0].serial_number == "SN789"


class TestEnergyReadingModel:
    """Test EnergyReading model."""

    def test_create_energy_reading(self, test_session):
        """Test creating an energy reading."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        reading = EnergyReading(
            site_id=12345,
            reading_date=date(2024, 1, 15),
            time_unit="DAY",
            energy_wh=25000.0,
        )
        test_session.add(reading)
        test_session.commit()

        retrieved = test_session.query(EnergyReading).filter_by(site_id=12345).first()
        assert retrieved is not None
        assert retrieved.energy_wh == 25000.0
        assert retrieved.time_unit == "DAY"


class TestPowerReadingModel:
    """Test PowerReading model."""

    def test_create_power_reading(self, test_session):
        """Test creating a power reading."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        reading = PowerReading(
            site_id=12345,
            timestamp=datetime(2024, 1, 15, 12, 0, 0),
            power_watts=5000.0,
        )
        test_session.add(reading)
        test_session.commit()

        retrieved = test_session.query(PowerReading).filter_by(site_id=12345).first()
        assert retrieved is not None
        assert retrieved.power_watts == 5000.0


class TestInverterTelemetryModel:
    """Test InverterTelemetry model."""

    def test_create_inverter_telemetry(self, test_session):
        """Test creating inverter telemetry."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        telemetry = InverterTelemetry(
            site_id=12345,
            serial_number="SN123",
            timestamp=datetime(2024, 1, 15, 12, 0, 0),
            total_active_power=5000.0,
            temperature=45.5,
            inverter_mode="MPPT",
            ac_voltage=240.0,
            ac_current=21.0,
        )
        test_session.add(telemetry)
        test_session.commit()

        retrieved = test_session.query(InverterTelemetry).filter_by(site_id=12345).first()
        assert retrieved is not None
        assert retrieved.total_active_power == 5000.0
        assert retrieved.inverter_mode == "MPPT"


class TestEnvironmentalBenefitsModel:
    """Test EnvironmentalBenefits model."""

    def test_create_environmental_benefits(self, test_session):
        """Test creating environmental benefits."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        benefits = EnvironmentalBenefits(
            site_id=12345,
            co2_saved=500.0,
            trees_planted=10.5,
            co2_units="KG",
        )
        test_session.add(benefits)
        test_session.commit()

        retrieved = test_session.query(EnvironmentalBenefits).filter_by(site_id=12345).first()
        assert retrieved is not None
        assert retrieved.co2_saved == 500.0
        assert retrieved.trees_planted == 10.5


class TestSyncMetadataModel:
    """Test SyncMetadata model."""

    def test_create_sync_metadata(self, test_session):
        """Test creating sync metadata."""
        site = Site(id=12345, name="Test Site")
        test_session.add(site)
        test_session.commit()

        metadata = SyncMetadata(
            site_id=12345,
            data_type="energy",
            last_sync_time=datetime(2024, 1, 15, 12, 0, 0),
            records_synced=100,
            status="success",
        )
        test_session.add(metadata)
        test_session.commit()

        retrieved = test_session.query(SyncMetadata).filter_by(
            site_id=12345, data_type="energy"
        ).first()
        assert retrieved is not None
        assert retrieved.records_synced == 100
        assert retrieved.status == "success"


class TestCascadeDelete:
    """Test cascade delete behavior."""

    def test_deleting_site_deletes_related_data(self, test_session):
        """Test that deleting a site cascades to related records."""
        # Create site with related data
        site = Site(id=99999, name="Cascade Test")
        test_session.add(site)
        test_session.commit()

        equipment = Equipment(
            site_id=99999,
            serial_number="CASCADE_SN",
            name="Cascade Inverter",
        )
        reading = EnergyReading(
            site_id=99999,
            reading_date=date(2024, 1, 1),
            time_unit="DAY",
            energy_wh=1000,
        )
        test_session.add_all([equipment, reading])
        test_session.commit()

        # Delete site
        test_session.delete(site)
        test_session.commit()

        # Verify related records are deleted
        assert test_session.query(Equipment).filter_by(serial_number="CASCADE_SN").first() is None
        assert test_session.query(EnergyReading).filter_by(site_id=99999).first() is None
