from __future__ import annotations

from pathlib import Path

import pytest

from mindbody_cli.commands.auth import _extract_client_from_capture
from mindbody_cli.errors import CliError

FIXTURE = Path(__file__).parent / "fixtures" / "capture_sample.jsonl"


def test_extracts_client_registration_from_capture() -> None:
    found = _extract_client_from_capture(FIXTURE)
    assert found["client_id"] == "Example.App.iOS"
    assert found["client_secret"] == "test-secret-value"
    assert found["redirect_uri"] == "x-example-oauth://authcode"


def test_missing_capture_is_a_usage_error(tmp_path) -> None:
    with pytest.raises(CliError) as exc:
        _extract_client_from_capture(tmp_path / "nope.jsonl")
    assert exc.value.code == "capture_not_found"
    assert exc.value.exit_code == 1


def test_capture_without_token_exchange_is_rejected(tmp_path) -> None:
    empty = tmp_path / "flows.jsonl"
    empty.write_text('{"method":"GET","path":"/health","req_headers":{}}\n')
    with pytest.raises(CliError) as exc:
        _extract_client_from_capture(empty)
    assert exc.value.code == "capture_missing_client"
