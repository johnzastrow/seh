"""Command-line interface for SolarEdge Harvest.

SolarEdge Harvest (seh) downloads data from SolarEdge solar monitoring servers
and stores it in a relational database (SQLite, PostgreSQL, or MariaDB).

Environment Variables:
    SEH_API_KEY          SolarEdge monitoring API key (required)
    SEH_DATABASE_URL     Database connection URL (default: sqlite:///./seh.db)
    SEH_SITE_IDS         Comma-separated list of site IDs to sync (optional)
    SEH_LOG_LEVEL        Logging level: DEBUG, INFO, WARNING, ERROR (default: INFO)
    SEH_LOG_FILE         Log file path (optional, logs to console if not set)

See .env.example for all configuration options.
"""

import asyncio
import csv
import json
import os
import subprocess
from datetime import date, datetime

import click
from rich.console import Console
from rich.table import Table

console = Console()


# =============================================================================
# Help text constants
# =============================================================================

MAIN_HELP = """
SolarEdge Harvest - Download SolarEdge monitoring data to a database.

SEH connects to the SolarEdge Monitoring API and downloads site information,
energy production, power readings, equipment data, and more into a local or
remote database for analysis and reporting.

QUICK START:
  1. Create a .env file with your API key:
     SEH_API_KEY=your_api_key_here

  2. Initialize the database:
     seh init-db

  3. Check API connectivity:
     seh check-api

  4. Sync data from SolarEdge:
     seh sync

EXAMPLES:
  # Basic sync (incremental, all sites)
  seh sync

  # Full sync (ignore last sync time)
  seh sync --full

  # Sync specific sites only
  seh sync --sites 123456,789012

  # Check sync status with diagnostics
  seh status --diagnostics

  # Export energy data to CSV
  seh export energy --start 2024-01-01 --end 2024-12-31

  # Export to Excel format
  seh export energy --format xlsx -o report.xlsx

  # Use a different config file
  seh -c /path/to/config.env sync

CONFIGURATION:
  Configuration is loaded from environment variables with the SEH_ prefix.
  You can use a .env file or set them directly in your environment.

  Required:
    SEH_API_KEY            Your SolarEdge API key

  Database:
    SEH_DATABASE_URL       Connection URL (default: sqlite:///./seh.db)
                           Examples:
                           - postgresql+psycopg://user:pass@host:5432/db
                           - mariadb+mariadbconnector://user:pass@host:3306/db

  Sync options:
    SEH_SITE_IDS           Comma-separated site IDs to sync (syncs all if not set)
    SEH_SKIP_DATA_TYPES    Comma-separated data types to skip (e.g., meter,alert)
                           Run 'seh check-api' to auto-detect unavailable endpoints
    SEH_ENERGY_LOOKBACK_DAYS   Days of energy data for first sync (default: 365)
    SEH_POWER_LOOKBACK_DAYS    Days of power data for first sync (default: 7)
    SEH_POWER_TIME_UNIT        Power data granularity (default: QUARTER_OF_AN_HOUR)
                               Options: QUARTER_OF_AN_HOUR, HOUR, DAY, WEEK, MONTH, YEAR

  Error handling:
    SEH_ERROR_HANDLING     Mode: strict, lenient, skip (default: lenient)
    SEH_MAX_RETRIES        Max API retry attempts (default: 3)

  Email notifications:
    SEH_SMTP_ENABLED       Enable email notifications (default: false)
    SEH_SMTP_HOST          SMTP server hostname
    SEH_SMTP_PORT          SMTP port (default: 587)
    SEH_SMTP_USERNAME      SMTP authentication username
    SEH_SMTP_PASSWORD      SMTP authentication password
    SEH_SMTP_FROM_EMAIL    Sender email address
    SEH_SMTP_TO_EMAILS     Comma-separated recipient email addresses
    SEH_NOTIFY_ON_ERROR    Send email on sync errors (default: true)
    SEH_NOTIFY_ON_SUCCESS  Send email on successful sync (default: false)

SCHEDULING:
  Use cron or systemd timers to run seh on a schedule:

    # Every hour
    0 * * * * /path/to/seh sync >> /var/log/seh.log 2>&1

    # Every 15 minutes during daylight hours
    */15 6-20 * * * /path/to/seh sync

MORE INFORMATION:
  API Documentation: https://knowledge-center.solaredge.com/sites/kc/files/se_monitoring_api.pdf
  GitHub: https://github.com/your-repo/seh
"""

