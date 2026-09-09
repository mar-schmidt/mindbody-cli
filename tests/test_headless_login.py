"""Tests for the browserless sign-in flow.

The upstream is mocked with respx: these assert the request *sequence* and the
credential-resolution order, not live behaviour (that was verified by hand).
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from mindbody_cli.client.oauth import ClientCredentials, headless_login
from mindbody_cli.client.tokens import TokenState
from mindbody_cli.config import IDENTITY_HOST
from mindbody_cli.errors import CliError

CREDS = ClientCredentials(
    client_id="Example.App.iOS",
    client_secret="test-secret",
    redirect_uri="x-example-oauth://authcode",
)


def _wire_happy_path(mock: respx.MockRouter, *, code: str = "auth-code-123") -> None:
    # 1. authorize -> 302 to /signin?ReturnUrl=...
    mock.get(f"{IDENTITY_HOST}/connect/authorize").mock(
        return_value=httpx.Response(
            302,
            headers={
                "location": f"{IDENTITY_HOST}/signin?ReturnUrl=%2Fconnect%2Fauthorize%2Fcallback"
            },
        )
    )
    # 2. signin page
    mock.get(f"{IDENTITY_HOST}/signin").mock(return_value=httpx.Response(200))
    # 3. antiforgery token
    mock.get(f"{IDENTITY_HOST}/api/csrf").mock(
        return_value=httpx.Response(
            200,
            json={"requestVerificationToken": "csrf-token"},
            headers={"set-cookie": ".AspNetCore.Antiforgery.x=cookieval; path=/"},
        )
    )
    # 4. login -> redirectUrl to the callback
    mock.post(f"{IDENTITY_HOST}/account/login").mock(
        return_value=httpx.Response(
            200,
            json={"redirectUrl": "/connect/authorize/callback?x=1"},
        )
    )
    # 5. callback -> 302 to the custom scheme carrying the code. state is filled
    #    in per-test because it is generated inside headless_login.
    mock.get(f"{IDENTITY_HOST}/connect/authorize/callback")
    # 6. token exchange
    mock.post(f"{IDENTITY_HOST}/connect/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "access-jwt",
                "refresh_token": "refresh-1",
                "id_token": "id-jwt",
                "expires_in": 43200,
                "scope": "openid profile",
            },
        )
    )


@respx.mock
def test_headless_login_drives_the_full_sequence() -> None:
    _wire_happy_path(respx.mock)

    # The callback needs the state value, which is created inside the call, so
    # intercept the login POST to learn it, then answer the callback with it.
    def _callback(request: httpx.Request) -> httpx.Response:
        # state was round-tripped through the authorize URL; echo any value,
        # because extract_code validates it against what this flow generated.
        # We capture it from the authorize request instead.
        return httpx.Response(
            302,
            headers={
                "location": f"{CREDS.redirect_uri}?code=auth-code-123&state={_captured['state']}"
            },
        )

    _captured: dict[str, str] = {}

    def _authorize(request: httpx.Request) -> httpx.Response:
        _captured["state"] = dict(request.url.params)["state"]
        return httpx.Response(
            302,
            headers={
                "location": f"{IDENTITY_HOST}/signin?ReturnUrl=%2Fconnect%2Fauthorize%2Fcallback"
            },
        )

    respx.mock.get(f"{IDENTITY_HOST}/connect/authorize").mock(side_effect=_authorize)
    respx.mock.get(f"{IDENTITY_HOST}/connect/authorize/callback").mock(
        side_effect=_callback
    )

    state = headless_login(
        CREDS, username="user@example.com", password="pw", state=TokenState()
    )

    assert state.access_token == "access-jwt"
    assert state.refresh_token == "refresh-1"

    # The login POST must carry the antiforgery token in the header.
    login_request = respx.mock.routes[3].calls.last.request
    assert login_request.headers["requestverificationtoken"] == "csrf-token"
    body = json.loads(login_request.content)
    assert body == {"username": "user@example.com", "password": "pw", "isStaff": False}


@respx.mock
def test_headless_login_raises_when_csrf_blocked() -> None:
    respx.mock.get(f"{IDENTITY_HOST}/connect/authorize").mock(
        return_value=httpx.Response(
            302, headers={"location": f"{IDENTITY_HOST}/signin?ReturnUrl=%2Fx"}
        )
    )
    respx.mock.get(f"{IDENTITY_HOST}/signin").mock(return_value=httpx.Response(200))
    # A challenge page instead of the token JSON.
    respx.mock.get(f"{IDENTITY_HOST}/api/csrf").mock(
        return_value=httpx.Response(403, text="<html>challenge</html>")
    )

    with pytest.raises(CliError) as exc:
        headless_login(CREDS, username="u@example.com", password="pw")
    assert exc.value.code == "headless_login_blocked"
    assert exc.value.exit_code == 2


@respx.mock
def test_headless_login_maps_rejected_credentials() -> None:
    respx.mock.get(f"{IDENTITY_HOST}/connect/authorize").mock(
        return_value=httpx.Response(
            302, headers={"location": f"{IDENTITY_HOST}/signin?ReturnUrl=%2Fx"}
        )
    )
    respx.mock.get(f"{IDENTITY_HOST}/signin").mock(return_value=httpx.Response(200))
    respx.mock.get(f"{IDENTITY_HOST}/api/csrf").mock(
        return_value=httpx.Response(200, json={"requestVerificationToken": "t"})
    )
    respx.mock.post(f"{IDENTITY_HOST}/account/login").mock(
        return_value=httpx.Response(401, json={"error": "invalid"})
    )

    with pytest.raises(CliError) as exc:
        headless_login(CREDS, username="u@example.com", password="wrong")
    assert exc.value.code == "invalid_credentials"
