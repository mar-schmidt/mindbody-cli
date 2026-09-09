"""OAuth2 authorization-code + PKCE flow against the Mindbody identity server.

Verified behaviour of the upstream (see docs/api.md for the evidence):

* ``/connect/token`` is **not** behind the WAF that guards the interactive
  sign-in pages, so refreshing works headlessly with no cookies at all;
* the ``password`` grant is advertised in discovery but rejected for this
  client, so there is no username/password path;
* ``http://localhost`` redirect URIs are rejected, so the usual loopback
  listener trick is unavailable and the one-time login has to capture the
  redirect out of the browser's address bar.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx

from mindbody_cli import exit_codes
from mindbody_cli.client.tokens import TokenState, TokenStore
from mindbody_cli.config import (
    ACCEPT_LANGUAGE,
    AUTHORIZE_PATH,
    CLIENT_ID_ENV,
    CLIENT_SECRET_ENV,
    IDENTITY_HOST,
    OAUTH_SCOPES,
    REDIRECT_URI_ENV,
    REDIRECT_URI_ENV as _REDIRECT_ENV,
    REVOCATION_PATH,
    TOKEN_PATH,
    USER_AGENT,
)
from mindbody_cli.errors import CliError

KEYRING_SERVICE = "mindbody-cli"
KEYRING_CLIENT_USERNAME = "oauth_client"
KEYRING_ACCOUNT_USERNAME = "account_password"


# ---------------------------------------------------------------------------
# Optional account credentials
#
# Storing the account password is opt-in. It buys one thing: an unattended
# host can recover by itself when the refresh chain breaks, instead of waiting
# for a human with a browser. It costs the obvious thing: a password at rest.
# Refresh tokens remain the normal path; this is only the fallback.
# ---------------------------------------------------------------------------


def store_account_password(username: str, password: str) -> None:
    """Persist account credentials for unattended re-authentication."""
    try:
        import keyring

        keyring.set_password(
            KEYRING_SERVICE,
            KEYRING_ACCOUNT_USERNAME,
            json.dumps({"username": username, "password": password}),
        )
    except Exception as exc:
        raise CliError(
            error="Failed to store account password in keyring",
            code="keyring_store_failed",
            exit_code=exit_codes.AUTH,
            details={"reason": str(exc)},
        ) from exc


def load_account_password() -> tuple[str, str] | None:
    """Return stored (username, password), or None when not configured."""
    try:
        import keyring

        raw = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT_USERNAME)
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return None
    return username, password


def clear_account_password() -> None:
    try:
        import keyring

        if keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT_USERNAME):
            keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT_USERNAME)
    except Exception:
        return


# ---------------------------------------------------------------------------
# Client registration
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ClientCredentials:
    """Identifiers this CLI presents to the authorization server."""

    client_id: str
    client_secret: str
    redirect_uri: str

    def basic_header(self) -> str:
        raw = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")


def store_client_credentials(creds: ClientCredentials) -> None:
    """Persist client registration in the OS keychain."""
    try:
        import keyring

        keyring.set_password(
            KEYRING_SERVICE,
            KEYRING_CLIENT_USERNAME,
            json.dumps(
                {
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "redirect_uri": creds.redirect_uri,
                }
            ),
        )
    except Exception as exc:
        raise CliError(
            error="Failed to store client registration in keyring",
            code="keyring_store_failed",
            exit_code=exit_codes.AUTH,
            details={"reason": str(exc)},
        ) from exc


def clear_client_credentials() -> None:
    try:
        import keyring

        if keyring.get_password(KEYRING_SERVICE, KEYRING_CLIENT_USERNAME):
            keyring.delete_password(KEYRING_SERVICE, KEYRING_CLIENT_USERNAME)
    except Exception:
        return


def _client_credentials_from_keyring() -> ClientCredentials | None:
    try:
        import keyring

        raw = keyring.get_password(KEYRING_SERVICE, KEYRING_CLIENT_USERNAME)
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not data.get("client_id") or not data.get("client_secret"):
        return None
    return ClientCredentials(
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        redirect_uri=data.get("redirect_uri") or "",
    )


def load_client_credentials() -> ClientCredentials:
    """Resolve client registration from env, then keychain.

    This project intentionally ships no default. See config.py and
    DISCLAIMER.md for why.
    """
    env_id = os.environ.get(CLIENT_ID_ENV)
    env_secret = os.environ.get(CLIENT_SECRET_ENV)
    env_redirect = os.environ.get(REDIRECT_URI_ENV)
    if env_id and env_secret and env_redirect:
        return ClientCredentials(env_id, env_secret, env_redirect)

    stored = _client_credentials_from_keyring()
    if stored and stored.redirect_uri:
        return ClientCredentials(
            client_id=env_id or stored.client_id,
            client_secret=env_secret or stored.client_secret,
            redirect_uri=env_redirect or stored.redirect_uri,
        )

    raise CliError(
        error="No OAuth client registration configured",
        code="client_not_configured",
        exit_code=exit_codes.AUTH,
        details={
            "hint": (
                "This CLI ships no vendor credentials. Provide your own via "
                f"{CLIENT_ID_ENV}, {CLIENT_SECRET_ENV} and {_REDIRECT_ENV}, "
                "or run `mindbody auth bootstrap --from-capture <flows.jsonl>` "
                "once to import them from your own captured traffic."
            ),
            "requiredEnv": [CLIENT_ID_ENV, CLIENT_SECRET_ENV, REDIRECT_URI_ENV],
        },
    )


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class PkcePair:
    verifier: str
    challenge: str
    state: str


def generate_pkce() -> PkcePair:
    """Create an S256 PKCE verifier/challenge pair and a CSRF state value."""
    verifier = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return PkcePair(
        verifier=verifier,
        challenge=challenge,
        state=secrets.token_urlsafe(24),
    )


def build_authorize_url(creds: ClientCredentials, pkce: PkcePair) -> str:
    """Build the URL the user opens in their own browser."""
    query = urllib.parse.urlencode(
        {
            "client_id": creds.client_id,
            "response_type": "code",
            "redirect_uri": creds.redirect_uri,
            "scope": OAUTH_SCOPES,
            "code_challenge": pkce.challenge,
            "code_challenge_method": "S256",
            "state": pkce.state,
            "prompt": "login",
        }
    )
    return f"{IDENTITY_HOST}{AUTHORIZE_PATH}?{query}"


def extract_code(redirect_url: str, *, expected_state: str | None) -> str:
    """Pull ``code`` out of the redirect the browser could not follow.

    The browser fails to open the custom scheme and stops with the full
    redirect in its address bar; the user pastes that back to us.
    """
    parsed = urllib.parse.urlparse(redirect_url.strip())
    params = urllib.parse.parse_qs(parsed.query)

    if "error" in params:
        raise CliError(
            error="Authorization server returned an error",
            code="authorize_error",
            exit_code=exit_codes.AUTH,
            details={
                "upstreamError": params.get("error", [""])[0],
                "description": params.get("error_description", [""])[0],
            },
        )

    codes = params.get("code")
    if not codes or not codes[0]:
        raise CliError(
            error="No authorization code found in the pasted URL",
            code="missing_authorization_code",
            exit_code=exit_codes.USAGE,
            details={
                "hint": (
                    "Paste the entire URL the browser stopped on, including "
                    "the ?code=... query string."
                )
            },
        )

    if expected_state:
        got_state = params.get("state", [None])[0]
        if got_state != expected_state:
            raise CliError(
                error="State mismatch in authorization response",
                code="state_mismatch",
                exit_code=exit_codes.AUTH,
                details={
                    "hint": (
                        "The pasted URL does not belong to this login attempt. "
                        "Start over with `mindbody auth login`."
                    )
                },
            )

    return codes[0]


# ---------------------------------------------------------------------------
# Token endpoint
# ---------------------------------------------------------------------------


def _token_request(
    creds: ClientCredentials,
    form: dict[str, str],
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    headers = {
        "Authorization": creds.basic_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": ACCEPT_LANGUAGE,
    }
    url = f"{IDENTITY_HOST}{TOKEN_PATH}"
    try:
        response = httpx.post(url, data=form, headers=headers, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise CliError(
            error="Timed out talking to the authorization server",
            code="network_timeout",
            exit_code=exit_codes.NETWORK,
            details={"url": url},
        ) from exc
    except httpx.RequestError as exc:
        raise CliError(
            error="Network error talking to the authorization server",
            code="network_error",
            exit_code=exit_codes.NETWORK,
            details={"url": url, "reason": str(exc)},
        ) from exc

    try:
        data = response.json()
    except ValueError:
        data = {"raw": response.text[:500]}

    if response.status_code >= 400:
        raise CliError(
            error="Authorization server rejected the token request",
            code="token_request_failed",
            exit_code=exit_codes.AUTH,
            details={
                "status": response.status_code,
                "grantType": form.get("grant_type"),
                "response": data,
            },
        )
    if not isinstance(data, dict) or "access_token" not in data:
        raise CliError(
            error="Unexpected token response shape",
            code="invalid_token_response",
            exit_code=exit_codes.AUTH,
            details={"response": data},
        )
    return data


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    """Best-effort decode of a JWT payload. Signature is not verified.

    We only read this to discover our own user id, which the server also
    returns elsewhere; nothing security-relevant is decided from it.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _apply_token_response(state: TokenState, data: dict[str, Any]) -> TokenState:
    state.previous_refresh_token = state.refresh_token
    state.access_token = data["access_token"]
    state.refresh_token = data.get("refresh_token") or state.refresh_token
    state.id_token = data.get("id_token") or state.id_token
    state.scope = data.get("scope") or state.scope
    expires_in = data.get("expires_in")
    state.expires_at = (
        time.time() + float(expires_in) if expires_in is not None else None
    )

    claims = _decode_jwt_claims(state.access_token or "")
    for key in ("MboUserId", "mbo_user_id", "userId", "sub"):
        raw = claims.get(key)
        if raw is None:
            continue
        try:
            state.user_id = int(raw)
            break
        except (TypeError, ValueError):
            continue
    return state


