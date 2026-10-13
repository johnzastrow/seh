"""Tests for sync strategies on SolarEdge API V2 and the orchestrator's V2 behaviour.

Fixtures mirror response shapes observed from the live V2 API on 2026-10-12, with
synthetic values.
"""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest
from sqlalchemy import select

from seh.db.models import (
    Alert,
    EnergyReading,
    EnvironmentalBenefits,
    Equipment,
    InventoryItem,
    PowerFlow,
    PowerReading,
    Site,
    SyncMetadata,
)
from seh.sync.orchestrator import SyncOrchestrator
from seh.sync.strategies.alert import AlertSyncStrategy
from seh.sync.strategies.energy import EnergySyncStrategy
from seh.sync.strategies.environmental import EnvironmentalSyncStrategy
from seh.sync.strategies.equipment import EquipmentSyncStrategy
from seh.sync.strategies.inventory import InventorySyncStrategy
from seh.sync.strategies.power import PowerSyncStrategy, _activity
from seh.sync.strategies.site import SiteSyncStrategy
from seh.sync.v2_fields import calendar_date, site_local, title_case, utc_to_site_local
from seh.utils.exceptions import APIError, AuthenticationError

SITE_ID = 12345

V2_SITE = {
    "siteId": SITE_ID,
    "name": "Test Site",
    "accountId": 6065,
    "peakPower": 12.76,
    "installationDate": "2026-01-27T00:00:00Z",
    "lastUpdateTime": "2026-10-12T22:03:51.658Z",
    "location": {
        "address": "1 Solar Way",
        "address2": None,
        "city": "Sunnyvale",
        "state": "Maine",
        "zip": "04000",
        "country": "United States",
        "timezone": "America/New_York",
    },
    "activationStatus": "ACTIVE",
    "note": "",
}

V2_DEVICES = [
    {
        "type": "INVERTER",
        "serialNumber": "INV-1",
        "manufacturer": "SolarEdge",
        "model": None,
        "partNumber": "USE11400H",
        "firmwareVersion": "4.24.16",
        "nameplate": 11400.0,
        "connectedTo": None,
        "name": "Inverter 1",
        "communicationType": "ETHERNET",
        "connectedOptimizers": 29,
    },
    {
        "type": "METER",
        "serialNumber": "MTR-1",
        "manufacturer": "SolarEdge",
        "model": "SE-RGMTR",
        "partNumber": None,
        "firmwareVersion": "3046",
        "nameplate": None,
        "connectedTo": "INV-1",
        "name": "Export Meter",
    },
    {
        "type": "METER",
        "serialNumber": None,
        "model": None,
        "firmwareVersion": None,
        "connectedTo": "INV-1",
        "name": "Self Consumption",
    },
    {
        "type": "OPTIMIZER",
        "serialNumber": "OPT-1",
        "manufacturer": "SolarEdge",
        "model": "S440",
        "partNumber": "S440",
        "connectedTo": "INV-1",
        "name": "Panel 1.1.1",
    },
]


def has_tz_database() -> bool:
    try:
        ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError:
        return False
    return True


@pytest.fixture
def site(test_session) -> Site:
    row = Site(id=SITE_ID, name="Old Name")
    test_session.add(row)
    test_session.commit()
    return row


def client_with(**methods) -> AsyncMock:
    client = AsyncMock()
    for name, value in methods.items():
        mock = getattr(client, name)
        if isinstance(value, Exception):
            mock.side_effect = value
        else:
            mock.return_value = value
    return client


def metadata(session, data_type: str) -> SyncMetadata:
    return session.scalars(select(SyncMetadata).where(SyncMetadata.data_type == data_type)).one()


