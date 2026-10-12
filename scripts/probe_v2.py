"""Throwaway probe for the SolarEdge Monitoring API V2 (OAuth2 Site Access).

Signs in once through the browser, then calls each V2 endpoint seh will need and
saves the raw responses so the real client can be built against actual shapes.
See docs/V2_MIGRATION_HANDOFF.md for context. Delete once the migration is done.

Usage (no project venv needed):
    uv run --no-project --with httpx python scripts/probe_v2.py login
    uv run --no-project --with httpx python scripts/probe_v2.py probe
    uv run --no-project --with httpx python scripts/probe_v2.py logout

Reads SEH_OAUTH_CLIENT_ID and SEH_OAUTH_CLIENT_SECRET (and optional SEH_SITE_ID)
from the environment or ./.env. Tokens and responses go to ./.seh-probe/ (gitignored).
Each API call costs 1 credit; a full probe run makes about 17 calls.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

AUTHORIZE_URL = "https://connect.solaredge.com/authorize"
TOKEN_URL = "https://monitoringapi.solaredge.com/v2/oauth2/token"
REVOKE_URL = "https://monitoringapi.solaredge.com/v2/oauth2/revoke-token"
API_BASE = "https://monitoringapi.solaredge.com/v2"
SCOPES = "SITE_DATA DEVICE_DATA"
ACCESS_DURATION_MONTHS = "24"

CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8765
REDIRECT_URI = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}/callback"

OUT_DIR = Path(".seh-probe")
TOKEN_FILE = OUT_DIR / "tokens.json"
RESPONSES_DIR = OUT_DIR / "responses"

# Response headers worth keeping: rate limits, credits, retry hints, tracing.
KEEP_HEADER_HINTS = ("ratelimit", "credit", "retry-after", "content-type", "trace")


class ProbeError(Exception):
    """Fatal, user-facing error."""


# --- configuration -----------------------------------------------------------


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env reader; real environment variables take precedence."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def client_credentials() -> tuple[str, str]:
    client_id = os.environ.get("SEH_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SEH_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise ProbeError(
            "Set SEH_OAUTH_CLIENT_ID and SEH_OAUTH_CLIENT_SECRET in .env or the environment."
        )
    return client_id, client_secret


# --- token storage -----------------------------------------------------------


def save_tokens(data: dict[str, Any]) -> None:
    """Write tokens atomically with owner-only permissions where the OS supports it."""
    OUT_DIR.mkdir(exist_ok=True)
    tmp = TOKEN_FILE.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, TOKEN_FILE)


def load_tokens() -> dict[str, Any]:
    if not TOKEN_FILE.is_file():
        raise ProbeError("No tokens found. Run the 'login' command first.")
    return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))


def store_token_response(body: dict[str, Any], previous: dict[str, Any] | None = None) -> dict:
    """Merge a token-endpoint response into the stored record and persist it immediately.

    Refresh tokens rotate, so the new one must be on disk before anything else happens.
    """
    record = dict(previous or {})
    record["token_response_keys"] = sorted(body.keys())  # shape only, for the migration notes
    for key in ("access_token", "refresh_token", "token_type", "scope"):
        if key in body:
            record[key] = body[key]
    record["obtained_at"] = int(time.time())
    record["expires_in"] = int(body.get("expires_in", 0) or 0)
    save_tokens(record)
    return record


def token_request(payload: dict[str, Any]) -> dict[str, Any]:
    """POST to the token endpoint. SolarEdge expects a JSON body (per community clients)."""
    client_id, client_secret = client_credentials()
    body = {**payload, "client_id": client_id, "client_secret": client_secret}
    resp = httpx.post(TOKEN_URL, json=body, timeout=30)
    if resp.status_code >= 400:
        raise ProbeError(f"Token request failed: HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def refresh(tokens: dict[str, Any]) -> dict[str, Any]:
    if not tokens.get("refresh_token"):
        raise ProbeError("No refresh token stored. Run 'login' again.")
    body = token_request({"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]})
    print("Access token refreshed.")
    return store_token_response(body, tokens)


def access_token_is_fresh(tokens: dict[str, Any]) -> bool:
    if not tokens.get("access_token"):
        return False
    if not tokens.get("expires_in"):
        return True  # unknown lifetime; rely on 401 handling
    return time.time() < tokens["obtained_at"] + tokens["expires_in"] - 60


# --- login -------------------------------------------------------------------


def pkce_pair() -> tuple[str, str]:
    """RFC 7636 S256 verifier and challenge; binds the code to this login run."""
    verifier = secrets.token_urlsafe(64)  # 86 chars, within the 43-128 limit
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorize_url(state: str, code_challenge: str | None) -> str:
    client_id, _ = client_credentials()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "access_duration": ACCESS_DURATION_MONTHS,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def state_problem(
    query: dict[str, str], expected_state: str, allow_missing: bool = False
) -> str | None:
    """Explain why a callback's state is unacceptable, without revealing any values.

    A missing state is tolerated only when explicitly allowed (SolarEdge was observed
    dropping it); a state that is present but wrong is always rejected.
    """
    names = ", ".join(sorted(query)) or "none"
    if "state" not in query:
        if allow_missing:
            return None
        return (
            f"redirect had no 'state' parameter (parameters received: {names}). "
            "Re-run with --allow-missing-state to accept this."
        )
    received = query["state"]
    if not secrets.compare_digest(received, expected_state):
        return (
            f"'state' differs from this login attempt (received length {len(received)}, "
            f"expected {len(expected_state)}; parameters received: {names}). "
            "This usually means the redirect came from an older login attempt or tab."
        )
    return None


def wait_for_callback(
    expected_state: str, timeout_s: int, allow_missing_state: bool = False
) -> dict[str, str]:
    """Serve one request on the loopback redirect URI and return its query parameters."""
    result: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/callback":
                self.send_error(404)
                return
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            # Reject callbacks that did not come from our authorize request (CSRF).
            problem = state_problem(query, expected_state, allow_missing_state)
            if problem:
                self._reply(400, "State mismatch. See the terminal for details.")
                result["error"] = "state_mismatch"
                result["error_description"] = problem
                return
            result.update(query)
            if "error" in query:
                self._reply(400, f"Authorization failed: {query['error']}. You can close this tab.")
            else:
                self._reply(200, "Authorization received. You can close this tab.")

        def _reply(self, status: int, text: str) -> None:
            body = text.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            pass  # keep the authorization code out of the console

    server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), Handler)
    server.timeout = 1
    deadline = time.time() + timeout_s
    try:
        while not result and time.time() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not result:
        raise ProbeError(f"No callback received within {timeout_s} seconds.")
    return result


def parse_pasted_redirect(expected_state: str, allow_missing_state: bool) -> dict[str, str]:
    pasted = input("Paste the full URL from the browser address bar: ").strip()
    query = {k: v[0] for k, v in parse_qs(urlparse(pasted).query).items()}
    problem = state_problem(query, expected_state, allow_missing_state)
    if problem:
        raise ProbeError(f"State mismatch in pasted URL: {problem}")
    return query


def cmd_login(args: argparse.Namespace) -> None:
    expected_site = os.environ.get("SEH_SITE_ID", "").strip()
    if args.allow_missing_state and not expected_site:
        # Without state, the expected site ID is the remaining check that the
        # redirect belongs to the user's own sign-in.
        raise ProbeError("--allow-missing-state requires SEH_SITE_ID to be set.")

    state = secrets.token_urlsafe(32)
    verifier, challenge = (None, None) if args.no_pkce else pkce_pair()
    url = build_authorize_url(state, challenge)
    print(f"PKCE: {'off' if args.no_pkce else 'on (S256)'}")
    if args.allow_missing_state:
        print(
            "WARNING: accepting a redirect without 'state'. Only complete the sign-in in the "
            "tab this command opens, and close other browser tabs you don't trust."
        )
    print("Opening the SolarEdge sign-in page. If it does not open, visit:\n")
    print(f"  {url}\n")

    if args.paste:
        if not args.no_browser:
            webbrowser.open(url)
        query = parse_pasted_redirect(state, args.allow_missing_state)
    else:
        # Start listening before the browser can redirect back.
        holder: dict[str, Any] = {}

        def run() -> None:
            try:
                holder["query"] = wait_for_callback(state, args.timeout, args.allow_missing_state)
            except Exception as exc:  # surfaced in the main thread
                holder["error"] = exc

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        if not args.no_browser:
            webbrowser.open(url)
        print(f"Waiting up to {args.timeout}s for the redirect to {REDIRECT_URI} ...")
        thread.join()
        if "error" in holder:
            raise holder["error"]
        query = holder["query"]

    if "error" in query:
        raise ProbeError(
            f"Authorization failed: {query.get('error')} {query.get('error_description', '')}"
        )
    if "code" not in query:
        raise ProbeError("Redirect did not include an authorization code.")

    state_returned = "state" in query
    if not state_returned and query.get("site_id") != expected_site:
        raise ProbeError(
            "Redirect had no 'state' and its site_id does not match SEH_SITE_ID; refusing it."
        )

    extras = {k: v for k, v in query.items() if k not in ("code", "state")}
    payload = {
        "grant_type": "authorization_code",
        "code": query["code"],
        "redirect_uri": REDIRECT_URI,
    }
    if verifier:
        payload["code_verifier"] = verifier
    try:
        body = token_request(payload)
    except ProbeError as exc:
        if verifier:
            raise ProbeError(
                f"{exc}\nIf this mentions PKCE or code_verifier, retry with --no-pkce."
            ) from exc
        raise
    record = store_token_response(body)
    record["callback_params"] = extras  # e.g. site_id appended by SolarEdge
    record["login_observations"] = {"state_returned": state_returned, "pkce_sent": bool(verifier)}
    if "site_id" in extras:
        record["site_id"] = extras["site_id"]
    save_tokens(record)

    print("\nSigned in. Tokens saved to", TOKEN_FILE)
    print("Token response fields:", ", ".join(record["token_response_keys"]))
    print("Access token lifetime (s):", record["expires_in"] or "not reported")
    print("Extra callback parameters:", ", ".join(f"{k}={v}" for k, v in extras.items()) or "none")


# --- probe -------------------------------------------------------------------


def fmt(dt: datetime) -> str:
    """UTC ISO-8601 instant. Offset-free timestamps are rejected ("required type [Instant]")."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def endpoint_plan(site_id: str) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """(name, path, params) for each call. Times are sent as UTC instants."""
    now = datetime.now(UTC).replace(microsecond=0)
    last_12h = [("from", fmt(now - timedelta(hours=12))), ("to", fmt(now))]
    last_7d = [("from", fmt(now - timedelta(days=7))), ("to", fmt(now))]
    since_2020 = [("from", "2020-01-01T00:00:00Z"), ("to", fmt(now))]
    s = f"/sites/{site_id}"
    return [
        ("sites_list", "/sites", [("page", "1"), ("sites-in-page", "10")]),  # expected: Fleet only
        ("site_details", s, []),
        ("overview", f"{s}/overview", []),
        (
            "power_quarter_hour",
            f"{s}/power",
            [("resolution", "QUARTER_HOUR"), ("unit", "W"), *last_12h],
        ),
        ("power_live", f"{s}/power/live", []),  # listed on developer.solaredge.com
        ("energy_day", f"{s}/energy", [("resolution", "DAY"), ("unit", "WH"), *last_7d]),
        ("energy_year", f"{s}/energy", [("resolution", "YEAR"), ("unit", "WH"), *since_2020]),
        ("devices_default", f"{s}/devices", []),
        (
            "devices_all_types",
            f"{s}/devices",
            [("types", t) for t in ("INVERTER", "BATTERY", "METER", "OPTIMIZER")],
        ),
        ("alerts", f"{s}/alerts", [("alerts-in-page", "100")]),
        ("inverters_telemetry", f"{s}/inverters/telemetry", [("resolution", "HOUR"), *last_12h]),
        ("meters_telemetry", f"{s}/meters/telemetry", [("resolution", "HOUR"), *last_12h]),
        ("storage_telemetry", f"{s}/storage/telemetry", [("resolution", "HOUR"), *last_12h]),
        ("power_flow", f"{s}/power-flow", []),  # expected: 403 below Advanced tier
        ("env_benefits_guess", f"{s}/environmental-benefits", []),  # path is a guess
    ]


def serial_followups(results: dict[str, Any]) -> list[tuple[str, str, list[tuple[str, str]]]]:
    """Per-device telemetry (/equipment/{serial}/telemetry, listed on the developer portal)."""
    body = results.get("devices_all_types", {}).get("body")
    if not isinstance(body, list):
        body = results.get("devices_default", {}).get("body")
    devices = body if isinstance(body, list) else []
    now = datetime.now(UTC).replace(microsecond=0)
    window = [("from", fmt(now - timedelta(hours=12))), ("to", fmt(now))]
    picked: dict[str, str] = {}
    for dev in devices:
        if not isinstance(dev, dict):
            continue
        kind = str(dev.get("type", "")).upper()
        serial = dev.get("serialNumber")
        if serial and kind in ("INVERTER", "OPTIMIZER") and kind not in picked:
            picked[kind] = str(serial)
    return [
        (f"equipment_telemetry_{kind.lower()}", f"/equipment/{serial}/telemetry", window)
        for kind, serial in picked.items()
    ]


def call(client: httpx.Client, tokens: dict[str, Any], path: str, params: list) -> tuple:
    """GET with bearer auth; on 401 refresh once and retry."""
    for attempt in (1, 2):
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {tokens['access_token']}",
        }
        resp = client.get(f"{API_BASE}{path}", params=params, headers=headers)
        if resp.status_code == 401 and attempt == 1:
            tokens = refresh(tokens)
            continue
        return resp, tokens
    raise AssertionError("unreachable")


def cmd_probe(args: argparse.Namespace) -> None:
    tokens = load_tokens()
    site_id = args.site or os.environ.get("SEH_SITE_ID") or tokens.get("site_id")
    if not site_id:
        raise ProbeError("No site ID. Pass --site, set SEH_SITE_ID, or check the login output.")
    if not access_token_is_fresh(tokens):
        tokens = refresh(tokens)

    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    plan = endpoint_plan(str(site_id))
    only = {n.strip() for n in (args.only or "").split(",") if n.strip()}
    if only:
        unknown = only - {n for n, _, _ in plan}
        if unknown:
            raise ProbeError(f"Unknown call name(s) for --only: {', '.join(sorted(unknown))}")
        plan = [c for c in plan if c[0] in only]
    print(f"Probing site {site_id}: {len(plan)} calls plus per-device follow-ups.\n")

    with httpx.Client(timeout=30) as client:
        queue = list(plan)
        followups_added = False
        while queue:
            name, path, params = queue.pop(0)
            resp, tokens = call(client, tokens, path, params)
            try:
                body: Any = resp.json()
            except ValueError:
                body = resp.text[:2000]
            kept = {
                k: v
                for k, v in resp.headers.items()
                if any(h in k.lower() for h in KEEP_HEADER_HINTS)
            }
            results[name] = {"status": resp.status_code, "body": body}
            record = {
                "request": {"path": path, "params": params},
                "status": resp.status_code,
                "headers": kept,
                "body": body,
            }
            (RESPONSES_DIR / f"{name}.json").write_text(
                json.dumps(record, indent=2), encoding="utf-8"
            )
            print(f"  {resp.status_code}  {name:<32} {path}")

            if resp.status_code == 429:
                wait = int(resp.headers.get("retry-after", "60"))
                print(f"      rate limited; waiting {wait}s")
                time.sleep(wait)
            else:
                time.sleep(6.5)  # stay under 10 calls/minute

            if (
                not only
                and not followups_added
                and not any(n.startswith("devices") for n, _, _ in queue)
            ):
                queue.extend(serial_followups(results))
                followups_added = True

    print(f"\nRaw responses saved under {RESPONSES_DIR}/")
    remaining = [
        f"{k}: {v}"
        for k, v in record["headers"].items()
        if "ratelimit" in k.lower() or "credit" in k.lower()
    ]
    if remaining:
        print("Last rate/credit headers:", "; ".join(remaining))


# --- logout ------------------------------------------------------------------


def cmd_logout(_: argparse.Namespace) -> None:
    tokens = load_tokens()
    client_id, client_secret = client_credentials()
    resp = httpx.post(
        REVOKE_URL,
        json={
            "token": tokens.get("refresh_token", ""),
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    print(f"Revoke returned HTTP {resp.status_code}: {resp.text[:200]}")
    TOKEN_FILE.unlink(missing_ok=True)
    print("Local token file deleted.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Sign in through the browser and store tokens")
    p_login.add_argument(
        "--paste",
        action="store_true",
        help="Paste the redirect URL instead of using the local listener",
    )
    p_login.add_argument(
        "--no-browser", action="store_true", help="Print the sign-in URL without opening a browser"
    )
    p_login.add_argument(
        "--timeout", type=int, default=300, help="Seconds to wait for the redirect (default 300)"
    )
    p_login.add_argument(
        "--allow-missing-state",
        action="store_true",
        help="Accept a redirect without 'state' (requires SEH_SITE_ID; wrong state still rejected)",
    )
    p_login.add_argument("--no-pkce", action="store_true", help="Do not send a PKCE challenge")
    p_login.set_defaults(func=cmd_login)

    p_probe = sub.add_parser("probe", help="Call each V2 endpoint and save the raw responses")
    p_probe.add_argument(
        "--site", help="Site ID (defaults to SEH_SITE_ID or the ID returned at login)"
    )
    p_probe.add_argument(
        "--only", help="Comma-separated call names to run (e.g. energy_day,power_quarter_hour)"
    )
    p_probe.set_defaults(func=cmd_probe)

    p_logout = sub.add_parser("logout", help="Revoke the refresh token and delete local tokens")
    p_logout.set_defaults(func=cmd_logout)

    args = parser.parse_args()
    load_dotenv()
    try:
        args.func(args)
    except ProbeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