SYNC_HELP = """
Synchronize data from SolarEdge monitoring servers to the database.

By default, performs an incremental sync starting from the last sync timestamp
with a configurable overlap buffer (default: 15 minutes) to catch any delayed data.

EXAMPLES:
  # Incremental sync (default)
  seh sync

  # Full sync - fetch all historical data
  seh sync --full

  # Sync specific sites only
  seh sync --sites 123456,789012

  # Sync a single site
  seh sync --sites 123456

  # Verbose output
  seh sync -v

SYNC BEHAVIOR:
  First sync:
    - Energy data: Last 365 days (configurable via SEH_ENERGY_LOOKBACK_DAYS)
    - Power data: Last 7 days (configurable via SEH_POWER_LOOKBACK_DAYS)
    - Equipment, alerts, environmental: All available data

  Subsequent syncs:
    - Fetches data since last sync time minus overlap buffer
    - Uses upsert (INSERT ON CONFLICT UPDATE) for idempotent updates

DATA TYPES SYNCED:
  - Sites: Installation details, location, timezone
  - Equipment: Inverters, optimizers, gateways
  - Energy: Daily and monthly production (Wh)
  - Power: 15-minute power readings (W)
  - Power Flow: PV, grid, load, storage power snapshots
  - Storage: Battery status and telemetry
  - Meters: Revenue-grade meter data
  - Alerts: System alerts and notifications
  - Environmental: CO2 savings, trees planted equivalents

API RATE LIMITS:
  SolarEdge enforces these limits:
  - 3 concurrent API requests maximum
  - 300 requests per account per day
  - 10 second timeout per request

  SEH respects these limits automatically. If you hit the daily limit,
  wait until the next day or contact SolarEdge for a higher quota.
"""

STATUS_HELP = """
Show synchronization status for all sites in the database.

Displays the last sync time, last data timestamp, and record counts
for each data type per site. Use --diagnostics for additional
system health information.

EXAMPLES:
  # Basic status
  seh status

  # Full diagnostics (API health, DB status, rate limits)
  seh status --diagnostics

  # Status for specific sites only
  seh status --sites 123456,789012

OUTPUT COLUMNS:
  Data Type    - Type of data (energy, power, equipment, etc.)
  Last Sync    - Timestamp of last successful sync
  Last Data    - Timestamp of most recent data record
  Records      - Total number of records in database
  Status       - Success, Error, or Partial
"""

EXPORT_HELP = """
Export data from the database to files for external analysis.

Supports CSV, JSON, Excel (.xlsx), and SQL dump formats.
Data can be filtered by site, date range, and other criteria.

EXAMPLES:
  # Export all sites to CSV
  seh export sites

  # Export energy data with date range
  seh export energy --start 2024-01-01 --end 2024-12-31

  # Export to JSON format
  seh export energy --format json -o energy.json

  # Export to Excel
  seh export energy --format xlsx -o report.xlsx

  # Filter by site
  seh export power --sites 123456 --start 2024-06-01

  # SQL dump of entire database
  seh export dump -o backup.sql

AVAILABLE EXPORTS:
  sites        - Site information (ID, name, location, peak power)
  energy       - Energy production readings (Wh, kWh)
  power        - Power readings (W, kW)
  equipment    - Inverters, optimizers, gateways
  telemetry    - Detailed inverter telemetry
  inventory    - Full equipment inventory
  environmental - CO2 savings, tree equivalents
  dump         - Full SQL database dump
"""


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


def parse_site_ids(sites_str: str | None) -> list[int] | None:
    """Parse comma-separated site IDs.

    Args:
        sites_str: Comma-separated site IDs or None.

    Returns:
        List of site IDs or None.
    """
    if not sites_str:
        return None
    try:
        return [int(s.strip()) for s in sites_str.split(",") if s.strip()]
    except ValueError:
        console.print("[red]Invalid site IDs format. Use comma-separated numbers.[/red]")
        raise SystemExit(1) from None


@click.group(help=MAIN_HELP)
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True),
    help="Path to .env configuration file.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output (sets log level to DEBUG).",
)
@click.version_option(version="0.2.0", prog_name="seh")
@click.pass_context
def cli(ctx: click.Context, config: str | None, verbose: bool) -> None:
    """SolarEdge Harvest - Download SolarEdge data to a database."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["verbose"] = verbose

    if verbose:
        os.environ["SEH_LOG_LEVEL"] = "DEBUG"


@cli.command(help="""
Initialize the database schema and views.

Creates all required tables and views in the configured database.
Safe to run multiple times - uses IF NOT EXISTS semantics.

EXAMPLES:
  # Initialize with default SQLite database
  seh init-db

  # Initialize PostgreSQL database
  SEH_DATABASE_URL="postgresql+psycopg://user:pass@localhost/seh" seh init-db

  # Initialize MariaDB database
  SEH_DATABASE_URL="mariadb+mariadbconnector://user:pass@localhost/seh" seh init-db

TABLES CREATED:
  seh_sites              - Site information
  seh_equipment          - Inverters, optimizers, gateways
  seh_batteries          - Storage units
  seh_energy_readings    - Daily/monthly energy production
  seh_power_readings     - 15-minute power data
  seh_power_flows        - PV, grid, load, storage snapshots
  seh_meters             - Meter devices
  seh_meter_readings     - Meter time-series data
  seh_alerts             - System alerts
  seh_environmental_benefits - CO2 savings
  seh_inventory          - Equipment inventory
  seh_inverter_telemetry - Detailed inverter data
  seh_optimizer_telemetry - Detailed optimizer data
  seh_sync_metadata      - Sync tracking

