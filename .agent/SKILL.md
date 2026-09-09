---
name: mindbody-cli
version: 1.0.0
description: >
  Use the Mindbody CLI to manage a user's own gym and studio class bookings:
  list bookings and waitlist positions, browse the studio schedule, book and
  cancel classes, join and leave waitlists, and inspect membership passes.
  Trigger this skill when the user mentions Mindbody, gym or studio class
  bookings, booking a class, cancelling a class, waitlists, class schedules,
  membership passes, classId, siteVisitId, or waitlistId.
author: mar-schmidt
repo: https://github.com/mar-schmidt/mindbody-cli
install:
  pip: pip install "git+https://github.com/mar-schmidt/mindbody-cli.git"
  pipx: pipx install "git+https://github.com/mar-schmidt/mindbody-cli.git"
requires:
  - python: ">=3.11"
compatibility:
  - claude-desktop
  - cursor
  - continue
  - generic-mcp
tags:
  - mindbody
  - fitness
  - bookings
  - waitlist
  - cli
---

# Skill: mindbody-cli

## When to use

Use this skill when the user wants to:

- see their upcoming class bookings or waitlist positions
- browse what classes are available at their studio
- book a class, or cancel one they have booked
- join or leave a waitlist for a full class
- check their membership: sessions remaining, expiry, active status

Do **not** use this skill to browse studios the user is not a member of, to
search for gyms, or to make purchases. It operates on one authenticated
account's own bookings.

## Critical: this tool takes real actions

`bookings create`, `bookings cancel`, `waitlist join`, and `waitlist leave`
change real reservations at a real business. Cancelling late can incur a fee.
Booking consumes a session from a membership pass.

**Always run a mutating command with `--dry-run` first and show the user what
would happen, unless the user has explicitly confirmed the specific class.**
Never book or cancel speculatively to "check" something — the read commands
exist for that.

## Output contract

Every command emits JSON. Never parse human-readable text; there is none.

**Success** → stdout, one line, always contains `"ok": true`:

```json
{"ok": true, "count": 2, "bookings": [...], "waitlist": [...]}
```

**Failure** → stderr, always exactly these three keys:

```json
{"error": "Not logged in", "code": "login_required", "details": {"hint": "..."}}
```

Branch on `code`, not on `error` (which is prose and may be reworded).

**Exit codes:**

| Code | Meaning | What to do |
|---|---|---|
| 0 | success | continue |
| 1 | usage or validation error | fix the arguments; do not retry unchanged |
| 2 | authentication | tell the user to run `mindbody auth login`; do not loop |
| 3 | upstream API error | report it; retry at most once |
| 4 | network error | retry once, then report |

## The identifier model — read this before booking anything

This is where clients most often go wrong. The upstream is several services
with **different id spaces**, and the id that books a class is not the id that
cancels it.

| Id | Comes from | Used by | Never use for |
|---|---|---|---|
| `classId` | `schedule` | `bookings create --class`, `waitlist join --class` | cancelling |
| `siteVisitId` | `bookings list` | `bookings cancel --visit-id` | booking |
| `waitlistId` | `waitlist list` | `waitlist leave --waitlist-id` | anything else |
| pass `id` | `passes` | `bookings create --pass` (optional) | identifying a class |

Rules that follow from this:

- To **book**, you need a `classId` from `schedule`.
- To **cancel**, you need a `siteVisitId` from `bookings list`. A `classId`
  will not work, and there is no command that converts one to the other.
- To **leave a waitlist**, you need a `waitlistId` from `waitlist list`. As a
  convenience `waitlist leave --class <classId>` resolves it for you.
- Never invent, guess, or increment an id. Always read it from a prior command
  in the same session.

## Commands

### Authentication

```bash
mindbody auth status                 # is the session usable?
mindbody auth status --refresh       # force refresh + re-resolve studio ids
mindbody auth login                  # interactive, browser
mindbody auth login --headless -u <email>   # browserless, for servers
mindbody auth logout                 # revokes upstream, clears local state
mindbody auth env                    # list env vars and exit codes
```

There are two ways to log in, and both are a one-time cost — afterwards the CLI
rotates and persists its own tokens and runs fully unattended.

- **Interactive** (`mindbody auth login`): opens a browser, the user signs in,
  and pastes back the URL the browser stops on. Needs a human once.
- **Headless** (`mindbody auth login --headless`): no browser. The username
  comes from `-u`/`--username` or `MINDBODY_USERNAME`; the password from
  `MINDBODY_PASSWORD`, `--password-stdin`, `--password`, or a hidden prompt.
  Adding `--save-credentials` stores them in the keychain so the CLI can
  recover by itself if the refresh token is ever lost; `auth logout` clears
  them. Suggest this only if the user wants unattended self-healing and
  accepts a password at rest.

**On exit code 2 (`login_required`), do not loop and do not retry.** Tell the
user to authenticate. Only run `auth login --headless` yourself if the user has
provided credentials for this purpose (via environment or explicitly); never
solicit a password to store it on your own initiative. Prefer `MINDBODY_PASSWORD`
or `--password-stdin` over `--password`, which is visible in the process list.

### Reading

