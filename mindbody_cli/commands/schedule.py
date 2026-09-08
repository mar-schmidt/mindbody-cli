"""Schedule discovery: find bookable class ids."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

import typer

from mindbody_cli.cli_common import run_json, usage_error
from mindbody_cli.client import gateway
from mindbody_cli.commands.bookings import resolve_location
from mindbody_cli.models import normalize_class_time
from mindbody_cli.runtime import get_runtime

app = typer.Typer(help="Schedule commands.")


def _parse_date(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise usage_error(
            "Invalid date",
            "invalid_date",
            {"value": value, "expectedFormat": "YYYY-MM-DD"},
        ) from exc
    return parsed.replace(tzinfo=UTC)


@app.callback(invoke_without_command=True)
def schedule(
    ctx: typer.Context,
    date: str | None = typer.Option(
        None,
        "--date",
        help="Single day to list, as YYYY-MM-DD. Defaults to today.",
    ),
    days: int = typer.Option(
        1,
        "--days",
        help="Number of days to include, starting at --date.",
    ),
    bookable_only: bool = typer.Option(
        False,
        "--bookable-only",
        help="Drop cancelled classes and classes with no spots left.",
    ),
) -> None:
    """List classes at your studio, with the classId needed to book."""
    if ctx.invoked_subcommand is not None:
        return

    def action() -> dict[str, Any]:
        runtime = get_runtime(ctx)
        client = runtime.client
        location = resolve_location(client.state)

        if date:
            start = _parse_date(date)
        else:
            start = datetime.now(UTC)

        window_start = start
        window_end = datetime.combine(
            (start + timedelta(days=max(1, days) - 1)).date(),
            time(23, 59, 59),
            tzinfo=UTC,
        )

        raw = gateway.list_schedules(
            client,
            location,
            start_from=window_start,
            start_to=window_end,
        )
        classes = [normalize_class_time(entry) for entry in raw]

        if bookable_only:
            classes = [
                c
                for c in classes
                if not c.get("isCancelled")
                and (c.get("spotsOpen") is None or c["spotsOpen"] > 0)
            ]

        classes.sort(key=lambda c: c.get("startTime") or "")

        return {
            "ok": True,
            "count": len(classes),
            "from": gateway.iso_utc(window_start),
            "to": gateway.iso_utc(window_end),
            "location": {
                "siteId": location.site_id,
                "locationId": location.location_id,
                "masterLocationId": location.master_location_id,
            },
            "classes": classes,
        }

    run_json(action, ctx)
