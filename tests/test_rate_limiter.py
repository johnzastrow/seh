"""Tests for API rate limiting and the monthly credit ledger."""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from structlog.testing import capture_logs

from seh.api.rate_limiter import CreditLedger, RateLimiter
from seh.utils.exceptions import RateLimitError


class FakeTime:
    """Monotonic clock whose sleep advances time instantly."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class MonthClock:
    def __init__(self, when: datetime) -> None:
        self.when = when

    def __call__(self) -> datetime:
        return self.when


@pytest.fixture
def fake_time() -> FakeTime:
    return FakeTime()


def limiter(fake_time: FakeTime, **kwargs) -> RateLimiter:
    return RateLimiter(monotonic=fake_time.monotonic, sleep=fake_time.sleep, **kwargs)


async def use(rl: RateLimiter, times: int = 1) -> None:
    for _ in range(times):
        async with rl:
            pass


class TestPerMinuteLimit:
    async def test_requests_under_limit_do_not_wait(self, fake_time):
        rl = limiter(fake_time, per_minute=10)
        await use(rl, 10)
        assert fake_time.sleeps == []
        assert rl.requests_last_minute == 10

    async def test_eleventh_request_waits_for_oldest_to_age_out(self, fake_time):
        rl = limiter(fake_time, per_minute=10)
        await use(rl, 5)
        fake_time.now += 20  # 5 more, 20 seconds later
        await use(rl, 5)

        await use(rl)

        assert fake_time.sleeps == [40.0]  # first five age out at t0 + 60
        assert rl.requests_last_minute == 6

    async def test_never_more_than_limit_in_any_minute(self, fake_time):
        rl = limiter(fake_time, per_minute=3)
        starts = []
        for _ in range(10):
            async with rl:
                starts.append(fake_time.now)
        for i in range(len(starts) - 3):
            assert starts[i + 3] - starts[i] >= 60

    async def test_server_reporting_zero_remaining_pauses_a_full_window(self, fake_time):
        rl = limiter(fake_time, per_minute=10)
        await use(rl)
        rl.note_remaining_minute("0")
        await use(rl)
        assert fake_time.sleeps == [60.0]

    @pytest.mark.parametrize("header", [None, "5", "junk"])
    def test_other_remaining_values_do_not_block(self, fake_time, header):
        rl = limiter(fake_time)
        rl.note_remaining_minute(header)
        assert rl._blocked_until == 0.0

    async def test_concurrency_is_bounded(self):
        rl = RateLimiter(max_concurrent=2, per_minute=100)
        active = peak = 0

        async def task():
            nonlocal active, peak
            async with rl:
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0.01)
                active -= 1

        await asyncio.gather(*(task() for _ in range(6)))
        assert peak == 2


class TestCreditLedger:
    def make(self, tmp_path, budget=5, when=datetime(2026, 10, 12, tzinfo=UTC)):
        return CreditLedger(tmp_path / "usage.json", budget, clock=MonthClock(when))

    def test_counts_persist_across_instances(self, tmp_path):
        self.make(tmp_path).consume()
        self.make(tmp_path).consume()
        assert self.make(tmp_path).usage() == ("2026-10", 2)

    def test_budget_exhaustion_raises_without_recording(self, tmp_path):
        ledger = self.make(tmp_path, budget=2)
        ledger.consume()
        ledger.consume()
        with pytest.raises(RateLimitError, match=r"2/2 for 2026-10"):
            ledger.consume()
        assert ledger.usage() == ("2026-10", 2)

    def test_new_month_starts_from_zero(self, tmp_path):
        self.make(tmp_path, budget=1).consume()
        november = self.make(tmp_path, budget=1, when=datetime(2026, 11, 1, tzinfo=UTC))
        assert november.usage() == ("2026-11", 0)
        november.consume()  # does not raise
        assert november.usage() == ("2026-11", 1)

    def test_unreadable_ledger_restarts_count_with_warning(self, tmp_path):
        (tmp_path / "usage.json").write_text("{broken", encoding="utf-8")
        with capture_logs() as logs:
            assert self.make(tmp_path).consume() == 1
        assert any("unreadable" in e["event"] for e in logs)

    def test_warns_once_at_eighty_percent(self, tmp_path):
        ledger = self.make(tmp_path, budget=10)
        with capture_logs() as logs:
            for _ in range(10):
                ledger.consume()
        warnings = [e for e in logs if e["event"] == "API credit budget mostly used"]
        assert len(warnings) == 1
        assert warnings[0]["used"] == 8

    def test_ledger_file_contents(self, tmp_path):
        self.make(tmp_path).consume()
        data = json.loads((tmp_path / "usage.json").read_text(encoding="utf-8"))
        assert data == {"month": "2026-10", "used": 1}


class TestLimiterWithLedger:
    async def test_budget_error_releases_concurrency_slot(self, fake_time, tmp_path):
        ledger = CreditLedger(tmp_path / "usage.json", 1)
        rl = limiter(fake_time, max_concurrent=1, ledger=ledger)
        await use(rl)
        for _ in range(3):  # would deadlock if the semaphore leaked
            with pytest.raises(RateLimitError):
                await use(rl)

    async def test_credits_used_reports_ledger(self, fake_time, tmp_path):
        ledger = CreditLedger(tmp_path / "usage.json", 100)
        rl = limiter(fake_time, ledger=ledger)
        await use(rl, 3)
        assert rl.credits_used()[1] == 3

    def test_no_ledger_means_no_credit_report(self, fake_time):
        assert limiter(fake_time).credits_used() is None
