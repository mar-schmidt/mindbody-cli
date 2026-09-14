"""Regression tests for the upcoming-bookings query.

The endpoint returns a single capped page, so the sort order decides which
slice of an account's history comes back. Asking ascending returns the oldest
page; for an account with more than a page of past bookings that page holds
nothing in the future and every upcoming booking silently disappears. This was
observed live on a real account with history back to 2022: `status` reported
one upcoming class and `bookings list` reported none.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import respx

from mindbody_cli.client import gateway
from mindbody_cli.client.http import MindbodyHttpClient
from mindbody_cli.client.tokens import TokenState, TokenStore
from mindbody_cli.config import AppPaths


def _client(tmp_path) -> MindbodyHttpClient:
    paths = AppPaths(
        token_path=tmp_path / "tokens.json",
        lock_path=tmp_path / "tokens.lock",
    )
    store = TokenStore(paths)
    store.save(
        TokenState(
            access_token="access",
            refresh_token="refresh",
            expires_at=(datetime.now(UTC) + timedelta(hours=1)).timestamp(),
        )
    )
    return MindbodyHttpClient(store)


def _entry(start: datetime) -> dict:
    stamp = start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": stamp,
        "attributes": {
            "startTime": stamp,
            "endTime": stamp,
            "name": "Group Class",
            "bookingRefJson": '{"mb_site_id":1,"mb_site_visit_id":1,"mb_waitlist_id":null}',
        },
    }


@respx.mock
def test_upcoming_query_is_descending(tmp_path) -> None:
    """The page must be the newest slice, or future bookings fall off it."""
    captured: dict[str, str] = {}

    def _respond(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(200, json={"data": []})

    respx.get(gateway.BOOKINGS_URL).mock(side_effect=_respond)

    gateway.list_upcoming_bookings(_client(tmp_path))

    assert captured["filter.ascending"] == "false", (
        "an ascending query returns the OLDEST capped page, which for an "
        "account with a long history contains no future bookings at all"
    )


@respx.mock
def test_upcoming_survives_a_page_full_of_history(tmp_path) -> None:
    """The real-account shape: one future booking behind a page of past ones."""
    now = datetime.now(UTC)
    future = now + timedelta(days=2)
    # Descending order, as the endpoint returns it: newest first.
    page = [_entry(future)] + [
        _entry(now - timedelta(days=n)) for n in range(1, 100)
    ]
    respx.get(gateway.BOOKINGS_URL).mock(
        return_value=httpx.Response(200, json={"data": page})
    )

    upcoming = gateway.list_upcoming_bookings(_client(tmp_path))

    assert len(upcoming) == 1
    assert upcoming[0]["attributes"]["startTime"].startswith(
        future.strftime("%Y-%m-%d")
    )


@respx.mock
def test_past_bookings_are_still_filtered_out(tmp_path) -> None:
    """Descending must not turn the query into 'return everything'."""
    now = datetime.now(UTC)
    page = [_entry(now - timedelta(days=n)) for n in range(1, 30)]
    respx.get(gateway.BOOKINGS_URL).mock(
        return_value=httpx.Response(200, json={"data": page})
    )

    assert gateway.list_upcoming_bookings(_client(tmp_path)) == []
