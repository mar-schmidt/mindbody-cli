"""Normalisation of upstream payloads into a stable CLI surface.

The upstream shapes are inconsistent between services, deeply nested, and
carry the identifiers needed for the *next* action buried inside encoded
reference strings. Every normaliser here does the same job: flatten the
entry, and hoist the ids a caller needs to act on it to the top level.

That is what makes the output usable by an agent without a second lookup --
``bookings list`` returns the exact id ``bookings cancel`` wants.
"""

from __future__ import annotations

from typing import Any

from mindbody_cli.refs import BookingRef, InventoryRef

# Observed booking status codes. Treated as a display aid only: the upstream
# list is not exhaustive and new codes must not break the client, so the
# reported title always falls back to whatever the server said.
STATUS_CODES = {
    7: "signed_in",
    8: "waitlisted",
    13: "client_on_waitlist",
}


def _status(attrs: dict[str, Any]) -> dict[str, Any]:
    raw = attrs.get("status")
    if isinstance(raw, list) and raw:
        raw = raw[0]
    if not isinstance(raw, dict):
        return {"code": None, "title": None, "message": None}
    code = raw.get("code", raw.get("id"))
    return {
        "code": code,
        "title": raw.get("title") or raw.get("status") or STATUS_CODES.get(code),
        "message": raw.get("message"),
    }


def normalize_booking(entry: dict[str, Any]) -> dict[str, Any]:
    """Flatten one entry from ``/v1/user/bookings``.

    Both confirmed bookings and waitlist positions arrive here. ``kind``
    disambiguates them, and only the id relevant to that kind is populated:
    ``siteVisitId`` cancels a booking, ``waitlistId`` leaves a waitlist.
    """
    attrs = entry.get("attributes") or {}
    booking_ref = BookingRef.from_raw(attrs.get("bookingRefJson"))
    inventory_ref = InventoryRef.from_raw(attrs.get("inventoryRefJson"))
    status = _status(attrs)

    return {
        "id": entry.get("id"),
        "kind": "waitlist" if booking_ref.is_waitlist else "booking",
        "name": attrs.get("name"),
        "startTime": attrs.get("startTime"),
        "endTime": attrs.get("endTime"),
        "locationName": attrs.get("locationName"),
        "businessName": attrs.get("locationBusinessName"),
        "timezone": attrs.get("locationTimezone"),
        "serviceType": attrs.get("serviceType"),
        "categoryType": attrs.get("categoryType"),
        "status": status,
        # Identifiers required to act on this entry:
        "classId": inventory_ref.class_id or None,
        "siteId": booking_ref.site_id or None,
        "siteVisitId": booking_ref.site_visit_id,
        "waitlistId": booking_ref.waitlist_id,
        # Opaque handle for the cancellability probe.
        "bookingRefJson": attrs.get("bookingRefJson"),
    }


def normalize_pass(entry: dict[str, Any]) -> dict[str, Any]:
    """Flatten one entry from ``/v1/user/passes``."""
    attrs = entry.get("attributes") or {}
    return {
        "id": entry.get("id"),
        "name": attrs.get("name"),
        "businessName": attrs.get("businessName"),
        "serviceType": attrs.get("serviceType"),
        "active": attrs.get("active"),
        "isUnlimited": attrs.get("isUnlimited"),
        "sessionsRemaining": attrs.get("sessionsRemaining"),
        "totalSessions": attrs.get("totalSessions"),
        "activatedDate": attrs.get("activatedDate"),
        "expirationDate": attrs.get("expirationDate"),
        "timezone": attrs.get("timezone"),
        "passRefJson": attrs.get("passRefJson"),
    }


def normalize_class_time(entry: dict[str, Any]) -> dict[str, Any]:
    """Flatten one schedule entry from ``/v1/location/schedules``.

    The gateway nests the interesting fields one level deeper than the
    envelope suggests (``attributes.attributes``), which is easy to get
    wrong at a call site and is handled once here.
    """
    outer = entry.get("attributes") or {}
    attrs = outer.get("attributes") or outer
    course = attrs.get("course") or {}
    staff = attrs.get("staff") or {}
    inventory_ref = InventoryRef.from_raw(
        attrs.get("inventoryRefJson") or course.get("inventoryRefJson")
    )
    status = _status(attrs)

    capacity = attrs.get("capacity")
    booked = attrs.get("totalBooked", attrs.get("bookedCount"))
    spots_open = attrs.get("spotsOpen")
    if spots_open is None and isinstance(capacity, int) and isinstance(booked, int):
        spots_open = max(0, capacity - booked)

    return {
        "classId": inventory_ref.class_id or None,
        "name": course.get("name") or attrs.get("name"),
        "description": course.get("description"),
        "category": course.get("category"),
        "startTime": attrs.get("startTime"),
        "endTime": attrs.get("endTime"),
        "durationMinutes": attrs.get("duration"),
        "staffName": staff.get("name"),
        "capacity": capacity,
        "spotsOpen": spots_open,
        "isCancelled": attrs.get("isCancelled"),
        "status": status,
        "waitlistId": attrs.get("waitlistId"),
        "waitlistPosition": attrs.get("waitlistPosition"),
        "siteVisitId": attrs.get("siteVisitId"),
        "siteId": inventory_ref.site_id or None,
        "inventoryRefJson": (
            attrs.get("inventoryRefJson") or course.get("inventoryRefJson")
        ),
    }


def normalize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Flatten the identity gateway profile."""
    return {
        "identityId": profile.get("id"),
        "firstName": profile.get("firstName"),
        "lastName": profile.get("lastName"),
        "email": profile.get("email"),
        "createdAt": profile.get("universalCreationDateUtc"),
        "countryCode": profile.get("countryCode"),
        "hasPassword": profile.get("hasPassword"),
    }


def summarize_activity_profile(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten ``/v1/user/activity_profile`` into counts plus studios."""
    attrs = data.get("attributes") or {}
    summary = attrs.get("summary") or {}
    locations = []
    for loc in attrs.get("businessLocations") or []:
        from mindbody_cli.refs import LocationRef

        ref = LocationRef.from_raw(loc.get("locationRefJson"))
        bookings = loc.get("bookings") or {}
        locations.append(
            {
                "name": loc.get("name"),
                "businessName": loc.get("businessName"),
                "segment": loc.get("segment"),
                "siteId": ref.site_id or None,
                "locationId": ref.location_id or None,
                "masterLocationId": ref.master_location_id or None,
                "upcoming": bookings.get("upcoming"),
                "past": bookings.get("past"),
            }
        )
    return {
        "totalUpcomingBookings": summary.get("totalUpcomingBookings"),
        "totalPastBookings": summary.get("totalPastBookings"),
        "hasAnyActivePass": summary.get("hasAnyActivePass"),
        "hasAnyUpcomingBooking": summary.get("hasAnyUpcomingBooking"),
        "segment": summary.get("segment"),
        "locations": locations,
    }
