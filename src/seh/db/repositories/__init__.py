"""Repository classes for database operations."""

from seh.db.repositories.alert import AlertRepository
from seh.db.repositories.battery import BatteryRepository
from seh.db.repositories.energy import EnergyRepository
from seh.db.repositories.environmental import EnvironmentalBenefitsRepository
from seh.db.repositories.equipment import EquipmentRepository
from seh.db.repositories.inventory import InventoryRepository
from seh.db.repositories.inverter_telemetry import InverterTelemetryRepository
from seh.db.repositories.meter import MeterRepository
from seh.db.repositories.power import PowerRepository
from seh.db.repositories.site import SiteRepository
from seh.db.repositories.sync_metadata import SyncMetadataRepository

__all__ = [
    "AlertRepository",
    "BatteryRepository",
    "EnergyRepository",
    "EnvironmentalBenefitsRepository",
    "EquipmentRepository",
    "InventoryRepository",
    "InverterTelemetryRepository",
    "MeterRepository",
    "PowerRepository",
    "SiteRepository",
    "SyncMetadataRepository",
]
