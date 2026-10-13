"""Cross-process exclusive file locks (fcntl on POSIX, msvcrt on Windows).

Used to serialize OAuth token refreshes and API credit accounting between seh processes,
for example a cron sync and a manual run. Locks are advisory and blocking.
"""

from __future__ import annotations

import contextlib
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def acquire(lock_path: Path) -> int:
    """Block until the lock is held; returns the descriptor to pass to release()."""
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            # LK_LOCK retries for about 10 seconds before raising OSError.
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
    except BaseException:
        os.close(fd)
        raise
    return fd


def release(fd: int) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


@contextlib.contextmanager
def locked(lock_path: Path) -> Iterator[None]:
    fd = acquire(lock_path)
    try:
        yield
    finally:
        release(fd)
