"""Resolution order for the OAuth client registration.

environment > keychain > bundled defaults. The bundled defaults must make the
common case work with no configuration at all.
"""

from __future__ import annotations

import mindbody_cli.client.oauth as oauth
from mindbody_cli import config
from mindbody_cli.client.oauth import load_client_credentials


def _clear_env(monkeypatch) -> None:
    for var in (
        config.CLIENT_ID_ENV,
        config.CLIENT_SECRET_ENV,
        config.REDIRECT_URI_ENV,
    ):
        monkeypatch.delenv(var, raising=False)


def test_defaults_used_when_nothing_configured(monkeypatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setattr(oauth, "_client_credentials_from_keyring", lambda: None)

    creds = load_client_credentials()
    assert creds.client_id == config.DEFAULT_CLIENT_ID
    assert creds.client_secret == config.DEFAULT_CLIENT_SECRET
    assert creds.redirect_uri == config.DEFAULT_REDIRECT_URI


def test_environment_overrides_defaults(monkeypatch) -> None:
    monkeypatch.setattr(oauth, "_client_credentials_from_keyring", lambda: None)
    monkeypatch.setenv(config.CLIENT_ID_ENV, "env-id")
    monkeypatch.setenv(config.CLIENT_SECRET_ENV, "env-secret")
    monkeypatch.setenv(config.REDIRECT_URI_ENV, "env://redirect")

    creds = load_client_credentials()
    assert creds.client_id == "env-id"
    assert creds.client_secret == "env-secret"
    assert creds.redirect_uri == "env://redirect"


def test_keychain_overrides_defaults(monkeypatch) -> None:
    _clear_env(monkeypatch)
    stored = oauth.ClientCredentials("kc-id", "kc-secret", "kc://redirect")
    monkeypatch.setattr(oauth, "_client_credentials_from_keyring", lambda: stored)

    creds = load_client_credentials()
    assert creds.client_id == "kc-id"
    assert creds.redirect_uri == "kc://redirect"


def test_never_raises_without_configuration(monkeypatch) -> None:
    # The old behaviour raised client_not_configured; that path is gone.
    _clear_env(monkeypatch)
    monkeypatch.setattr(oauth, "_client_credentials_from_keyring", lambda: None)
    creds = load_client_credentials()
    assert creds.client_id and creds.client_secret and creds.redirect_uri
