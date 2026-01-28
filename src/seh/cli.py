"""Command-line interface for SolarEdge Harvest."""

import asyncio
import csv
import json
import os
import sys
from datetime import datetime, date
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


def get_event_loop() -> asyncio.AbstractEventLoop:
    """Get or create an event loop."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.new_event_loop()


def run_async(coro):
    """Run an async coroutine."""
    loop = get_event_loop()
    return loop.run_until_complete(coro)


def load_settings(config_path: str | None = None):
    """Load and validate settings.

    Args:
        config_path: Optional path to .env file.

    Returns:
        Validated Settings object.
    """
    if config_path:
        os.environ["SEH_ENV_FILE"] = config_path

    # Clear cached settings to pick up new env file
    from seh.config.settings import get_settings
    get_settings.cache_clear()

    try:
        from seh.config.logging import configure_logging
        from seh.config.settings import get_settings

        settings = get_settings()
        configure_logging(settings)
        return settings
    except Exception as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        console.print("\n[yellow]Hint:[/yellow] Create a .env file with SEH_API_KEY=your_key")
        console.print("See .env.example for all available options.")
        raise SystemExit(1) from None


@click.group()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    help="Path to .env configuration file",
)
@click.pass_context
def cli(ctx: click.Context, config: str | None) -> None:
    """SolarEdge Harvest - Download SolarEdge data to a database."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


@cli.command()
@click.pass_context
def init_db(ctx: click.Context) -> None:
    """Initialize the database schema and views."""
    from seh.config.logging import get_logger
    from seh.db.engine import create_engine, create_tables
    from seh.db.views import create_views

    settings = load_settings(ctx.obj.get("config_path"))
    logger = get_logger(__name__)

    console.print("[bold]Initializing database...[/bold]")

    try:
        engine = create_engine(settings)
        create_tables(engine)
        console.print("  Tables created")

        create_views(engine)
        console.print("  Views created")

        console.print("[green]Database initialized successfully![/green]")
        logger.info("Database initialized", url=settings.database_url)
    except Exception as e:
        console.print(f"[red]Failed to initialize database:[/red] {e}")
        logger.error("Database initialization failed", error=str(e))
        raise SystemExit(1) from None


@cli.command()
@click.pass_context
def check_api(ctx: click.Context) -> None:
    """Check API connectivity and list available sites."""
    from seh.api.client import SolarEdgeClient
    from seh.config.logging import get_logger

    settings = load_settings(ctx.obj.get("config_path"))
    logger = get_logger(__name__)

    console.print("[bold]Checking SolarEdge API connection...[/bold]")

    async def _check():
        async with SolarEdgeClient(settings) as client:
            sites = await client.get_sites()
            return sites

    try:
        sites = run_async(_check())

        if not sites:
            console.print("[yellow]No sites found for this API key.[/yellow]")
            return

        table = Table(title="Available Sites")
        table.add_column("ID", style="cyan")
        table.add_column("Name", style="green")
        table.add_column("Status")
        table.add_column("Peak Power (kW)")
        table.add_column("Last Update")

        for site in sites:
            peak_power = site.get("peakPower")
            peak_str = f"{peak_power:.2f}" if peak_power else "-"

            last_update = site.get("lastUpdateTime")
            if last_update:
                try:
                    dt = datetime.fromisoformat(last_update.replace("Z", "+00:00"))
                    last_str = dt.strftime("%Y-%m-%d %H:%M")
                except (ValueError, AttributeError):
                    last_str = last_update
            else:
                last_str = "-"

            table.add_row(
                str(site.get("id")),
                site.get("name", "Unknown"),
                site.get("status", "-"),
                peak_str,
                last_str,
            )

        console.print(table)
        console.print(f"\n[green]Found {len(sites)} site(s)[/green]")
        logger.info("API check successful", sites=len(sites))

    except Exception as e:
        console.print(f"[red]API check failed:[/red] {e}")
        logger.error("API check failed", error=str(e))
        raise SystemExit(1) from None


