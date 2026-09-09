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
# The DEFAULT_* values below are the identifiers the vendor's own iOS client
# presents to the authorization server. They ship inside the publicly
# distributed app and are sent on every login by every user of it: a public
# client identifier, not a confidential secret, authorizing nothing without a
# user's own credentials and consent.
#
# They are bundled as defaults so a new user needs only their own username and
# password. Environment variables and the OS keychain still take precedence
# (see load_client_credentials), so an operator can override or replace them
# without editing source. See DISCLAIMER.md.
# ---------------------------------------------------------------------------

CLIENT_ID_ENV = "MINDBODY_OAUTH_CLIENT_ID"
CLIENT_SECRET_ENV = "MINDBODY_OAUTH_CLIENT_SECRET"
REDIRECT_URI_ENV = "MINDBODY_OAUTH_REDIRECT_URI"

DEFAULT_CLIENT_ID = "Mindbody.ConnectApp.iOS"
DEFAULT_CLIENT_SECRET = "93ea5f23-03d1-7808-5ee1-3d0d49e4ae9c"
DEFAULT_REDIRECT_URI = "x-mindbodyconnect-oauth-mindbody://authcode"

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

USERNAME_ENV = "MINDBODY_USERNAME"
PASSWORD_ENV = "MINDBODY_PASSWORD"
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
