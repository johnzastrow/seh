"""Tests for database dumps (seh.db.dump and 'seh export dump')."""

import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from seh.cli import cli
from seh.db import dump as dump_module
from seh.db.dump import DumpError, dump_database, safe_url

SECRET = 'p@ss:w\\o"rd'  # characters that need escaping in every credentials format
ENCODED_SECRET = "p%40ss%3Aw%5Co%22rd"


class FakeRun:
    """Captures the dump command and the credentials file contents while it runs."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.cmd: list[str] = []
        self.env: dict | None = None
        self.secrets_file: str | None = None
        self.secrets_content: str | None = None

    def __call__(self, cmd, stdout, stderr, env, check):
        self.cmd, self.env = cmd, env
        for arg in cmd:
            if arg.startswith("--defaults-extra-file="):
                self.secrets_file = arg.split("=", 1)[1]
        if env and env.get("PGPASSFILE"):
            self.secrets_file = env["PGPASSFILE"]
        if self.secrets_file:
            self.secrets_content = Path(self.secrets_file).read_text(encoding="utf-8")
            if os.name == "posix":
                assert os.stat(self.secrets_file).st_mode & 0o777 == 0o600
        os.write(stdout, b"-- dump --\n")
        if self.fail:
            raise subprocess.CalledProcessError(2, cmd, stderr=b"Access denied for user")


@pytest.fixture
def fake_run(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(dump_module.subprocess, "run", run)
    monkeypatch.setattr(dump_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    return run


def mariadb_url(password: str = ENCODED_SECRET) -> str:
    return f"mariadb+mariadbconnector://jcz:{password}@localhost:3306/weather"


class TestMariaDB:
    def test_password_never_on_command_line(self, fake_run, tmp_path):
        dump_database(mariadb_url(), str(tmp_path / "out.sql"))

        joined = " ".join(fake_run.cmd)
        assert SECRET not in joined and ENCODED_SECRET not in joined
        assert not any(a.startswith("-p") and a != "-P" for a in fake_run.cmd)
        assert fake_run.cmd[0] == "mysqldump"
        assert fake_run.cmd[1].startswith("--defaults-extra-file=")  # must come first
        assert "--single-transaction" in fake_run.cmd
        assert fake_run.cmd[-1] == "weather"

    def test_option_file_has_decoded_escaped_password_and_is_removed(self, fake_run, tmp_path):
        dump_database(mariadb_url(), str(tmp_path / "out.sql"))

        assert fake_run.secrets_content == '[client]\npassword="p@ss:w\\\\o\\"rd"\n'
        assert not Path(fake_run.secrets_file).exists()

    def test_option_file_removed_when_dump_fails(self, monkeypatch, tmp_path):
        run = FakeRun(fail=True)
        monkeypatch.setattr(dump_module.subprocess, "run", run)
        monkeypatch.setattr(dump_module.shutil, "which", lambda name: name)

        with pytest.raises(DumpError, match="Access denied") as exc_info:
            dump_database(mariadb_url(), str(tmp_path / "out.sql"))

        assert SECRET not in str(exc_info.value)
        assert not Path(run.secrets_file).exists()

    def test_no_password_means_no_option_file(self, fake_run, tmp_path):
        dump_database("mysql+pymysql://jcz@localhost/weather", str(tmp_path / "out.sql"))
        assert not any(a.startswith("--defaults-extra-file") for a in fake_run.cmd)


class TestPostgreSQL:
    def test_password_passed_via_pgpass_file(self, fake_run, tmp_path, monkeypatch):
        monkeypatch.setenv("PGPASSWORD", "stale-value")
        url = f"postgresql+psycopg://seh:{ENCODED_SECRET}@db.local:5432/seh"

        dump_database(url, str(tmp_path / "out.sql"))

        assert SECRET not in " ".join(fake_run.cmd)
        assert fake_run.cmd[:2] == ["pg_dump", "--no-password"]
        assert "PGPASSWORD" not in fake_run.env
        assert fake_run.secrets_content == 'db.local:5432:seh:seh:p@ss\\:w\\\\o"rd\n'
        assert not Path(fake_run.secrets_file).exists()


class TestSQLite:
    def test_dumps_file_database(self, fake_run, tmp_path):
        dump_database("sqlite:///./seh.db", str(tmp_path / "out.sql"))
        assert fake_run.cmd == ["sqlite3", "./seh.db", ".dump"]

    def test_in_memory_database_is_rejected(self, fake_run, tmp_path):
        with pytest.raises(DumpError, match="in-memory"):
            dump_database("sqlite:///:memory:", str(tmp_path / "out.sql"))


class TestOutputAndErrors:
    @pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
    def test_dump_file_is_owner_only_even_if_it_existed(self, fake_run, tmp_path):
        out = tmp_path / "out.sql"
        out.write_text("old", encoding="utf-8")
        os.chmod(out, 0o644)

        dump_database(mariadb_url(), str(out))

        assert out.stat().st_mode & 0o777 == 0o600
        assert out.read_text(encoding="utf-8") == "-- dump --\n"

    def test_unsupported_database_message_hides_password(self, fake_run, tmp_path):
        with pytest.raises(DumpError) as exc_info:
            dump_database(f"oracle://scott:{ENCODED_SECRET}@db/orcl", str(tmp_path / "x.sql"))
        assert ENCODED_SECRET not in str(exc_info.value)
        assert SECRET not in str(exc_info.value)

    def test_missing_tool_is_reported(self, monkeypatch, tmp_path):
        monkeypatch.setattr(dump_module.shutil, "which", lambda name: None)
        with pytest.raises(DumpError, match="mysqldump not found"):
            dump_database(mariadb_url(), str(tmp_path / "out.sql"))

    def test_safe_url_masks_password(self):
        assert ENCODED_SECRET not in safe_url(mariadb_url())
        assert "***" in safe_url(mariadb_url())


def test_cli_export_dump_reports_failure_without_password(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEH_DATABASE_URL", mariadb_url())
    monkeypatch.delenv("SEH_LOG_FILE", raising=False)
    run = FakeRun(fail=True)
    monkeypatch.setattr(dump_module.subprocess, "run", run)
    monkeypatch.setattr(dump_module.shutil, "which", lambda name: name)

    result = CliRunner().invoke(cli, ["export", "dump", "-o", "backup.sql"])

    assert result.exit_code == 1
    assert "Dump failed" in result.output
    assert SECRET not in result.output and ENCODED_SECRET not in result.output
