"""Command-line interface for SolarEdge Harvest."""

import asyncio
import os
from datetime import datetime

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
    """Initialize the database schema."""
    from seh.config.logging import get_logger
    from seh.db.engine import create_engine, create_tables

    settings = load_settings(ctx.obj.get("config_path"))
    logger = get_logger(__name__)

    console.print("[bold]Initializing database...[/bold]")

    try:
        engine = create_engine(settings)
        create_tables(engine)
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


if __name__ == "__main__":
    cli()
