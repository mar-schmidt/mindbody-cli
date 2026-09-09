"""Self-healing re-authentication when the refresh chain breaks."""

from __future__ import annotations

import pytest

import mindbody_cli.client.oauth as oauth
from mindbody_cli.client.oauth import ClientCredentials, ensure_fresh_tokens
from mindbody_cli.client.tokens import TokenState, TokenStore
from mindbody_cli.config import AppPaths
from mindbody_cli.errors import CliError
from mindbody_cli import exit_codes

CREDS = ClientCredentials("id", "secret", "x://authcode")


def _store(tmp_path) -> TokenStore:
    token = tmp_path / "tokens.json"
    paths = AppPaths(token_path=token, lock_path=token.with_suffix(".lock"))
    return TokenStore(paths, backend="file")


def _auth_failure() -> CliError:
    return CliError("expired", "auth_required", exit_codes.AUTH, {})


def test_recovers_with_saved_credentials(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    store.save(TokenState(refresh_token="dead", expires_at=0))

    monkeypatch.setattr(oauth, "refresh_tokens", lambda creds, state: (_ for _ in ()).throw(_auth_failure()))
    monkeypatch.setattr(oauth, "load_account_password", lambda: ("u@example.com", "pw"))

    def _fake_headless(creds, *, username, password, state=None, timeout=30.0):
        return TokenState(access_token="new", refresh_token="fresh", username=username)

    monkeypatch.setattr(oauth, "headless_login", _fake_headless)

    state = ensure_fresh_tokens(store, CREDS, force=True)
    assert state.access_token == "new"
    assert state.refresh_token == "fresh"
    # Recovery is persisted, not just returned.
    assert store.load().refresh_token == "fresh"


def test_raises_when_no_saved_credentials(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    store.save(TokenState(refresh_token="dead", expires_at=0))

    monkeypatch.setattr(oauth, "refresh_tokens", lambda creds, state: (_ for _ in ()).throw(_auth_failure()))
    monkeypatch.setattr(oauth, "load_account_password", lambda: None)

    with pytest.raises(CliError) as exc:
        ensure_fresh_tokens(store, CREDS, force=True)
    assert exc.value.code == "auth_required"


def test_non_auth_failure_is_not_recovered(tmp_path, monkeypatch) -> None:
    store = _store(tmp_path)
    store.save(TokenState(refresh_token="x", expires_at=0))

    net = CliError("down", "network_error", exit_codes.NETWORK, {})
    monkeypatch.setattr(oauth, "refresh_tokens", lambda creds, state: (_ for _ in ()).throw(net))
    # Even with saved credentials, a network error must propagate untouched.
    monkeypatch.setattr(oauth, "load_account_password", lambda: ("u", "p"))

    with pytest.raises(CliError) as exc:
        ensure_fresh_tokens(store, CREDS, force=True)
    assert exc.value.code == "network_error"
