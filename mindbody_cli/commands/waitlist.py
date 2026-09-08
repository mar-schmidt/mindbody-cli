"""Waitlist commands: list, join, leave."""

from __future__ import annotations

from typing import Any

import typer

from mindbody_cli.cli_common import run_json, usage_error
from mindbody_cli.client import connect, gateway
from mindbody_cli.commands.bookings import find_class, resolve_location
from mindbody_cli.models import normalize_booking
from mindbody_cli.runtime import get_runtime

app = typer.Typer(help="Waitlist commands.", no_args_is_help=True)


@app.command("list")
def list_waitlist(
    ctx: typer.Context,
    with_position: bool = typer.Option(
        False,
        "--with-position",
        help="Also fetch queue position (one extra request per entry).",
    ),
) -> None:
    """List waitlist positions.

    Queue position is not part of the bookings payload, so ``--with-position``
    costs one additional class lookup per entry.
    """

    def action() -> dict[str, Any]:
        runtime = get_runtime(ctx)
        client = runtime.client
        raw = gateway.list_upcoming_bookings(client)
        entries = [
            entry
            for entry in (normalize_booking(item) for item in raw)
            if entry["kind"] == "waitlist"
        ]

        if with_position:
            for entry in entries:
                class_id = entry.get("classId")
                if not class_id:
                    continue
                try:
                    detail = connect.get_class(client, int(class_id))
                except Exception:
                    continue
                entry["waitlistPosition"] = detail.get("WaitlistPosition")
                if entry.get("waitlistId") is None:
                    entry["waitlistId"] = detail.get("WaitlistID")

        return {"ok": True, "count": len(entries), "waitlist": entries}

    run_json(action, ctx)


@app.command("join")
def join(
    ctx: typer.Context,
    class_id: int = typer.Option(..., "--class", help="classId from `schedule`."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Join the waitlist for a full class."""

    def action() -> dict[str, Any]:
        runtime = get_runtime(ctx)
        client = runtime.client
        location = resolve_location(client.state)
        target = find_class(client, location, class_id)

        if dry_run:
            return {"ok": True, "dryRun": True, "wouldJoin": target}

        connect.join_waitlist(client, class_id)
        gateway.clear_cache(client)

        # The join responds 201 with an empty body, so the assigned waitlist
        # id has to be read back before it can ever be used to leave.
        waitlist_id = None
        try:
            for item in gateway.list_upcoming_bookings(client):
                entry = normalize_booking(item)
                if entry["kind"] == "waitlist" and entry.get("classId") == class_id:
                    waitlist_id = entry.get("waitlistId")
                    break
        except Exception:
            waitlist_id = None

        return {
            "ok": True,
            "joined": True,
            "classId": class_id,
            "waitlistId": waitlist_id,
            "class": target,
            "note": (
                None
                if waitlist_id
                else "Waitlist id not yet visible; re-run `waitlist list`."
            ),
        }

    run_json(action, ctx)


@app.command("leave")
def leave(
    ctx: typer.Context,
    waitlist_id: int | None = typer.Option(
        None,
        "--waitlist-id",
        help="waitlistId from `waitlist list`.",
    ),
    class_id: int | None = typer.Option(
        None,
        "--class",
        help="Resolve the waitlist id from a class id instead.",
    ),
) -> None:
    """Leave a waitlist."""

    def action() -> dict[str, Any]:
        runtime = get_runtime(ctx)
        client = runtime.client

        resolved = waitlist_id
        if resolved is None:
            if class_id is None:
                raise usage_error(
                    "Provide either --waitlist-id or --class",
                    "missing_waitlist_identifier",
                    {"hint": "Run `mindbody waitlist list` to see both."},
                )
            for item in gateway.list_upcoming_bookings(client):
                entry = normalize_booking(item)
                if entry["kind"] == "waitlist" and entry.get("classId") == class_id:
                    resolved = entry.get("waitlistId")
                    break
            if resolved is None:
                raise usage_error(
                    "No waitlist entry found for that class",
                    "waitlist_entry_not_found",
                    {"classId": class_id},
                )

        connect.leave_waitlist(client, int(resolved))
        gateway.clear_cache(client)
        return {"ok": True, "left": True, "waitlistId": int(resolved)}

    run_json(action, ctx)