```bash
mindbody status                      # counts, studio, pass state (one call)
mindbody profile                     # name, email, account creation
mindbody passes                      # memberships: sessions left, expiry
mindbody passes --status active

mindbody bookings list               # upcoming bookings + waitlist entries
mindbody bookings list --all         # include past
mindbody bookings list --no-waitlist # confirmed bookings only

mindbody waitlist list               # waitlist entries
mindbody waitlist list --with-position   # adds queue position, costs 1 req/entry

mindbody schedule                        # today at the user's studio
mindbody schedule --date 2026-09-15
mindbody schedule --date 2026-09-15 --days 3
mindbody schedule --bookable-only        # drop cancelled and full classes
```

`bookings list` returns two arrays, `bookings` and `waitlist`. A waitlist entry
is not a booking; do not report "you are booked" for one.

### Mutating

```bash
mindbody bookings create --class <classId> --dry-run
mindbody bookings create --class <classId>
mindbody bookings create --class <classId> --pass <passId>

mindbody bookings cancel --visit-id <siteVisitId> --dry-run
mindbody bookings cancel --visit-id <siteVisitId>
mindbody bookings cancel --visit-id <siteVisitId> --force

mindbody waitlist join --class <classId>
mindbody waitlist leave --waitlist-id <waitlistId>
mindbody waitlist leave --class <classId>
```

`--pass` is optional; the first active pass with sessions remaining is used.
Pass it explicitly when the user has more than one membership and the choice
matters.

`--force` on cancel overrides the penalty check. **Only use it after showing
the user the `cancellability.message` from the `--dry-run` and getting an
explicit go-ahead.** It may cost them money.

## Workflows

### Check what is booked

1. `mindbody bookings list`
2. Report `bookings` and `waitlist` separately.
3. Each entry has `name`, `startTime`, `locationName`, and its action id.

### Book a class

1. `mindbody schedule --date <date>` (add `--bookable-only` to filter).
2. Pick the entry matching what the user asked for. Confirm the match with the
   user if more than one class plausibly fits.
3. `mindbody bookings create --class <classId> --dry-run` — shows the class and
   which pass would pay.
4. Show that to the user; on confirmation run without `--dry-run`.
5. On success, report `bookingId` / `siteVisitId` — the user needs it to cancel.

If the class is full, `schedule` shows `spotsOpen: 0`. Offer the waitlist
instead of retrying the booking.

### Cancel a booking

1. `mindbody bookings list` to get `siteVisitId`.
2. `mindbody bookings cancel --visit-id <id> --dry-run` to read the
   cancellation policy result.
3. If `cancellability.status.code` is `1`, cancellation is free — proceed on
   the user's confirmation.
4. If it is anything else, **show the user `cancellability.status.message`
   verbatim and ask** before considering `--force`.

### Join and leave a waitlist

1. `mindbody schedule` → `classId` of the full class.
2. `mindbody waitlist join --class <classId>`.
3. The response may report `waitlistId: null` with a `note` — the id is not
   immediately visible. Run `mindbody waitlist list` to get it.
4. To leave: `mindbody waitlist leave --waitlist-id <id>`.

### Check membership before booking

1. `mindbody passes --status active`
2. If `sessionsRemaining` is 0 and `isUnlimited` is false, booking will fail
   with `no_usable_pass`. Tell the user before attempting it.

## Error reference

| `code` | Cause | Recovery |
|---|---|---|
| `login_required` | no stored session | ask the user to run `mindbody auth login`; do not retry |
| `auth_required` | upstream rejected the token | as above |
| `client_not_configured` | no OAuth client registration | ask the user to configure it; see the README |
| `missing_location` | studio ids unresolved | run `mindbody auth status --refresh` |
| `class_not_found` | `classId` not in the upcoming schedule | re-run `schedule`; the id may be stale or from another studio |
| `no_usable_pass` | no active pass with sessions left | run `passes`; tell the user their membership is exhausted |
| `booking_rejected` | upstream refused the booking | read `details.errorMessage`; do not retry blindly |
| `cancellation_not_free` | cancelling incurs a penalty | show `details.cancellability`; ask before `--force` |
| `waitlist_entry_not_found` | no waitlist entry for that class | run `waitlist list` |
| `token_lock_timeout` | another process is refreshing | wait a few seconds, retry once |
| `upstream_error` | API returned an error status | inspect `details.response`; retry at most once |
| `network_timeout` / `network_error` | transport failure | retry once |
| `usage_error` | bad arguments | fix the command; do not retry unchanged |

## What NOT to do

- Do not run `bookings create` or `bookings cancel` without first showing the
  user a `--dry-run` result, unless they named the exact class.
- Do not pass `--force` to `cancel` without explicit user consent about the fee.
- Do not use a `classId` where a `siteVisitId` is required, or vice versa.
- Do not guess, construct, or increment identifiers.
- Do not treat a waitlist entry as a confirmed booking.
- Do not retry on exit code 2. Re-authenticate instead: a human for the browser
  flow, or `auth login --headless` only with credentials the user has already
  provided for that purpose.
- Do not solicit the user's password just to store it. Headless login is for
  credentials the user chose to supply (env/stdin), not something to request.
- Do not parse the human-readable `--format text` output; use the default JSON.
- Do not poll `schedule` in a loop to snipe a cancellation. This is a personal
  tool, and the disclaimer asks users to keep request volume reasonable.

## Additional references

- Basic examples: `examples/basic.md`
- Advanced and scripted usage: `examples/advanced.md`

## Changelog

- `1.0.0`: Initial release. Auth, bookings, waitlists, schedule, memberships.
