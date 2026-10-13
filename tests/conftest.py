"""Shared test fixtures."""

import os
from datetime import date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from seh.config.settings import Settings
from seh.db.base import Base
from seh.db.engine import get_session


@pytest.fixture(autouse=True)
def isolated_state_files(tmp_path, monkeypatch):
    """Keep tests away from the real token file and API credit ledger in ~/.config/seh."""
    monkeypatch.setenv("SEH_TOKEN_FILE", str(tmp_path / "state" / "tokens.json"))
    monkeypatch.setenv("SEH_USAGE_FILE", str(tmp_path / "state" / "usage.json"))


@pytest.fixture
def test_settings(tmp_path) -> Settings:
    """Create test settings with in-memory SQLite."""
    # Set environment variables for testing
    os.environ["SEH_OAUTH_CLIENT_ID"] = "test_client_id"
    os.environ["SEH_OAUTH_CLIENT_SECRET"] = "test_client_secret_12345"
    os.environ["SEH_DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["SEH_LOG_LEVEL"] = "DEBUG"

    return Settings(
        oauth_client_id="test_client_id",
        oauth_client_secret="test_client_secret_12345",
        site_ids="12345",
        token_file=str(tmp_path / "tokens.json"),
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