def exchange_code(
    creds: ClientCredentials,
    *,
    code: str,
    verifier: str,
    state: TokenState | None = None,
) -> TokenState:
    """Trade a one-time authorization code for tokens."""
    data = _token_request(
        creds,
        {
            "grant_type": "authorization_code",
            "redirect_uri": creds.redirect_uri,
            "code_verifier": verifier,
            "code": code,
        },
    )
    return _apply_token_response(state or TokenState(), data)


def refresh_tokens(creds: ClientCredentials, state: TokenState) -> TokenState:
    """Rotate the refresh token and obtain a fresh access token."""
    if not state.refresh_token:
        raise CliError(
            error="No refresh token stored",
            code="login_required",
            exit_code=exit_codes.AUTH,
            details={"hint": "Run `mindbody auth login`."},
        )
    data = _token_request(
        creds,
        {
            "grant_type": "refresh_token",
            "refresh_token": state.refresh_token,
        },
    )
    return _apply_token_response(state, data)


def revoke_refresh_token(creds: ClientCredentials, refresh_token: str) -> bool:
    """Best-effort revocation. Returns True when upstream accepted it."""
    headers = {
        "Authorization": creds.basic_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": USER_AGENT,
    }
    try:
        response = httpx.post(
            f"{IDENTITY_HOST}{REVOCATION_PATH}",
            data={
                "token": refresh_token,
                "token_type_hint": "refresh_token",
            },
            headers=headers,
            timeout=15.0,
        )
    except httpx.RequestError:
        return False
    return response.status_code < 400


