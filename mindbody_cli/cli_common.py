"""Shared command execution helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import typer

from mindbody_cli import exit_codes
from mindbody_cli.errors import CliError
from mindbody_cli.output import print_error, print_success_formatted
from mindbody_cli.runtime import Runtime


def run_json(
    callable_fn: Callable[[], dict[str, Any]],
    ctx: typer.Context | None = None,
) -> None:
    """Run a command and print stable JSON success/error payloads.

    The context is passed in explicitly rather than discovered from a global.
    Typer vendors its own copy of click, so the ambient ``click`` package's
    context stack is always empty here and silently yields the wrong output
    format.
    """
    output_format = "json"
    if ctx is not None and isinstance(ctx.obj, Runtime):
        output_format = ctx.obj.output_format

    try:
        payload = callable_fn()
        print_success_formatted(payload, output_format)
    except CliError as exc:
        print_error(exc.error, exc.code, exc.details)
        raise typer.Exit(code=exc.exit_code) from exc
    except typer.Exit:
        raise
    except Exception as exc:
        print_error(
            "Unexpected internal error",
            "internal_error",
            {"reason": str(exc), "type": type(exc).__name__},
        )
        raise typer.Exit(code=exit_codes.UPSTREAM) from exc


def usage_error(message: str, code: str, details: dict[str, Any]) -> CliError:
    """Build a validation error with the usage exit code."""
    return CliError(
        error=message,
        code=code,
        exit_code=exit_codes.USAGE,
        details=details,
    )
