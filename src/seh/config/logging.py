"""Logging configuration using structlog with operation tracking and email notifications."""

import logging
import smtplib
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

from seh.config.settings import Settings


@dataclass
class SyncStats:
    """Statistics for a sync operation."""

    data_type: str
    site_id: int | None = None
    records_processed: int = 0
    records_inserted: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    duration_seconds: float = 0.0

    def finish(self) -> None:
        """Mark the operation as complete and calculate duration."""
        self.end_time = datetime.now(timezone.utc)
        self.duration_seconds = (self.end_time - self.start_time).total_seconds()

    def add_error(self, error: str) -> None:
        """Add an error message."""
        self.errors.append(error)

    def add_warning(self, warning: str) -> None:
        """Add a warning message."""
        self.warnings.append(warning)

    @property
    def success(self) -> bool:
        """Check if the operation was successful (no errors)."""
        return len(self.errors) == 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "data_type": self.data_type,
            "site_id": self.site_id,
            "records_processed": self.records_processed,
            "records_inserted": self.records_inserted,
            "records_updated": self.records_updated,
            "records_skipped": self.records_skipped,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "duration_seconds": self.duration_seconds,
            "success": self.success,
        }


@dataclass
class SyncSummary:
    """Summary of a complete sync operation across all sites and data types."""

    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    duration_seconds: float = 0.0
    sites_processed: int = 0
    total_records: int = 0
    stats: list[SyncStats] = field(default_factory=list)

    def add_stats(self, stats: SyncStats) -> None:
        """Add stats from a sync operation."""
        self.stats.append(stats)
        self.total_records += stats.records_processed

    def finish(self) -> None:
        """Mark the sync as complete."""
        self.end_time = datetime.now(timezone.utc)
        self.duration_seconds = (self.end_time - self.start_time).total_seconds()

    @property
    def total_errors(self) -> int:
        """Get total error count across all operations."""
        return sum(len(s.errors) for s in self.stats)

    @property
    def total_warnings(self) -> int:
        """Get total warning count across all operations."""
        return sum(len(s.warnings) for s in self.stats)

    @property
    def success(self) -> bool:
        """Check if the entire sync was successful."""
        return self.total_errors == 0

    @property
    def all_errors(self) -> list[tuple[str, int | None, str]]:
        """Get all errors as (data_type, site_id, error) tuples."""
        errors = []
        for s in self.stats:
            for error in s.errors:
                errors.append((s.data_type, s.site_id, error))
        return errors

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            "sites_processed": self.sites_processed,
            "total_records": self.total_records,
            "total_errors": self.total_errors,
            "total_warnings": self.total_warnings,
            "duration_seconds": self.duration_seconds,
            "success": self.success,
            "operations": [s.to_dict() for s in self.stats],
        }

    def format_text_summary(self) -> str:
        """Format a human-readable text summary."""
        lines = [
            "=" * 60,
            "SYNC SUMMARY",
            "=" * 60,
            f"Status: {'SUCCESS' if self.success else 'FAILED'}",
            f"Duration: {self.duration_seconds:.1f} seconds",
            f"Sites processed: {self.sites_processed}",
            f"Total records: {self.total_records}",
            f"Errors: {self.total_errors}",
            f"Warnings: {self.total_warnings}",
            "",
            "OPERATIONS:",
            "-" * 40,
        ]

        for s in self.stats:
            site_str = f" (site {s.site_id})" if s.site_id else ""
            status = "OK" if s.success else "FAILED"
            lines.append(
                f"  {s.data_type}{site_str}: {s.records_processed} records, "
                f"{len(s.errors)} errors [{status}]"
            )

        if self.total_errors > 0:
            lines.extend(["", "ERRORS:", "-" * 40])
            for data_type, site_id, error in self.all_errors:
                site_str = f" (site {site_id})" if site_id else ""
                lines.append(f"  [{data_type}{site_str}] {error}")

        lines.append("=" * 60)
        return "\n".join(lines)


