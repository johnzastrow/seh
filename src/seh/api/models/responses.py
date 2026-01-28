"""Pydantic models for SolarEdge API responses."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class Location(BaseModel):
    """Site location details."""

    country: str | None = None
    state: str | None = None
    city: str | None = None
    address: str | None = None
    address2: str | None = None
    zip: str | None = Field(default=None, alias="zip")
    timeZone: str | None = None


class PrimaryModule(BaseModel):
    """Primary solar module details."""

    manufacturerName: str | None = None
    modelName: str | None = None
    maximumPower: float | None = None


class PublicSettings(BaseModel):
    """Public settings for a site."""

    isPublic: bool | None = None
    name: str | None = None


class Site(BaseModel):
    """Site summary from sites list."""

    id: int
    name: str
    accountId: int | None = None
    status: str | None = None
    peakPower: float | None = None
    lastUpdateTime: datetime | None = None
    installationDate: date | None = None
    currency: str | None = None
    notes: str | None = None
    type: str | None = None
    location: Location | None = None
    primaryModule: PrimaryModule | None = None
    publicSettings: PublicSettings | None = None


class SiteDetails(BaseModel):
    """Detailed site information."""

    details: Site


class SitesResponse(BaseModel):
    """Response from /sites endpoint."""

    sites: dict


class Inverter(BaseModel):
    """Inverter details."""

    name: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    communicationMethod: str | None = None
    cpuVersion: str | None = None
    dsp1Version: str | None = None
    dsp2Version: str | None = None
    SN: str | None = None
    connectedOptimizers: int | None = None


class EquipmentData(BaseModel):
    """Equipment list response."""

    reporters: dict


class EnergyValue(BaseModel):
    """Single energy value."""

    date: str
    value: float | None = None


class EnergyData(BaseModel):
    """Energy data response."""

    energy: dict


class EnergyDetails(BaseModel):
    """Detailed energy data."""

    energyDetails: dict


class PowerValue(BaseModel):
    """Single power value."""

    date: str
    value: float | None = None


class PowerData(BaseModel):
    """Power data response."""

    power: dict


class PowerDetails(BaseModel):
    """Detailed power data."""

    powerDetails: dict


class Connection(BaseModel):
    """Power flow connection."""

    from_: str = Field(alias="from")
    to: str


class SiteCurrentPowerFlow(BaseModel):
    """Current power flow at a site."""

    updateRefreshRate: int | None = None
    unit: str | None = None
    connections: list[Connection] = []
    GRID: dict | None = None
    LOAD: dict | None = None
    PV: dict | None = None
    STORAGE: dict | None = None


class PowerFlowData(BaseModel):
    """Power flow response."""

    siteCurrentPowerFlow: SiteCurrentPowerFlow


class BatteryInfo(BaseModel):
    """Battery/storage unit info."""

    nameplate: float | None = None
    serialNumber: str | None = None
    modelNumber: str | None = None
    manufacturerName: str | None = None


class BatteryTelemetryValue(BaseModel):
    """Single battery telemetry value."""

    timeStamp: datetime
    power: float | None = None
    batteryState: str | None = None
    lifeTimeEnergyCharged: float | None = None
    lifeTimeEnergyDischarged: float | None = None
    batteryPercentageState: float | None = None
    fullPackEnergyAvailable: float | None = None
    internalTemp: float | None = None


class BatteryTelemetry(BaseModel):
    """Battery telemetry data."""

    serialNumber: str
    modelNumber: str | None = None
    manufacturerName: str | None = None
    nameplate: float | None = None
    telemetryCount: int | None = None
    telemetries: list[BatteryTelemetryValue] = []


class StorageData(BaseModel):
    """Storage data response."""

    storageData: dict


class MeterInfo(BaseModel):
    """Meter device info."""

    name: str
    manufacturer: str | None = None
    model: str | None = None
    type: str | None = None
    SN: str | None = None
    connectedTo: str | None = None
    form: str | None = None


class MeterValue(BaseModel):
    """Single meter reading value."""

    date: str
    type: str | None = None
    values: dict = {}


class MeterData(BaseModel):
    """Meter data from API."""

    meters: list[MeterInfo] = []


class MeterReading(BaseModel):
    """Meter reading data."""

    meterEnergyDetails: dict
