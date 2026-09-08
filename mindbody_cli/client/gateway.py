"""The modern gateway: ``prod-mkt-gateway.mindbody.io``.

Reads (bookings, passes, schedules, activity profile) and class booking
creation live here. Cancellation does not -- see ``connect.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from mindbody_cli.client.http import MindbodyHttpClient
from mindbody_cli.config import GATEWAY_HOST
from mindbody_cli.refs import InventoryRef, LocationRef

BOOKINGS_URL = f"{GATEWAY_HOST}/v1/user/bookings"
PASSES_URL = f"{GATEWAY_HOST}/v1/user/passes"
ACTIVITY_PROFILE_URL = f"{GATEWAY_HOST}/v1/user/activity_profile"
SCHEDULES_URL = f"{GATEWAY_HOST}/v1/location/schedules"
CLASS_BOOKINGS_URL = f"{GATEWAY_HOST}/v1/class-bookings"
CANCELLABILITY_URL = f"{GATEWAY_HOST}/v1/user/bookings/cancellability"
CACHE_CLEAR_URL = f"{GATEWAY_HOST}/v1/user/cache/clear"


def iso_utc(value: datetime) -> str:
    """Format a datetime the way the gateway expects it."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def list_bookings(
    client: MindbodyHttpClient,
    *,
    page_size: int = 30,
    before: datetime | None = None,
    ascending: bool = False,
    include_classes: bool = True,
) -> list[dict[str, Any]]:
    """Return raw booking entries, newest first by default.

    Both confirmed bookings and waitlist entries come back from this one
    endpoint; they are distinguished by ``status.code`` and by which id in
    ``bookingRefJson`` is populated.
    """
    params: dict[str, Any] = {
        "page.size": page_size,
        "filter.ascending": str(ascending).lower(),
        "filter.include_classes": str(include_classes).lower(),
    }
    if before is not None:
        params["filter.before"] = iso_utc(before)

    data = client.request_json("GET", BOOKINGS_URL, params=params)
    return list(data.get("data") or []) if isinstance(data, dict) else []


def list_upcoming_bookings(
    client: MindbodyHttpClient,
    *,
    page_size: int = 50,
    horizon_days: int = 400,
) -> list[dict[str, Any]]:
    """Bookings from now forward.

    ``filter.before`` is an upper bound on start time, so a forward-looking
    query asks for everything before a far horizon in ascending order and
    then drops anything already in the past.
    """
    horizon = datetime.now(UTC) + timedelta(days=horizon_days)
    entries = list_bookings(
        client,
        page_size=page_size,
        before=horizon,
        ascending=True,
    )
    now = datetime.now(UTC)
    upcoming: list[dict[str, Any]] = []
    for entry in entries:
        attrs = entry.get("attributes") or {}
        start = attrs.get("startTime")
        if not start:
            continue
        try:
            parsed = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed >= now:
            upcoming.append(entry)
    return upcoming


def list_passes(
    client: MindbodyHttpClient,
    *,
    status: str = "both",
) -> list[dict[str, Any]]:
    """Return membership passes. ``status`` is one of active/inactive/both."""
    data = client.request_json("GET", PASSES_URL, params={"status": status})
    return list(data.get("data") or []) if isinstance(data, dict) else []


def get_activity_profile(client: MindbodyHttpClient) -> dict[str, Any]:
    """Return the account summary: counts, studios, and pass state."""
    data = client.request_json("POST", ACTIVITY_PROFILE_URL, payload={})
    if isinstance(data, dict):
        return data.get("data") or {}
    return {}


def list_schedules(
    client: MindbodyHttpClient,
    location: LocationRef,
    *,
    start_from: datetime,
    start_to: datetime,
    bookable_with_passes: str = "any",
    online_bookable: str = "any",
) -> list[dict[str, Any]]:
    """Return the schedule for one studio between two instants.

    Use this rather than ``/v1/search/class_times``: the latter is a
    geographic search across all studios and returns nothing useful when you
    already know which location you want.
    """
    payload = {
        "location_ref_json": location.to_json(),
        "start_time_from": iso_utc(start_from),
        "start_time_to": iso_utc(start_to),
        "bookable_with_passes": bookable_with_passes,
        "online_bookable": online_bookable,
    }
    data = client.request_json("POST", SCHEDULES_URL, payload=payload)
    return list(data.get("data") or []) if isinstance(data, dict) else []


def create_class_booking(
    client: MindbodyHttpClient,
    inventory: InventoryRef,
    *,
    payment_id: str,
) -> dict[str, Any]:
    """Book a class using a membership pass.

    ``payment_id`` is the pass id from :func:`list_passes`; there is no
    "book with my default pass" affordance upstream.
    """
    payload = {
        "inventory_ref_json": inventory.to_json(),
        "payment_id": str(payment_id),
    }
    data = client.request_json("POST", CLASS_BOOKINGS_URL, payload=payload)
    return data.get("data") or {} if isinstance(data, dict) else {}


def check_cancellability(
    client: MindbodyHttpClient,
    booking_ref_json: str,
) -> dict[str, Any]:
    """Ask whether a booking can be cancelled, and at what cost."""
    data = client.request_json(
        "POST",
        CANCELLABILITY_URL,
        payload={"bookingRefJson": booking_ref_json},
    )
    if isinstance(data, dict):
        return (data.get("data") or {}).get("attributes") or {}
    return {}


def clear_cache(client: MindbodyHttpClient) -> None:
    """Invalidate the gateway's user cache after a mutation.

    The gateway caches reads aggressively. Without this, a list issued
    immediately after a booking or cancellation can return stale data.
    """
    try:
        client.request_no_content("POST", CACHE_CLEAR_URL, payload={})
    except Exception:
        # Best effort: a failed cache bust must never fail the mutation that
        # already succeeded.
        return
