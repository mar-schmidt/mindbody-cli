from __future__ import annotations

import json

from mindbody_cli.output import print_error, print_success_formatted


def test_error_contract_has_stable_keys(capsys) -> None:
    print_error(
        "Authentication required",
        "auth_required",
        {"url": "https://example.invalid"},
    )
    payload = json.loads(capsys.readouterr().err)
    assert set(payload) == {"error", "code", "details"}
    assert payload["code"] == "auth_required"


def test_success_json_is_single_line(capsys) -> None:
    print_success_formatted({"ok": True, "count": 2}, "json")
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    assert json.loads(out)["ok"] is True


def test_text_format_is_indented(capsys) -> None:
    print_success_formatted({"ok": True}, "text")
    out = capsys.readouterr().out
    assert "\n  " in out
    assert json.loads(out)["ok"] is True
