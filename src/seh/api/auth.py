"""OAuth2 token storage and refresh for the SolarEdge Monitoring API V2 (Site Access).

SolarEdge issues short-lived access tokens (about 2 hours) and *rotating* refresh tokens:
every refresh returns a new refresh token and invalidates the old one. Losing the new one
means the user must sign in again, so this module:

- persists the new token set to disk before it is used,
- serializes refreshes within a process (asyncio lock) and across processes (file lock),
  re-reading the file after taking the lock in case another process already refreshed,
- never logs or prints token values.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
import structlog
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from seh.utils.exceptions import APIError, AuthenticationError

if TYPE_CHECKING:
    from pathlib import Path

    from seh.config.settings import Settings

logger = structlog.get_logger(__name__)

TOKEN_FILE_VERSION = 1
# Refresh this long before expiry so a token never lapses mid-sync.
REFRESH_SKEW = timedelta(seconds=120)
# Used only if SolarEdge omits expires_in; a 401 still triggers a refresh.
DEFAULT_EXPIRES_IN = 3600

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TokenSet(BaseModel):
    """One OAuth grant: access and refresh tokens plus metadata."""

    model_config = ConfigDict(frozen=True)

    access_token: SecretStr
    refresh_token: SecretStr
    token_type: str = "bearer"
    expires_at: datetime
    obtained_at: datetime
    site_id: int | None = None
    scope: str | None = None

    def expires_within(self, margin: timedelta, now: datetime) -> bool:
        """True if the access token expires within `margin` of `now`."""
        return now >= self.expires_at - margin

    @classmethod
    def from_token_response(
        cls,
        body: dict[str, Any],
        now: datetime,
        previous: TokenSet | None = None,
        site_id: int | None = None,
    ) -> TokenSet:
        """Build a token set from a token-endpoint response.

        If the response omits refresh_token (no rotation), the previous one is kept.
        """
        access = body.get("access_token")
        refresh = body.get("refresh_token") or (
            previous.refresh_token.get_secret_value() if previous else None
        )
        if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh:
            raise APIError("Token response is missing access_token or refresh_token")
        raw_expires = body.get("expires_in")
        try:
            # 0 is a real value (already expired), so only a missing field gets the default.
            expires_in = DEFAULT_EXPIRES_IN if raw_expires is None else max(0, int(raw_expires))
        except (TypeError, ValueError):
            expires_in = DEFAULT_EXPIRES_IN
        return cls(
            access_token=SecretStr(access),
            refresh_token=SecretStr(refresh),
            token_type=str(body.get("token_type") or "bearer"),
            expires_at=now + timedelta(seconds=expires_in),
            obtained_at=now,
            site_id=site_id if site_id is not None else (previous.site_id if previous else None),
            scope=body.get("scope") or (previous.scope if previous else None),
        )

    def to_storage(self) -> dict[str, Any]:
        """Serialize for the token file. This is the only place secrets are unwrapped."""
        return {
            "version": TOKEN_FILE_VERSION,
            "access_token": self.access_token.get_secret_value(),
            "refresh_token": self.refresh_token.get_secret_value(),
            "token_type": self.token_type,
            "expires_at": self.expires_at.isoformat(),
            "obtained_at": self.obtained_at.isoformat(),
            "site_id": self.site_id,
            "scope": self.scope,
        }


class TokenStore:
    """Token file with atomic, owner-only writes and a cross-process lock."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_name(path.name + ".lock")

    def load(self) -> TokenSet | None:
        """Return the stored tokens, None if there is no file, or raise if it is unusable."""
        if not self.path.is_file():
            return None
        self._check_permissions()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") != TOKEN_FILE_VERSION:
                raise ValueError(f"unsupported token file version {data.get('version')!r}")
            return TokenSet.model_validate(data)
        except (OSError, ValueError, ValidationError, AttributeError) as exc:
            # Fail closed: never guess at a partially readable credential file.
            raise AuthenticationError(
                f"Token file {self.path} is unreadable ({type(exc).__name__}). "
                "Run 'seh auth login' to sign in again."
            ) from None

    def save(self, tokens: TokenSet) -> None:
        """Atomically replace the token file; it is never visible half-written or world-readable."""
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".tokens-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(tokens.to_storage(), fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            if os.name == "posix":
                os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

    def delete(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()

    def _check_permissions(self) -> None:
        """Tighten a token file that other users can read (POSIX only)."""
        if os.name != "posix":
            return
        mode = self.path.stat().st_mode & 0o777
        if mode & 0o077:
            logger.warning(
                "Token file permissions were too open; restricting to owner",
                path=str(self.path),
                mode=oct(mode),
            )
            os.chmod(self.path, 0o600)

    # Cross-process lock: blocking, so callers run it in a worker thread.

    def acquire_lock(self) -> int:
        self.lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
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

    def release_lock(self, fd: int) -> None:
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


class OAuthTokenManager:
    """Supplies valid access tokens, refreshing and persisting them as needed."""

    def __init__(
        self,
        settings: Settings,
        store: TokenStore | None = None,
        http_client: httpx.AsyncClient | None = None,
        clock: Clock = _utcnow,
    ) -> None:
        self._settings = settings
        self._store = store or TokenStore(settings.token_path)
        self._http = http_client
        self._clock = clock
        self._tokens: TokenSet | None = None
        self._lock = asyncio.Lock()

    @property
    def store(self) -> TokenStore:
        return self._store

    async def get_access_token(self) -> str:
        """Return an access token valid for at least REFRESH_SKEW, refreshing if needed."""
        async with self._lock:
            tokens = self._tokens or self._load_required()
            if tokens.expires_within(REFRESH_SKEW, self._clock()):
                tokens = await self._refresh(tokens)
            self._tokens = tokens
            return tokens.access_token.get_secret_value()

    async def handle_unauthorized(self, rejected_token: str) -> str:
        """Called after a 401: refresh unless another caller already replaced the token."""
        async with self._lock:
            tokens = self._tokens or self._load_required()
            if tokens.access_token.get_secret_value() != rejected_token:
                return tokens.access_token.get_secret_value()
            tokens = await self._refresh(tokens, force=True)
            self._tokens = tokens
            return tokens.access_token.get_secret_value()

    async def exchange_code(
        self, code: str, code_verifier: str | None, site_id: int | None
    ) -> TokenSet:
        """Exchange an authorization code for tokens and persist them (used by sign-in)."""
        payload: dict[str, Any] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._settings.oauth_redirect_uri,
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier
        body = await self._post(self._settings.oauth_token_url, payload, "Token exchange")
        tokens = TokenSet.from_token_response(body, self._clock(), site_id=site_id)
        async with self._lock, self._file_lock():
            self._store.save(tokens)
            self._tokens = tokens
        logger.info("OAuth sign-in stored", expires_at=tokens.expires_at.isoformat())
        return tokens

    async def revoke(self) -> bool:
        """Revoke the refresh token at SolarEdge and delete the local file.

        Returns True if SolarEdge accepted the revocation. The local file is deleted
        either way so a failed revoke never leaves usable credentials behind.
        """
        async with self._lock, self._file_lock():
            tokens = self._store.load()
            revoked = False
            if tokens is not None:
                try:
                    await self._post(
                        self._settings.oauth_revoke_url,
                        {"token": tokens.refresh_token.get_secret_value()},
                        "Token revocation",
                    )
                    revoked = True
                except (APIError, AuthenticationError) as exc:
                    logger.warning("Token revocation failed", error=str(exc))
            self._store.delete()
            self._tokens = None
        return revoked

    def _load_required(self) -> TokenSet:
        tokens = self._store.load()
        if tokens is None:
            raise AuthenticationError(
                f"Not signed in (no token file at {self._store.path}). Run 'seh auth login'."
            )
        return tokens

    async def _refresh(self, tokens: TokenSet, force: bool = False) -> TokenSet:
        """Refresh under the cross-process lock, persisting the rotated token before use."""
        async with self._file_lock():
            on_disk = self._store.load()
            # Another process may have refreshed while we waited for the lock; its
            # rotated refresh token supersedes ours, which SolarEdge has now invalidated.
            if (
                on_disk is not None
                and on_disk.refresh_token.get_secret_value()
                != tokens.refresh_token.get_secret_value()
            ):
                if force or on_disk.expires_within(REFRESH_SKEW, self._clock()):
                    tokens = on_disk  # still needs a refresh; use the newest refresh token
                else:
                    return on_disk
            body = await self._post(
                self._settings.oauth_token_url,
                {
                    "grant_type": "refresh_token",
                    "refresh_token": tokens.refresh_token.get_secret_value(),
                },
                "Token refresh",
            )
            new_tokens = TokenSet.from_token_response(body, self._clock(), previous=tokens)
            self._store.save(new_tokens)
        logger.info("OAuth access token refreshed", expires_at=new_tokens.expires_at.isoformat())
        return new_tokens

    @contextlib.asynccontextmanager
    async def _file_lock(self) -> Any:
        fd = await asyncio.to_thread(self._store.acquire_lock)
        try:
            yield
        finally:
            self._store.release_lock(fd)

    async def _post(self, url: str, payload: dict[str, Any], what: str) -> dict[str, Any]:
        """POST a JSON body with client credentials (SolarEdge's token endpoint takes JSON)."""
        client_id, client_secret = self._settings.require_oauth_credentials()
        body = {**payload, "client_id": client_id, "client_secret": client_secret}
        try:
            if self._http is not None:
                resp = await self._http.post(url, json=body)
            else:
                async with httpx.AsyncClient(timeout=self._settings.api_timeout) as client:
                    resp = await client.post(url, json=body)
        except httpx.RequestError as exc:
            raise APIError(f"{what} failed: {type(exc).__name__}") from exc

        if resp.status_code in (400, 401, 403):
            # Rejected grant or client: retrying cannot help, the user must sign in again.
            raise AuthenticationError(
                f"{what} rejected by SolarEdge (HTTP {resp.status_code}: "
                f"{_error_summary(resp)}). Run 'seh auth login' to sign in again."
            )
        if resp.status_code >= 400:
            raise APIError(
                f"{what} failed (HTTP {resp.status_code}: {_error_summary(resp)})",
                status_code=resp.status_code,
            )
        if not resp.content:
            return {}
        try:
            data = resp.json()
        except ValueError as exc:
            raise APIError(f"{what} returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise APIError(f"{what} returned an unexpected response")
        return data


def _error_summary(resp: httpx.Response) -> str:
    """Short, non-secret description of an error response."""
    try:
        data = resp.json()
    except ValueError:
        return resp.reason_phrase or "error"
    if isinstance(data, dict):
        for key in ("error_description", "error", "detail", "title"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value[:200]
    return resp.reason_phrase or "error"
