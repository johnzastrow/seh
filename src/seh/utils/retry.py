"""Retry decorator with exponential backoff."""

import asyncio
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import structlog

from seh.utils.exceptions import APIError, RateLimitError

P = ParamSpec("P")
T = TypeVar("T")

logger = structlog.get_logger(__name__)


def retry_with_backoff(
    max_retries: int = 5,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    exceptions: tuple[type[Exception], ...] = (APIError,),
) -> Callable[[Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]]:
    """Decorator that retries an async function with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Base delay in seconds (doubles each retry).
        max_delay: Maximum delay between retries.
        exceptions: Tuple of exception types to catch and retry.

    Returns:
        Decorated function.
    """

    def decorator(
        func: Callable[P, Coroutine[Any, Any, T]]
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_exception: Exception | None = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except RateLimitError:
                    # Don't retry rate limit errors
                    raise
                except APIError as e:
                    # Don't retry client errors (4xx) - they won't succeed on retry
                    if e.status_code and 400 <= e.status_code < 500:
                        raise
                    last_exception = e
                except exceptions as e:
                    last_exception = e

                    if attempt == max_retries:
                        logger.error(
                            "Max retries exceeded",
                            function=func.__name__,
                            attempts=attempt + 1,
                            error=str(e),
                        )
                        raise

                    delay = min(base_delay * (2**attempt), max_delay)
                    logger.warning(
                        "Retrying after error",
                        function=func.__name__,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)

            # This should never be reached, but satisfies type checker
            if last_exception:
                raise last_exception
            raise RuntimeError("Unexpected state in retry decorator")

        return wrapper

    return decorator
