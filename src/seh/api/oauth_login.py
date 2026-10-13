"""Interactive OAuth2 sign-in for SolarEdge Site Access (used by 'seh auth login').

Flow: build an authorize URL with a random `state` and a PKCE S256 challenge, receive the
redirect on a loopback listener (or as a pasted URL), validate it, then exchange the code.

SolarEdge was observed dropping `state` from the redirect. Policy (see
docs/V2_MIGRATION_HANDOFF.md, section 7):
- a `state` that is present but wrong is always rejected;
- a missing `state` is accepted only because PKCE binds the code to this run's verifier,
  and the redirect's `site_id` must be one of the configured SEH_SITE_IDS.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import socket
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlencode, urlparse

from seh.config.settings import OAUTH_REDIRECT_HOST
from seh.utils.exceptions import AuthenticationError

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable

    from seh.config.settings import Settings

OAUTH_SCOPES = "SITE_DATA DEVICE_DATA"
# Longest Site Access grant SolarEdge allows, in months.
ACCESS_DURATION_MONTHS = "24"
CALLBACK_PATH = "/callback"


@dataclass(frozen=True)
class LoginRequest:
    """Per-attempt secrets: never reused, never logged."""

    state: str
    code_verifier: str
    code_challenge: str

    @classmethod
    def new(cls) -> LoginRequest:
        verifier = secrets.token_urlsafe(64)  # 86 chars, within RFC 7636's 43-128
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return cls(
            state=secrets.token_urlsafe(32), code_verifier=verifier, code_challenge=challenge
        )


@dataclass(frozen=True)
class CallbackResult:
    code: str
    site_id: int
    state_returned: bool


def build_authorize_url(settings: Settings, request: LoginRequest) -> str:
    client_id, _ = settings.require_oauth_credentials()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "scope": OAUTH_SCOPES,
        "state": request.state,
        "access_duration": ACCESS_DURATION_MONTHS,
        "code_challenge": request.code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{settings.oauth_authorize_url}?{urlencode(params)}"


def validate_callback(
    query: dict[str, str], request: LoginRequest, allowed_site_ids: list[int]
) -> CallbackResult:
    """Check a redirect's parameters; raise AuthenticationError with a safe message if invalid."""
    if "error" in query:
        detail = query.get("error_description") or query["error"]
        raise AuthenticationError(f"SolarEdge sign-in failed: {detail[:200]}")

    received_state = query.get("state")
    if received_state is not None and not secrets.compare_digest(received_state, request.state):
        raise AuthenticationError(
            "Sign-in redirect does not belong to this login attempt (state mismatch). "
            "Close old sign-in tabs and run 'seh auth login' again."
        )

    code = query.get("code")
    if not code:
        raise AuthenticationError("Sign-in redirect did not include an authorization code.")

    raw_site = query.get("site_id", "")
    try:
        site_id = int(raw_site)
    except ValueError:
        raise AuthenticationError("Sign-in redirect did not include a valid site_id.") from None
    if site_id not in allowed_site_ids:
        allowed = ", ".join(str(s) for s in allowed_site_ids)
        raise AuthenticationError(
            f"You approved access to site {site_id}, but SEH_SITE_IDS is {allowed}. "
            "Approve the configured site, or update SEH_SITE_IDS."
        )
    return CallbackResult(code=code, site_id=site_id, state_returned=received_state is not None)


def parse_redirect_url(url: str) -> dict[str, str]:
    """Extract query parameters from a pasted redirect URL."""
    return {k: v[0] for k, v in parse_qs(urlparse(url.strip()).query).items()}


def ensure_port_free(port: int) -> None:
    """Fail early with a clear message if the loopback port is taken."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((OAUTH_REDIRECT_HOST, port))
        except OSError:
            raise AuthenticationError(
                f"Port {port} on {OAUTH_REDIRECT_HOST} is already in use. Close the program "
                "using it, or use 'seh auth login --paste'."
            ) from None


def wait_for_callback(
    port: int,
    timeout_s: float,
    validate: Callable[[dict[str, str]], CallbackResult],
    ready: threading.Event | None = None,
) -> CallbackResult:
    """Serve the loopback redirect URI until one /callback request arrives or time runs out.

    The listener binds to 127.0.0.1 only and stops after the first callback, valid or not.
    """
    outcome: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_error(404)  # e.g. favicon requests; keep waiting
                return
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            try:
                outcome["result"] = validate(query)
                self._reply(200, "Signed in to SolarEdge. You can close this tab.")
            except AuthenticationError as exc:
                outcome["error"] = exc
                self._reply(400, f"Sign-in failed: {exc}\n\nSee the terminal for details.")

        def _reply(self, status: int, text: str) -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # the request line contains the authorization code

    server = HTTPServer((OAUTH_REDIRECT_HOST, port), Handler)
    server.timeout = 0.5
    if ready is not None:
        ready.set()
    deadline = time.monotonic() + timeout_s
    try:
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()

    if "error" in outcome:
        raise outcome["error"]
    if "result" not in outcome:
        raise AuthenticationError(f"No sign-in redirect received within {int(timeout_s)} seconds.")
    result: CallbackResult = outcome["result"]
    return result
