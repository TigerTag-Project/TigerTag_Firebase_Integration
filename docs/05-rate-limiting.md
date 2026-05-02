# 05 — Rate limiting & abuse prevention

Firestore Security Rules are **binary** — allow or deny per request. They
don't do rate limiting on their own. To prevent abuse (a script hammering
the API, exfiltration attempts, runaway loops), combine the four layers
below.

## Layer 1 — Polling discipline (client-side)

**Recommended polling interval: 5 minutes minimum.** Filament inventories
change rarely; a faster poll wastes Firestore reads (which the TigerTag
team pays for) and burns mobile battery on the friend's side.

| Use case | Interval |
|----------|----------|
| HA "current weight" sensor | 5 min |
| HA "rack overview" dashboard | 15 min |
| ESP32 scale sync after weighing | event-driven (write only on change) |
| Python CLI poll | 1 min OK if interactive, 30 min if cron |

Document the polling interval in your client's settings. **Never** let
users go below 30 seconds — Firestore will start throttling the project.

## Layer 2 — Bounded list reads (Security Rules)

Without a `limit()` clause, a malicious script can request
`users/{uid}/inventory` and get every doc in one shot. Cap this in the
rules:

```javascript
match /users/{uid}/inventory/{spoolId} {
  allow get:  if isOwner(uid) || canFriendOrPublicRead(uid);
  allow list: if (isOwner(uid) || canFriendOrPublicRead(uid))
              && request.query.limit != null
              && request.query.limit <= 200;
}
```

Two effects:
1. Forces clients to paginate via `nextPageToken` for large inventories.
2. Bounds each individual request to 200 docs — limits the "blast radius"
   of a single leaked token.

200 docs is plenty for any real user (typical inventory: 30 spools).

## Layer 3 — Firebase App Check (production-grade)

App Check cryptographically attests that a request comes from a legitimate
**app instance**, not a script that scraped tokens. Recommended for
production.

### Enable on Firestore

Firebase Console → Build → App Check → Firestore → "Enforce".

⚠️ **Test in "Monitor" mode first** for at least one week. App Check
silently logs failures without blocking, so you can verify all your
legitimate clients (desktop, mobile, ESP32, HA) are passing the check
before flipping the enforcement switch.

### Per-platform attestation

| Platform | Provider |
|----------|----------|
| Web (desktop app) | reCAPTCHA Enterprise (recommended) or v3 |
| iOS | DeviceCheck or App Attest |
| Android | Play Integrity API |
| Server-side / scripts | **Service account** (only for Admin SDK — not applicable here) |
| **Third-party clients (HA, ESP32)** | **Debug tokens** (see below) |

### Third-party debug tokens

For clients that can't sign cryptographic attestations natively (HA, ESP32,
home-grown scripts), the TigerTag team can issue **debug tokens** via the
Firebase Console:

1. The integration developer requests a debug token (private GitHub issue
   or email) and provides their use case.
2. The team generates a token in Firebase Console → App Check → Manage
   debug tokens, names it (e.g. "Home Assistant — alice@example.com").
3. The token is embedded in the client config (env var, not hardcoded).
4. The team can **revoke individual tokens** if they detect abuse.

```python
# HA / Python
import os
APP_CHECK_TOKEN = os.environ.get("TIGERTAG_APP_CHECK_TOKEN")

headers = {
    "Authorization":      f"Bearer {id_token}",
    "X-Firebase-AppCheck": APP_CHECK_TOKEN,
}
```

If App Check is enforced and the header is missing/invalid, Firestore
returns 401 Unauthorized.

## Layer 4 — Monitoring & blacklist (operational)

### Cloud Logging on Firestore reads
Enable Cloud Audit Logs for Firestore data reads. Logs end up in BigQuery
or Cloud Logging.

### Anomaly detection
Set up an alert for any uid generating > N reads/hour. The TigerTag team
can investigate and:

- Revoke the user's tokens (force a new sign-in)
- Add a server-side blacklist entry (Cloud Function intercept)
- Raise per-uid quotas in App Check

### Budget alerts
Set a Firebase budget alert at e.g. $50/month. If usage spikes (typically
a runaway client), you'll know within hours.

## Recommended deployment plan

| Step | When | Risk |
|------|------|------|
| 1. Polling discipline in client docs | now | none |
| 2. Add `request.query.limit <= 200` to rules | now | breaks any client that listed > 200 — none in practice |
| 3. Enable App Check in Monitor mode | next sprint | none, just observe |
| 4. Whitelist 3rd-party clients (debug tokens) | when developers ask | low |
| 5. Flip App Check to Enforce | after 2 weeks of clean Monitor logs | high — test thoroughly |
| 6. Add Cloud Logging anomaly alert | once App Check is enforcing | none |

## What about Firestore's built-in quotas?

The free Spark plan includes 50K reads/day and 20K writes/day. The Blaze
(pay-as-you-go) plan has no daily caps but charges per operation. Neither
has a per-user rate limit out of the box — you have to build it yourself
(or trust App Check + good client behaviour).

For a typical TigerTag user (30 spools, 5 friends polled every 5 min), a
day's worth of reads is:
```
288 polls/day × (1 own + 5 friends × 1 list) = 1,728 reads/day
```
Even with 1,000 active users that's < 2M reads/day — well within Blaze
budget at ~$0.06 per 100K reads = $1/day for the whole user base.

The risk is a runaway client polling at 1Hz × 100 spools × 1000 users =
8.6M reads/day = $5/day from a single bad actor. App Check + the layer-2
list cap make this nearly impossible.
