# Advanced usage

## Setup on a headless host

No browser needed. Provide credentials through the environment or stdin — not
the command line, where they land in the process list and shell history.

```bash
export MINDBODY_USERNAME="you@example.com"
read -rs MINDBODY_PASSWORD && export MINDBODY_PASSWORD
mindbody auth login --headless
unset MINDBODY_PASSWORD
```

```json
{"ok": true, "authenticated": true, "mode": "headless",
 "account": {"username": "you@example.com", "siteId": 25441, "userId": 27208803}}
```

From here the host runs unattended: the refresh token rotates and persists
automatically, so later commands need no credentials at all.

If the sign-in service ever starts challenging the headless client, you will
get `headless_login_blocked`; fall back to the interactive browser flow
(`mindbody auth login`) once to re-seed the refresh token.

### Reading the password from a secret file

```bash
mindbody auth login --headless -u you@example.com --password-stdin < ~/.mb-secret
```

### Splitting the browser flow across machines

When you do want the browser flow but the browser is on a different machine:

```bash
mindbody auth login --print-url          # prints authorizeUrl + codeVerifier
# open authorizeUrl elsewhere, sign in, copy the URL it stops on, then:
mindbody auth exchange --redirect-url "<pasted>" --code-verifier "<verifier>"
```

## Composing with jq

Find the next class and book it:

```bash
CLASS=$(mindbody schedule --days 2 --bookable-only \
  | jq -r '.classes[0].classId')

mindbody bookings create --class "$CLASS" --dry-run
```

Cancel everything on a given date:

```bash
mindbody bookings list \
  | jq -r '.bookings[] | select(.startTime | startswith("2026-09-10")) | .siteVisitId' \
  | while read -r id; do
      mindbody bookings cancel --visit-id "$id" --dry-run
    done
```

Check whether a membership is running out:

```bash
mindbody passes --status active \
  | jq '.passes[] | select(.isUnlimited == false and .sessionsRemaining < 5)'
```

## Handling errors in scripts

Branch on the exit code, and read `code` for detail:

```bash
if ! out=$(mindbody bookings create --class "$CLASS" 2>err.json); then
  case $? in
    2) echo "Login expired; run: mindbody auth login" >&2 ;;
    1) jq -r '.code' err.json ;;
    3) echo "Upstream error:" >&2; jq -r '.details.response' err.json >&2 ;;
    4) echo "Network problem, retrying once" >&2 ;;
  esac
fi
```

A successful HTTP call is not a successful booking — the CLI already checks the
upstream `errorCode` and turns it into exit code 3 with `code:
"booking_rejected"`, so trusting the exit code is sufficient.

## Multiple studios

Studio ids are resolved at login from the first studio on the account. If the
account belongs to more than one, pin the studio explicitly:

```bash
export MINDBODY_SITE_ID=12345
export MINDBODY_LOCATION_ID=1
export MINDBODY_MASTER_LOCATION_ID=678910
```

`mindbody status` lists every studio on the account with its ids.

## Running from cron

Token refresh is safe under concurrency: refreshes take an exclusive lock, so a
cron job and an interactive run cannot consume the same rotating token. If a
run reports `token_lock_timeout`, another process held the lock longer than 30
seconds; retry once.

```cron
*/30 * * * * /usr/local/bin/mindbody bookings list >> ~/mb.log 2>&1
```

Keep the frequency low. See DISCLAIMER.md.
