"""Typed wrappers for the upstream ``*RefJson`` fields.

The API encodes composite identifiers as a JSON *string* nested inside a JSON
document::

    "bookingRefJson": "{\\"mb_site_id\\":25441,\\"mb_site_visit_id\\":806714}"

Three variants exist (location, inventory, booking) and they are both read
from responses and echoed back in request bodies. Key order varies between
endpoints, and sentinel values differ by context -- a waitlist entry carries
``mb_site_visit_id: -1`` and a real ``mb_waitlist_id``, while a confirmed
booking carries the reverse.

Parsing these ad hoc at each call site is the single most likely source of
bugs in a client, so all of it is funnelled through this module.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from mindbody_cli import exit_codes
from mindbody_cli.errors import CliError

INVENTORY_SOURCE_MB = "MB"


def parse_ref(raw: Any, *, field: str) -> dict[str, Any]:
    """Decode a ``*RefJson`` string into a dict.

    Accepts an already-decoded dict as well, because a few endpoints return
    the object inline rather than as an encoded string.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise CliError(
            error="Unexpected reference field type",
            code="invalid_ref_type",
            exit_code=exit_codes.UPSTREAM,
            details={"field": field, "type": type(raw).__name__},
        )
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise CliError(
            error="Failed to decode reference field",
            code="invalid_ref_json",
            exit_code=exit_codes.UPSTREAM,
            details={"field": field, "reason": str(exc)},
        ) from exc
    if not isinstance(value, dict):
        raise CliError(
            error="Reference field did not decode to an object",
            code="invalid_ref_shape",
            exit_code=exit_codes.UPSTREAM,
            details={"field": field, "type": type(value).__name__},
        )
    return value


def serialize_ref(value: dict[str, Any]) -> str:
    """Encode a reference dict back into the compact string form."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


@dataclass(slots=True)
class LocationRef:
    """Identifies a studio location."""

    site_id: int
    location_id: int
    master_location_id: int
    inventory_source: str = INVENTORY_SOURCE_MB

    @classmethod
    def from_raw(cls, raw: Any, *, field: str = "locationRefJson") -> "LocationRef":
        data = parse_ref(raw, field=field)
        return cls(
            site_id=int(data.get("mb_site_id", 0)),
            location_id=int(data.get("mb_location_id", 0)),
            master_location_id=int(data.get("mb_master_location_id", 0)),
            inventory_source=data.get("inventory_source") or INVENTORY_SOURCE_MB,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "inventory_source": self.inventory_source,
            "mb_master_location_id": self.master_location_id,
            "mb_location_id": self.location_id,
            "mb_site_id": self.site_id,
        }

    def to_json(self) -> str:
        return serialize_ref(self.to_dict())


@dataclass(slots=True)
class InventoryRef:
    """Identifies a bookable class occurrence."""

    site_id: int
    class_id: int
    location_id: int | None = None
    master_location_id: int | None = None
    class_description_id: int | None = None
    class_schedule_id: int | None = None
    inventory_source: str = INVENTORY_SOURCE_MB
    inventory_category: str = "class_time"

    @classmethod
    def from_raw(cls, raw: Any, *, field: str = "inventoryRefJson") -> "InventoryRef":
        data = parse_ref(raw, field=field)
        return cls(
            site_id=int(data.get("mb_site_id", 0)),
            class_id=int(data.get("mb_class_id", 0)),
            location_id=data.get("mb_location_id"),
            master_location_id=data.get("mb_master_location_id"),
            class_description_id=data.get("mb_class_description_id"),
            class_schedule_id=data.get("mb_class_schedule_id"),
            inventory_source=data.get("inventory_source") or INVENTORY_SOURCE_MB,
            inventory_category=data.get("inventory_category") or "class_time",
        )

    def to_dict(self) -> dict[str, Any]:
        # Only emit keys the upstream actually sends; a null master location
        # id is rejected where an absent one is accepted.
        value: dict[str, Any] = {
            "inventory_source": self.inventory_source,
            "inventory_category": self.inventory_category,
            "mb_class_id": self.class_id,
            "mb_site_id": self.site_id,
        }
        if self.class_description_id is not None:
            value["mb_class_description_id"] = self.class_description_id
        if self.master_location_id is not None:
            value["mb_master_location_id"] = self.master_location_id
        if self.location_id is not None:
            value["mb_location_id"] = self.location_id
        return value

    def to_json(self) -> str:
        return serialize_ref(self.to_dict())


@dataclass(slots=True)
class BookingRef:
    """Identifies an existing booking or waitlist entry.

    ``site_visit_id`` is ``-1`` for waitlist entries; ``waitlist_id`` is
    ``None`` for confirmed bookings. Exactly one of them is meaningful, and
    which one determines how the entry must be cancelled.
    """

    site_id: int
    site_visit_id: int | None = None
    waitlist_id: int | None = None
    program_type: str = "Class"
    inventory_source: str = INVENTORY_SOURCE_MB

    @classmethod
    def from_raw(cls, raw: Any, *, field: str = "bookingRefJson") -> "BookingRef":
        data = parse_ref(raw, field=field)
        visit_id = data.get("mb_site_visit_id")
        return cls(
            site_id=int(data.get("mb_site_id", 0)),
            site_visit_id=None if visit_id in (None, -1) else int(visit_id),
            waitlist_id=data.get("mb_waitlist_id"),
            program_type=data.get("mb_program_type") or "Class",
            inventory_source=data.get("inventory_source") or INVENTORY_SOURCE_MB,
        )

    @property
    def is_waitlist(self) -> bool:
        """True when this entry is a waitlist position, not a booking."""
        return self.waitlist_id is not None and self.site_visit_id is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mb_program_type": self.program_type,
            "mb_site_id": self.site_id,
            "inventory_source": self.inventory_source,
            "mb_site_visit_id": (
                self.site_visit_id if self.site_visit_id is not None else -1
            ),
        }

    def to_json(self) -> str:
        return serialize_ref(self.to_dict())
