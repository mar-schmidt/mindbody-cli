# Disclaimer

## No affiliation

`mindbody-cli` is an independent, unofficial project. It is **not** affiliated
with, authorised by, endorsed by, sponsored by, or in any way officially
connected to Mindbody, Inc. or any of its subsidiaries or affiliates.

"MINDBODY", "Mindbody", and any related names, marks, logos, and product names
are trademarks of Mindbody, Inc. They are used in this project **nominatively**
— solely to identify the third-party service this software interoperates with,
which cannot be described without naming it. No claim of ownership, licence,
partnership, or endorsement is made or implied.

## What this project contains

This repository contains original work by its authors:

- Python source code written from scratch for this project.
- URLs, HTTP method names, JSON field names, and parameter names, recorded by
  observing the network traffic of a client the authors were entitled to use,
  running against **their own account**.

## What this project does not contain

- No Mindbody source code, in whole or in part.
- No decompiled, disassembled, or otherwise reverse-engineered binaries.
- No Mindbody images, icons, fonts, copy, or other creative assets.
- **No Mindbody credentials, API keys, client secrets, or tokens.** The client
  registration required to talk to the authorization server is deliberately
  *not* vendored here. Users supply their own; see the README.
- No circumvention of any technical protection measure. The project
  authenticates through the service's own published OAuth 2.0 endpoints using
  the user's own credentials, and does nothing an ordinary logged-in user of
  the official client could not do.

Facts about an interface — that a given path accepts a given field — are
recorded here for the purpose of interoperability. The authors believe this is
lawful in their jurisdiction, and it is analogous to the many independent
clients written for other services. That belief is not legal advice, and the
authors make no representation that it applies to your jurisdiction or to your
use.

## Your responsibilities

By using this software you accept that:

- **You are bound by Mindbody's Terms of Service**, not by this project. Using
  an unofficial client may violate those terms. Read them, and decide for
  yourself. If your account is suspended or terminated as a result, that is
  between you and Mindbody.
- **You use only your own account**, with credentials you are entitled to use.
- **You do not use this to scrape, resell, or redistribute** data belonging to
  Mindbody or to the studios on its platform.
- **You keep your request volume reasonable.** This tool is for one person
  managing their own bookings, not for automated bulk access.
- **Booking and cancellation are real actions** with real consequences at a
  real business, including cancellation fees. `--dry-run` exists for a reason.

## No warranty

This software is provided "AS IS", without warranty of any kind. It talks to
an undocumented interface with no stability guarantees; it can break without
notice, and a change upstream can cause a command to fail, or to do something
other than what you intended. The authors accept no liability for missed
classes, cancellation charges, lost membership sessions, account suspension,
or any other damages. See LICENSE.

## Rights holders

If you represent Mindbody, Inc. and believe any part of this repository
infringes your rights, please open an issue or contact the maintainer through
GitHub. The authors will engage in good faith and promptly remove or amend
anything that is genuinely infringing. No response is intended as a challenge
to your rights.
