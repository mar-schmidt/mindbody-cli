"""Booking commands: list, create, cancel."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import typer

from mindbody_cli.cli_common import run_json, usage_error
from mindbody_cli.client import connect, gateway
from mindbody_cli.client.http import MindbodyHttpClient
from mindbody_cli.client.tokens import TokenState
from mindbody_cli.config import (
    get_default_location_id,
    get_default_master_location_id,
    get_default_site_id,
)
from mindbody_cli.models import normalize_booking, normalize_class_time
from mindbody_cli.refs import InventoryRef, LocationRef
from mindbody_cli.runtime import get_runtime

app = typer.Typer(help="Booking commands.", no_args_is_help=True)

# Cancellability status code 1 is the only observed "free of charge" outcome.
# Anything else may carry a fee or be refused, so it requires --force.
CANCELLABLE_WITHOUT_PENALTY = 1


def resolve_location(state: TokenState) -> LocationRef:
    """Resolve the studio to operate on, from flags/env or stored state."""
    site_id = get_default_site_id() or state.site_id
    location_id = get_default_location_id() or state.location_id
    master_location_id = get_default_master_location_id() or state.master_location_id

    if not site_id or not master_location_id:
        raise usage_error(
            "No studio location resolved",
            "missing_location",
            {
                "hint": (
                    "Run `mindbody auth status --refresh` to resolve your "
                    "studio automatically, or set MINDBODY_SITE_ID, "
                    "MINDBODY_LOCATION_ID and MINDBODY_MASTER_LOCATION_ID."
                ),
                "siteId": site_id,
                "locationId": location_id,
                "masterLocationId": master_location_id,
            },
        )

    return LocationRef(
        site_id=int(site_id),
        location_id=int(location_id or 1),
        master_location_id=int(master_location_id),
    )


def find_class(
    client: MindbodyHttpClient,
    location: LocationRef,
    class_id: int,
    *,
    horizon_days: int = 30,
) -> dict[str, Any]:
    """Locate a class in the upcoming schedule by its class id.

    Booking needs the full inventory reference, not just the class id, and
    the schedule is the only place that hands it out.
    """
    now = datetime.now(UTC)
    entries = gateway.list_schedules(
        client,
        location,
        start_from=now,
        start_to=now + timedelta(days=horizon_days),
    )
    for entry in entries:
        normalized = normalize_class_time(entry)
        if normalized.get("classId") == class_id:
            return normalized

    raise usage_error(
        "Class not found in the upcoming schedule",
        "class_not_found",
        {
            "classId": class_id,
            "horizonDays": horizon_days,
            "hint": "Run `mindbody schedule` to list bookable class ids.",
        },
    )


def select_pass(
    client: MindbodyHttpClient,
    explicit_pass_id: str | None,
) -> str:
    """Choose which membership pass pays for a booking.

    There is no upstream notion of a default pass, so absent an explicit
    choice we take the first active pass with sessions left.
    """
    if explicit_pass_id:
        return explicit_pass_id

    from mindbody_cli.models import normalize_pass

    passes = [normalize_pass(p) for p in gateway.list_passes(client, status="active")]
    usable = [
        p
        for p in passes
        if p.get("active")
        and (p.get("isUnlimited") or (p.get("sessionsRemaining") or 0) > 0)
    ]
    if not usable:
        raise usage_error(
            "No usable membership pass found",
            "no_usable_pass",
            {
                "hint": (
                    "Run `mindbody passes` to inspect your memberships, then "
                    "pass --pass <id> explicitly."
                ),
                "passCount": len(passes),
            },
        )
    return str(usable[0]["id"])


@app.command("list")
def list_bookings(
    ctx: typer.Context,
    upcoming: bool = typer.Option(
        True,
        "--upcoming/--all",
        help="Only future entries (default) or the full history.",
    ),
    include_waitlist: bool = typer.Option(
        True,
        "--include-waitlist/--no-waitlist",
        help="Include waitlist positions alongside confirmed bookings.",
    ),
    page_size: int = typer.Option(30, "--page-size"),
) -> None:
    """List bookings and waitlist positions."""

    def action() -> dict[str, Any]:
        runtime = get_runtime(ctx)
        client = runtime.client

        if upcoming:
            raw = gateway.list_upcoming_bookings(client, page_size=page_size)
        else:
            raw = gateway.list_bookings(
                client,
                page_size=page_size,
                before=datetime.now(UTC) + timedelta(days=400),
            )

        entries = [normalize_booking(item) for item in raw]
        if not include_waitlist:
            entries = [e for e in entries if e["kind"] == "booking"]

        return {
            "ok": True,
            "count": len(entries),
            "bookings": [e for e in entries if e["kind"] == "booking"],
            "waitlist": [e for e in entries if e["kind"] == "waitlist"],
        }

    run_json(action, ctx)


@app.command("create")
def create_booking(
    ctx: typer.Context,
    class_id: int = typer.Option(..., "--class", help="classId from `schedule`."),
    pass_id: str | None = typer.Option(
        None,
        "--pass",
        help="Membership pass id. Defaults to the first usable active pass.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Resolve everything and report what would be booked.",
    ),
) -> None:
    """Book a class using a membership pass."""

    def action() -> dict[str, Any]:
        runtime = get_runtime(ctx)
        client = runtime.client
        location = resolve_location(client.state)
        target = find_class(client, location, class_id)

        inventory = InventoryRef.from_raw(target.get("inventoryRefJson"))
        if not inventory.class_id:
            inventory = InventoryRef(
                site_id=location.site_id,
                class_id=class_id,
                location_id=location.location_id,
                master_location_id=location.master_location_id,
            )

        chosen_pass = select_pass(client, pass_id)

        if dry_run:
            return {
                "ok": True,
                "dryRun": True,
                "wouldBook": target,
                "passId": chosen_pass,
            }

        result = gateway.create_class_booking(
            client,
            inventory,
            payment_id=chosen_pass,
        )
        attributes = result.get("attributes") or {}

        # A 201 does not mean the booking succeeded: the gateway reports
        # business failures inside the body of a successful HTTP response.
        error_code = attributes.get("errorCode")
        if error_code:
            from mindbody_cli import exit_codes
            from mindbody_cli.errors import CliError

            raise CliError(
                error="Upstream refused the booking",
                code="booking_rejected",
                exit_code=exit_codes.UPSTREAM,
                details={
                    "classId": class_id,
                    "errorCode": error_code,
                    "errorMessage": attributes.get("errorMessage"),
                },
            )

        gateway.clear_cache(client)

        return {
            "ok": True,
            "booked": True,
            "bookingId": result.get("id"),
            "siteVisitId": result.get("id"),
            "classId": attributes.get("classId", class_id),
            "passId": chosen_pass,
            "class": target,
        }

    run_json(action, ctx)


@app.command("cancel")
def cancel_booking(
    ctx: typer.Context,
    visit_id: int = typer.Option(
        ...,
        "--visit-id",
        help="siteVisitId from `bookings list`.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Cancel even when upstream reports a penalty or refusal.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Only report cancellability.",
    ),
) -> None:
    """Cancel a confirmed booking."""

    def action() -> dict[str, Any]:
        runtime = get_runtime(ctx)
        client = runtime.client
        location = resolve_location(client.state)

        from mindbody_cli.refs import BookingRef

        ref = BookingRef(site_id=location.site_id, site_visit_id=visit_id)
        cancellability = gateway.check_cancellability(client, ref.to_json())
        status = cancellability.get("status") or {}
        code = status.get("code")

        if dry_run:
            return {
                "ok": True,
                "dryRun": True,
                "siteVisitId": visit_id,
                "cancellability": status,
            }

        if code != CANCELLABLE_WITHOUT_PENALTY and not force:
            from mindbody_cli import exit_codes
            from mindbody_cli.errors import CliError

            raise CliError(
                error="Cancellation would not be free of charge",
                code="cancellation_not_free",
                exit_code=exit_codes.USAGE,
                details={
                    "siteVisitId": visit_id,
                    "cancellability": status,
                    "hint": "Re-run with --force to cancel anyway.",
                },
            )

        connect.cancel_visit(client, visit_id)
        gateway.clear_cache(client)

        return {
            "ok": True,
            "cancelled": True,
            "siteVisitId": visit_id,
            "cancellability": status,
            "forced": bool(force and code != CANCELLABLE_WITHOUT_PENALTY),
        }

    run_json(action, ctx)
