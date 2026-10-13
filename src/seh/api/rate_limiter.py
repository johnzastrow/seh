"""Rate limiting for the SolarEdge Monitoring API V2.

Three limits apply to every request:

- concurrency: at most `max_concurrent` requests in flight;
- per minute: at most `per_minute` requests in any rolling 60 seconds (Free tier: 10).
  Callers wait for a slot instead of failing;
- monthly credits: each request costs 1 credit and the Free tier has 2000 per month with
  no overage. Usage is recorded in a small JSON ledger shared by all seh processes, and a
  request that would exceed the budget fails before it is sent.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
import time
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from seh.utils import filelock
from seh.utils.exceptions import RateLimitError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

logger = structlog.get_logger(__name__)

WINDOW_SECONDS = 60.0
# Warn once per process when this share of the monthly budget has been used.
WARN_FRACTION = 0.8


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CreditLedger:
    """Persistent count of API calls in the current calendar month (UTC)."""

    def __init__(
        self, path: Path, monthly_budget: int, clock: Callable[[], datetime] = _utcnow
    ) -> None:
        self.path = path
        self.lock_path = path.with_name(path.name + ".lock")
        self.monthly_budget = monthly_budget
        self._clock = clock
        self._warned = False

    def _month(self) -> str:
        return self._clock().strftime("%Y-%m")

    def usage(self) -> tuple[str, int]:
        """Return (month, credits used this month)."""
        with filelock.locked(self.lock_path):
            return self._month(), self._read_used()

    def consume(self) -> int:
        """Record one call and return the month's total; raise if the budget is spent."""
        with filelock.locked(self.lock_path):
            used = self._read_used()
            if used >= self.monthly_budget:
                raise RateLimitError(
                    f"Monthly API credit budget used ({used}/{self.monthly_budget} for "
                    f"{self._month()}). It resets on the 1st (UTC); raise "
                    "SEH_API_MONTHLY_CREDITS only if your SolarEdge plan allows more."
                )
            used += 1
            self._write_used(used)
        if not self._warned and used >= self.monthly_budget * WARN_FRACTION:
            self._warned = True
            logger.warning(
                "API credit budget mostly used",
                used=used,
                budget=self.monthly_budget,
                month=self._month(),
            )
        return used

    def _read_used(self) -> int:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return 0
        except (OSError, ValueError):
            logger.warning(
                "API credit ledger unreadable; starting count from zero", path=str(self.path)
            )
            return 0
        if not isinstance(data, dict) or data.get("month") != self._month():
            return 0  # new month (or unexpected content): count starts over
        used = data.get("used")
        return used if isinstance(used, int) and used >= 0 else 0

    def _write_used(self, used: int) -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".usage-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"month": self._month(), "used": used}, fh)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise


class RateLimiter:
    """Concurrency, rolling per-minute, and monthly-credit limits for API requests."""

    def __init__(
        self,
        max_concurrent: int = 3,
        per_minute: int = 10,
        ledger: CreditLedger | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        """Initialize the rate limiter.

        Args:
            max_concurrent: Maximum requests in flight.
            per_minute: Maximum requests started in any rolling 60 seconds.
            ledger: Monthly credit ledger; None disables credit accounting.
            monotonic: Clock, injectable for tests.
            sleep: Async sleep, injectable for tests.
        """
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._per_minute = per_minute
        self._ledger = ledger
        self._monotonic = monotonic
        self._sleep = sleep
        self._starts: deque[float] = deque()
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait for a request slot.

        Raises:
            RateLimitError: If the monthly credit budget is used up.
        """
        await self._semaphore.acquire()
        try:
            async with self._lock:
                await self._wait_for_minute_slot()
                if self._ledger is not None:
                    await asyncio.to_thread(self._ledger.consume)
                self._starts.append(self._monotonic())
        except BaseException:
            self._semaphore.release()
            raise

    async def _wait_for_minute_slot(self) -> None:
        while True:
            now = self._monotonic()
            while self._starts and now - self._starts[0] >= WINDOW_SECONDS:
                self._starts.popleft()
            waits = []
            if len(self._starts) >= self._per_minute:
                waits.append(self._starts[0] + WINDOW_SECONDS - now)
            if self._blocked_until > now:
                waits.append(self._blocked_until - now)
            if not waits:
                return
            wait = max(waits)
            logger.debug("Waiting for API rate limit", seconds=round(wait, 1))
            await self._sleep(wait)

    async def release(self) -> None:
        """Release the slot after a request completes."""
        self._semaphore.release()

    def note_remaining_minute(self, remaining: str | None) -> None:
        """Honour SolarEdge's x-ratelimit-remaining-minute header.

        Other clients of the same app share the per-minute quota, so when SolarEdge reports
        none left, pause new requests for a full window.
        """
        try:
            left = int(remaining) if remaining is not None else None
        except ValueError:
            return
        if left is not None and left <= 0:
            self._blocked_until = self._monotonic() + WINDOW_SECONDS

    @property
    def requests_last_minute(self) -> int:
        now = self._monotonic()
        return sum(1 for t in self._starts if now - t < WINDOW_SECONDS)

    def credits_used(self) -> tuple[str, int] | None:
        """(month, credits used) from the ledger, or None without one."""
        return self._ledger.usage() if self._ledger is not None else None

    async def __aenter__(self) -> RateLimiter:
        """Context manager entry."""
        await self.acquire()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Context manager exit."""
        await self.release()