VIEWS CREATED:
  v_seh_site_summary     - Site overview
  v_seh_daily_energy     - Daily energy with kWh conversion
  v_seh_latest_power     - Most recent power per site
  v_seh_power_flow_current - Current power flow status
  v_seh_sync_status      - Sync status overview
  v_seh_equipment_list   - Equipment with site names
  v_seh_battery_status   - Battery status overview
  v_seh_energy_monthly   - Monthly energy aggregation
""")
@click.pass_context
def init_db(ctx: click.Context) -> None:
    """Initialize the database schema and views."""
    from seh.config.logging import get_logger
    from seh.db.engine import create_engine, create_tables
    from seh.db.views import create_views

    settings = load_settings(ctx.obj.get("config_path"))
    logger = get_logger(__name__)

    console.print("[bold]Initializing database...[/bold]")
    console.print(f"  Database: {settings.database_url.split('@')[-1] if '@' in settings.database_url else settings.database_url}")

    try:
        engine = create_engine(settings)
        create_tables(engine)
        console.print("  [green]Tables created[/green]")

        create_views(engine)
        console.print("  [green]Views created[/green]")

        console.print("\n[green]Database initialized successfully![/green]")
        logger.info("Database initialized", url=settings.database_url)
    except Exception as e:
        console.print(f"\n[red]Failed to initialize database:[/red] {e}")
        logger.error("Database initialization failed", error=str(e))
        raise SystemExit(1) from None


@cli.command(help="""
Check API connectivity and list available sites.

Validates your API key and displays all sites accessible with your credentials.
Use this command to verify configuration before running sync.

By default, also probes all API endpoints to detect which ones are available
for your account. Endpoints that return errors (400, 403, etc.) can be
automatically excluded from future syncs to prevent log pollution.

EXAMPLES:
  # Basic API check with endpoint probing
  seh check-api

  # Skip endpoint probing
  seh check-api --no-probe

  # Probe and auto-update .env without prompting
  seh check-api --update-config

  # With custom config file
  seh -c production.env check-api

OUTPUT:
  Displays:
  - Available sites table (ID, name, status, peak power, last update)
  - Endpoint availability table showing which data types work/fail
  - Option to exclude failing endpoints from future syncs

TROUBLESHOOTING:
  "API check failed: 401" - Invalid API key
  "API check failed: 403" - API key lacks permissions for this site
  "No sites found" - API key is valid but has no associated sites
