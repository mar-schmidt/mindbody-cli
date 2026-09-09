# mindbody-cli

JSON-first CLI for the Mindbody consumer APIs, built for scripts and AI agents.

> **Unofficial.** Not affiliated with, endorsed by, or connected to Mindbody,
> Inc. Read [DISCLAIMER.md](DISCLAIMER.md) before using it — using an unofficial
> client may violate Mindbody's Terms of Service, and booking actions have real
> consequences at a real business.

## Features

- machine-readable JSON output by default (`--format text` for humans)
- stable error contract (`error`, `code`, `details`) on stderr
- fixed exit codes for automation
- browserless by design: sign in with credentials, then run unattended forever
- rotation-safe token storage (atomic writes, cross-process locking)
- `--dry-run` on every mutating command

## Install

```bash
pip install "git+https://github.com/mar-schmidt/mindbody-cli.git"
mindbody --help
```

Or with pipx:

```bash
pipx install "git+https://github.com/mar-schmidt/mindbody-cli.git"
```

Both `mindbody` and the shorter `mb` are installed.

## Setup

All you need is your own account. The CLI already carries the public OAuth
client identifier it presents to the sign-in server (the same one the vendor's
mobile app uses — a public client id, not a secret; see
[DISCLAIMER.md](DISCLAIMER.md)), so there is nothing to configure before
logging in.

### Overriding the bundled client (optional)

If you would rather supply your own client registration, set it via environment
variables — they take precedence over the bundled default:

```bash
export MINDBODY_OAUTH_CLIENT_ID="..."
export MINDBODY_OAUTH_CLIENT_SECRET="..."
export MINDBODY_OAUTH_REDIRECT_URI="..."
```

Or import it once into your OS keychain from your own captured traffic:

```bash
mindbody auth bootstrap --from-capture ./flows.jsonl
```

### Log in

Login is browserless by default and a one-time cost — afterwards the rotating
refresh token keeps everything running with no further interaction. Username
from `-u` or `MINDBODY_USERNAME`; password from `MINDBODY_PASSWORD`,
`--password-stdin`, `--password`, or a hidden prompt.

```bash
# Safest: password via environment or stdin, never on the command line.
export MINDBODY_USERNAME="you@example.com"
read -rs MINDBODY_PASSWORD && export MINDBODY_PASSWORD
mindbody auth login
unset MINDBODY_PASSWORD

# Or pipe it:
printf '%s' "$PW" | mindbody auth login -u you@example.com --password-stdin
```

`--password` exists too, but it is visible in the process list and shell
history — prefer the environment variable or stdin.

Add `--save-credentials` to store the username and password in the keychain.
The CLI then re-authenticates itself if the refresh token is ever lost —
useful on an unattended host, at the cost of a password at rest. `mindbody auth
logout` clears them again.

**Browser fallback.** If the sign-in service ever starts challenging direct
sign-in, `--browser` runs the interactive flow instead:

```bash
mindbody auth login --browser
```

The identity server rejects loopback redirect URIs, so the browser cannot hand
the code back automatically: it opens your browser, you sign in, the browser
stops on a page it cannot open, and you paste that URL back. Fully scripted
variant:

```bash
mindbody auth login --print-url            # returns authorizeUrl + codeVerifier
mindbody auth exchange --redirect-url "<pasted>" --code-verifier "<verifier>"
```

### Verify

```bash
mindbody auth status
```

## Usage

```bash
# What do I have?
mindbody status                    # booking counts, studio, pass state
mindbody profile                   # account profile
mindbody passes                    # memberships, sessions left, expiry

# What can I book?
mindbody schedule                              # today
mindbody schedule --date 2026-09-15 --days 3   # a window
mindbody schedule --bookable-only              # drop full and cancelled

# Bookings
mindbody bookings list
mindbody bookings create --class 48089 --dry-run
mindbody bookings create --class 48089
mindbody bookings cancel --visit-id 806714 --dry-run
mindbody bookings cancel --visit-id 806714

# Waitlists
mindbody waitlist list --with-position
mindbody waitlist join --class 48192
mindbody waitlist leave --waitlist-id 78637

# Done
mindbody auth logout               # revokes upstream, then clears local state
```

## Output contract

Success goes to **stdout** as a single line of JSON with `"ok": true`.
Failure goes to **stderr** with stable keys:

```json
{"error": "Not logged in", "code": "login_required", "details": {"hint": "..."}}
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | usage or validation error |
| 2 | authentication required or rejected |
| 3 | upstream API error |
| 4 | network error |

## Environment variables

| Variable | Purpose |
|---|---|
| `MINDBODY_OAUTH_CLIENT_ID` | OAuth client id |
| `MINDBODY_OAUTH_CLIENT_SECRET` | OAuth client secret |
| `MINDBODY_OAUTH_REDIRECT_URI` | OAuth redirect URI |
| `MINDBODY_USERNAME` | Account email for login |
| `MINDBODY_PASSWORD` | Account password for login |
| `MINDBODY_CLI_TOKEN_PATH` | Token state file path |
| `MINDBODY_CLI_TOKEN_BACKEND` | `auto` (default), `keyring`, or `file` |
| `MINDBODY_SITE_ID` | Default studio site id |
| `MINDBODY_LOCATION_ID` | Default location id |
| `MINDBODY_MASTER_LOCATION_ID` | Default master location id |

Studio ids are resolved automatically at login; the variables only matter if
your account belongs to more than one studio.

## Token storage

Tokens live in the OS keychain when one is available, otherwise in
`~/.config/mindbody-cli/tokens.json` with mode `0600`.

The authorization server **rotates the refresh token on every use**: the token
you send is dead as soon as the response is produced. Losing a rotated token
means redoing the interactive login, so writes are atomic (temp file, `fsync`,
`rename`) and every refresh holds an exclusive `flock` for its duration. A cron
job and a manual invocation cannot consume the same token.

## For AI agents

An agent skill lives in [`.agent/SKILL.md`](.agent/SKILL.md), packaged as a
`.skill` archive on every release. It documents the workflows, the id
relationships between commands, and the failure modes.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Documentation

- [`docs/api.md`](docs/api.md) — the upstream API surface, and what was
  verified against it
- [`DISCLAIMER.md`](DISCLAIMER.md) — affiliation, trademarks, your obligations
- [`.agent/SKILL.md`](.agent/SKILL.md) — the agent-facing skill

## License

MIT for the original code in this repository. No rights are granted in any
Mindbody trademark, service, or data. See [LICENSE](LICENSE).