class EmailNotifier:
    """Send email notifications for sync operations."""

    def __init__(self, settings: Settings) -> None:
        """Initialize email notifier with settings."""
        self.settings = settings
        self._logger = structlog.get_logger("email_notifier")

    def send_notification(
        self,
        subject: str,
        body: str,
        html_body: str | None = None,
    ) -> bool:
        """Send an email notification.

        Args:
            subject: Email subject line.
            body: Plain text body.
            html_body: Optional HTML body.

        Returns:
            True if email was sent successfully.
        """
        if not self.settings.smtp_enabled:
            return False

        if not self.settings.smtp_from_email:
            self._logger.error("SMTP from_email not configured")
            return False

        to_emails = self.settings.get_to_email_list()
        if not to_emails:
            self._logger.error("SMTP to_emails not configured")
            return False

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.settings.smtp_from_email
            msg["To"] = ", ".join(to_emails)

            # Attach plain text
            msg.attach(MIMEText(body, "plain"))

            # Attach HTML if provided
            if html_body:
                msg.attach(MIMEText(html_body, "html"))

            # Connect and send
            if self.settings.smtp_use_tls:
                server = smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port)
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self.settings.smtp_host, self.settings.smtp_port)

            if self.settings.smtp_username and self.settings.smtp_password:
                password = self.settings.smtp_password.get_secret_value()
                server.login(self.settings.smtp_username, password)

            server.sendmail(
                self.settings.smtp_from_email,
                to_emails,
                msg.as_string(),
            )
            server.quit()

            self._logger.info("Email notification sent", subject=subject, recipients=len(to_emails))
            return True

        except Exception as e:
            self._logger.error("Failed to send email notification", error=str(e))
            return False

    def notify_sync_complete(self, summary: SyncSummary) -> bool:
        """Send notification about sync completion.

        Args:
            summary: Sync summary to include in notification.

        Returns:
            True if notification was sent.
        """
        if summary.success and not self.settings.notify_on_success:
            return False
        if not summary.success and not self.settings.notify_on_error:
            return False

        status = "SUCCESS" if summary.success else "FAILED"
        subject = f"[SEH] Sync {status} - {summary.sites_processed} sites, {summary.total_records} records"

        body = summary.format_text_summary()

        html_body = self._format_html_summary(summary)

        return self.send_notification(subject, body, html_body)

    def _format_html_summary(self, summary: SyncSummary) -> str:
        """Format an HTML summary for email."""
        status_color = "green" if summary.success else "red"
        status_text = "SUCCESS" if summary.success else "FAILED"

        rows = []
        for s in summary.stats:
            site_str = f" (site {s.site_id})" if s.site_id else ""
            row_color = "#f0f0f0" if s.success else "#ffcccc"
            rows.append(
                f'<tr style="background-color: {row_color}">'
                f"<td>{s.data_type}{site_str}</td>"
                f"<td>{s.records_processed}</td>"
                f"<td>{len(s.errors)}</td>"
                f'<td>{"OK" if s.success else "FAILED"}</td>'
                f"</tr>"
            )

        error_html = ""
        if summary.total_errors > 0:
            error_rows = []
            for data_type, site_id, error in summary.all_errors:
                site_str = f" (site {site_id})" if site_id else ""
                error_rows.append(f"<li><strong>{data_type}{site_str}:</strong> {error}</li>")
            error_html = f'<h3>Errors</h3><ul>{"".join(error_rows)}</ul>'

        return f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h2 style="color: {status_color};">Sync {status_text}</h2>
            <p>
                <strong>Duration:</strong> {summary.duration_seconds:.1f} seconds<br>
                <strong>Sites:</strong> {summary.sites_processed}<br>
                <strong>Total records:</strong> {summary.total_records}<br>
                <strong>Errors:</strong> {summary.total_errors}<br>
                <strong>Warnings:</strong> {summary.total_warnings}
            </p>
            <h3>Operations</h3>
            <table border="1" cellpadding="5" cellspacing="0">
                <tr style="background-color: #ddd;">
                    <th>Data Type</th>
                    <th>Records</th>
                    <th>Errors</th>
                    <th>Status</th>
                </tr>
                {"".join(rows)}
            </table>
            {error_html}
        </body>
        </html>
        """


class OperationTimer:
    """Context manager for timing operations."""

    def __init__(self, operation_name: str, logger: Any = None, **context: Any) -> None:
        """Initialize timer.

        Args:
            operation_name: Name of the operation being timed.
            logger: Optional logger to use.
            **context: Additional context to log.
        """
        self.operation_name = operation_name
        self.logger = logger or structlog.get_logger()
        self.context = context
        self.start_time: float = 0
        self.end_time: float = 0

    def __enter__(self) -> "OperationTimer":
        """Start timing."""
        self.start_time = time.time()
        self.logger.info(
            f"Starting {self.operation_name}",
            operation=self.operation_name,
            **self.context,
        )
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Stop timing and log duration."""
        self.end_time = time.time()
        duration = self.end_time - self.start_time

        if exc_type is not None:
            self.logger.error(
                f"Failed {self.operation_name}",
                operation=self.operation_name,
                duration_seconds=duration,
                error=str(exc_val),
                **self.context,
            )
        else:
            self.logger.info(
                f"Completed {self.operation_name}",
                operation=self.operation_name,
                duration_seconds=duration,
                **self.context,
            )

    @property
    def duration(self) -> float:
        """Get duration in seconds."""
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time


def configure_logging(settings: Settings) -> None:
    """Configure structlog and standard logging.

    Args:
        settings: Application settings containing logging configuration.
    """
    # Map string log level to logging constant
    log_level = getattr(logging, settings.log_level)

    # Configure standard logging
    handlers: list[logging.Handler] = []

    # Console handler (always enabled)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    handlers.append(console_handler)

    # File handler (if configured)
    if settings.log_file:
        log_path = Path(settings.log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            filename=log_path,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
        )
        file_handler.setLevel(log_level)
        handlers.append(file_handler)

    # Configure root logger
    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        format="%(message)s",
    )

    # Determine if we're in a TTY for colored output
    is_tty = sys.stdout.isatty()

    # Configure processors based on environment
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.ExtraAdder(),
    ]

    if is_tty:
        # Development: colored console output
        processors: list[structlog.types.Processor] = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(colors=True),
        ]
    else:
        # Production: JSON output
        processors = [
            *shared_processors,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Optional logger name (typically __name__).

    Returns:
        A bound structlog logger.
    """
    return structlog.get_logger(name)