""")
@click.option(
    "--probe/--no-probe",
    default=True,
    help="Probe API endpoints to detect availability (default: enabled).",
)
@click.option(
    "--update-config",
    is_flag=True,
    help="Automatically update .env with exclusions (no prompt).",
)
@click.pass_context
def check_api(ctx: click.Context, probe: bool, update_config: bool) -> None:
    """Check API connectivity and list available sites."""
    from datetime import timedelta

    from seh.api.client import SolarEdgeClient
    from seh.config.logging import get_logger
    from seh.config.settings import update_env_file
    from seh.utils.exceptions import APIError

    settings = load_settings(ctx.obj.get("config_path"))
    logger = get_logger(__name__)

    console.print("[bold]Checking SolarEdge API connection...[/bold]")

    async def _check():
        async with SolarEdgeClient(settings) as client:
            sites = await client.get_sites()
            return client, sites

    async def _probe_endpoints(client: SolarEdgeClient, site_id: int) -> dict[str, dict]:
        """Probe all API endpoints for a site.

        Returns:
            Dict mapping data_type to {status: str, code: int|None, notes: str}
        """
        from datetime import datetime

        results: dict[str, dict] = {}
        now = datetime.now()
        yesterday = now - timedelta(days=1)

        # Probe site details
        try:
            await client.get_site_details(site_id)
            results["site"] = {"status": "ok", "code": None, "notes": ""}
        except APIError as e:
            results["site"] = {"status": "error", "code": e.status_code, "notes": str(e)[:50]}

        # Probe equipment
        equipment_list = []
        try:
            equipment_list = await client.get_equipment(site_id)
            count = len(equipment_list)
            results["equipment"] = {"status": "ok", "code": None, "notes": f"{count} inverter(s)" if count else "No equipment"}
        except APIError as e:
            results["equipment"] = {"status": "error", "code": e.status_code, "notes": str(e)[:50]}

        # Probe energy
        try:
            await client.get_energy(site_id, yesterday.date(), now.date())
            results["energy"] = {"status": "ok", "code": None, "notes": ""}
        except APIError as e:
            results["energy"] = {"status": "error", "code": e.status_code, "notes": str(e)[:50]}

        # Probe power
        try:
            await client.get_power(site_id, yesterday, now)
            results["power"] = {"status": "ok", "code": None, "notes": ""}
        except APIError as e:
            results["power"] = {"status": "error", "code": e.status_code, "notes": str(e)[:50]}

        # Probe storage
        try:
            storage_data = await client.get_storage_data(site_id, yesterday, now)
            batteries = storage_data.get("batteries", [])
            results["storage"] = {"status": "ok", "code": None, "notes": f"{len(batteries)} battery(ies)" if batteries else "No batteries"}
        except APIError as e:
            results["storage"] = {"status": "error", "code": e.status_code, "notes": str(e)[:50]}

        # Probe meters
        try:
            meters = await client.get_meters(site_id)
            count = len(meters)
            results["meter"] = {"status": "ok", "code": None, "notes": f"{count} meter(s)" if count else "No meters"}
        except APIError as e:
            results["meter"] = {"status": "error", "code": e.status_code, "notes": str(e)[:50]}

        # Probe environmental benefits
        try:
            await client.get_environmental_benefits(site_id)
            results["environmental"] = {"status": "ok", "code": None, "notes": ""}
        except APIError as e:
            results["environmental"] = {"status": "error", "code": e.status_code, "notes": str(e)[:50]}

        # Probe alerts
        try:
            alerts = await client.get_alerts(site_id)
            count = len(alerts)
            results["alert"] = {"status": "ok", "code": None, "notes": f"{count} alert(s)" if count else "No alerts"}
        except APIError as e:
            results["alert"] = {"status": "error", "code": e.status_code, "notes": str(e)[:50]}

        # Probe inventory
        try:
            await client.get_inventory(site_id)
            results["inventory"] = {"status": "ok", "code": None, "notes": ""}
        except APIError as e:
            results["inventory"] = {"status": "error", "code": e.status_code, "notes": str(e)[:50]}

        # Probe inverter telemetry (requires equipment)
        if equipment_list:
            try:
                serial = equipment_list[0].get("serialNumber")
                if serial:
                    await client.get_inverter_data(site_id, serial, yesterday, now)
                    results["inverter_telemetry"] = {"status": "ok", "code": None, "notes": ""}
                else:
                    results["inverter_telemetry"] = {"status": "ok", "code": None, "notes": "No serial found"}
            except APIError as e:
                results["inverter_telemetry"] = {"status": "error", "code": e.status_code, "notes": str(e)[:50]}
        else:
            results["inverter_telemetry"] = {"status": "ok", "code": None, "notes": "No equipment to probe"}

        # Optimizer telemetry - typically accessed via inverter data endpoint
        # We'll mark it as requiring equipment similar to inverter telemetry
        results["optimizer_telemetry"] = {"status": "ok", "code": None, "notes": "Requires optimizer serial"}

        return results

    try:
        _, sites = run_async(_check())

        if not sites:
            console.print("[yellow]No sites found for this API key.[/yellow]")
            return

        # Display sites table
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

        # Endpoint probing
        if probe:
            first_site = sites[0]
            site_id = first_site.get("id")
            site_name = first_site.get("name", "Unknown")

            console.print(f"\n[bold]Probing API endpoints for site {site_id} ({site_name})...[/bold]")

            async def _do_probe():
                async with SolarEdgeClient(settings) as probe_client:
                    return await _probe_endpoints(probe_client, site_id)

            probe_results = run_async(_do_probe())

            # Display probe results
            probe_table = Table(title="Endpoint Availability")
            probe_table.add_column("Data Type", style="cyan")
            probe_table.add_column("Status")
            probe_table.add_column("Notes")

            failed_types: list[str] = []
            data_type_order = [
                "site", "equipment", "energy", "power", "storage",
                "meter", "environmental", "alert", "inventory",
                "inverter_telemetry", "optimizer_telemetry"
            ]

            for data_type in data_type_order:
                result = probe_results.get(data_type, {})
                status = result.get("status", "unknown")
                code = result.get("code")
                notes = result.get("notes", "")

                if status == "ok":
                    status_str = "[green]OK[/green]"
                else:
                    status_str = f"[red]{code or 'Error'}[/red]"
                    failed_types.append(data_type)

                probe_table.add_row(data_type, status_str, notes[:40] if notes else "")

            console.print(probe_table)

            # Handle failures
            if failed_types:
                console.print(f"\n[yellow]Warning:[/yellow] {len(failed_types)} endpoint(s) unavailable: {', '.join(failed_types)}")

                # Check current skip list
                current_skip = settings.get_skip_data_types_list() or []
                new_skips = [t for t in failed_types if t not in current_skip]

                if new_skips:
                    all_skips = sorted(set(current_skip + new_skips))
                    skip_value = ",".join(all_skips)

                    if update_config:
                        # Auto-update without prompting
                        update_env_file("SEH_SKIP_DATA_TYPES", skip_value)
                        console.print(f"\n[green]Updated .env with:[/green] SEH_SKIP_DATA_TYPES={skip_value}")
                    else:
                        # Prompt user
                        console.print("\nWould you like to exclude these from future syncs?")
                        console.print(f"This will set: SEH_SKIP_DATA_TYPES={skip_value}")
                        response = click.prompt("Update .env?", type=click.Choice(["y", "n"], case_sensitive=False), default="y")

                        if response.lower() == "y":
                            update_env_file("SEH_SKIP_DATA_TYPES", skip_value)
                            console.print(f"\n[green]Updated .env with:[/green] SEH_SKIP_DATA_TYPES={skip_value}")
                        else:
                            console.print("\n[yellow]Skipped .env update[/yellow]")

                    console.print("\n[dim]Tip: Run 'seh check-api' again after API key changes to reassess.[/dim]")
                else:
                    console.print("\n[dim]All failing endpoints already in skip list.[/dim]")
            else:
                console.print("\n[green]All endpoints available![/green]")

        logger.info("API check successful", sites=len(sites))

    except Exception as e:
        console.print(f"[red]API check failed:[/red] {e}")
        logger.error("API check failed", error=str(e))
        raise SystemExit(1) from None


@cli.command(help=SYNC_HELP)
@click.option("--full", is_flag=True, help="Perform full sync (ignore last sync time).")
@click.option(
    "--sites",
    "-s",
    "sites_str",
    type=str,
    help="Comma-separated site IDs to sync (syncs all if not specified).",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output.",
)
@click.pass_context
def sync(ctx: click.Context, full: bool, sites_str: str | None, verbose: bool) -> None:
    """Synchronize data from SolarEdge to the database."""
    from seh.api.client import SolarEdgeClient
    from seh.config.logging import EmailNotifier, SyncSummary, get_logger
    from seh.db.engine import create_engine, create_tables
    from seh.sync.orchestrator import SyncOrchestrator

    if verbose:
        os.environ["SEH_LOG_LEVEL"] = "DEBUG"

    settings = load_settings(ctx.obj.get("config_path"))
    logger = get_logger(__name__)
    notifier = EmailNotifier(settings)

    # Parse site IDs from command line or settings
    site_ids = parse_site_ids(sites_str) or settings.get_site_ids_list()

    mode = "full" if full else "incremental"
    sites_info = f" (sites: {','.join(map(str, site_ids))})" if site_ids else " (all sites)"
    console.print(f"[bold]Starting {mode} sync{sites_info}...[/bold]")

    sync_summary = SyncSummary()

    async def _sync():
        engine = create_engine(settings)
        create_tables(engine)  # Ensure tables exist

        async with SolarEdgeClient(settings) as client:
            orchestrator = SyncOrchestrator(client, engine, settings)

            if site_ids:
                results = []
                for sid in site_ids:
                    result = await orchestrator.sync_site(sid, full=full)
                    results.append(result)
                return results
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

        sync_summary.sites_processed = len(results)
        sync_summary.total_records = total_records
        sync_summary.finish()

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

        # Send email notification if configured
        notifier.notify_sync_complete(sync_summary)

    except Exception as e:
        console.print(f"[red]Sync failed:[/red] {e}")
        logger.error("Sync failed", error=str(e))
        raise SystemExit(1) from None


@cli.command(help=STATUS_HELP)
@click.option(
    "--diagnostics",
    "-d",
    is_flag=True,
    help="Show full diagnostics (API health, DB status, rate limits).",
)
@click.option(
    "--sites",
    "-s",
    "sites_str",
    type=str,
    help="Comma-separated site IDs to show status for.",
)
@click.pass_context
def status(ctx: click.Context, diagnostics: bool, sites_str: str | None) -> None:
    """Show sync status for all sites."""
    from seh.api.client import SolarEdgeClient
    from seh.config.logging import get_logger
    from seh.db.engine import create_engine

    settings = load_settings(ctx.obj.get("config_path"))
    logger = get_logger(__name__)

    site_ids = parse_site_ids(sites_str)

    console.print("[bold]Sync Status[/bold]")

    # Show diagnostics if requested
    if diagnostics:
        console.print("\n[bold cyan]System Diagnostics[/bold cyan]")

        # Database status
        db_type = "SQLite" if "sqlite" in settings.database_url else \
                  "PostgreSQL" if "postgresql" in settings.database_url else \
                  "MariaDB" if "mariadb" in settings.database_url else "Unknown"
        console.print(f"  Database: {db_type}")
        console.print(f"  Connection: {settings.database_url.split('@')[-1] if '@' in settings.database_url else settings.database_url}")

        # API configuration
        console.print(f"\n  API Base URL: {settings.api_base_url}")
        console.print(f"  Max Concurrent: {settings.api_max_concurrent}")
        console.print(f"  Daily Limit: {settings.api_daily_limit}")
        console.print(f"  Request Timeout: {settings.api_timeout}s")

        # Sync configuration
        console.print(f"\n  Energy Lookback: {settings.energy_lookback_days} days")
        console.print(f"  Power Lookback: {settings.power_lookback_days} days")
        console.print(f"  Power Granularity: {settings.power_time_unit}")
        console.print(f"  Overlap Buffer: {settings.sync_overlap_minutes} minutes")
        console.print(f"  Error Handling: {settings.error_handling}")

        # Email configuration
        if settings.smtp_enabled:
            console.print("\n  Email Notifications: Enabled")
            console.print(f"  SMTP Host: {settings.smtp_host}:{settings.smtp_port}")
            console.print(f"  Notify on Error: {settings.notify_on_error}")
            console.print(f"  Notify on Success: {settings.notify_on_success}")
        else:
            console.print("\n  Email Notifications: Disabled")

        console.print("")

    try:
        engine = create_engine(settings)

        async def _status():
            async with SolarEdgeClient(settings) as client:
                from seh.sync.orchestrator import SyncOrchestrator
                orchestrator = SyncOrchestrator(client, engine, settings)
                return orchestrator.get_sync_status()

        statuses = run_async(_status())

        if not statuses:
            console.print("[yellow]No sites found in database. Run 'seh sync' first.[/yellow]")
            return

        # Filter by site IDs if specified
        if site_ids:
            statuses = [s for s in statuses if s.get("site_id") in site_ids]

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


@cli.group(help=EXPORT_HELP)
@click.pass_context
def export(ctx: click.Context) -> None:
    """Export data to CSV, JSON, Excel, or SQL dump files."""
    pass


def write_output(data: list[dict], output: str | None, format: str, name: str) -> None:
    """Write data to file or stdout.

    Args:
        data: List of dictionaries to export.
        output: Output file path or None for auto-generated.
        format: Output format (csv, json, or xlsx).
        name: Data name for auto-generated filename.
    """
    if not data:
        console.print("[yellow]No data to export.[/yellow]")
        return

    # Generate filename if not provided
    if output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"seh_{name}_{timestamp}.{format}"

    # Convert datetime objects to strings for JSON/CSV
    for row in data:
        for key, value in row.items():
            if isinstance(value, (datetime, date)):
                row[key] = value.isoformat()

    if format == "json":
        with open(output, "w") as f:
            json.dump(data, f, indent=2, default=str)
    elif format == "xlsx":
        try:
            import openpyxl
            from openpyxl.utils.dataframe import dataframe_to_rows
        except ImportError:
            console.print("[red]Excel export requires openpyxl. Install with:[/red]")
            console.print("  uv pip install openpyxl")
            raise SystemExit(1) from None

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = name

        # Write headers
        if data:
            headers = list(data[0].keys())
            ws.append(headers)

            # Write data rows
            for row in data:
                ws.append([row.get(h) for h in headers])

        wb.save(output)
    else:  # csv
        if data:
            with open(output, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)

    console.print(f"[green]Exported {len(data)} records to {output}[/green]")


@export.command("sites", help="""
Export site information to a file.

