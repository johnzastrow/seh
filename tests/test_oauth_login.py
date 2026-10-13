"""Tests for the interactive OAuth sign-in (seh.api.oauth_login and 'seh auth' commands)."""

import base64
import hashlib
import socket
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from click.testing import CliRunner

from seh.api.auth import OAuthTokenManager, TokenSet, TokenStore
from seh.api.oauth_login import (
    LoginRequest,
    build_authorize_url,
    ensure_port_free,
    parse_redirect_url,
    validate_callback,
    wait_for_callback,
)
from seh.cli import cli
from seh.config.settings import Settings
from seh.utils.exceptions import AuthenticationError

SITE = 4242


@pytest.fixture
def request_() -> LoginRequest:
    return LoginRequest.new()


@pytest.fixture
def settings(tmp_path, monkeypatch) -> Settings:
    for var in ("SEH_OAUTH_CLIENT_ID", "SEH_OAUTH_CLIENT_SECRET", "SEH_SITE_IDS"):
        monkeypatch.delenv(var, raising=False)
    return Settings(
        _env_file=None,
        oauth_client_id="client-id",
        oauth_client_secret="client-secret",
        site_ids=str(SITE),
        token_file=str(tmp_path / "tokens.json"),
    )


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestLoginRequest:
    def test_pkce_challenge_is_s256_of_verifier(self, request_):
        digest = hashlib.sha256(request_.code_verifier.encode()).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        assert request_.code_challenge == expected
        assert 43 <= len(request_.code_verifier) <= 128

    def test_each_request_is_unique(self):
        a, b = LoginRequest.new(), LoginRequest.new()
        assert a.state != b.state
        assert a.code_verifier != b.code_verifier


class TestBuildAuthorizeUrl:
    def test_contains_required_parameters(self, settings, request_):
        url = build_authorize_url(settings, request_)
        parsed = urlparse(url)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == settings.oauth_authorize_url
        assert params == {
            "response_type": "code",
            "client_id": "client-id",
            "redirect_uri": "http://127.0.0.1:8765/callback",
            "scope": "SITE_DATA DEVICE_DATA",
            "state": request_.state,
            "access_duration": "24",
            "code_challenge": request_.code_challenge,
            "code_challenge_method": "S256",
        }

    def test_never_contains_client_secret_or_verifier(self, settings, request_):
        url = build_authorize_url(settings, request_)
        assert "client-secret" not in url
        assert request_.code_verifier not in url


class TestValidateCallback:
    def test_accepts_matching_state(self, request_):
        result = validate_callback(
            {"code": "c", "state": request_.state, "site_id": str(SITE)}, request_, [SITE]
        )
        assert (result.code, result.site_id, result.state_returned) == ("c", SITE, True)

    def test_accepts_missing_state_when_site_matches(self, request_):
        """SolarEdge drops state; PKCE plus the site check stand in for it."""
        result = validate_callback({"code": "c", "site_id": str(SITE)}, request_, [SITE])
        assert result.state_returned is False

    def test_rejects_wrong_state_even_with_matching_site(self, request_):
        with pytest.raises(AuthenticationError, match="state mismatch"):
            validate_callback(
                {"code": "c", "state": "other", "site_id": str(SITE)}, request_, [SITE]
            )

    def test_rejects_unconfigured_site(self, request_):
        with pytest.raises(AuthenticationError, match="SEH_SITE_IDS"):
            validate_callback({"code": "c", "site_id": "999"}, request_, [SITE])

    @pytest.mark.parametrize("site", ["", "abc"])
    def test_rejects_missing_or_invalid_site(self, request_, site):
        with pytest.raises(AuthenticationError, match="site_id"):
            validate_callback({"code": "c", "site_id": site}, request_, [SITE])

    def test_rejects_missing_code(self, request_):
        with pytest.raises(AuthenticationError, match="authorization code"):
            validate_callback({"site_id": str(SITE)}, request_, [SITE])

    def test_reports_provider_error(self, request_):
        with pytest.raises(AuthenticationError, match="access_denied"):
            validate_callback({"error": "access_denied"}, request_, [SITE])

    def test_error_message_never_contains_code(self, request_):
        with pytest.raises(AuthenticationError) as exc_info:
            validate_callback({"code": "secret-code", "site_id": "1"}, request_, [SITE])
        assert "secret-code" not in str(exc_info.value)


