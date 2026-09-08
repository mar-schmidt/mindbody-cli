"""HTTP client spanning the several Mindbody backends.

Unlike a single-origin API client this one takes absolute URLs, because the
four hosts involved are genuinely different services with different
conventions. What they share is the bearer token and the client fingerprint,
which is what this wrapper centralises -- along with a single, uniform
mapping from transport failures to the CLI's stable error contract.
"""

from __future__ import annotations

from typing import Any

import httpx

from mindbody_cli import exit_codes
from mindbody_cli.client.oauth import (
    ClientCredentials,
    ensure_fresh_tokens,
    load_client_credentials,
)
from mindbody_cli.client.tokens import TokenState, TokenStore
from mindbody_cli.config import ACCEPT_LANGUAGE, USER_AGENT
from mindbody_cli.errors import CliError


class MindbodyHttpClient:
    """Authenticated HTTP wrapper with proactive and reactive token refresh."""

    def __init__(
        self,
        store: TokenStore,
        *,
        timeout_seconds: float = 30.0,
        credentials: ClientCredentials | None = None,
    ) -> None:
        self._store = store
        self._credentials = credentials
        self._state: TokenState | None = None
        self._client = httpx.Client(
            timeout=timeout_seconds,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": ACCEPT_LANGUAGE,
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    # -- auth ------------------------------------------------------------

    @property
    def credentials(self) -> ClientCredentials:
        if self._credentials is None:
            self._credentials = load_client_credentials()
        return self._credentials

    @property
    def state(self) -> TokenState:
        """Current token state, refreshed proactively when near expiry."""
        if self._state is None:
            # Deliberately pass the (possibly unset) cached credentials rather
            # than resolving them here: a logged-out user must be told to log
            # in, not told their client registration is missing.
            self._state = ensure_fresh_tokens(self._store, self._credentials)
        return self._state

    def _force_refresh(self) -> TokenState:
        self._state = ensure_fresh_tokens(
            self._store,
            self.credentials,
            force=True,
        )
        return self._state

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.state.access_token}"}

    # -- requests --------------------------------------------------------

    def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        payload: Any = None,
        allow_204: bool = False,
        retry_on_auth: bool = True,
    ) -> Any:
        """Perform an authenticated request and return decoded JSON."""
        try:
            response = self._client.request(
                method,
                url,
                params=params,
                json=payload,
                headers=self._auth_headers(),
            )
        except httpx.TimeoutException as exc:
            raise CliError(
                error="Network timeout",
                code="network_timeout",
                exit_code=exit_codes.NETWORK,
                details={"url": url},
            ) from exc
        except httpx.RequestError as exc:
            raise CliError(
                error="Network request failed",
                code="network_error",
                exit_code=exit_codes.NETWORK,
                details={"url": url, "reason": str(exc)},
            ) from exc

        if response.status_code in (401, 403) and retry_on_auth:
            # The access token may have been revoked or expired early. Refresh
            # once, then retry exactly once so a genuine 403 cannot loop.
            self._force_refresh()
            return self.request_json(
                method,
                url,
                params=params,
                payload=payload,
                allow_204=allow_204,
                retry_on_auth=False,
            )

        if response.status_code in (401, 403):
            raise CliError(
                error="Authentication rejected by upstream",
                code="auth_required",
                exit_code=exit_codes.AUTH,
                details={
                    "status": response.status_code,
                    "url": url,
                    "hint": "Run `mindbody auth login` to re-authenticate.",
                },
            )

        if response.status_code == 204:
            if allow_204:
                return None
            return None

        if response.status_code >= 400:
            body: Any
            try:
                body = response.json()
            except ValueError:
                body = response.text[:1000]
            raise CliError(
                error="Upstream API returned an error",
                code="upstream_error",
                exit_code=exit_codes.UPSTREAM,
                details={
                    "status": response.status_code,
                    "url": url,
                    "response": body,
                },
            )

        if not response.content:
            return {}

        try:
            return response.json()
        except ValueError as exc:
            raise CliError(
                error="Invalid upstream JSON response",
                code="invalid_json",
                exit_code=exit_codes.UPSTREAM,
                details={"url": url, "status": response.status_code},
            ) from exc

    def request_no_content(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        payload: Any = None,
    ) -> None:
        self.request_json(
            method,
            url,
            params=params,
            payload=payload,
            allow_204=True,
        )