class TestV2Fields:
    def test_site_local_drops_offset_keeping_wall_time(self):
        assert site_local("2026-10-12T06:15:00-04:00") == datetime(2026, 10, 12, 6, 15)

    @pytest.mark.parametrize("value", [None, "", "not a time", 5])
    def test_site_local_rejects_bad_values(self, value):
        assert site_local(value) is None

    @pytest.mark.skipif(not has_tz_database(), reason="needs the IANA tz database")
    def test_utc_to_site_local_uses_site_timezone(self):
        assert utc_to_site_local("2026-10-12T22:03:51Z", "America/New_York") == datetime(
            2026, 10, 12, 18, 3, 51
        )

    def test_utc_to_site_local_falls_back_to_machine_timezone(self):
        expected = datetime(2026, 10, 12, 22, 0, tzinfo=UTC).astimezone()
        assert utc_to_site_local("2026-10-12T22:00:00Z", "Not/AZone") == expected.replace(
            tzinfo=None
        )

    def test_calendar_date_does_not_shift_across_timezones(self):
        assert calendar_date("2026-01-27T00:00:00Z") == datetime(2026, 1, 27)

    def test_title_case(self):
        assert title_case("ACTIVE") == "Active"
        assert title_case("PENDING_COMMUNICATION") == "Pending Communication"
        assert title_case(None) is None


class TestSiteSync:
    async def test_writes_v2_fields(self, test_session, test_settings, site):
        client = client_with(get_site=V2_SITE)

        assert await SiteSyncStrategy(client, test_session, test_settings).sync(SITE_ID) == 1

        test_session.expire_all()
        row = test_session.get(Site, SITE_ID)
        assert row.name == "Test Site"
        assert row.account_id == 6065
        assert row.status == "Active"
        assert row.peak_power == 12.76
        assert row.timezone == "America/New_York"
        assert row.zip_code == "04000"
        assert row.installation_date == datetime(2026, 1, 27)
        assert row.last_update_time is not None
        client.get_site.assert_awaited_once_with(SITE_ID)

    async def test_keeps_v1_only_columns(self, test_session, test_settings, site):
        site.currency = "USD"
        site.primary_module_model = "SPR-400"
        site.site_type = "Optimizers & Inverters"
        test_session.commit()

        await SiteSyncStrategy(client_with(get_site=V2_SITE), test_session, test_settings).sync(
            SITE_ID
        )

        test_session.expire_all()
        row = test_session.get(Site, SITE_ID)
        assert (row.currency, row.primary_module_model, row.site_type) == (
            "USD",
            "SPR-400",
            "Optimizers & Inverters",
        )

    async def test_no_data_records_error(self, test_session, test_settings):
        strategy = SiteSyncStrategy(client_with(get_site={}), test_session, test_settings)
        assert await strategy.sync(SITE_ID) == 0


class TestEquipmentSync:
    async def test_stores_inverters_only(self, test_session, test_settings, site):
        client = client_with(get_devices=V2_DEVICES)

        assert await EquipmentSyncStrategy(client, test_session, test_settings).sync(SITE_ID) == 1

        row = test_session.scalars(select(Equipment)).one()
        assert row.serial_number == "INV-1"
        assert row.model == "USE11400H"  # from partNumber
        assert row.equipment_type == "Inverter"
        assert row.communication_method == "ETHERNET"
        assert row.cpu_version == "4.24.16"
        assert row.connected_optimizers == 29

    async def test_keeps_v1_dsp_versions(self, test_session, test_settings, site):
        test_session.add(
            Equipment(site_id=SITE_ID, serial_number="INV-1", name="Inverter 1", dsp1_version="1.0")
        )
        test_session.commit()

        await EquipmentSyncStrategy(
            client_with(get_devices=V2_DEVICES), test_session, test_settings
        ).sync(SITE_ID)

        test_session.expire_all()
        assert test_session.scalars(select(Equipment)).one().dsp1_version == "1.0"

    async def test_skips_inverter_without_serial(self, test_session, test_settings, site):
        devices = [{"type": "INVERTER", "name": "No Serial"}]
        strategy = EquipmentSyncStrategy(
            client_with(get_devices=devices), test_session, test_settings
        )
        assert await strategy.sync(SITE_ID) == 0


