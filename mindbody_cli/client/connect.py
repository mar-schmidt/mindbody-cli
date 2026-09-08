"""The legacy REST service: ``connect.mindbodyonline.com``.

Cancellation and waitlist membership live here rather than on the gateway,
and this service has its own conventions: PascalCase request bodies, numeric
path ids, 204 responses with empty bodies, and a user id that is *not* the
identity id returned by the identity gateway.
"""

from __future__ import annotations

from typing import Any

from mindbody_cli import exit_codes
from mindbody_cli.client.http import MindbodyHttpClient
from mindbody_cli.config import CONNECT_HOST
from mindbody_cli.errors import CliError


def _require_user_id(client: MindbodyHttpClient) -> int:
    user_id = client.state.user_id
    if not user_id:
        raise CliError(
            error="No Mindbody user id resolved",
            code="missing_user_id",
            exit_code=exit_codes.AUTH,
            details={
                "hint": (
                    "Run `mindbody auth status --refresh` to resolve account "
                    "identifiers, or `mindbody auth login` if that fails."
                )
            },
        )
    return int(user_id)


def list_sites(client: MindbodyHttpClient) -> list[dict[str, Any]]:
    """Studios the account is linked to."""
    user_id = _require_user_id(client)
    data = client.request_json("GET", f"{CONNECT_HOST}/rest/user/{user_id}/sites")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("Sites", "sites", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def get_class(client: MindbodyHttpClient, class_id: int) -> dict[str, Any]:
    """Class detail, including waitlist position when the user is queued."""
    data = client.request_json("GET", f"{CONNECT_HOST}/rest/Class/{class_id}")
    return data if isinstance(data, dict) else {}


def cancel_visit(client: MindbodyHttpClient, site_visit_id: int) -> None:
    """Cancel a confirmed booking.

    Note the id: this is ``mb_site_visit_id`` from ``bookingRefJson``, not the
    gateway's booking uuid and not the class id.
    """
    user_id = _require_user_id(client)
    client.request_no_content(
        "DELETE",
        f"{CONNECT_HOST}/rest/user/{user_id}/visits/{site_visit_id}",
    )


def join_waitlist(client: MindbodyHttpClient, class_id: int) -> None:
    """Join a full class's waitlist.

    Returns 201 with an empty body -- the assigned waitlist id has to be read
    back from the bookings list afterwards.
    """
    user_id = _require_user_id(client)
    client.request_no_content(
        "POST",
        f"{CONNECT_HOST}/rest/user/{user_id}/waitlist",
        params={"checkVerified": "true"},
        payload={"ClassId": int(class_id)},
    )


def leave_waitlist(client: MindbodyHttpClient, waitlist_id: int) -> None:
    """Leave a waitlist using ``mb_waitlist_id`` from ``bookingRefJson``."""
    user_id = _require_user_id(client)
    client.request_no_content(
        "DELETE",
        f"{CONNECT_HOST}/rest/user/{user_id}/waitlist/{waitlist_id}",
    )
