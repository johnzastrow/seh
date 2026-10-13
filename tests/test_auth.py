"""Tests for OAuth token storage and refresh (seh.api.auth)."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from structlog.testing import capture_logs

from seh.api.auth import OAuthTokenManager, TokenSet, TokenStore
from seh.config.settings import Settings
from seh.utils.exceptions import APIError, AuthenticationError

NOW = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)
TOKEN_URL = "https://monitoringapi.solaredge.com/v2/oauth2/token"
REVOKE_URL = "https://monitoringapi.solaredge.com/v2/oauth2/revoke-token"


class FakeClock:
    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class TokenEndpoint:
    """httpx MockTransport handler that issues rotating tokens and records requests."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.counter = 0
        self.fail_with: tuple[int, dict] | None = None
        self.delay = 0.0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append((str(request.url), body))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_with:
            status, payload = self.fail_with
            return httpx.Response(status, json=payload)
        if str(request.url) == REVOKE_URL:
            return httpx.Response(200)
        self.counter += 1
        return httpx.Response(
            200,
            json={
                "access_token": f"access-{self.counter}",
                "refresh_token": f"refresh-{self.counter}",
                "token_type": "bearer",
                "expires_in": 7200,
            },
        )

    def refresh_calls(self) -> list[dict]:
        return [b for _, b in self.requests if b.get("grant_type") == "refresh_token"]


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    for var in ("SEH_OAUTH_CLIENT_ID", "SEH_OAUTH_CLIENT_SECRET", "SEH_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return Settings(
        _env_file=None,
        oauth_client_id="client-id",
        oauth_client_secret="client-secret",
        token_file=str(tmp_path / "seh" / "tokens.json"),
        site_ids="123",
    )


@pytest.fixture
def endpoint() -> TokenEndpoint:
    return TokenEndpoint()


@pytest.fixture
def store(settings) -> TokenStore:
    return TokenStore(settings.token_path)


def make_tokens(access="access-0", refresh="refresh-0", expires_in=7200, now=NOW) -> TokenSet:
    return TokenSet.from_token_response(
        {"access_token": access, "refresh_token": refresh, "expires_in": expires_in},
        now,
        site_id=123,
    )


def make_manager(settings, store, endpoint, clock=None) -> OAuthTokenManager:
    http = httpx.AsyncClient(transport=httpx.MockTransport(endpoint))
    return OAuthTokenManager(settings, store=store, http_client=http, clock=clock or FakeClock())


class TestTokenSet:
    def test_from_token_response_computes_expiry(self):
        tokens = make_tokens(expires_in=7200)
        assert tokens.expires_at == NOW + timedelta(seconds=7200)
        assert tokens.site_id == 123

    def test_from_token_response_keeps_previous_refresh_token_when_not_rotated(self):
        previous = make_tokens()
        tokens = TokenSet.from_token_response(
            {"access_token": "new", "expires_in": 60}, NOW, previous=previous
        )
        assert tokens.refresh_token.get_secret_value() == "refresh-0"
        assert tokens.site_id == 123

    def test_from_token_response_without_access_token_raises(self):
        with pytest.raises(APIError):
            TokenSet.from_token_response({"refresh_token": "r"}, NOW)

    def test_repr_hides_secrets(self):
        tokens = make_tokens(access="very-secret-access", refresh="very-secret-refresh")
        text = repr(tokens) + str(tokens)
        assert "very-secret-access" not in text
        assert "very-secret-refresh" not in text

    def test_expires_within(self):
        tokens = make_tokens(expires_in=100)
        assert tokens.expires_within(timedelta(seconds=120), NOW)
        assert not tokens.expires_within(timedelta(seconds=60), NOW)


class TestTokenStore:
    def test_load_missing_file_returns_none(self, store):
        assert store.load() is None

    def test_save_then_load_round_trips(self, store):
        store.save(make_tokens())
        loaded = store.load()
        assert loaded is not None
        assert loaded.access_token.get_secret_value() == "access-0"
        assert loaded.refresh_token.get_secret_value() == "refresh-0"
        assert loaded.expires_at == NOW + timedelta(seconds=7200)

    def test_save_leaves_no_temp_files(self, store):
        store.save(make_tokens())
        store.save(make_tokens(access="access-1"))
        assert sorted(p.name for p in store.path.parent.iterdir()) == ["tokens.json"]

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
    def test_save_writes_owner_only_file_and_directory(self, store):
        store.save(make_tokens())
        assert store.path.stat().st_mode & 0o777 == 0o600
        assert store.path.parent.stat().st_mode & 0o777 == 0o700

    @pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
    def test_load_tightens_loose_permissions(self, store):
        store.save(make_tokens())
        os.chmod(store.path, 0o644)
        store.load()
        assert store.path.stat().st_mode & 0o777 == 0o600

    def test_corrupt_file_raises_authentication_error(self, store):
        store.path.parent.mkdir(parents=True)
        store.path.write_text("{not json", encoding="utf-8")
        with pytest.raises(AuthenticationError, match="seh auth login"):
            store.load()

    def test_unknown_version_raises_authentication_error(self, store):
        store.save(make_tokens())
        data = json.loads(store.path.read_text(encoding="utf-8"))
        data["version"] = 99
        store.path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(AuthenticationError):
            store.load()

    def test_delete_is_idempotent(self, store):
        store.save(make_tokens())
        store.delete()
        store.delete()
        assert not store.path.exists()

    def test_lock_can_be_acquired_and_released_repeatedly(self, store):
        for _ in range(3):
            fd = store.acquire_lock()
            store.release_lock(fd)