class TestInventorySync:
    async def test_stores_all_device_types(self, test_session, test_settings, site):
        client = client_with(get_devices=V2_DEVICES)

        assert await InventorySyncStrategy(client, test_session, test_settings).sync(SITE_ID) == 4

        rows = {r.name: r for r in test_session.scalars(select(InventoryItem))}
        assert rows["Inverter 1"].category == "inverters"
        assert rows["Inverter 1"].cpu_version == "4.24.16"
        assert rows["Inverter 1"].max_power == 11400.0
        assert rows["Export Meter"].category == "meters"
        assert rows["Export Meter"].firmware_version == "3046"
        assert rows["Export Meter"].connected_to == "INV-1"
        assert rows["Self Consumption"].serial_number == ""
        assert rows["Panel 1.1.1"].category == "optimizers"

    async def test_updates_existing_v1_rows_in_place(self, test_session, test_settings, site):
        test_session.add(
            InventoryItem(
                site_id=SITE_ID, name="Export Meter", serial_number="MTR-1", category="meters"
            )
        )
        test_session.commit()

        await InventorySyncStrategy(
            client_with(get_devices=V2_DEVICES), test_session, test_settings
        ).sync(SITE_ID)

        meters = test_session.scalars(
            select(InventoryItem).where(InventoryItem.name == "Export Meter")
        ).all()
        assert len(meters) == 1

    async def test_forbidden_is_skipped(self, test_session, test_settings, site):
        client = client_with(get_devices=APIError("Authorization Failed", status_code=403))

        assert await InventorySyncStrategy(client, test_session, test_settings).sync(SITE_ID) == 0
        assert metadata(test_session, "inventory").status == "skipped"


class TestEnvironmentalSync:
    async def test_stores_co2_and_keeps_v1_fields(self, test_session, test_settings, site):
        test_session.add(EnvironmentalBenefits(site_id=SITE_ID, trees_planted=12.0))
        test_session.commit()
        client = client_with(
            get_environmental_benefits={
                "co2Emissions": 8400.5,
                "evMiles": 35391.5,
                "unit": "METRIC",
            }
        )

        assert (
            await EnvironmentalSyncStrategy(client, test_session, test_settings).sync(SITE_ID) == 1
        )

        test_session.expire_all()
        row = test_session.scalars(select(EnvironmentalBenefits)).one()
        assert row.co2_saved == 8400.5
        assert row.co2_units == "KG"
        assert row.trees_planted == 12.0

    async def test_bad_request_is_skipped(self, test_session, test_settings, site):
        client = client_with(get_environmental_benefits=APIError("Bad", status_code=400))
        assert (
            await EnvironmentalSyncStrategy(client, test_session, test_settings).sync(SITE_ID) == 0
        )


class TestAlertSync:
    async def test_stores_v2_alerts(self, test_session, test_settings, site):
        alerts = [
            {
                "alertId": 77,
                "type": "INVERTER_FAULT",
                "category": "Inverter",
                "impact": 4,
                "status": "OPEN",
                "openedAt": "2026-10-10T09:30:00-04:00",
                "component": {"serialNumber": "INV-1", "name": "Inverter 1"},
            },
            {"alertId": "not-a-number"},
        ]
        client = client_with(get_alerts=alerts)

        assert await AlertSyncStrategy(client, test_session, test_settings).sync(SITE_ID) == 1

        row = test_session.scalars(select(Alert)).one()
        assert row.alert_id == 77
        assert row.severity == "4"
        assert row.alert_type == "INVERTER_FAULT"
        assert row.name == "Inverter 1"
        assert row.serial_number == "INV-1"
        assert row.alert_timestamp == datetime(2026, 10, 10, 9, 30)
        assert metadata(test_session, "alert").last_data_timestamp == datetime(2026, 10, 10, 9, 30)

    async def test_no_alerts(self, test_session, test_settings, site):
        client = client_with(get_alerts=[])
        assert await AlertSyncStrategy(client, test_session, test_settings).sync(SITE_ID) == 0

    async def test_forbidden_is_skipped(self, test_session, test_settings, site):
        client = client_with(get_alerts=APIError("Forbidden", status_code=403))
        assert await AlertSyncStrategy(client, test_session, test_settings).sync(SITE_ID) == 0
        assert metadata(test_session, "alert").status == "skipped"

    async def test_server_error_is_raised(self, test_session, test_settings, site):
        client = client_with(get_alerts=APIError("Boom", status_code=500))
        with pytest.raises(APIError):
            await AlertSyncStrategy(client, test_session, test_settings).sync(SITE_ID)
        assert metadata(test_session, "alert").status == "error"