class TestCallbackListener:
    def run_listener(self, request_, query: str, port: int):
        ready = threading.Event()
        holder: dict = {}

        def listen():
            try:
                holder["result"] = wait_for_callback(
                    port, 5, lambda q: validate_callback(q, request_, [SITE]), ready
                )
            except AuthenticationError as exc:
                holder["error"] = exc

        thread = threading.Thread(target=listen)
        thread.start()
        ready.wait(5)
        # A stray request (e.g. favicon) must not end the wait.
        assert httpx.get(f"http://127.0.0.1:{port}/favicon.ico").status_code == 404
        response = httpx.get(f"http://127.0.0.1:{port}/callback?{query}")
        thread.join(5)
        return response, holder

    def test_valid_redirect_returns_result(self, request_):
        response, holder = self.run_listener(request_, f"code=abc&site_id={SITE}", free_port())
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert holder["result"].code == "abc"

    def test_invalid_redirect_raises_and_shows_error_page(self, request_):
        response, holder = self.run_listener(request_, "code=abc&state=bad&site_id=1", free_port())
        assert response.status_code == 400
        assert isinstance(holder["error"], AuthenticationError)

    def test_timeout_raises(self, request_):
        with pytest.raises(AuthenticationError, match="No sign-in redirect"):
            wait_for_callback(free_port(), 0.6, lambda q: validate_callback(q, request_, [SITE]))

    def test_ensure_port_free_detects_busy_port(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen()
            with pytest.raises(AuthenticationError, match="already in use"):
                ensure_port_free(sock.getsockname()[1])


def test_parse_redirect_url():
    query = parse_redirect_url(" http://127.0.0.1:8765/callback?code=abc&site_id=42 ")
    assert query == {"code": "abc", "site_id": "42"}


# --- 'seh auth' commands ------------------------------------------------------


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    """Run CLI commands from an empty directory so the repository .env is not read."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEH_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("SEH_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("SEH_SITE_IDS", str(SITE))
    monkeypatch.setenv("SEH_TOKEN_FILE", str(tmp_path / "tokens.json"))
    monkeypatch.setenv("SEH_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("SEH_LOG_FILE", raising=False)
    return TokenStore(tmp_path / "tokens.json")


def saved_tokens(expires_in: int = 7200) -> TokenSet:
    now = datetime.now(UTC)
    return TokenSet.from_token_response(
        {"access_token": "acc-secret", "refresh_token": "ref-secret", "expires_in": expires_in},
        now,
        site_id=SITE,
    )


class TestAuthCommands:
    def test_login_paste_flow_exchanges_code(self, cli_env, monkeypatch):
        calls = {}

        async def fake_exchange(self, code, code_verifier, site_id):
            calls.update(code=code, verifier=code_verifier, site_id=site_id)
            tokens = saved_tokens()
            self.store.save(tokens)
            return tokens

        monkeypatch.setattr(OAuthTokenManager, "exchange_code", fake_exchange)
        pasted = f"http://127.0.0.1:8765/callback?code=the-code&site_id={SITE}\n"

        result = CliRunner().invoke(cli, ["auth", "login", "--paste", "--no-browser"], input=pasted)

        assert result.exit_code == 0, result.output
        assert calls["code"] == "the-code"
        assert calls["site_id"] == SITE
        assert len(calls["verifier"]) >= 43
        assert "Signed in" in result.output
        assert "the-code" not in result.output  # pasted input is hidden

    def test_login_rejects_unconfigured_site(self, cli_env):
        pasted = "http://127.0.0.1:8765/callback?code=x&site_id=999\n"
        result = CliRunner().invoke(cli, ["auth", "login", "--paste", "--no-browser"], input=pasted)
        assert result.exit_code == 1
        assert "SEH_SITE_IDS" in result.output
        assert not cli_env.path.exists()

    def test_login_requires_site_ids(self, cli_env, monkeypatch):
        monkeypatch.delenv("SEH_SITE_IDS")
        result = CliRunner().invoke(cli, ["auth", "login", "--paste", "--no-browser"])
        assert result.exit_code == 1
        assert "SEH_SITE_IDS must be set" in result.output

    def test_status_when_signed_out(self, cli_env):
        result = CliRunner().invoke(cli, ["auth", "status"])
        assert result.exit_code == 1
        assert "Not signed in" in result.output

    def test_status_when_signed_in_hides_tokens(self, cli_env):
        cli_env.save(saved_tokens())
        result = CliRunner().invoke(cli, ["auth", "status"])
        assert result.exit_code == 0, result.output
        assert f"Site: {SITE}" in result.output
        assert "acc-secret" not in result.output
        assert "ref-secret" not in result.output

    def test_status_refresh_reports_rejected_sign_in(self, cli_env, monkeypatch):
        cli_env.save(saved_tokens())

        async def rejected(self, token):
            raise AuthenticationError("Token refresh rejected by SolarEdge")

        monkeypatch.setattr(OAuthTokenManager, "handle_unauthorized", rejected)
        result = CliRunner().invoke(cli, ["auth", "status", "--refresh"])
        assert result.exit_code == 1
        assert "rejected" in result.output

    def test_logout_revokes(self, cli_env, monkeypatch):
        cli_env.save(saved_tokens())

        async def fake_revoke(self):
            self.store.delete()
            return True

        monkeypatch.setattr(OAuthTokenManager, "revoke", fake_revoke)
        result = CliRunner().invoke(cli, ["auth", "logout", "--yes"])
        assert result.exit_code == 0, result.output
        assert "Signed out" in result.output
        assert not cli_env.path.exists()

    def test_logout_asks_for_confirmation(self, cli_env):
        cli_env.save(saved_tokens())
        result = CliRunner().invoke(cli, ["auth", "logout"], input="n\n")
        assert result.exit_code == 1  # aborted
        assert cli_env.path.exists()


def test_expired_status_message(cli_env):
    tokens = saved_tokens(expires_in=0)
    cli_env.save(tokens.model_copy(update={"expires_at": tokens.expires_at - timedelta(hours=1)}))
    result = CliRunner().invoke(cli, ["auth", "status"])
    assert "expired" in result.output