EXAMPLES:
  seh export sites                    # CSV to auto-named file
  seh export sites -f json            # JSON format
  seh export sites -f xlsx -o sites.xlsx  # Excel format
""")
@click.option("--format", "-f", type=click.Choice(["csv", "json", "xlsx"]), default="csv", help="Output format.")
@click.option("--output", "-o", type=click.Path(), help="Output file path.")
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


@export.command("energy", help="""
Export energy production readings.

Exports daily or monthly energy readings in Wh and kWh.

EXAMPLES:
  # All energy data
  seh export energy

  # Specific date range
  seh export energy --start 2024-01-01 --end 2024-12-31

  # Specific site to Excel
  seh export energy --sites 123456 -f xlsx -o energy_report.xlsx
""")
@click.option("--format", "-f", type=click.Choice(["csv", "json", "xlsx"]), default="csv", help="Output format.")
@click.option("--output", "-o", type=click.Path(), help="Output file path.")
@click.option("--sites", "-s", "sites_str", type=str, help="Comma-separated site IDs.")
@click.option("--start", type=click.DateTime(), help="Start date (YYYY-MM-DD).")
@click.option("--end", type=click.DateTime(), help="End date (YYYY-MM-DD).")
@click.pass_context
def export_energy(ctx: click.Context, format: str, output: str | None, sites_str: str | None, start: datetime | None, end: datetime | None) -> None:
    """Export energy readings."""
    from sqlalchemy import select

    from seh.db.engine import create_engine, get_session
    from seh.db.models.energy import EnergyReading
    from seh.db.models.site import Site

    settings = load_settings(ctx.obj.get("config_path"))
    engine = create_engine(settings)
    site_ids = parse_site_ids(sites_str)

    with get_session(engine) as session:
        stmt = select(EnergyReading, Site.name).join(Site)

        if site_ids:
            stmt = stmt.where(EnergyReading.site_id.in_(site_ids))
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


@export.command("power", help="""
Export power readings.

