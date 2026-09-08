"""Configuration: filesystem paths, environment defaults, API constants.

Every constant here was derived by observing the official Mindbody mobile
client against the author's own account. Nothing is copied from Mindbody
source code, and no Mindbody credential is vendored into this repository.
See DISCLAIMER.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# API hosts
#
# The consumer-facing surface is not one API. Booking goes to the modern
# gateway while cancellation and waitlists go to an older REST service, and
# they use different id spaces and naming conventions.
# ---------------------------------------------------------------------------

IDENTITY_HOST = "https://signin.mindbodyonline.com"
GATEWAY_HOST = "https://prod-mkt-gateway.mindbody.io"
CONNECT_HOST = "https://connect.mindbodyonline.com"
IDENTITY_API_HOST = "https://www.mindbodyapis.com"

AUTHORIZE_PATH = "/connect/authorize"
TOKEN_PATH = "/connect/token"
REVOCATION_PATH = "/connect/revocation"
DISCOVERY_PATH = "/.well-known/openid-configuration"

# ---------------------------------------------------------------------------
# OAuth public client
#
# This project deliberately ships NO client credentials. The authorization
# server expects the identifiers used by the vendor's own mobile client, and
# those belong to the vendor, not to this project. Vendoring them here would
# redistribute someone else's identifiers and is exactly what DISCLAIMER.md
# says this project does not do.
#
# Supply them yourself via environment variables, or run
# `mindbody auth bootstrap` once to import them from your own captured
# traffic into your OS keychain.
# ---------------------------------------------------------------------------

CLIENT_ID_ENV = "MINDBODY_OAUTH_CLIENT_ID"
CLIENT_SECRET_ENV = "MINDBODY_OAUTH_CLIENT_SECRET"
REDIRECT_URI_ENV = "MINDBODY_OAUTH_REDIRECT_URI"

OAUTH_SCOPES = (
    "openid profile email offline_access "
    "Mindbody.Api.Connect Mindbody.Api.Rest Mindbody.Api.Payments "
    "Mindbody.Identity.UserGateway Mindbody.Identity.BusinessLinks "
    "Identity.Legacy.Gateway Mindbody.Clients"
)

# The upstream WAF is sensitive to client fingerprint. Presenting the mobile
# client's own User-Agent is the difference between a 200 and a block.
USER_AGENT = "MINDBODY/8.22.0 (iPhone; iOS 27.0; Scale/3.00)"
ACCEPT_LANGUAGE = "sv-US;q=1, en-US;q=0.9"

# Refresh this many seconds before the access token actually expires, so
# unattended jobs never spend a request discovering the token died.
TOKEN_REFRESH_MARGIN_SECONDS = 300

# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------

TOKEN_PATH_ENV = "MINDBODY_CLI_TOKEN_PATH"
TOKEN_BACKEND_ENV = "MINDBODY_CLI_TOKEN_BACKEND"
SITE_ID_ENV = "MINDBODY_SITE_ID"
LOCATION_ID_ENV = "MINDBODY_LOCATION_ID"
MASTER_LOCATION_ID_ENV = "MINDBODY_MASTER_LOCATION_ID"


@dataclass(slots=True)
class AppPaths:
    """Resolved filesystem paths used by the CLI."""

    token_path: Path
    lock_path: Path

    @property
    def config_dir(self) -> Path:
        return self.token_path.parent


def get_app_paths() -> AppPaths:
    """Resolve token file path from env or default config location."""
    from_env = os.environ.get(TOKEN_PATH_ENV)
    if from_env:
        token_path = Path(from_env).expanduser()
    else:
        token_path = Path.home() / ".config" / "mindbody-cli" / "tokens.json"
    return AppPaths(
        token_path=token_path,
        lock_path=token_path.with_suffix(".lock"),
    )


def get_token_backend() -> str:
    """Return the configured token backend: 'keyring', 'file', or 'auto'."""
    value = os.environ.get(TOKEN_BACKEND_ENV, "auto").strip().lower()
    if value not in {"auto", "keyring", "file"}:
        return "auto"
    return value


def _env_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def get_default_site_id() -> int | None:
    return _env_int(SITE_ID_ENV)


def get_default_location_id() -> int | None:
    return _env_int(LOCATION_ID_ENV)


def get_default_master_location_id() -> int | None:
    return _env_int(MASTER_LOCATION_ID_ENV)
