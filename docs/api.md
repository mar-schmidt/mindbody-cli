# Upstream API notes

What this CLI talks to, and how it was determined. Every claim marked
**verified** was tested against the live service; everything else was observed
in traffic from the official mobile client running against the author's own
account.

Identifiers in examples are placeholders. No account data is published here.

## 1. There is no single API

Five hosts, three generations, different conventions. This is the single most
important fact for anyone reading the code: booking and cancelling a booking
do not talk to the same service.

| Host | Role | Style |
|---|---|---|
| `signin.mindbodyonline.com` | OAuth2 / OIDC identity server | OAuth, WAF-protected |
| `prod-mkt-gateway.mindbody.io` | Bookings, passes, schedules, booking creation | JSON:API-like |
| `connect.mindbodyonline.com` | Cancellation, waitlists, class detail | Older REST, PascalCase |
| `www.mindbodyapis.com` | Account profile | REST |
| `payments.mindbodyonline.com` | Payment methods | Not used by this CLI |

All of them accept `Authorization: Bearer <access_token>` from the same token
exchange.

## 2. Authentication

### 2.1 The flow

OAuth 2.0 authorization code with PKCE (S256).

1. `GET /connect/authorize` with `code_challenge`, `code_challenge_method=S256`,
   `redirect_uri`, `client_id`, `state`, `prompt=login` → 302 to `/signin`
2. The user signs in interactively in a real browser
3. The server redirects to the client's registered custom scheme with `?code=`
4. `POST /connect/token`
   - `Authorization: Basic base64(<client_id>:<client_secret>)`
   - `Content-Type: application/x-www-form-urlencoded`
   - `grant_type=authorization_code&redirect_uri=…&code_verifier=…&code=…`

Response: `access_token` (JWT, 12 h), `refresh_token` (opaque), `id_token`,
`expires_in: 43200`.

### 2.2 The WAF does not cover the token endpoint — **verified**

The interactive sign-in pages (`/signin`, `/api/csrf`, `/account/search`,
`/account/login`) sit behind a JavaScript challenge and require a
`cf_clearance` cookie.

`/connect/token` does not. A `refresh_token` grant with no cookies at all —
only Basic auth and the client's User-Agent — returns 200 with a fresh access
token and all scopes intact.

**Consequence:** the browser is needed exactly once. All subsequent operation
is headless.

### 2.3 The password grant is unavailable — **verified**

Discovery advertises `password` in `grant_types_supported`, but that describes
the server, not what a given client may do.

Tested with valid credentials: `400 {"Type":"bad-request","Title":"Request
invalid for target resource","Code":400}`. The envelope is not the identity
server's OAuth error format, which suggests rejection in a layer ahead of the
token logic.

**Consequence:** there is no username/password path, and this CLI stores no
password.

### 2.4 Refresh tokens rotate — **verified**

The token sent is invalidated when the response is produced, and a new refresh
token is returned. See `client/tokens.py` for the atomicity and locking this
forces.

### 2.5 Loopback redirect URIs are rejected — **verified**

Identical `/connect/authorize` requests varying only `redirect_uri`:

| `redirect_uri` | Result |
|---|---|
| the client's registered custom scheme | 302 → `/signin` (accepted) |
| `http://localhost:<port>/callback` | 302 → `/home/error` (rejected) |
| `http://127.0.0.1:<port>/callback` | 302 → `/home/error` (rejected) |

**Consequence:** the standard CLI loopback-listener pattern is unavailable. The
one-time login captures the redirect from the browser's address bar instead.

### 2.6 Revocation exists — **verified**

`/connect/revocation` is present in the discovery document, so `auth logout`
revokes the refresh token upstream before clearing local state, rather than
merely forgetting it locally.

### 2.7 Required headers

```
Authorization:   Bearer <access_token>
Content-Type:    application/json
User-Agent:      <mobile client UA>
Accept-Language: <locale>
```

The User-Agent matters: an unfamiliar one is the most likely way to trip bot
detection. `Accept-Language` selects the language of `status.message` strings.

## 3. The `*RefJson` pattern

Composite identifiers are JSON strings nested inside JSON documents:

```json
"bookingRefJson": "{\"mb_site_id\":<site>,\"mb_site_visit_id\":<visit>}"
```

Three variants — `locationRefJson`, `inventoryRefJson`, `bookingRefJson`. Key
order varies between endpoints. All parsing and serialisation is funnelled
through `refs.py`; doing it ad hoc at call sites is the most likely source of
bugs in any client.