@cli.command()
@click.option("--full", is_flag=True, help="Perform full sync (ignore last sync time)")
@click.option("--site", "-s", "site_id", type=int, help="Sync specific site only")
@click.pass_context
def sync(ctx: click.Context, full: bool, site_id: int | None) -> None:
    """Synchronize data from SolarEdge to the database."""
    from seh.api.client import SolarEdgeClient
    from seh.config.logging import get_logger
    from seh.db.engine import create_engine, create_tables
    from seh.sync.orchestrator import SyncOrchestrator

    settings = load_settings(ctx.obj.get("config_path"))
    logger = get_logger(__name__)

    mode = "full" if full else "incremental"
    console.print(f"[bold]Starting {mode} sync...[/bold]")

    async def _sync():
        engine = create_engine(settings)
        create_tables(engine)  # Ensure tables exist

        async with SolarEdgeClient(settings) as client:
            orchestrator = SyncOrchestrator(client, engine, settings)

            if site_id:
                result = await orchestrator.sync_site(site_id, full=full)
                return [result]
            else:
                summary = await orchestrator.sync_all(full=full)
                return summary.results

    try:
        results = run_async(_sync())

        # Display results
        table = Table(title="Sync Results")
        table.add_column("Site ID", style="cyan")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Records")
        table.add_column("Duration")

        total_records = 0
        success_count = 0

        for result in results:
            status = "[green]Success[/green]" if result.success else "[red]Failed[/red]"
            records = sum(result.records_synced.values())
            total_records += records

            if result.success:
                success_count += 1

            table.add_row(
                str(result.site_id),
                result.site_name or "Unknown",
                status,
                str(records),
                f"{result.duration_seconds:.1f}s",
            )

        console.print(table)
        console.print(f"\n[bold]Summary:[/bold] {success_count}/{len(results)} sites synced, {total_records} total records")

        # Show errors if any
        for result in results:
            if result.errors:
                console.print(f"\n[red]Errors for site {result.site_id}:[/red]")
                for data_type, error in result.errors.items():
                    console.print(f"  - {data_type}: {error}")

        logger.info(
            "Sync complete",
            mode=mode,
            sites=len(results),
            successful=success_count,
            records=total_records,
        )

    except Exception as e:
        console.print(f"[red]Sync failed:[/red] {e}")
        logger.error("Sync failed", error=str(e))
        raise SystemExit(1) from None


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show sync status for all sites."""
    from seh.api.client import SolarEdgeClient
    from seh.config.logging import get_logger
    from seh.db.engine import create_engine
    from seh.sync.orchestrator import SyncOrchestrator

    settings = load_settings(ctx.obj.get("config_path"))
    logger = get_logger(__name__)

    console.print("[bold]Sync Status[/bold]")

    try:
        engine = create_engine(settings)

        async def _status():
            async with SolarEdgeClient(settings) as client:
                orchestrator = SyncOrchestrator(client, engine, settings)
                return orchestrator.get_sync_status()

        statuses = run_async(_status())

        if not statuses:
            console.print("[yellow]No sites found in database. Run 'seh sync' first.[/yellow]")
            return

        for site_status in statuses:
            console.print(f"\n[bold cyan]Site {site_status['site_id']}: {site_status['site_name']}[/bold cyan]")

            table = Table()
            table.add_column("Data Type")
            table.add_column("Last Sync")
            table.add_column("Last Data")
            table.add_column("Records")
            table.add_column("Status")

            data_types = site_status.get("data_types", {})
            if not data_types:
                console.print("  No sync data available")
                continue

            for data_type, info in data_types.items():
                last_sync = info.get("last_sync")
                last_data = info.get("last_data")
                records = info.get("records")
                sync_status = info.get("status", "unknown")

                last_sync_str = last_sync.strftime("%Y-%m-%d %H:%M") if last_sync else "-"
                last_data_str = last_data.strftime("%Y-%m-%d %H:%M") if last_data else "-"
                records_str = str(records) if records is not None else "-"

                if sync_status == "success":
                    status_str = "[green]Success[/green]"
                elif sync_status == "error":
                    status_str = "[red]Error[/red]"
                else:
                    status_str = sync_status

                table.add_row(data_type, last_sync_str, last_data_str, records_str, status_str)

            console.print(table)

        logger.info("Status displayed", sites=len(statuses))

    except Exception as e:
        console.print(f"[red]Failed to get status:[/red] {e}")
        logger.error("Status check failed", error=str(e))
        raise SystemExit(1) from None


@cli.group()
@click.pass_context
def export(ctx: click.Context) -> None:
    """Export data to CSV or JSON files."""
    pass


def write_output(data: list[dict], output: str | None, format: str, name: str) -> None:
    """Write data to file or stdout.

    Args:
        data: List of dictionaries to export.
        output: Output file path or None for auto-generated.
        format: Output format (csv or json).
        name: Data name for auto-generated filename.
    """
    if not data:
        console.print("[yellow]No data to export.[/yellow]")
        return

    # Generate filename if not provided
    if output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"seh_{name}_{timestamp}.{format}"

    # Convert datetime objects to strings
    for row in data:
        for key, value in row.items():
            if isinstance(value, (datetime, date)):
                row[key] = value.isoformat()

    if format == "json":
        with open(output, "w") as f:
            json.dump(data, f, indent=2, default=str)
    else:  # csv
        if data:
            with open(output, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)

    console.print(f"[green]Exported {len(data)} records to {output}[/green]")


@export.command("sites")
@click.option("--format", "-f", type=click.Choice(["csv", "json"]), default="csv", help="Output format")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.pass_context
def export_sites(ctx: click.Context, format: str, output: str | None) -> None:
    """Export site information."""
    from seh.db.engine import create_engine, get_session
    from seh.db.repositories.site import SiteRepository

    settings = load_settings(ctx.obj.get("config_path"))
    engine = create_engine(settings)

    with get_session(engine) as session:
        repo = SiteRepository(session)
        sites = repo.get_all()

        data = []
        for site in sites:
            data.append({
                "id": site.id,
                "name": site.name,
                "status": site.status,
                "peak_power": site.peak_power,
                "city": site.city,
                "state": site.state,
                "country": site.country,
                "timezone": site.timezone,
                "installation_date": site.installation_date,
                "last_update_time": site.last_update_time,
                "primary_module_manufacturer": site.primary_module_manufacturer,
                "primary_module_model": site.primary_module_model,
            })

        write_output(data, output, format, "sites")


@export.command("energy")
@click.option("--format", "-f", type=click.Choice(["csv", "json"]), default="csv", help="Output format")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--site", "-s", "site_id", type=int, help="Filter by site ID")
@click.option("--start", type=click.DateTime(), help="Start date (YYYY-MM-DD)")
@click.option("--end", type=click.DateTime(), help="End date (YYYY-MM-DD)")
@click.pass_context
def export_energy(ctx: click.Context, format: str, output: str | None, site_id: int | None, start: datetime | None, end: datetime | None) -> None:
    """Export energy readings."""
    from sqlalchemy import select
    from seh.db.engine import create_engine, get_session
    from seh.db.models.energy import EnergyReading
    from seh.db.models.site import Site

    settings = load_settings(ctx.obj.get("config_path"))
    engine = create_engine(settings)

    with get_session(engine) as session:
        stmt = select(EnergyReading, Site.name).join(Site)

        if site_id:
            stmt = stmt.where(EnergyReading.site_id == site_id)
        if start:
            stmt = stmt.where(EnergyReading.reading_date >= start.date())
        if end:
            stmt = stmt.where(EnergyReading.reading_date <= end.date())

        stmt = stmt.order_by(EnergyReading.site_id, EnergyReading.reading_date)
        results = session.execute(stmt).all()

        data = []
        for reading, site_name in results:
            data.append({
                "site_id": reading.site_id,
                "site_name": site_name,
                "reading_date": reading.reading_date,
                "time_unit": reading.time_unit,
                "energy_wh": reading.energy_wh,
                "energy_kwh": round(reading.energy_wh / 1000, 2) if reading.energy_wh else None,
            })

        write_output(data, output, format, "energy")


@export.command("power")
@click.option("--format", "-f", type=click.Choice(["csv", "json"]), default="csv", help="Output format")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--site", "-s", "site_id", type=int, help="Filter by site ID")
@click.option("--start", type=click.DateTime(), help="Start datetime (YYYY-MM-DD HH:MM:SS)")
@click.option("--end", type=click.DateTime(), help="End datetime (YYYY-MM-DD HH:MM:SS)")
@click.pass_context
def export_power(ctx: click.Context, format: str, output: str | None, site_id: int | None, start: datetime | None, end: datetime | None) -> None:
    """Export power readings."""
    from sqlalchemy import select
    from seh.db.engine import create_engine, get_session
    from seh.db.models.power import PowerReading
    from seh.db.models.site import Site

    settings = load_settings(ctx.obj.get("config_path"))
    engine = create_engine(settings)

    with get_session(engine) as session:
        stmt = select(PowerReading, Site.name).join(Site)

        if site_id:
            stmt = stmt.where(PowerReading.site_id == site_id)
        if start:
            stmt = stmt.where(PowerReading.timestamp >= start)
        if end:
            stmt = stmt.where(PowerReading.timestamp <= end)

        stmt = stmt.order_by(PowerReading.site_id, PowerReading.timestamp)
        results = session.execute(stmt).all()

        data = []
        for reading, site_name in results:
            data.append({
                "site_id": reading.site_id,
                "site_name": site_name,
                "timestamp": reading.timestamp,
                "power_watts": reading.power_watts,
                "power_kw": round(reading.power_watts / 1000, 2) if reading.power_watts else None,
            })

        write_output(data, output, format, "power")


@export.command("equipment")
@click.option("--format", "-f", type=click.Choice(["csv", "json"]), default="csv", help="Output format")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--site", "-s", "site_id", type=int, help="Filter by site ID")
@click.pass_context
def export_equipment(ctx: click.Context, format: str, output: str | None, site_id: int | None) -> None:
    """Export equipment list."""
    from sqlalchemy import select
    from seh.db.engine import create_engine, get_session
    from seh.db.models.equipment import Equipment
    from seh.db.models.site import Site

    settings = load_settings(ctx.obj.get("config_path"))
    engine = create_engine(settings)

    with get_session(engine) as session:
        stmt = select(Equipment, Site.name).join(Site)

        if site_id:
            stmt = stmt.where(Equipment.site_id == site_id)

        stmt = stmt.order_by(Equipment.site_id, Equipment.equipment_type, Equipment.name)
        results = session.execute(stmt).all()

        data = []
        for equip, site_name in results:
            data.append({
                "site_id": equip.site_id,
                "site_name": site_name,
                "serial_number": equip.serial_number,
                "name": equip.name,
                "manufacturer": equip.manufacturer,
                "model": equip.model,
                "equipment_type": equip.equipment_type,
                "cpu_version": equip.cpu_version,
                "connected_optimizers": equip.connected_optimizers,
                "last_report_date": equip.last_report_date,
            })

        write_output(data, output, format, "equipment")


@export.command("telemetry")
@click.option("--format", "-f", type=click.Choice(["csv", "json"]), default="csv", help="Output format")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--site", "-s", "site_id", type=int, help="Filter by site ID")
@click.option("--serial", type=str, help="Filter by inverter serial number")
@click.option("--start", type=click.DateTime(), help="Start datetime (YYYY-MM-DD HH:MM:SS)")
@click.option("--end", type=click.DateTime(), help="End datetime (YYYY-MM-DD HH:MM:SS)")
@click.pass_context
def export_telemetry(ctx: click.Context, format: str, output: str | None, site_id: int | None, serial: str | None, start: datetime | None, end: datetime | None) -> None:
    """Export inverter telemetry data."""
    from sqlalchemy import select
    from seh.db.engine import create_engine, get_session
    from seh.db.models.inverter_telemetry import InverterTelemetry
    from seh.db.models.site import Site

    settings = load_settings(ctx.obj.get("config_path"))
    engine = create_engine(settings)

    with get_session(engine) as session:
        stmt = select(InverterTelemetry, Site.name).join(Site)

        if site_id:
            stmt = stmt.where(InverterTelemetry.site_id == site_id)
        if serial:
            stmt = stmt.where(InverterTelemetry.serial_number == serial)
        if start:
            stmt = stmt.where(InverterTelemetry.timestamp >= start)
        if end:
            stmt = stmt.where(InverterTelemetry.timestamp <= end)

        stmt = stmt.order_by(InverterTelemetry.site_id, InverterTelemetry.serial_number, InverterTelemetry.timestamp)
        results = session.execute(stmt).all()

        data = []
        for telem, site_name in results:
            data.append({
                "site_id": telem.site_id,
                "site_name": site_name,
                "serial_number": telem.serial_number,
                "timestamp": telem.timestamp,
                "total_active_power": telem.total_active_power,
                "total_energy": telem.total_energy,
                "temperature": telem.temperature,
                "inverter_mode": telem.inverter_mode,
                "ac_voltage": telem.ac_voltage,
                "ac_current": telem.ac_current,
                "ac_frequency": telem.ac_frequency,
                "power_limit": telem.power_limit,
            })

        write_output(data, output, format, "telemetry")


@export.command("inventory")
@click.option("--format", "-f", type=click.Choice(["csv", "json"]), default="csv", help="Output format")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--site", "-s", "site_id", type=int, help="Filter by site ID")
@click.pass_context
def export_inventory(ctx: click.Context, format: str, output: str | None, site_id: int | None) -> None:
    """Export inventory items."""
    from sqlalchemy import select
    from seh.db.engine import create_engine, get_session
    from seh.db.models.inventory import InventoryItem
    from seh.db.models.site import Site

    settings = load_settings(ctx.obj.get("config_path"))
    engine = create_engine(settings)

    with get_session(engine) as session:
        stmt = select(InventoryItem, Site.name).join(Site)

        if site_id:
            stmt = stmt.where(InventoryItem.site_id == site_id)

        stmt = stmt.order_by(InventoryItem.site_id, InventoryItem.category, InventoryItem.name)
        results = session.execute(stmt).all()

        data = []
        for item, site_name in results:
            data.append({
                "site_id": item.site_id,
                "site_name": site_name,
                "name": item.name,
                "category": item.category,
                "manufacturer": item.manufacturer,
                "model": item.model,
                "serial_number": item.serial_number,
                "firmware_version": item.firmware_version,
            })

        write_output(data, output, format, "inventory")


@export.command("environmental")
@click.option("--format", "-f", type=click.Choice(["csv", "json"]), default="csv", help="Output format")
@click.option("--output", "-o", type=click.Path(), help="Output file path")
@click.option("--site", "-s", "site_id", type=int, help="Filter by site ID")
@click.pass_context
def export_environmental(ctx: click.Context, format: str, output: str | None, site_id: int | None) -> None:
    """Export environmental benefits."""
    from sqlalchemy import select
    from seh.db.engine import create_engine, get_session
    from seh.db.models.environmental import EnvironmentalBenefits
    from seh.db.models.site import Site

    settings = load_settings(ctx.obj.get("config_path"))
    engine = create_engine(settings)

    with get_session(engine) as session:
        stmt = select(EnvironmentalBenefits, Site.name).join(Site)

        if site_id:
            stmt = stmt.where(EnvironmentalBenefits.site_id == site_id)

        stmt = stmt.order_by(EnvironmentalBenefits.site_id)
        results = session.execute(stmt).all()

        data = []
        for env, site_name in results:
            data.append({
                "site_id": env.site_id,
                "site_name": site_name,
                "co2_saved": env.co2_saved,
                "so2_saved": env.so2_saved,
                "nox_saved": env.nox_saved,
                "co2_units": env.co2_units,
                "trees_planted": env.trees_planted,
                "light_bulbs": env.light_bulbs,
            })

        write_output(data, output, format, "environmental")


if __name__ == "__main__":
    cli()
