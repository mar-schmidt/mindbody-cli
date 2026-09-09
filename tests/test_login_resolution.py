"""Credential-resolution order for `auth login`.

flag -> environment -> stdin -> prompt, for both username and password.
The network call is stubbed; only which credentials reach it is asserted.
"""

from __future__ import annotations

import io

import pytest

import mindbody_cli.commands.auth as auth
from mindbody_cli.client.oauth import ClientCredentials
from mindbody_cli.client.tokens import TokenState
from mindbody_cli.config import PASSWORD_ENV, USERNAME_ENV
from mindbody_cli.errors import CliError

CREDS = ClientCredentials("id", "secret", "x://authcode")


class _FakeStore:
    backend = "file"

    def load(self) -> TokenState:
        return TokenState()

    def save(self, state: TokenState) -> None:  # noqa: D401
        self._saved = state


class _FakeRuntime:
    def __init__(self) -> None:
        self.store = _FakeStore()


@pytest.fixture
def captured(monkeypatch):
    """Capture the credentials that reach headless_login, and short-circuit it."""
    seen: dict[str, str] = {}

    def _fake_headless_login(creds, *, username, password, state=None, timeout=30.0):
        seen["username"] = username
        seen["password"] = password
        return TokenState(access_token="a", refresh_token="r", username=username)

    monkeypatch.setattr(auth, "headless_login", _fake_headless_login)
    # Skip the post-login identifier resolution, which would hit the network.
    monkeypatch.setattr(auth, "_resolve_identifiers", lambda runtime, state: state)
    for var in (USERNAME_ENV, PASSWORD_ENV):
        monkeypatch.delenv(var, raising=False)
    return seen


def test_flags_win(captured) -> None:
    auth._headless_login(_FakeRuntime(), CREDS, "flag@example.com", "flagpw", False)
    assert captured == {"username": "flag@example.com", "password": "flagpw"}


def test_environment_is_used_when_flags_absent(captured, monkeypatch) -> None:
    monkeypatch.setenv(USERNAME_ENV, "env@example.com")
    monkeypatch.setenv(PASSWORD_ENV, "envpw")
    auth._headless_login(_FakeRuntime(), CREDS, None, None, False)
    assert captured == {"username": "env@example.com", "password": "envpw"}


def test_flag_overrides_environment(captured, monkeypatch) -> None:
    monkeypatch.setenv(PASSWORD_ENV, "envpw")
    auth._headless_login(_FakeRuntime(), CREDS, "u@example.com", "flagpw", False)
    assert captured["password"] == "flagpw"


def test_password_stdin(captured, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("stdinpw\n"))
    auth._headless_login(_FakeRuntime(), CREDS, "u@example.com", None, True)
    assert captured["password"] == "stdinpw"


def test_missing_username_is_usage_error(captured) -> None:
    with pytest.raises(CliError) as exc:
        auth._headless_login(_FakeRuntime(), CREDS, None, "pw", False)
    assert exc.value.code == "missing_username"
    assert exc.value.exit_code == 1


def test_missing_password_is_usage_error(captured, monkeypatch) -> None:
    # No flag, no env, stdin not requested, and not a TTY.
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    with pytest.raises(CliError) as exc:
        auth._headless_login(_FakeRuntime(), CREDS, "u@example.com", None, False)
    assert exc.value.code == "missing_password"
