from __future__ import annotations

import json

import pytest

from mindbody_cli.errors import CliError
from mindbody_cli.refs import BookingRef, InventoryRef, LocationRef, parse_ref


def test_parse_ref_accepts_encoded_string() -> None:
    raw = json.dumps({"mb_site_id": 25441})
    assert parse_ref(raw, field="x") == {"mb_site_id": 25441}


def test_parse_ref_accepts_inline_object() -> None:
    assert parse_ref({"mb_site_id": 1}, field="x") == {"mb_site_id": 1}


def test_parse_ref_rejects_malformed_json() -> None:
    with pytest.raises(CliError) as exc:
        parse_ref("{not json", field="bookingRefJson")
    assert exc.value.code == "invalid_ref_json"


def test_location_ref_round_trip() -> None:
    raw = json.dumps(
        {
            "inventory_source": "MB",
            "mb_master_location_id": 1424962,
            "mb_location_id": 1,
            "mb_site_id": 25441,
        }
    )
    ref = LocationRef.from_raw(raw)
    assert ref.site_id == 25441
    assert ref.master_location_id == 1424962
    assert json.loads(ref.to_json()) == json.loads(raw)


def test_booking_ref_detects_waitlist_entry() -> None:
    # A waitlist entry carries a sentinel visit id and a real waitlist id.
    raw = json.dumps(
        {
            "mb_site_id": 25441,
            "mb_site_visit_id": -1,
            "inventory_source": "MB",
            "mb_program_type": "Class",
            "mb_waitlist_id": 78637,
        }
    )
    ref = BookingRef.from_raw(raw)
    assert ref.is_waitlist is True
    assert ref.waitlist_id == 78637
    assert ref.site_visit_id is None


def test_booking_ref_detects_confirmed_booking() -> None:
    raw = json.dumps(
        {
            "mb_site_id": 25441,
            "mb_site_visit_id": 806714,
            "mb_waitlist_id": None,
        }
    )
    ref = BookingRef.from_raw(raw)
    assert ref.is_waitlist is False
    assert ref.site_visit_id == 806714


def test_inventory_ref_omits_absent_optional_keys() -> None:
    ref = InventoryRef(site_id=25441, class_id=48089)
    payload = json.loads(ref.to_json())
    assert "mb_master_location_id" not in payload
    assert payload["mb_class_id"] == 48089
