"""Runtime context shared by commands."""

from __future__ import annotations

from dataclasses import dataclass, field

import typer

from mindbody_cli.client.http import MindbodyHttpClient
from mindbody_cli.client.tokens import TokenStore
from mindbody_cli.config import AppPaths


@dataclass(slots=True)
class Runtime:
    """Objects used by command handlers.

    The HTTP client is created lazily: commands like ``auth bootstrap`` and
    ``--help`` must work before any credentials exist.
    """

    paths: AppPaths
    store: TokenStore
    output_format: str = "json"
    _client: MindbodyHttpClient | None = field(default=None, repr=False)

    @property
    def client(self) -> MindbodyHttpClient:
        if self._client is None:
            self._client = MindbodyHttpClient(self.store)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def get_runtime(ctx: typer.Context) -> Runtime:
    value = ctx.obj
    if not isinstance(value, Runtime):
        raise RuntimeError("Runtime is not initialized")
    return value
