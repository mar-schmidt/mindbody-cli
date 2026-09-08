# Basic examples

All output is JSON on stdout. Errors are JSON on stderr.

## Is the session usable?

```bash
mindbody auth status
```

```json
{"ok": true, "authenticated": true, "backend": "keyring",
 "account": {"expiresInSeconds": 41203, "siteId": 12345},
 "profile": {"firstName": "Alex", "email": "alex@example.com"}}
```

When not logged in, exit code 2:

```json
{"error": "Not logged in", "code": "login_required",
 "details": {"hint": "Run `mindbody auth login` once to authenticate."}}
```

## What is coming up?

```bash
mindbody bookings list
```

```json
{"ok": true, "count": 2,
 "bookings": [
   {"kind": "booking", "name": "Group Class",
    "startTime": "2026-09-10T10:00:00Z", "locationName": "Example Gym",
    "status": {"code": 7, "title": "signed_in"},
    "classId": 48089, "siteVisitId": 806714, "waitlistId": null}],
 "waitlist": [
   {"kind": "waitlist", "name": "Group Class",
    "startTime": "2026-09-11T04:00:00Z",
    "status": {"code": 8, "title": "waitlisted"},
    "classId": 48192, "siteVisitId": null, "waitlistId": 78637}]}
```

Note which id is populated: `siteVisitId` cancels the booking, `waitlistId`
leaves the waitlist.

## What can I book today?

```bash
mindbody schedule --bookable-only
```

```json
{"ok": true, "count": 1, "from": "2026-09-08T17:00:00Z",
 "classes": [
   {"classId": 48089, "name": "Group Class",
    "startTime": "2026-09-08T17:30:00Z", "durationMinutes": 60,
    "staffName": "Coach", "capacity": 18, "spotsOpen": 3,
    "isCancelled": false}]}
```

## Book it

Always preview first:

```bash
mindbody bookings create --class 48089 --dry-run
```

```json
{"ok": true, "dryRun": true, "passId": "157212",
 "wouldBook": {"classId": 48089, "name": "Group Class", "spotsOpen": 3}}
```

Then commit:

```bash
mindbody bookings create --class 48089
```

```json
{"ok": true, "booked": true, "bookingId": "806714",
 "siteVisitId": "806714", "classId": 48089, "passId": "157212"}
```

## Cancel it

```bash
mindbody bookings cancel --visit-id 806714 --dry-run
```

```json
{"ok": true, "dryRun": true, "siteVisitId": 806714,
 "cancellability": {"code": 1, "title": "cancellable",
                    "message": "Booking can be cancelled without penalty."}}
```

```bash
mindbody bookings cancel --visit-id 806714
```

## Membership

```bash
mindbody passes --status active
```

```json
{"ok": true, "count": 1,
 "passes": [{"id": "aae53d41", "name": "2 classes / week",
             "sessionsRemaining": 40, "totalSessions": 40,
             "isUnlimited": false, "active": true,
             "expirationDate": "2026-12-19T23:00:00Z"}]}
```