def ensure_fresh_tokens(
    store: TokenStore,
    creds: ClientCredentials | None = None,
    *,
    force: bool = False,
) -> TokenState:
    """Return a usable token state, refreshing under lock when required.

    The lock is taken *before* re-reading state so that a process which waited
    on it observes whatever the winner committed, rather than refreshing again
    with a token that is already dead.
    """
    state = store.load()
    if not state.is_authenticated:
        raise CliError(
            error="Not logged in",
            code="login_required",
            exit_code=exit_codes.AUTH,
            details={"hint": "Run `mindbody auth login` once to authenticate."},
        )
    if not force and not state.needs_refresh():
        return state

    resolved = creds or load_client_credentials()
    with store.refresh_lock():
        state = store.load()
        if not force and not state.needs_refresh():
            return state
        try:
            state = refresh_tokens(resolved, state)
        except CliError as exc:
            # The refresh chain is broken -- a rotated token was lost, or the
            # session was revoked elsewhere. Recover automatically only if the
            # account holder opted in by saving their credentials; otherwise
            # surface the error so they re-authenticate deliberately.
            recovered = _recover_with_saved_credentials(resolved, state, exc)
            if recovered is None:
                raise
            state = recovered
        store.save(state)
    return state


def _recover_with_saved_credentials(
    creds: ClientCredentials,
    state: TokenState,
    failure: CliError,
) -> TokenState | None:
    """Re-run headless sign-in from saved credentials, or None to give up."""
    if failure.exit_code != exit_codes.AUTH:
        return None
    saved = load_account_password()
    if not saved:
        return None
    username, password = saved
    refreshed = headless_login(
        creds,
        username=username,
        password=password,
        state=state,
    )
    refreshed.username = username
    return refreshed


# ---------------------------------------------------------------------------
# Non-interactive sign-in
# ---------------------------------------------------------------------------

# The sign-in pages are served to a web view and answer to a browser-shaped
# client; the token endpoint expects the native client's own agent.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/27.0 Mobile/15E148 "
    "Safari/604.1"
)


def _absolute(url: str) -> str:
    return url if url.startswith("http") else f"{IDENTITY_HOST}{url}"