Exports 15-minute power readings in W and kW.

EXAMPLES:
  # All power data
  seh export power

  # Specific date range
  seh export power --start 2024-06-01 --end 2024-06-30

  # Specific site
  seh export power --sites 123456
""")
@click.option("--format", "-f", type=click.Choice(["csv", "json", "xlsx"]), default="csv", help="Output format.")
@click.option("--output", "-o", type=click.Path(), help="Output file path.")
@click.option("--sites", "-s", "sites_str", type=str, help="Comma-separated site IDs.")
@click.option("--start", type=click.DateTime(), help="Start datetime (YYYY-MM-DD HH:MM:SS).")
@click.option("--end", type=click.DateTime(), help="End datetime (YYYY-MM-DD HH:MM:SS).")
@click.pass_context
def export_power(ctx: click.Context, format: str, output: str | None, sites_str: str | None, start: datetime | None, end: datetime | None) -> None:
    """Export power readings."""
    from sqlalchemy import select

    from seh.db.engine import create_engine, get_session
    from seh.db.models.power import PowerReading
    from seh.db.models.site import Site

    settings = load_settings(ctx.obj.get("config_path"))
    engine = create_engine(settings)
    site_ids = parse_site_ids(sites_str)

    with get_session(engine) as session:
        stmt = select(PowerReading, Site.name).join(Site)

        if site_ids:
            stmt = stmt.where(PowerReading.site_id.in_(site_ids))
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


@export.command("equipment", help="""
Export equipment list (inverters, optimizers, gateways).

