"""Tests for repository classes."""

from datetime import datetime, date

import pytest

from seh.db.models import Site, Equipment, EnergyReading, PowerReading
from seh.db.repositories import (
    SiteRepository,
    EquipmentRepository,
    EnergyRepository,
    PowerRepository,
    EnvironmentalBenefitsRepository,
    InventoryRepository,
    SyncMetadataRepository,
)


class TestSiteRepository:
    """Test SiteRepository."""

    def test_get_all_empty(self, test_session):
        """Test get_all returns empty list when no sites."""
        repo = SiteRepository(test_session)
        assert repo.get_all() == []

    def test_get_all_with_sites(self, test_session, sample_site_data):
        """Test get_all returns all sites."""
        repo = SiteRepository(test_session)

        # Create sites
        site1 = Site(**sample_site_data)
        site2 = Site(id=12346, name="Site 2")
        test_session.add_all([site1, site2])
        test_session.commit()

        sites = repo.get_all()
        assert len(sites) == 2

    def test_get_by_id(self, test_session, sample_site_data):
        """Test get_by_id returns correct site."""
        repo = SiteRepository(test_session)

        site = Site(**sample_site_data)
        test_session.add(site)
        test_session.commit()

        retrieved = repo.get_by_id(12345)
        assert retrieved is not None
        assert retrieved.name == "Test Site"

    def test_get_by_id_not_found(self, test_session):
        """Test get_by_id returns None for non-existent site."""
        repo = SiteRepository(test_session)
        assert repo.get_by_id(99999) is None

    def test_upsert_create(self, test_session, sample_site_data):
        """Test upsert creates new site."""
        repo = SiteRepository(test_session)

        site = repo.upsert(sample_site_data)
        assert site.id == 12345
        assert site.name == "Test Site"

    def test_upsert_update(self, test_session, sample_site_data):
        """Test upsert updates existing site."""
        repo = SiteRepository(test_session)

        # Create site
        repo.upsert(sample_site_data)

        # Update site
        updated_data = {**sample_site_data, "name": "Updated Name"}
        site = repo.upsert(updated_data)

        assert site.name == "Updated Name"

        # Verify only one site exists
        assert len(repo.get_all()) == 1


class TestEquipmentRepository:
    """Test EquipmentRepository."""

    def test_get_by_site_id(self, test_session, sample_site_data, sample_equipment_data):
        """Test get_by_site_id returns equipment for site."""
        # Create site first
        site = Site(**sample_site_data)
        test_session.add(site)
        test_session.commit()

        repo = EquipmentRepository(test_session)
        repo.upsert(sample_equipment_data)

        equipment = repo.get_by_site_id(12345)
        assert len(equipment) == 1
        assert equipment[0].serial_number == "SN123456"

    def test_get_by_serial(self, test_session, sample_site_data, sample_equipment_data):
        """Test get_by_serial returns correct equipment."""
        site = Site(**sample_site_data)
        test_session.add(site)
        test_session.commit()

        repo = EquipmentRepository(test_session)
        repo.upsert(sample_equipment_data)

        equipment = repo.get_by_serial("SN123456")
        assert equipment is not None
        assert equipment.name == "Inverter 1"

    def test_upsert_creates_equipment(self, test_session, sample_site_data, sample_equipment_data):
        """Test upsert creates new equipment."""
        site = Site(**sample_site_data)
        test_session.add(site)
        test_session.commit()

        repo = EquipmentRepository(test_session)
        equipment = repo.upsert(sample_equipment_data)

        assert equipment.serial_number == "SN123456"
        assert equipment.manufacturer == "SolarEdge"


class TestEnergyRepository:
    """Test EnergyRepository."""

    def test_get_by_site_id(self, test_session, sample_site_data, sample_energy_data):
        """Test get_by_site_id returns energy readings."""
        site = Site(**sample_site_data)
        test_session.add(site)
        test_session.commit()

        repo = EnergyRepository(test_session)
        repo.upsert_batch([sample_energy_data])

        readings = repo.get_by_site_id(12345)
        assert len(readings) == 1
        assert readings[0].energy_wh == 25000.0

    def test_get_by_date_range(self, test_session, sample_site_data):
        """Test get_by_site_id with date range filters correctly."""
        site = Site(**sample_site_data)
        test_session.add(site)
        test_session.commit()

        repo = EnergyRepository(test_session)

        # Create multiple readings
        readings_data = [
            {
                "site_id": 12345,
                "reading_date": date(2024, 1, day),
                "time_unit": "DAY",
                "energy_wh": 1000.0 * day,
            }
            for day in range(1, 11)
        ]
        repo.upsert_batch(readings_data)

        # Query range using get_by_site_id with filters
        readings = repo.get_by_site_id(
            12345,
            start_date=date(2024, 1, 3),
            end_date=date(2024, 1, 7),
        )
        assert len(readings) == 5

    def test_upsert_batch_idempotent(self, test_session, sample_site_data, sample_energy_data):
        """Test upsert_batch is idempotent."""
        site = Site(**sample_site_data)
        test_session.add(site)
        test_session.commit()

        repo = EnergyRepository(test_session)

        # Insert twice
        repo.upsert_batch([sample_energy_data])
        repo.upsert_batch([sample_energy_data])

        # Should only have one record
        readings = repo.get_by_site_id(12345)
        assert len(readings) == 1


class TestPowerRepository:
    """Test PowerRepository."""

    def test_get_by_site_id(self, test_session, sample_site_data, sample_power_data):
        """Test get_by_site_id returns power readings."""
        site = Site(**sample_site_data)
        test_session.add(site)
        test_session.commit()

        repo = PowerRepository(test_session)
        repo.upsert_batch([sample_power_data])

        readings = repo.get_by_site_id(12345)
        assert len(readings) == 1
        assert readings[0].power_watts == 5000.0

    def test_upsert_batch_idempotent(self, test_session, sample_site_data, sample_power_data):
        """Test upsert_batch is idempotent."""
        site = Site(**sample_site_data)
        test_session.add(site)
        test_session.commit()

        repo = PowerRepository(test_session)

        # Insert twice
        repo.upsert_batch([sample_power_data])
        repo.upsert_batch([sample_power_data])

        # Should only have one record
        readings = repo.get_by_site_id(12345)
        assert len(readings) == 1


class TestSyncMetadataRepository:
    """Test SyncMetadataRepository."""

    def test_get_by_site_and_type(self, test_session, sample_site_data):
        """Test get_by_site_and_type returns correct metadata."""
        site = Site(**sample_site_data)
        test_session.add(site)
        test_session.commit()

        repo = SyncMetadataRepository(test_session)
        repo.upsert(
            site_id=12345,
            data_type="energy",
            last_sync_time=datetime(2024, 1, 15, 12, 0, 0),
            records_synced=100,
        )

        metadata = repo.get_by_site_and_type(12345, "energy")
        assert metadata is not None
        assert metadata.records_synced == 100

    def test_upsert_updates_existing(self, test_session, sample_site_data):
        """Test upsert updates existing metadata."""
        site = Site(**sample_site_data)
        test_session.add(site)
        test_session.commit()

        repo = SyncMetadataRepository(test_session)

        # Create
        repo.upsert(
            site_id=12345,
            data_type="energy",
            last_sync_time=datetime(2024, 1, 15, 12, 0, 0),
            records_synced=100,
        )

        # Update
        repo.upsert(
            site_id=12345,
            data_type="energy",
            last_sync_time=datetime(2024, 1, 16, 12, 0, 0),
            records_synced=200,
        )

        metadata = repo.get_by_site_and_type(12345, "energy")
        assert metadata.records_synced == 200