def headless_login(
    creds: ClientCredentials,
    *,
    username: str,
    password: str,
    state: TokenState | None = None,
    timeout: float = 30.0,
) -> TokenState:
    """Complete the authorization-code flow without opening a browser.

    This drives the service's own published sign-in form on behalf of the
    account holder, using credentials they supplied for their own account. It
    is the same request sequence the official client performs. It exists
    because the alternative -- pasting a redirect URL out of a browser -- is
    not viable on an unattended host.

    The sign-in service uses standard ASP.NET Core antiforgery: ``/api/csrf``
    returns a token in its body and sets a paired cookie, and the login POST
    echoes that token in a ``requestverificationtoken`` header. No JavaScript
    is involved, so an ordinary HTTP client with a cookie jar suffices.

    This path can stop working the moment the operator enables a stricter
    challenge on the login POST. That is not something to defeat: the error
    raised below points at the browser flow instead.
    """
    pkce = generate_pkce()
    authorize_url = build_authorize_url(creds, pkce)

    headers = {
        "User-Agent": BROWSER_USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": ACCEPT_LANGUAGE,
        "Origin": IDENTITY_HOST,
    }

    with httpx.Client(
        timeout=timeout,
        follow_redirects=False,
        headers=headers,
    ) as http:
        try:
            # 1. Start the flow. The server redirects to the sign-in page,
            #    carrying the whole authorize request in ReturnUrl.
            first = http.get(authorize_url)
            location = first.headers.get("location")
            if first.status_code != 302 or not location:
                raise CliError(
                    error="Authorization endpoint did not start a sign-in flow",
                    code="headless_login_unexpected_response",
                    exit_code=exit_codes.AUTH,
                    details={"status": first.status_code},
                )
            signin_url = _absolute(location)
            return_url = urllib.parse.parse_qs(
                urllib.parse.urlparse(signin_url).query
            ).get("ReturnUrl", [""])[0]

            # 2. Load the sign-in page so the session is established normally.
            http.get(signin_url)

            # 3. Antiforgery token, plus the cookie that pairs with it.
            csrf_response = http.get(f"{IDENTITY_HOST}/api/csrf")
            try:
                token = csrf_response.json()["requestVerificationToken"]
            except (ValueError, KeyError) as exc:
                raise CliError(
                    error="Could not obtain an antiforgery token",
                    code="headless_login_blocked",
                    exit_code=exit_codes.AUTH,
                    details={
                        "status": csrf_response.status_code,
                        "hint": (
                            "The sign-in service is not answering this client. "
                            "Use the browser flow: `mindbody auth login`."
                        ),
                    },
                ) from exc

            # 4. Submit the account holder's credentials.
            login_response = http.post(
                f"{IDENTITY_HOST}/account/login",
                params={"ReturnUrl": return_url} if return_url else None,
                json={
                    "username": username,
                    "password": password,
                    "isStaff": False,
                },
                headers={
                    "requestverificationtoken": token,
                    "Content-Type": "application/json",
                    "Referer": signin_url,
                },
            )

            if login_response.status_code in (401, 403):
                raise CliError(
                    error="Sign-in was rejected",
                    code="invalid_credentials",
                    exit_code=exit_codes.AUTH,
                    details={
                        "status": login_response.status_code,
                        "hint": (
                            "Either the credentials are wrong, or the service "
                            "is challenging this client. Run `mindbody auth "
                            "login` in a browser to tell the two apart."
                        ),
                    },
                )
            if login_response.status_code >= 400:
                body: Any
                try:
                    body = login_response.json()
                except ValueError:
                    body = login_response.text[:400]
                raise CliError(
                    error="Sign-in failed",
                    code="headless_login_failed",
                    exit_code=exit_codes.AUTH,
                    details={
                        "status": login_response.status_code,
                        "response": body,
                    },
                )

            try:
                redirect_url = login_response.json()["redirectUrl"]
            except (ValueError, KeyError) as exc:
                raise CliError(
                    error="Sign-in response did not contain a redirect",
                    code="headless_login_unexpected_response",
                    exit_code=exit_codes.AUTH,
                    details={"status": login_response.status_code},
                ) from exc

            # 5. Follow the callback. It hands the code over on the custom
            #    scheme a browser cannot open but which we can simply read.
            callback = http.get(_absolute(redirect_url))
            code_location = callback.headers.get("location")
            if not code_location:
                raise CliError(
                    error="Authorization callback did not return a code",
                    code="headless_login_no_code",
                    exit_code=exit_codes.AUTH,
                    details={"status": callback.status_code},
                )
        except httpx.TimeoutException as exc:
            raise CliError(
                error="Timed out during sign-in",
                code="network_timeout",
                exit_code=exit_codes.NETWORK,
                details={"host": IDENTITY_HOST},
            ) from exc
        except httpx.RequestError as exc:
            raise CliError(
                error="Network error during sign-in",
                code="network_error",
                exit_code=exit_codes.NETWORK,
                details={"host": IDENTITY_HOST, "reason": str(exc)},
            ) from exc

    code = extract_code(code_location, expected_state=pkce.state)
    return exchange_code(creds, code=code, verifier=pkce.verifier, state=state)
