"""JSON output helpers."""

from __future__ import annotations

import json
import sys
from typing import Any


def _json_dump(value: dict[str, Any], stderr: bool = False) -> None:
    stream = sys.stderr if stderr else sys.stdout
    stream.write(json.dumps(value, ensure_ascii=False))
    stream.write("\n")
    stream.flush()


def print_success(data: dict[str, Any]) -> None:
    """Print a successful command result as JSON."""
    _json_dump(data, stderr=False)


def print_success_formatted(data: dict[str, Any], output_format: str) -> None:
    """Print success payload in requested output format."""
    if output_format == "text":
        sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
        sys.stdout.flush()
        return
    print_success(data)


def print_error(error: str, code: str, details: dict[str, Any]) -> None:
    """Print a failure payload with stable keys."""
    _json_dump(
        {"error": error, "code": code, "details": details},
        stderr=True,
    )
