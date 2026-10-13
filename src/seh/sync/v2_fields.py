"""Helpers for turning SolarEdge API V2 response fields into database values.

The database keeps the V1 conventions so existing rows, views, and downstream queries
stay valid:

- timestamps are naive and in the site's local wall-clock time;
- V2 series timestamps already carry the site's UTC offset ("2026-10-12T06:00:00-04:00"),
  so dropping the offset yields site-local time;
- a few V2 fields are instants in UTC ("...Z") and are converted to the site's timezone.

Strategies only write the columns V2 provides. Columns that only V1 supplied are left out
of upserts so their last V1 values are kept rather than overwritten with NULL.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from seh.api.client import parse_timestamp

# V2 device type -> seh_inventory.category (V1 category names, plus optimizers).
INVENTORY_CATEGORIES = {
    "INVERTER": "inverters",
    "METER": "meters",
    "BATTERY": "batteries",
    "OPTIMIZER": "optimizers",
    "GATEWAY": "gateways",
    "SENSOR": "sensors",
}


def site_local(value: object) -> datetime | None:
    """Series timestamp with offset -> naive site-local datetime; None if unparseable."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return parse_timestamp(value).replace(tzinfo=None)
    except ValueError:
        return None


def utc_to_site_local(value: object, timezone_name: str | None) -> datetime | None:
    """UTC instant ("...Z") -> naive datetime in the site's timezone.

    Falls back to this machine's local timezone if the site's zone is unknown (or the
    platform has no tz database, as on Windows without the tzdata package).
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        instant = parse_timestamp(value)
    except ValueError:
        return None
    try:
        zone = ZoneInfo(timezone_name) if timezone_name else None
    except (ZoneInfoNotFoundError, ValueError):
        zone = None
    return instant.astimezone(zone).replace(tzinfo=None)


def calendar_date(value: object) -> datetime | None:
    """Date-valued field ("2026-01-27T00:00:00Z") -> naive midnight of that calendar date.

    Converting it as an instant would shift it to the previous evening in US timezones.
    """
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d")
    except ValueError:
        return None


def title_case(value: object) -> str | None:
    """V2 enums are upper case ("ACTIVE"); V1 stored "Active"."""
    return value.replace("_", " ").title() if isinstance(value, str) and value else None


def model_name(device: dict[str, object]) -> str | None:
    """V2 inverters report the model as partNumber; other devices use model."""
    value = device.get("model") or device.get("partNumber")
    return value if isinstance(value, str) else None
