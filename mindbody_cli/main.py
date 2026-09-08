"""CLI entrypoint."""

from __future__ import annotations

import typer

from mindbody_cli.client.tokens import TokenStore
from mindbody_cli.commands.auth import app as auth_app
from mindbody_cli.commands.bookings import app as bookings_app
from mindbody_cli.commands.profile import (
    app as profile_app,
    passes_app,
    status_app,
)
from mindbody_cli.commands.schedule import app as schedule_app
from mindbody_cli.commands.waitlist import app as waitlist_app
from mindbody_cli.config import get_app_paths
from mindbody_cli.runtime import Runtime

app = typer.Typer(
    help=(
        "JSON-first CLI for the Mindbody consumer APIs. "
        "Unofficial and not affiliated with Mindbody, Inc."
    ),
    no_args_is_help=True,
)
app.pretty_exceptions_enable = False

app.add_typer(auth_app, name="auth")
app.add_typer(bookings_app, name="bookings")
app.add_typer(waitlist_app, name="waitlist")
app.add_typer(schedule_app, name="schedule")
app.add_typer(profile_app, name="profile")
app.add_typer(passes_app, name="passes")
app.add_typer(status_app, name="status")


@app.callback()
def main(
    ctx: typer.Context,
    output_format: str = typer.Option(
        "json",
        "--format",
        help="Output format: json (default) or text.",
    ),
) -> None:
    """Initialize runtime objects for each command invocation."""
    if output_format not in {"json", "text"}:
        raise typer.BadParameter("format must be one of: json, text")
    paths = get_app_paths()
    ctx.obj = Runtime(
        paths=paths,
        store=TokenStore(paths),
        output_format=output_format,
    )


def run() -> None:
    """Entry point that keeps the exit-code contract stable.

    Typer vendors its own copy of click and reports parameter validation with
    click's exit code 2, which is this CLI's authentication code. Machine
    consumers branch on those codes, so usage failures are re-emitted through
    the standard error contract with the usage exit code instead.

    Note that ``typer.Exit`` is a plain RuntimeError subclass here, unrelated
    to the vendored click exception tree, so the two are caught separately.
    """
    import typer.exceptions as texc

    from mindbody_cli import exit_codes
    from mindbody_cli.output import print_error

    try:
        # In non-standalone mode Typer *returns* the exit code from a
        # ``typer.Exit`` raised inside a command rather than propagating it
        # (typer/core.py). Dropping that return value silently turns every
        # failed command into a success.
        result = app(standalone_mode=False)
        if isinstance(result, int) and result != 0:
            raise SystemExit(result)
    except texc.Exit as exc:
        raise SystemExit(getattr(exc, "exit_code", 0)) from exc
    except texc.Abort:
        print_error("Aborted by user", "aborted", {})
        raise SystemExit(exit_codes.USAGE) from None
    except texc.TyperException as exc:
        # Help output and "no args" both surface as exceptions in
        # non-standalone mode; neither is a failure.
        name = type(exc).__name__
        if name in {"NoArgsIsHelpError", "PrintHelp"}:
            raise SystemExit(exit_codes.SUCCESS) from None
        print_error(str(exc), "usage_error", {"type": name})
        raise SystemExit(exit_codes.USAGE) from exc


if __name__ == "__main__":
    run()