class TestOrchestrator:
    def settings_running(self, test_settings, *types: str):
        test_settings.skip_data_types = ",".join(
            sorted(test_settings.VALID_DATA_TYPES - set(types))
        )
        return test_settings

    async def test_sync_all_uses_configured_site_ids(self, test_engine, test_settings):
        settings = self.settings_running(test_settings, "site")
        client = client_with(get_site={**V2_SITE, "siteId": 12345})

        summary = await SyncOrchestrator(client, test_engine, settings).sync_all()

        client.get_sites.assert_not_called()  # no credit spent listing sites
        assert [r.site_id for r in summary.results] == [12345]
        assert summary.results[0].site_name == "Test Site"
        assert summary.results[0].success

    async def test_authentication_error_stops_sync_in_lenient_mode(
        self, test_engine, test_settings
    ):
        settings = self.settings_running(test_settings, "site", "environmental")
        settings.error_handling = "lenient"
        client = client_with(
            get_site=V2_SITE,
            get_environmental_benefits=AuthenticationError("Run 'seh auth login'"),
        )

        with pytest.raises(AuthenticationError):
            await SyncOrchestrator(client, test_engine, settings).sync_site(SITE_ID)

    async def test_ordinary_error_is_recorded_and_sync_continues(self, test_engine, test_settings):
        settings = self.settings_running(test_settings, "site", "environmental", "alert")
        client = client_with(
            get_site=V2_SITE,
            get_environmental_benefits=APIError("Server error", status_code=500),
            get_alerts=[],
        )

        result = await SyncOrchestrator(client, test_engine, settings).sync_site(SITE_ID)

        assert not result.success
        assert "environmental" in result.errors
        assert result.records_synced["alert"] == 0
        client.get_alerts.assert_awaited_once()


# --- power, power flow, energy (story 6b) ------------------------------------------------


def power_series(*points: tuple[str, float | None]) -> list[dict]:
    return [{"timestamp": t, "value": v} for t, v in points]


V2_POWER_FLOW = {
    "updatedAt": "2026-10-12T18:01:51.308-04:00",
    "refreshRate": 3,
    "unit": "kW",
    "pv": {"active": False, "power": 0.0},
    "load": {"active": True, "power": 1.79},
    "storage": {"active": False, "power": None, "status": None, "chargeLevel": None},
    "grid": {"active": True, "power": 1.79, "status": "IMPORT"},
}


class TestPowerSync:
    async def test_stores_readings_in_site_local_time(self, test_session, test_settings, site):
        client = client_with(
            get_power=power_series(
                ("2026-10-12T06:00:00-04:00", 0.0),
                ("2026-10-12T12:15:00-04:00", 10024.0),
                ("2026-10-12T12:30:00-04:00", None),  # interval without data yet
            ),
            get_power_flow={},
        )

        count = await PowerSyncStrategy(client, test_session, test_settings).sync(
            SITE_ID, full=True
        )

        assert count == 2
        rows = test_session.scalars(select(PowerReading).order_by(PowerReading.timestamp)).all()
        assert [(r.timestamp, r.power_watts) for r in rows] == [
            (datetime(2026, 10, 12, 6, 0), 0.0),
            (datetime(2026, 10, 12, 12, 15), 10024.0),
        ]
        assert metadata(test_session, "power").last_data_timestamp == datetime(2026, 10, 12, 12, 15)

    async def test_full_sync_requests_lookback_at_configured_resolution(
        self, test_session, test_settings, site
    ):
        client = client_with(get_power=[], get_power_flow={})
        await PowerSyncStrategy(client, test_session, test_settings).sync(SITE_ID, full=True)

        _site, start, end = client.get_power.await_args.args
        assert client.get_power.await_args.kwargs == {"resolution": "QUARTER_HOUR"}
        assert timedelta(days=6, hours=23) < end - start <= timedelta(days=7, seconds=1)

    async def test_incremental_sync_resumes_from_last_reading(
        self, test_session, test_settings, site
    ):
        client = client_with(
            get_power=power_series(("2026-10-12T12:15:00-04:00", 1.0)), get_power_flow={}
        )
        strategy = PowerSyncStrategy(client, test_session, test_settings)
        await strategy.sync(SITE_ID, full=True)

        await strategy.sync(SITE_ID)

        _site, start, _end = client.get_power.await_args.args
        assert start == datetime(2026, 10, 12, 12, 0)  # last reading minus 15 min overlap

    async def test_stores_power_flow_snapshot(self, test_session, test_settings, site):
        client = client_with(get_power=[], get_power_flow=V2_POWER_FLOW)

        await PowerSyncStrategy(client, test_session, test_settings).sync(SITE_ID, full=True)

        flow = test_session.scalars(select(PowerFlow)).one()
        assert flow.timestamp == datetime(2026, 10, 12, 18, 1, 51, 308000)
        assert flow.unit == "kW"
        assert (flow.pv_status, flow.pv_power) == ("Idle", 0.0)
        assert (flow.load_status, flow.load_power) == ("Active", 1.79)
        assert (flow.grid_status, flow.grid_power) == ("Active", 1.79)
        assert flow.storage_status is None

    @pytest.mark.parametrize(
        ("component", "expected"),
        [
            ({"active": True, "power": 2.5}, "Active"),
            ({"active": True, "power": 0.0}, "Idle"),  # PV at night: V2 still says active
            ({"active": False, "power": None}, "Idle"),
            ({}, None),
        ],
    )
    def test_status_matches_v1_meaning(self, component, expected):
        assert _activity(component) == expected

    async def test_power_flow_failure_does_not_fail_power_sync(
        self, test_session, test_settings, site
    ):
        client = client_with(
            get_power=power_series(("2026-10-12T12:15:00-04:00", 5.0)),
            get_power_flow=APIError("Authorization Failed", status_code=403),
        )
        assert await PowerSyncStrategy(client, test_session, test_settings).sync(SITE_ID) == 1