EXAMPLES:
  seh export equipment
  seh export equipment --sites 123456 -f xlsx
""")
@click.option("--format", "-f", type=click.Choice(["csv", "json", "xlsx"]), default="csv", help="Output format.")
@click.option("--output", "-o", type=click.Path(), help="Output file path.")
@click.option("--sites", "-s", "sites_str", type=str, help="Comma-separated site IDs.")
@click.pass_context
def export_equipment(ctx: click.Context, format: str, output: str | None, sites_str: str | None) -> None:
    """Export equipment list."""
    from sqlalchemy import select

    from seh.db.engine import create_engine, get_session
    from seh.db.models.equipment import Equipment
    from seh.db.models.site import Site

    settings = load_settings(ctx.obj.get("config_path"))
    engine = create_engine(settings)
    site_ids = parse_site_ids(sites_str)

    with get_session(engine) as session:
        stmt = select(Equipment, Site.name).join(Site)

        if site_ids:
            stmt = stmt.where(Equipment.site_id.in_(site_ids))

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


@export.command("telemetry", help="""
Export inverter telemetry data.

EXAMPLES:
  seh export telemetry --sites 123456 --start 2024-06-01
  seh export telemetry --serial INV123456 -f xlsx
""")
@click.option("--format", "-f", type=click.Choice(["csv", "json", "xlsx"]), default="csv", help="Output format.")
@click.option("--output", "-o", type=click.Path(), help="Output file path.")
@click.option("--sites", "-s", "sites_str", type=str, help="Comma-separated site IDs.")
@click.option("--serial", type=str, help="Filter by inverter serial number.")
@click.option("--start", type=click.DateTime(), help="Start datetime (YYYY-MM-DD HH:MM:SS).")
@click.option("--end", type=click.DateTime(), help="End datetime (YYYY-MM-DD HH:MM:SS).")
@click.pass_context
def export_telemetry(ctx: click.Context, format: str, output: str | None, sites_str: str | None, serial: str | None, start: datetime | None, end: datetime | None) -> None:
    """Export inverter telemetry data."""
    from sqlalchemy import select

    from seh.db.engine import create_engine, get_session
    from seh.db.models.inverter_telemetry import InverterTelemetry
    from seh.db.models.site import Site

    settings = load_settings(ctx.obj.get("config_path"))
    engine = create_engine(settings)
    site_ids = parse_site_ids(sites_str)

    with get_session(engine) as session:
        stmt = select(InverterTelemetry, Site.name).join(Site)

        if site_ids:
            stmt = stmt.where(InverterTelemetry.site_id.in_(site_ids))
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


@export.command("inventory", help="""
Export equipment inventory items.

EXAMPLES:
  seh export inventory
  seh export inventory --sites 123456
