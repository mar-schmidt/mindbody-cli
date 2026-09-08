# Advanced usage

## Scripted setup on a headless host

`auth login` needs a browser once. Split it across machines:

```bash
# On the headless host: get the URL and the verifier.
mindbody auth login --print-url
```

```json
{"ok": true, "stage": "authorize_url",
 "authorizeUrl": "https://signin.mindbodyonline.com/connect/authorize?...",
 "state": "…", "codeVerifier": "…"}
```

Open `authorizeUrl` on any machine with a browser, sign in, and copy the URL
the browser stops on. Then, back on the host:

```bash
mindbody auth exchange \
  --redirect-url "x-mindbodyconnect-oauth-mindbody://authcode?code=…&state=…" \
  --code-verifier "…"
```

From here the host runs unattended: the refresh token is rotated and persisted
automatically.

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