class TestOAuthTokenManager:
    async def test_not_signed_in_raises(self, settings, store, endpoint):
        manager = make_manager(settings, store, endpoint)
        with pytest.raises(AuthenticationError, match="seh auth login"):
            await manager.get_access_token()

    async def test_fresh_token_is_used_without_refresh(self, settings, store, endpoint):
        store.save(make_tokens())
        manager = make_manager(settings, store, endpoint)
        assert await manager.get_access_token() == "access-0"
        assert endpoint.requests == []

    async def test_expiring_token_is_refreshed_and_rotation_persisted(
        self, settings, store, endpoint
    ):
        store.save(make_tokens(expires_in=60))  # inside the refresh margin
        manager = make_manager(settings, store, endpoint)

        assert await manager.get_access_token() == "access-1"

        [call] = endpoint.refresh_calls()
        assert call == {
            "grant_type": "refresh_token",
            "refresh_token": "refresh-0",
            "client_id": "client-id",
            "client_secret": "client-secret",
        }
        on_disk = store.load()
        assert on_disk.refresh_token.get_secret_value() == "refresh-1"
        assert on_disk.site_id == 123  # metadata survives refresh

    async def test_concurrent_callers_share_one_refresh(self, settings, store, endpoint):
        store.save(make_tokens(expires_in=0))
        endpoint.delay = 0.05
        manager = make_manager(settings, store, endpoint)

        results = await asyncio.gather(*(manager.get_access_token() for _ in range(5)))

        assert set(results) == {"access-1"}
        assert len(endpoint.refresh_calls()) == 1

    async def test_uses_token_refreshed_by_another_process(self, settings, store, endpoint):
        clock = FakeClock()
        store.save(make_tokens())
        stale = make_manager(settings, store, endpoint, clock)
        assert await stale.get_access_token() == "access-0"  # cached in memory

        # Another process refreshes, rotating the refresh token on disk.
        other = make_manager(settings, store, endpoint, clock)
        clock.now = NOW + timedelta(seconds=7150)
        assert await other.get_access_token() == "access-1"

        # The first process must adopt the new token instead of reusing refresh-0.
        assert await stale.get_access_token() == "access-1"
        assert [c["refresh_token"] for c in endpoint.refresh_calls()] == ["refresh-0"]

    async def test_rejected_refresh_raises_and_keeps_file(self, settings, store, endpoint):
        store.save(make_tokens(expires_in=0))
        endpoint.fail_with = (400, {"error": "invalid_grant"})
        manager = make_manager(settings, store, endpoint)

        with pytest.raises(AuthenticationError, match="invalid_grant"):
            await manager.get_access_token()
        assert store.load().refresh_token.get_secret_value() == "refresh-0"

    async def test_server_error_raises_api_error(self, settings, store, endpoint):
        store.save(make_tokens(expires_in=0))
        endpoint.fail_with = (503, {"title": "Service Unavailable"})
        manager = make_manager(settings, store, endpoint)

        with pytest.raises(APIError) as exc_info:
            await manager.get_access_token()
        assert not isinstance(exc_info.value, AuthenticationError)
        assert exc_info.value.status_code == 503

    async def test_network_error_raises_api_error(self, settings, store):
        store.save(make_tokens(expires_in=0))

        def boom(request):
            raise httpx.ConnectError("unreachable")

        manager = make_manager(settings, store, boom)
        with pytest.raises(APIError, match="ConnectError"):
            await manager.get_access_token()

    async def test_handle_unauthorized_forces_refresh(self, settings, store, endpoint):
        store.save(make_tokens())  # not near expiry
        manager = make_manager(settings, store, endpoint)
        token = await manager.get_access_token()

        assert await manager.handle_unauthorized(token) == "access-1"
        assert len(endpoint.refresh_calls()) == 1

    async def test_handle_unauthorized_skips_when_already_replaced(self, settings, store, endpoint):
        store.save(make_tokens())
        manager = make_manager(settings, store, endpoint)
        await manager.get_access_token()

        assert await manager.handle_unauthorized("some-older-token") == "access-0"
        assert endpoint.requests == []

    async def test_exchange_code_posts_pkce_and_saves_site(self, settings, store, endpoint):
        manager = make_manager(settings, store, endpoint)

        tokens = await manager.exchange_code("the-code", "the-verifier", site_id=123)

        [(url, body)] = endpoint.requests
        assert url == TOKEN_URL
        assert body == {
            "grant_type": "authorization_code",
            "code": "the-code",
            "redirect_uri": "http://127.0.0.1:8765/callback",
            "code_verifier": "the-verifier",
            "client_id": "client-id",
            "client_secret": "client-secret",
        }
        assert tokens.site_id == 123
        assert store.load().access_token.get_secret_value() == "access-1"

    async def test_revoke_posts_refresh_token_and_deletes_file(self, settings, store, endpoint):
        store.save(make_tokens())
        manager = make_manager(settings, store, endpoint)

        assert await manager.revoke() is True
        [(url, body)] = endpoint.requests
        assert url == REVOKE_URL
        assert body["token"] == "refresh-0"
        assert not store.path.exists()

    async def test_revoke_failure_still_deletes_file(self, settings, store, endpoint):
        store.save(make_tokens())
        endpoint.fail_with = (500, {"title": "oops"})
        manager = make_manager(settings, store, endpoint)

        assert await manager.revoke() is False
        assert not store.path.exists()

    async def test_tokens_never_logged(self, settings, store, endpoint):
        store.save(make_tokens(expires_in=0))
        manager = make_manager(settings, store, endpoint)

        with capture_logs() as logs:
            await manager.get_access_token()

        text = json.dumps(logs, default=str)
        for secret in ("access-0", "refresh-0", "access-1", "refresh-1", "client-secret"):
            assert secret not in text
        assert any(e["event"] == "OAuth access token refreshed" for e in logs)
