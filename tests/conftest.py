"""Shared test fixtures."""

import os
from datetime import datetime, date
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from seh.config.settings import Settings
from seh.db.base import Base
from seh.db.engine import get_session


@pytest.fixture
def test_settings() -> Settings:
    """Create test settings with in-memory SQLite."""
    # Set environment variables for testing
    os.environ["SEH_API_KEY"] = "test_api_key_12345"
    os.environ["SEH_DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["SEH_LOG_LEVEL"] = "DEBUG"

    return Settings(
        api_key="test_api_key_12345",
        database_url="sqlite:///:memory:",
        log_level="DEBUG",
    )


@pytest.fixture
def test_engine(test_settings):
    """Create test database engine with tables."""
    engine = create_engine(test_settings.database_url)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def test_session(test_engine) -> Session:
    """Create test database session."""
    with get_session(test_engine) as session:
        yield session


@pytest.fixture
def mock_api_client():
    """Create mock API client."""
    client = AsyncMock()

    # Mock site data
    client.get_sites.return_value = [
        {
            "id": 12345,
            "name": "Test Site",
            "status": "Active",
            "peakPower": 10.5,
            "lastUpdateTime": "2024-01-15T12:00:00Z",
        }
    ]

    client.get_site_details.return_value = {
        "name": "Test Site",
        "accountId": 1001,
        "status": "Active",
        "peakPower": 10.5,
        "currency": "USD",
        "location": {
            "country": "United States",
            "state": "California",
            "city": "San Francisco",
            "address": "123 Solar St",
            "timeZone": "America/Los_Angeles",
        },
        "primaryModule": {
            "manufacturerName": "SunPower",
            "modelName": "SPR-400",
            "maximumPower": 400,
        },
    }

    # Mock equipment data
    client.get_equipment.return_value = [
        {
            "name": "Inverter 1",
            "manufacturer": "SolarEdge",
            "model": "SE10000H",
            "serialNumber": "SN123456",
            "kWpDC": 10.0,
        }
    ]

    # Mock energy data
    client.get_energy.return_value = [
        {"date": "2024-01-01", "value": 25000},
        {"date": "2024-01-02", "value": 28000},
    ]

    # Mock power data
    client.get_power.return_value = [
        {"date": "2024-01-15 12:00:00", "value": 5000},
        {"date": "2024-01-15 12:15:00", "value": 5200},
    ]

    # Mock power flow
    client.get_power_flow.return_value = {
        "unit": "kW",
        "connections": [],
        "GRID": {"status": "Active", "currentPower": 2.5},
        "LOAD": {"status": "Active", "currentPower": 3.0},
        "PV": {"status": "Active", "currentPower": 5.5},
    }

    # Mock storage data
    client.get_storage_data.return_value = {
        "batteryCount": 0,
        "batteries": [],
    }

    # Mock environmental benefits
    client.get_environmental_benefits.return_value = {
        "treesPlanted": 10.5,
        "lightBulbs": 1000,
        "gasEmissionSaved": {
            "co2": 500.0,
            "so2": 1.5,
            "nox": 0.8,
            "units": "KG",
        },
    }

    # Mock inventory
    client.get_inventory.return_value = {
        "inverters": [
            {
                "name": "Inverter 1",
                "manufacturer": "SolarEdge",
                "model": "SE10000H",
                "SN": "SN123456",
            }
        ],
        "meters": [],
    }

    # Mock inverter telemetry
    client.get_inverter_data.return_value = [
        {
            "date": "2024-01-15 12:00:00",
            "totalActivePower": 5000,
            "totalEnergy": 100000,
            "temperature": 45.5,
            "inverterMode": "MPPT",
            "L1Data": {
                "acCurrent": 21.5,
                "acVoltage": 240.0,
                "acFrequency": 60.0,
            },
        }
    ]

    # Mock alerts (forbidden)
    from seh.utils.exceptions import APIError
    client.get_alerts.side_effect = APIError("Forbidden", status_code=403)

    # Mock meters (not available)
    client.get_meters.side_effect = APIError("Bad Request", status_code=400)

    return client


@pytest.fixture
def sample_site_data():
    """Sample site data for testing."""
    return {
        "id": 12345,
        "name": "Test Site",
        "account_id": 1001,
        "status": "Active",
        "peak_power": 10.5,
        "country": "United States",
        "state": "California",
        "city": "San Francisco",
        "timezone": "America/Los_Angeles",
    }


@pytest.fixture
def sample_equipment_data():
    """Sample equipment data for testing."""
    return {
        "site_id": 12345,
        "serial_number": "SN123456",
        "name": "Inverter 1",
        "manufacturer": "SolarEdge",
        "model": "SE10000H",
        "equipment_type": "Inverter",
    }


@pytest.fixture
def sample_energy_data():
    """Sample energy reading data for testing."""
    return {
        "site_id": 12345,
        "reading_date": date(2024, 1, 15),
        "time_unit": "DAY",
        "energy_wh": 25000.0,
    }


@pytest.fixture
def sample_power_data():
    """Sample power reading data for testing."""
    return {
        "site_id": 12345,
        "timestamp": datetime(2024, 1, 15, 12, 0, 0),
        "power_watts": 5000.0,
    }
