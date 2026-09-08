from __future__ import annotations

import json
import os
import time

from mindbody_cli.client.tokens import TokenState, TokenStore
from mindbody_cli.config import AppPaths


def _paths(tmp_path) -> AppPaths:
    token = tmp_path / "tokens.json"
    return AppPaths(token_path=token, lock_path=token.with_suffix(".lock"))


def test_save_is_atomic_and_private(tmp_path) -> None:
    store = TokenStore(_paths(tmp_path), backend="file")
    store.save(TokenState(access_token="a", refresh_token="r"))

    path = _paths(tmp_path).token_path
    assert path.exists()
    # 0o600: readable only by the owner.
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    # No temp files left behind by the rename.
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith(".tokens-")] == []
    assert json.loads(path.read_text())["refresh_token"] == "r"


def test_rotation_retains_previous_token(tmp_path) -> None:
    from mindbody_cli.client.oauth import _apply_token_response

    state = TokenState(refresh_token="old")
    _apply_token_response(
        state,
        {"access_token": "new-access", "refresh_token": "new", "expires_in": 43200},
    )
    assert state.refresh_token == "new"
    assert state.previous_refresh_token == "old"


def test_needs_refresh_respects_margin() -> None:
    fresh = TokenState(access_token="a", expires_at=time.time() + 3600)
    assert fresh.needs_refresh() is False

    # Inside the margin the token is treated as already stale.
    near = TokenState(access_token="a", expires_at=time.time() + 60)
    assert near.needs_refresh(margin=300) is True

    assert TokenState().needs_refresh() is True


def test_redacted_never_leaks_secrets() -> None:
    state = TokenState(
        access_token="secret-access",
        refresh_token="secret-refresh",
        id_token="secret-id",
        expires_at=time.time() + 100,
    )
    blob = json.dumps(state.redacted())
    assert "secret-access" not in blob
    assert "secret-refresh" not in blob
    assert "secret-id" not in blob


def test_load_round_trip(tmp_path) -> None:
    store = TokenStore(_paths(tmp_path), backend="file")
    store.save(TokenState(refresh_token="r", user_id=27208803, site_id=25441))
    loaded = store.load()
    assert loaded.refresh_token == "r"
    assert loaded.user_id == 27208803
    assert loaded.site_id == 25441
    assert loaded.is_authenticated is True


def test_clear_removes_state(tmp_path) -> None:
    store = TokenStore(_paths(tmp_path), backend="file")
    store.save(TokenState(refresh_token="r"))
    store.clear()
    assert store.load().is_authenticated is False


def test_refresh_lock_is_exclusive(tmp_path) -> None:
    import pytest

    from mindbody_cli.errors import CliError

    store = TokenStore(_paths(tmp_path), backend="file")
    with store.refresh_lock():
        other = TokenStore(_paths(tmp_path), backend="file")
        with pytest.raises(CliError) as exc:
            with other.refresh_lock(timeout_seconds=0.3):
                pass
    assert exc.value.code == "token_lock_timeout"