Sentinels matter: a waitlist entry has `mb_site_visit_id: -1` and a real
`mb_waitlist_id`; a confirmed booking has the reverse. Which one is populated
determines how the entry must be cancelled.

## 4. Endpoints

### 4.1 Bookings and waitlists share one endpoint

```
GET prod-mkt-gateway.mindbody.io/v1/user/bookings
    ?page.size=30&filter.before=<ISO8601Z>&filter.ascending=false
```

Both confirmed bookings and waitlist positions come back here, distinguished by
`status.code` and by `bookingRefJson`.

Observed status codes: `7 signed_in`, `8 waitlisted`, `13 client_on_waitlist`.
**The list is not exhaustive.** Read `status.code` generically and display
`status.title` / `status.message`; never hardcode the enum as a whitelist.

Queue position is *not* in this payload — it comes from `/v1/location/schedules`
or `/rest/Class/{id}`, which is why `waitlist list --with-position` costs an
extra request per entry.

### 4.2 Schedule

```
POST prod-mkt-gateway.mindbody.io/v1/location/schedules
{
  "location_ref_json": "<LocationRef>",
  "start_time_from": "<ISO8601Z>",
  "start_time_to": "<ISO8601Z>",
  "bookable_with_passes": "any",
  "online_bookable": "any"
}
```

Use this, not `/v1/search/class_times` — the latter is a geographic search
across all studios and returns nothing useful for a known location.

Note the payload nests the interesting fields one level deeper than the
envelope suggests (`attributes.attributes`).

### 4.3 Booking a class

```
POST prod-mkt-gateway.mindbody.io/v1/class-bookings
{"inventory_ref_json": "<InventoryRef>", "payment_id": "<pass id>"}
→ 201 {"data":{"id":"<siteVisitId>","attributes":{"errorCode":null,…}}}
```

Two traps:

- `payment_id` is the **membership pass id** from `/v1/user/passes`. There is
  no "book with my default pass".
- **A 201 does not mean the booking succeeded.** Business failures are reported
  as `errorCode` / `errorMessage` inside the body of a successful HTTP
  response. This CLI checks both and raises `booking_rejected`.

### 4.4 Cancelling — different service, different id

```
POST prod-mkt-gateway.mindbody.io/v1/user/bookings/cancellability
{"bookingRefJson": "<BookingRef>"}
→ {"data":{"attributes":{"status":{"code":1,"title":"cancellable",…}}}}

DELETE connect.mindbodyonline.com/rest/user/{userId}/visits/{siteVisitId}
→ 204
```

Code `1` is the only observed penalty-free outcome. Other codes were not
reachable without incurring a real fee, so this CLI treats anything else as
requiring `--force` and surfaces the upstream `message` verbatim.

The path id is `mb_site_visit_id` from `bookingRefJson` — not the gateway's
booking uuid, and not the class id.

### 4.5 Waitlists — legacy service, PascalCase

```
POST connect.mindbodyonline.com/rest/user/{userId}/waitlist?checkVerified=true
{"ClassId": <classId>}
→ 201, empty body

DELETE connect.mindbodyonline.com/rest/user/{userId}/waitlist/{waitlistId}
→ 204
```

The join returns no body, so the assigned `mb_waitlist_id` must be read back
from `/v1/user/bookings` before it can ever be used to leave.

### 4.6 Profile and memberships

```
GET  www.mindbodyapis.com/identity/gateway/V2/Users/Me
GET  prod-mkt-gateway.mindbody.io/v1/user/passes?status=both
POST prod-mkt-gateway.mindbody.io/v1/user/activity_profile
```

`activity_profile` is the best single call for an overview: booking counts,
studios, and pass state together. It is also where this CLI resolves the
studio ids it needs for every subsequent request.

Note the two distinct user identities: the identity gateway returns an opaque
identity id, while the legacy REST service expects a numeric user id in its
paths. They are not interchangeable.

### 4.7 Cache invalidation after mutations

```
POST prod-mkt-gateway.mindbody.io/v1/user/cache/clear → 204
```

The gateway caches reads aggressively; the official client calls this after
every mutation. Without it, a list issued immediately after a booking can
return stale data. Treated as best-effort here — a failed cache bust must not
fail a mutation that already succeeded.

## 5. Known unknowns

- The full booking status enum. Only three codes were observed.
- Cancellability outcomes other than "free of charge" — untestable without
  incurring a real fee.
- Rate limits. None were observed, but none were probed either. Client-side
  backoff is advisable.
- Purchase flows. Booking with an existing pass works; booking that requires a
  purchase is out of scope.
