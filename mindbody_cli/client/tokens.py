"""Persisted OAuth token state.

The authorization server rotates the refresh token on every use: the token
you send is dead the moment the response is produced. That makes persistence
a critical section. If the process dies between receiving a rotated token and
committing it, the user is locked out and has to redo the interactive login.

Two defences, both required:

* every write is atomic (write to a temp file in the same directory, then
  ``os.replace``), so a crash can never leave a half-written state file;
* every refresh holds an exclusive ``flock`` for its whole duration, so a
  cron job and a manual invocation cannot consume the same token in parallel.

The previous refresh token is retained in ``previous_refresh_token`` so that a
failed rotation can be diagnosed and, where the server still honours it,
manually recovered.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from mindbody_cli import exit_codes
from mindbody_cli.config import (
    TOKEN_REFRESH_MARGIN_SECONDS,
    AppPaths,
    get_token_backend,
)
from mindbody_cli.errors import CliError

KEYRING_SERVICE = "mindbody-cli"
KEYRING_USERNAME = "tokens"


@dataclass(slots=True)
class TokenState:
    """Everything needed to keep talking to the API without a browser."""

    access_token: str | None = None
    refresh_token: str | None = None
    previous_refresh_token: str | None = None
    id_token: str | None = None
    expires_at: float | None = None
    scope: str | None = None
    username: str | None = None
    user_id: int | None = None
    identity_id: str | None = None
    site_id: int | None = None
    location_id: int | None = None
    master_location_id: int | None = None
    updated_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TokenState":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in value.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_authenticated(self) -> bool:
        return bool(self.refresh_token or self.access_token)

    def needs_refresh(self, *, margin: int = TOKEN_REFRESH_MARGIN_SECONDS) -> bool:
        """True when the access token is missing, expired, or about to be."""
        if not self.access_token:
            return True
        if self.expires_at is None:
            return True
        return time.time() >= (self.expires_at - margin)

    def redacted(self) -> dict[str, Any]:
        """Summary safe to print in command output."""
        return {
            "authenticated": self.is_authenticated,
            "expiresAt": self.expires_at,
            "expiresInSeconds": (
                max(0, int(self.expires_at - time.time()))
                if self.expires_at
                else None
            ),
            "scope": self.scope,
            "username": self.username,
            "userId": self.user_id,
            "identityId": self.identity_id,
            "siteId": self.site_id,
            "locationId": self.location_id,
            "masterLocationId": self.master_location_id,
            "updatedAt": self.updated_at,
        }


def _keyring_available() -> bool:
    try:
        import keyring
        import keyring.backends.fail

        backend = keyring.get_keyring()
        return not isinstance(backend, keyring.backends.fail.Keyring)
    except Exception:
        return False


class TokenStore:
    """Loads and atomically persists :class:`TokenState`."""

    def __init__(self, paths: AppPaths, backend: str | None = None) -> None:
        self.paths = paths
        requested = backend or get_token_backend()
        if requested == "auto":
            requested = "keyring" if _keyring_available() else "file"
        self.backend = requested

    # -- reading ---------------------------------------------------------

    def load(self) -> TokenState:
        raw = self._read_raw()
        if raw is None:
            return TokenState()
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise CliError(
                error="Stored token state is not valid JSON",
                code="token_state_corrupt",
                exit_code=exit_codes.AUTH,
                details={
                    "backend": self.backend,
                    "path": str(self.paths.token_path),
                    "hint": "Run `mindbody auth login` to re-authenticate.",
                    "reason": str(exc),
                },
            ) from exc
        if not isinstance(data, dict):
            return TokenState()
        return TokenState.from_dict(data)

    def _read_raw(self) -> str | None:
        if self.backend == "keyring":
            try:
                import keyring

                return keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
            except Exception as exc:
                raise CliError(
                    error="Failed to read tokens from keyring",
                    code="keyring_read_failed",
                    exit_code=exit_codes.AUTH,
                    details={"reason": str(exc)},
                ) from exc

        path = self.paths.token_path
        if not path.exists():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CliError(
                error="Failed to read token state",
                code="token_state_read_failed",
                exit_code=exit_codes.AUTH,
                details={"path": str(path), "reason": str(exc)},
            ) from exc

    # -- writing ---------------------------------------------------------

    def save(self, state: TokenState) -> None:
        from datetime import UTC, datetime

        state.updated_at = datetime.now(UTC).isoformat()
        payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2)

        if self.backend == "keyring":
            try:
                import keyring

                keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, payload)
                return
            except Exception as exc:
                raise CliError(
                    error="Failed to store tokens in keyring",
                    code="keyring_store_failed",
                    exit_code=exit_codes.AUTH,
                    details={"reason": str(exc)},
                ) from exc

        self._atomic_write(payload)

    def _atomic_write(self, payload: str) -> None:
        """Write via temp file + rename so readers never see a partial file."""
        path = self.paths.token_path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass

        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=".tokens-",
            suffix=".tmp",
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                # Durability matters here: a rotated refresh token that only
                # exists in the page cache is lost on power failure.
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        except OSError as exc:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise CliError(
                error="Failed to persist token state",
                code="token_state_write_failed",
                exit_code=exit_codes.AUTH,
                details={"path": str(path), "reason": str(exc)},
            ) from exc

    def clear(self) -> None:
        if self.backend == "keyring":
            try:
                import keyring

                if keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME):
                    keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
            except Exception:
                pass
            return

        path = self.paths.token_path
        if path.exists():
            try:
                path.unlink()
            except OSError as exc:
                raise CliError(
                    error="Failed to remove token state",
                    code="token_state_delete_failed",
                    exit_code=exit_codes.AUTH,
                    details={"path": str(path), "reason": str(exc)},
                ) from exc

    # -- locking ---------------------------------------------------------

    @contextmanager
    def refresh_lock(self, timeout_seconds: float = 30.0) -> Iterator[None]:
        """Serialize token refresh across concurrent processes."""
        lock_path = self.paths.lock_path
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+")
        deadline = time.monotonic() + timeout_seconds
        try:
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise CliError(
                            error="Timed out waiting for the token refresh lock",
                            code="token_lock_timeout",
                            exit_code=exit_codes.AUTH,
                            details={
                                "path": str(lock_path),
                                "timeoutSeconds": timeout_seconds,
                                "hint": (
                                    "Another mindbody process is refreshing. "
                                    "If none is running, delete the lock file."
                                ),
                            },
                        ) from None
                    time.sleep(0.1)
            yield
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
