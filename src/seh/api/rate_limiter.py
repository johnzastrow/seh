"""Rate limiter for SolarEdge API requests."""

import asyncio
from datetime import datetime, timedelta
from typing import Any

import structlog

from seh.utils.exceptions import RateLimitError

logger = structlog.get_logger(__name__)


class RateLimiter:
    """Rate limiter with concurrent request limit and daily quota tracking."""

    def __init__(
        self,
        max_concurrent: int = 3,
        daily_limit: int = 300,
    ) -> None:
        """Initialize the rate limiter.

        Args:
            max_concurrent: Maximum concurrent requests allowed.
            daily_limit: Maximum requests per day.
        """
        self._max_concurrent = max_concurrent
        self._daily_limit = daily_limit
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._request_times: list[datetime] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire permission to make a request.

        Raises:
            RateLimitError: If daily limit would be exceeded.
        """
        async with self._lock:
            # Clean up old request times (older than 24 hours)
            cutoff = datetime.now() - timedelta(days=1)
            self._request_times = [t for t in self._request_times if t > cutoff]

            # Check daily limit
            if len(self._request_times) >= self._daily_limit:
                oldest = min(self._request_times)
                wait_until = oldest + timedelta(days=1)
                raise RateLimitError(
                    f"Daily API limit ({self._daily_limit}) reached. "
                    f"Resets at {wait_until.isoformat()}"
                )

        # Acquire semaphore for concurrent limit
        await self._semaphore.acquire()

    async def release(self) -> None:
        """Release the rate limiter after a request completes."""
        async with self._lock:
            self._request_times.append(datetime.now())
        self._semaphore.release()

    async def __aenter__(self) -> "RateLimiter":
        """Context manager entry."""
        await self.acquire()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Context manager exit."""
        await self.release()

    @property
    def requests_today(self) -> int:
        """Get the number of requests made in the last 24 hours."""
        cutoff = datetime.now() - timedelta(days=1)
        return len([t for t in self._request_times if t > cutoff])

    @property
    def remaining_requests(self) -> int:
        """Get the number of remaining requests for today."""
        return max(0, self._daily_limit - self.requests_today)
