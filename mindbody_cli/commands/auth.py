"""Authentication command group."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

import typer

from mindbody_cli import exit_codes
from mindbody_cli.cli_common import run_json, usage_error
from mindbody_cli.client import gateway, identity
from mindbody_cli.client.oauth import (
    ClientCredentials,
    build_authorize_url,
    clear_account_password,
    clear_client_credentials,
    exchange_code,
    extract_code,
    generate_pkce,
    headless_login,
    load_client_credentials,
    revoke_refresh_token,
    store_account_password,
    store_client_credentials,
)
from mindbody_cli.client.tokens import TokenState
from mindbody_cli.config import (
    CLIENT_ID_ENV,
    CLIENT_SECRET_ENV,
    PASSWORD_ENV,
    REDIRECT_URI_ENV,
    USERNAME_ENV,
)
from mindbody_cli.errors import CliError
from mindbody_cli.models import normalize_profile, summarize_activity_profile
from mindbody_cli.runtime import get_runtime

app = typer.Typer(help="Authentication commands.", no_args_is_help=True)


def _resolve_identifiers(runtime: Any, state: TokenState) -> TokenState:
    """Populate account identifiers the other services need in their paths."""
    client = runtime.client
    try:
        profile = identity.get_me(client)
        state.identity_id = profile.get("id") or state.identity_id
    except CliError:
        pass

    try:
        state.user_id = gateway.resolve_user_id(client) or state.user_id
    except CliError:
        pass

    try:
        activity = summarize_activity_profile(gateway.get_activity_profile(client))
        locations = activity.get("locations") or []
        if locations:
            first = locations[0]
            state.site_id = first.get("siteId") or state.site_id
            state.location_id = first.get("locationId") or state.location_id
            state.master_location_id = (
                first.get("masterLocationId") or state.master_location_id
            )
    except CliError:
        pass

    return state


@app.command("bootstrap")
def bootstrap(
    ctx: typer.Context,
    from_capture: Path | None = typer.Option(
        None,
        "--from-capture",
        help="Path to a flows.jsonl produced by your own traffic capture.",
    ),
    client_id: str | None = typer.Option(None, "--client-id"),
    client_secret: str | None = typer.Option(None, "--client-secret"),
    redirect_uri: str | None = typer.Option(None, "--redirect-uri"),
) -> None:
    """Store an OAuth client registration in the OS keychain.

    Optional: the CLI bundles a working public client by default. Use this only
    to override it -- supply --client-id/--client-secret/--redirect-uri, or
    import them from traffic you captured from your own account.
    """

    def action() -> dict[str, Any]:
        resolved_id = client_id
        resolved_secret = client_secret
        resolved_redirect = redirect_uri
        source = "flags"

        if from_capture is not None:
            source = str(from_capture)
            found = _extract_client_from_capture(from_capture)
            resolved_id = resolved_id or found.get("client_id")
            resolved_secret = resolved_secret or found.get("client_secret")
            resolved_redirect = resolved_redirect or found.get("redirect_uri")

        missing = [
            name
            for name, value in (
                ("client_id", resolved_id),
                ("client_secret", resolved_secret),
                ("redirect_uri", resolved_redirect),
            )
            if not value
        ]
        if missing:
            raise usage_error(
                "Incomplete OAuth client registration",
                "incomplete_client_registration",
                {
                    "missing": missing,
                    "hint": (
                        "Pass --from-capture with a capture that contains a "
                        "POST to /connect/token, or supply --client-id, "
                        "--client-secret and --redirect-uri explicitly."
                    ),
                },
            )

        creds = ClientCredentials(
            client_id=str(resolved_id),
            client_secret=str(resolved_secret),
            redirect_uri=str(resolved_redirect),
        )
        store_client_credentials(creds)
        return {
            "ok": True,
            "stored": True,
            "source": source,
            "clientId": creds.client_id,
            "redirectUri": creds.redirect_uri,
            "note": "Client secret stored in the OS keychain; not printed.",
        }

    run_json(action, ctx)


def _extract_client_from_capture(path: Path) -> dict[str, str]:
    """Recover client registration from a captured token exchange."""
    if not path.exists():
        raise usage_error(
            "Capture file not found",
            "capture_not_found",
            {"path": str(path)},
        )

    found: dict[str, str] = {}
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                request_path = str(entry.get("path", "")).split("?")[0]

                if request_path == "/connect/token":
                    headers = entry.get("req_headers") or {}
                    auth = next(
                        (
                            v
                            for k, v in headers.items()
                            if k.lower() == "authorization"
                        ),
                        "",
                    )
                    if auth.lower().startswith("basic "):
                        try:
                            decoded = base64.b64decode(auth.split(" ", 1)[1])
                            client_id, _, secret = decoded.decode().partition(":")
                            if client_id and secret:
                                found["client_id"] = client_id
                                found["client_secret"] = secret
                        except Exception:
                            pass
                    body = entry.get("req_body") or ""
                    params = urllib.parse.parse_qs(body)
                    if "redirect_uri" in params:
                        found["redirect_uri"] = params["redirect_uri"][0]

                if "redirect_uri" not in found and "/connect/authorize" in request_path:
                    query = str(entry.get("path", ""))
                    if "?" in query:
                        params = urllib.parse.parse_qs(query.split("?", 1)[1])
                        if "redirect_uri" in params:
                            found["redirect_uri"] = params["redirect_uri"][0]
    except OSError as exc:
        raise usage_error(
            "Failed to read capture file",
            "capture_read_failed",
            {"path": str(path), "reason": str(exc)},
        ) from exc

    if not found:
        raise usage_error(
            "No OAuth client registration found in capture",
            "capture_missing_client",
            {
                "path": str(path),
                "hint": "The capture must include a POST to /connect/token.",
            },
        )
    return found


def _headless_login(
    runtime: Any,
    creds: ClientCredentials,
    account: str | None,
    password: str | None,
    password_stdin: bool,
    save_credentials: bool = False,
) -> dict[str, Any]:
    """Sign in on a host with no browser available.

    Username resolves flag -> ``MINDBODY_USERNAME``; password resolves flag ->
    ``MINDBODY_PASSWORD`` -> stdin -> hidden prompt. Environment variables and
    stdin are safer than a ``--password`` flag, which is visible in the process
    list and shell history; the flag exists for parity and convenience, with
    that caveat documented.
    """
    resolved_user = account or os.environ.get(USERNAME_ENV)
    if not resolved_user:
        raise usage_error(
            "No username provided",
            "missing_username",
            {
                "hint": (
                    "Pass --username/-u, or set MINDBODY_USERNAME. Example: "
                    "mindbody auth login -u you@example.com"
                )
            },
        )

    secret = password or os.environ.get(PASSWORD_ENV)
    if not secret and password_stdin:
        secret = sys.stdin.readline().rstrip("\n")
    if not secret and not password_stdin and sys.stdin.isatty():
        secret = typer.prompt("Password", hide_input=True, err=True)
    if not secret:
        raise usage_error(
            "No password provided",
            "missing_password",
            {
                "hint": (
                    "Pass --password, set MINDBODY_PASSWORD, or pipe it with "
                    "--password-stdin. Environment or stdin is preferred over "
                    "--password, which is visible in the process list."
                )
            },
        )

    state = headless_login(
        creds,
        username=resolved_user,
        password=secret,
        state=runtime.store.load(),
    )
    state.username = resolved_user
    runtime.store.save(state)
    state = _resolve_identifiers(runtime, state)
    runtime.store.save(state)

    if save_credentials:
        store_account_password(resolved_user, secret)

    return {
        "ok": True,
        "authenticated": True,
        "mode": "credentials",
        "backend": runtime.store.backend,
        "savedCredentials": save_credentials,
        "account": state.redacted(),
    }


@app.command("login")
def login(
    ctx: typer.Context,
    account: str | None = typer.Option(
        None,
        "--username",
        "-u",
        help="Account email (or set MINDBODY_USERNAME).",
    ),
    password: str | None = typer.Option(
        None,
        "--password",
        help=(
            "Account password (or set MINDBODY_PASSWORD). Visible in the "
            "process list; prefer MINDBODY_PASSWORD or --password-stdin."
        ),
    ),
    password_stdin: bool = typer.Option(
        False,
        "--password-stdin",
        help="Read the password from stdin rather than prompting for it.",
    ),
    save_credentials: bool = typer.Option(
        False,
        "--save-credentials",
        help=(
            "Store credentials in the keychain so the CLI can re-authenticate "
            "itself if the refresh token is ever lost."
        ),
    ),
    browser: bool = typer.Option(
        False,
        "--browser",
        help="Use the interactive browser flow instead of signing in directly.",
    ),
    no_browser: bool = typer.Option(
        False,
        "--no-browser",
        help="With --browser, print the authorize URL instead of opening it.",
    ),
    print_url: bool = typer.Option(
        False,
        "--print-url",
        help="Print the authorize URL and exit (implies --browser).",
    ),
) -> None:
    """Log in. Signs in directly with credentials -- no browser needed.

    This is the default because the CLI is built to run unattended. Provide the
    username with -u or MINDBODY_USERNAME and the password via MINDBODY_PASSWORD,
    --password-stdin, --password, or a prompt. Login happens once; the rotating
    refresh token keeps the CLI running afterwards.

    The interactive browser flow remains available behind --browser, as a
    fallback if the sign-in service ever starts challenging direct sign-in.
    """

    def action() -> dict[str, Any]:
        runtime = get_runtime(ctx)
        creds = load_client_credentials()

        if not (browser or print_url):
            return _headless_login(
                runtime,
                creds,
                account,
                password,
                password_stdin,
                save_credentials,
            )

        pkce = generate_pkce()
        url = build_authorize_url(creds, pkce)

        if print_url:
            return {
                "ok": True,
                "stage": "authorize_url",
                "authorizeUrl": url,
                "state": pkce.state,
                "codeVerifier": pkce.verifier,
                "next": (
                    "Open the URL, sign in, then run `mindbody auth exchange "
                    "--redirect-url <url> --code-verifier <verifier>`."
                ),
            }

        # The PKCE verifier is generated per invocation, so the code must be
        # redeemed by the same process that created the authorize URL. The
        # non-interactive split is `auth login --print-url` then `auth exchange`.
        if not no_browser:
            webbrowser.open(url)
        typer.echo(
            "Open this URL, sign in, then paste the URL the browser "
            "stops on:\n\n"
            f"{url}\n",
            err=True,
        )
        pasted = typer.prompt("Redirect URL", err=True)

        code = extract_code(pasted, expected_state=pkce.state)
        state = exchange_code(
            creds,
            code=code,
            verifier=pkce.verifier,
            state=runtime.store.load(),
        )
        runtime.store.save(state)
        state = _resolve_identifiers(runtime, state)
        runtime.store.save(state)

        return {
            "ok": True,
            "authenticated": True,
            "mode": "browser",
            "backend": runtime.store.backend,
            "account": state.redacted(),
        }

    run_json(action, ctx)


@app.command("exchange")
def exchange(
    ctx: typer.Context,
    redirect_url: str = typer.Option(..., "--redirect-url"),
    code_verifier: str = typer.Option(..., "--code-verifier"),
) -> None:
    """Complete a login started with `auth login --print-url`."""

    def action() -> dict[str, Any]:
        runtime = get_runtime(ctx)
        creds = load_client_credentials()
        code = extract_code(redirect_url, expected_state=None)
        state = exchange_code(
            creds,
            code=code,
            verifier=code_verifier,
            state=runtime.store.load(),
        )
        runtime.store.save(state)
        state = _resolve_identifiers(runtime, state)
        runtime.store.save(state)
        return {
            "ok": True,
            "authenticated": True,
            "account": state.redacted(),
        }

    run_json(action, ctx)


@app.command("status")
def status(
    ctx: typer.Context,
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="Force a token refresh and re-resolve account identifiers.",
    ),
) -> None:
    """Report whether stored credentials still work."""

    def action() -> dict[str, Any]:
        runtime = get_runtime(ctx)
        state = runtime.store.load()
        if not state.is_authenticated:
            return {
                "ok": True,
                "authenticated": False,
                "backend": runtime.store.backend,
                "hint": "Run `mindbody auth login`.",
            }

        if refresh:
            from mindbody_cli.client.oauth import ensure_fresh_tokens

            state = ensure_fresh_tokens(
                runtime.store,
                runtime.client.credentials,
                force=True,
            )
            state = _resolve_identifiers(runtime, state)
            runtime.store.save(state)

        profile = normalize_profile(identity.get_me(runtime.client))
        state = runtime.store.load()
        return {
            "ok": True,
            "authenticated": True,
            "backend": runtime.store.backend,
            "account": state.redacted(),
            "profile": profile,
        }

    run_json(action, ctx)


@app.command("logout")
def logout(
    ctx: typer.Context,
    forget_client: bool = typer.Option(
        False,
        "--forget-client",
        help="Also remove the stored OAuth client registration.",
    ),
) -> None:
    """Revoke the refresh token upstream and clear local state."""

    def action() -> dict[str, Any]:
        runtime = get_runtime(ctx)
        state = runtime.store.load()
        revoked = False

        if state.refresh_token:
            try:
                creds = load_client_credentials()
                revoked = revoke_refresh_token(creds, state.refresh_token)
            except CliError:
                # Revocation is best effort. Local state must still be cleared,
                # otherwise a misconfigured client makes logout impossible.
                revoked = False

        runtime.store.clear()
        # Saved account credentials must go too. Leaving them would let the
        # next command silently re-authenticate, so logout would not log out.
        clear_account_password()
        if forget_client:
            clear_client_credentials()

        return {
            "ok": True,
            "revokedUpstream": revoked,
            "clearedLocal": True,
            "forgotClient": forget_client,
        }

    run_json(action, ctx)


@app.command("env")
def env(ctx: typer.Context) -> None:
    """List the environment variables this CLI reads."""

    def action() -> dict[str, Any]:
        return {
            "ok": True,
            "variables": {
                CLIENT_ID_ENV: "OAuth client id",
                CLIENT_SECRET_ENV: "OAuth client secret",
                REDIRECT_URI_ENV: "OAuth redirect URI",
                USERNAME_ENV: "Account email for login",
                PASSWORD_ENV: "Account password for login",
                "MINDBODY_CLI_TOKEN_PATH": "Token state file path",
                "MINDBODY_CLI_TOKEN_BACKEND": "auto | keyring | file",
                "MINDBODY_SITE_ID": "Default site id",
                "MINDBODY_LOCATION_ID": "Default location id",
                "MINDBODY_MASTER_LOCATION_ID": "Default master location id",
            },
            "exitCodes": {
                "0": "success",
                "1": "usage or validation",
                "2": "authentication",
                "3": "upstream API",
                "4": "network",
            },
        }

    run_json(action, ctx)


__all__ = ["app", "exit_codes"]
