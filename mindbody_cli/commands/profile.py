"""Profile and membership commands."""

from __future__ import annotations

from typing import Any

import typer

from mindbody_cli.cli_common import run_json
from mindbody_cli.client import gateway, identity
from mindbody_cli.models import (
    normalize_pass,
    normalize_profile,
    summarize_activity_profile,
)
from mindbody_cli.runtime import get_runtime

app = typer.Typer(help="Profile commands.")


@app.callback(invoke_without_command=True)
def profile(
    ctx: typer.Context,
    raw: bool = typer.Option(False, "--raw", help="Return the upstream payload."),
) -> None:
    """Show the account profile."""
    if ctx.invoked_subcommand is not None:
        return

    def action() -> dict[str, Any]:
        runtime = get_runtime(ctx)
        data = identity.get_me(runtime.client)
        return {
            "ok": True,
            "profile": data if raw else normalize_profile(data),
        }

    run_json(action, ctx)


passes_app = typer.Typer(help="Membership commands.")


@passes_app.callback(invoke_without_command=True)
def passes(
    ctx: typer.Context,
    status: str = typer.Option(
        "both",
        "--status",
        help="active, inactive, or both.",
    ),
) -> None:
    """List membership passes with remaining sessions and expiry."""
    if ctx.invoked_subcommand is not None:
        return

    def action() -> dict[str, Any]:
        runtime = get_runtime(ctx)
        entries = [
            normalize_pass(item)
            for item in gateway.list_passes(runtime.client, status=status)
        ]
        return {"ok": True, "count": len(entries), "passes": entries}

    run_json(action, ctx)


status_app = typer.Typer(help="Account summary.")


@status_app.callback(invoke_without_command=True)
def account_status(ctx: typer.Context) -> None:
    """Booking counts, studios, and pass state in a single call."""
    if ctx.invoked_subcommand is not None:
        return

    def action() -> dict[str, Any]:
        runtime = get_runtime(ctx)
        summary = summarize_activity_profile(
            gateway.get_activity_profile(runtime.client)
        )
        return {"ok": True, "summary": summary}

    run_json(action, ctx)
