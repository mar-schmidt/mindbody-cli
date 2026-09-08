"""The identity gateway: ``www.mindbodyapis.com``.

Only the account profile lives here. Note that the ``id`` it returns is an
identity-service id and is *not* interchangeable with the numeric user id the
legacy REST service expects in its paths.
"""

from __future__ import annotations

from typing import Any

from mindbody_cli.client.http import MindbodyHttpClient
from mindbody_cli.config import IDENTITY_API_HOST

ME_URL = f"{IDENTITY_API_HOST}/identity/gateway/V2/Users/Me"


def get_me(client: MindbodyHttpClient) -> dict[str, Any]:
    """Return the authenticated user's profile."""
    data = client.request_json("GET", ME_URL)
    return data if isinstance(data, dict) else {}
