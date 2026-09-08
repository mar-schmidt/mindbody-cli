from __future__ import annotations

import json

from mindbody_cli.models import (
    normalize_booking,
    normalize_class_time,
    normalize_pass,
)


def _booking_entry(*, waitlist: bool) -> dict:
    booking_ref = {
        "mb_site_id": 25441,
        "mb_site_visit_id": -1 if waitlist else 806714,
        "inventory_source": "MB",
        "mb_program_type": "Class",
        "mb_waitlist_id": 78637 if waitlist else None,
    }
    return {
        "id": "abc",
        "attributes": {
            "name": "Group Class",
            "startTime": "2026-09-10T10:00:00Z",
            "locationName": "Test Studio",
            "status": [
                {"code": 8 if waitlist else 7, "title": "x", "message": "y"}
            ],
            "bookingRefJson": json.dumps(booking_ref),
            "inventoryRefJson": json.dumps(
                {"mb_class_id": 48192, "mb_site_id": 25441}
            ),
        },
    }


def test_normalize_booking_marks_confirmed_booking() -> None:
    entry = normalize_booking(_booking_entry(waitlist=False))
    assert entry["kind"] == "booking"
    # The id needed to cancel is hoisted to the top level.
    assert entry["siteVisitId"] == 806714
    assert entry["waitlistId"] is None
    assert entry["classId"] == 48192


def test_normalize_booking_marks_waitlist_entry() -> None:
    entry = normalize_booking(_booking_entry(waitlist=True))
    assert entry["kind"] == "waitlist"
    assert entry["waitlistId"] == 78637
    assert entry["siteVisitId"] is None


def test_normalize_class_time_reads_nested_attributes() -> None:
    raw = {
        "id": "sched-1",
        "attributes": {
            "attributes": {
                "startTime": "2026-09-11T04:00:00Z",
                "capacity": 18,
                "duration": 60,
                "staff": {"name": "Coach"},
                "course": {"name": "Group Class", "category": "Gym classes"},
                "waitlistId": 78637,
                "waitlistPosition": 4,
                "inventoryRefJson": json.dumps(
                    {"mb_class_id": 48192, "mb_site_id": 25441}
                ),
            }
        },
    }
    entry = normalize_class_time(raw)
    assert entry["classId"] == 48192
    assert entry["name"] == "Group Class"
    assert entry["capacity"] == 18
    assert entry["waitlistPosition"] == 4
    assert entry["staffName"] == "Coach"


def test_normalize_pass_exposes_remaining_sessions() -> None:
    raw = {
        "id": "aae53d41",
        "attributes": {
            "name": "2 pass / vecka",
            "sessionsRemaining": 40,
            "totalSessions": 40,
            "active": True,
            "isUnlimited": False,
        },
    }
    entry = normalize_pass(raw)
    assert entry["sessionsRemaining"] == 40
    assert entry["active"] is True
