"""End-to-end checks of the machine-facing contract.

These run the real entry point in a subprocess because the exit-code mapping
lives in ``main.run()``, which an in-process runner would bypass.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

CASES = [
    (["auth", "env"], 0, None),
    (["bookings", "list"], 2, "login_required"),
    (["waitlist", "list"], 2, "login_required"),
    (["schedule"], 2, "login_required"),
    (["--format", "xml", "auth", "env"], 1, "usage_error"),
    (["nosuchcommand"], 1, "usage_error"),
    (["bookings", "create"], 1, "usage_error"),
]


def _run(args: list[str], tmp_path) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "MINDBODY_CLI_TOKEN_PATH": str(tmp_path / "tokens.json"),
        "MINDBODY_CLI_TOKEN_BACKEND": "file",
    }
    return subprocess.run(
        [sys.executable, "-m", "mindbody_cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.parametrize("args,expected_code,expected_error", CASES)
def test_exit_code_contract(args, expected_code, expected_error, tmp_path) -> None:
    result = _run(args, tmp_path)
    assert result.returncode == expected_code, result.stderr

    if expected_error is None:
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
    else:
        payload = json.loads(result.stderr)
        assert payload["code"] == expected_error
        assert set(payload) == {"error", "code", "details"}


def test_success_output_is_parseable_json(tmp_path) -> None:
    result = _run(["auth", "status"], tmp_path)
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["authenticated"] is False
