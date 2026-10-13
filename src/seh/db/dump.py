"""SQL dumps of the seh database without exposing the database password.

Command-line arguments are visible to every user on the machine (`ps`, /proc/<pid>/cmdline),
so passwords are never passed as arguments. Instead the dump tools read them from a
temporary credentials file that only the current user can read and that is deleted as
soon as the dump finishes:

- MariaDB/MySQL: an option file passed with --defaults-extra-file
- PostgreSQL: a password file passed through PGPASSFILE

The dump file itself is created owner-only (0600 on POSIX), because it contains all
harvested data, including the site address.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
from typing import TYPE_CHECKING

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from seh.utils.exceptions import SEHError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import URL


class DumpError(SEHError):
    """The database dump failed. Messages never contain the database password."""


def safe_url(db_url: str) -> str:
    """Database URL with the password masked, for messages."""
    try:
        return make_url(db_url).render_as_string(hide_password=True)
    except ArgumentError:
        return "<unparseable database URL>"


def dump_database(db_url: str, output: str) -> None:
    """Write a SQL dump of the database at `db_url` to `output`.

    Raises:
        DumpError: If the database type is unsupported, the dump tool is missing,
            or the tool fails.
    """
    try:
        url = make_url(db_url)
    except ArgumentError:
        raise DumpError("SEH_DATABASE_URL is not a valid database URL.") from None

    backend = url.get_backend_name()
    if backend == "sqlite":
        cmd, env, secrets_file = _sqlite_command(url), None, None
    elif backend == "postgresql":
        secrets_file = _write_private_file(_pgpass_line(url)) if url.password else None
        cmd = _pg_dump_command(url)
        env = {**os.environ, "PGPASSFILE": secrets_file} if secrets_file else None
        if env is not None:
            env.pop("PGPASSWORD", None)
    elif backend in ("mysql", "mariadb"):
        secrets_file = _write_private_file(_mysql_option_file(url)) if url.password else None
        cmd, env = _mysqldump_command(url, secrets_file), None
    else:
        raise DumpError(f"Unsupported database type for dump: {safe_url(db_url)}")

    try:
        _run_to_file(cmd, env, output)
    finally:
        if secrets_file:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(secrets_file)


def _sqlite_command(url: URL) -> list[str]:
    if not url.database or url.database == ":memory:":
        raise DumpError("Cannot dump an in-memory SQLite database.")
    return ["sqlite3", url.database, ".dump"]


def _pg_dump_command(url: URL) -> list[str]:
    cmd = ["pg_dump", "--no-password"]
    if url.host:
        cmd += ["-h", url.host]
    if url.port:
        cmd += ["-p", str(url.port)]
    if url.username:
        cmd += ["-U", url.username]
    cmd.append(url.database or "")
    return cmd


def _pgpass_line(url: URL) -> str:
    """One .pgpass entry; ':' and '\\' must be escaped in every field."""

    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace(":", "\\:")

    fields = [url.host or "*", str(url.port or "*"), url.database or "*", url.username or "*"]
    return (
        ":".join(esc(f) if f != "*" else f for f in fields) + ":" + esc(url.password or "") + "\n"
    )


def _mysqldump_command(url: URL, option_file: str | None) -> list[str]:
    # --defaults-extra-file must be the first option to take effect.
    cmd = ["mysqldump"]
    if option_file:
        cmd.append(f"--defaults-extra-file={option_file}")
    cmd.append("--single-transaction")  # consistent InnoDB snapshot without locking tables
    if url.host:
        cmd += ["-h", url.host]
    if url.port:
        cmd += ["-P", str(url.port)]
    if url.username:
        cmd += ["-u", url.username]
    cmd.append(url.database or "")
    return cmd


def _mysql_option_file(url: URL) -> str:
    """[client] section with a double-quoted, escaped password."""
    password = (url.password or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'[client]\npassword="{password}"\n'


def _write_private_file(content: str) -> str:
    """Write a temporary file readable only by the current user; return its path."""
    fd, path = tempfile.mkstemp(prefix="seh-dump-", suffix=".cnf")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        if os.name == "posix":
            os.chmod(path, 0o600)  # mkstemp already uses 0600; make it explicit
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(path)
        raise
    return path


@contextlib.contextmanager
def _private_output(path: str) -> Iterator[int]:
    """Open the dump file for writing with owner-only permissions."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        if os.name == "posix":
            os.chmod(path, 0o600)  # an existing file keeps its old mode otherwise
        yield fd
    finally:
        os.close(fd)


def _run_to_file(cmd: list[str], env: dict[str, str] | None, output: str) -> None:
    if shutil.which(cmd[0]) is None:
        raise DumpError(f"{cmd[0]} not found. Install it and make sure it is on PATH.")
    with _private_output(output) as fd:
        try:
            subprocess.run(cmd, stdout=fd, stderr=subprocess.PIPE, env=env, check=True)
        except subprocess.CalledProcessError as e:
            # The command line holds no secrets, but keep the message to the tool's own error.
            detail = (e.stderr or b"").decode("utf-8", "replace").strip()[:500]
            raise DumpError(f"{cmd[0]} failed (exit code {e.returncode}): {detail}") from None