class TestEnergySync:
    async def test_stores_daily_energy(self, test_session, test_settings, site):
        client = client_with(
            get_energy=power_series(
                ("2026-10-11T00:00:00-04:00", 18292.0),
                ("2026-10-12T00:00:00-04:00", 36939.0),
                ("2026-10-13T00:00:00-04:00", None),
            )
        )

        count = await EnergySyncStrategy(client, test_session, test_settings).sync(
            SITE_ID, full=True
        )

        assert count == 2
        rows = test_session.scalars(
            select(EnergyReading).order_by(EnergyReading.reading_date)
        ).all()
        assert [(r.reading_date, r.time_unit, r.energy_wh) for r in rows] == [
            (date(2026, 10, 11), "DAY", 18292.0),
            (date(2026, 10, 12), "DAY", 36939.0),
        ]
        assert metadata(test_session, "energy").last_data_timestamp == datetime(2026, 10, 12)

    async def test_requests_through_end_of_today(self, test_session, test_settings, site):
        client = client_with(get_energy=[])
        await EnergySyncStrategy(client, test_session, test_settings).sync(SITE_ID, full=True)

        _site, start, end = client.get_energy.await_args.args
        assert end == date.today() + timedelta(days=1)
        assert start == date.today() - timedelta(days=test_settings.energy_lookback_days)
        assert client.get_energy.await_args.kwargs == {"resolution": "DAY"}


class TestBaseStrategy:
    def test_start_time_without_history_uses_lookback(self, test_session, test_settings, site):
        strategy = EnergySyncStrategy(AsyncMock(), test_session, test_settings)
        assert strategy.get_last_sync(SITE_ID) is None
        days_ago = (datetime.now() - strategy.get_start_time(SITE_ID, lookback_days=7)).days
        assert 6 <= days_ago <= 7

    async def test_error_keeps_high_water_mark(self, test_session, test_settings, site):
        client = client_with(
            get_power=power_series(("2026-10-12T12:15:00-04:00", 1.0)), get_power_flow={}
        )
        strategy = PowerSyncStrategy(client, test_session, test_settings)
        await strategy.sync(SITE_ID, full=True)

        client.get_power.side_effect = APIError("Scheduled window", status_code=503)
        with pytest.raises(APIError):
            await strategy.sync(SITE_ID)

        meta = metadata(test_session, "power")
        assert meta.status == "error"
        assert meta.last_data_timestamp == datetime(2026, 10, 12, 12, 15)