""")
@click.option("--format", "-f", type=click.Choice(["csv", "json", "xlsx"]), default="csv", help="Output format.")
@click.option("--output", "-o", type=click.Path(), help="Output file path.")
@click.option("--sites", "-s", "sites_str", type=str, help="Comma-separated site IDs.")
@click.pass_context
def export_inventory(ctx: click.Context, format: str, output: str | None, sites_str: str | None) -> None:
    """Export inventory items."""
    from sqlalchemy import select

    from seh.db.engine import create_engine, get_session
    from seh.db.models.inventory import InventoryItem
    from seh.db.models.site import Site

    settings = load_settings(ctx.obj.get("config_path"))
    engine = create_engine(settings)
    site_ids = parse_site_ids(sites_str)

    with get_session(engine) as session:
        stmt = select(InventoryItem, Site.name).join(Site)

        if site_ids:
            stmt = stmt.where(InventoryItem.site_id.in_(site_ids))

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


@export.command("environmental", help="""
Export environmental benefits data (CO2 savings, tree equivalents).

EXAMPLES:
  seh export environmental
  seh export environmental -f xlsx -o environmental_report.xlsx
""")
@click.option("--format", "-f", type=click.Choice(["csv", "json", "xlsx"]), default="csv", help="Output format.")
@click.option("--output", "-o", type=click.Path(), help="Output file path.")
@click.option("--sites", "-s", "sites_str", type=str, help="Comma-separated site IDs.")
@click.pass_context
def export_environmental(ctx: click.Context, format: str, output: str | None, sites_str: str | None) -> None:
    """Export environmental benefits."""
    from sqlalchemy import select

    from seh.db.engine import create_engine, get_session
    from seh.db.models.environmental import EnvironmentalBenefits
    from seh.db.models.site import Site

    settings = load_settings(ctx.obj.get("config_path"))
    engine = create_engine(settings)
    site_ids = parse_site_ids(sites_str)

    with get_session(engine) as session:
        stmt = select(EnvironmentalBenefits, Site.name).join(Site)

        if site_ids:
            stmt = stmt.where(EnvironmentalBenefits.site_id.in_(site_ids))

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


@export.command("dump", help="""
Export database to SQL dump file.

Creates a SQL dump that can be used to restore the database.
Supports SQLite, PostgreSQL, and MariaDB.

EXAMPLES:
  seh export dump                     # Auto-named file
  seh export dump -o backup.sql       # Specific filename

NOTE: For large databases, this may take some time and
produce large files.
""")
@click.option("--output", "-o", type=click.Path(), help="Output file path.")
@click.pass_context
def export_dump(ctx: click.Context, output: str | None) -> None:
    """Export database to SQL dump."""
    settings = load_settings(ctx.obj.get("config_path"))

    if output is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"seh_dump_{timestamp}.sql"

    db_url = settings.database_url

    try:
        if "sqlite" in db_url:
            # SQLite dump
            db_path = db_url.replace("sqlite:///", "")
            result = subprocess.run(
                ["sqlite3", db_path, ".dump"],
                capture_output=True,
                text=True,
                check=True,
            )
            with open(output, "w") as f:
                f.write(result.stdout)

        elif "postgresql" in db_url:
            # PostgreSQL dump using pg_dump
            # Extract connection info from URL
            # Format: postgresql+psycopg://user:pass@host:port/db
            import urllib.parse
            parsed = urllib.parse.urlparse(db_url.replace("+psycopg", ""))

            env = os.environ.copy()
            if parsed.password:
                env["PGPASSWORD"] = parsed.password

            cmd = ["pg_dump"]
            if parsed.hostname:
                cmd.extend(["-h", parsed.hostname])
            if parsed.port:
                cmd.extend(["-p", str(parsed.port)])
            if parsed.username:
                cmd.extend(["-U", parsed.username])
            cmd.extend(["-f", output, parsed.path.lstrip("/")])

            subprocess.run(cmd, env=env, check=True)

        elif "mariadb" in db_url or "mysql" in db_url:
            # MariaDB/MySQL dump using mysqldump
            import urllib.parse
            parsed = urllib.parse.urlparse(db_url.replace("+mariadbconnector", "").replace("+pymysql", ""))

            cmd = ["mysqldump"]
            if parsed.hostname:
                cmd.extend(["-h", parsed.hostname])
            if parsed.port:
                cmd.extend(["-P", str(parsed.port)])
            if parsed.username:
                cmd.extend(["-u", parsed.username])
            if parsed.password:
                cmd.append(f"-p{parsed.password}")
            cmd.append(parsed.path.lstrip("/"))

            with open(output, "w") as f:
                subprocess.run(cmd, stdout=f, check=True)

        else:
            console.print(f"[red]Unsupported database type for dump: {db_url}[/red]")
            raise SystemExit(1)

        console.print(f"[green]Database exported to {output}[/green]")

    except subprocess.CalledProcessError as e:
        console.print(f"[red]Dump failed:[/red] {e}")
        raise SystemExit(1) from None
    except FileNotFoundError as e:
        console.print(f"[red]Dump tool not found:[/red] {e}")
        console.print("[yellow]Ensure sqlite3/pg_dump/mysqldump is installed and in PATH[/yellow]")
        raise SystemExit(1) from None


if __name__ == "__main__":
    cli()
