# 05 — Rate limiting & abuse prevention

Firestore Security Rules are **binary** — allow or deny per request. They
don't do rate limiting on their own. To prevent abuse (a script hammering
the API, exfiltration attempts, runaway loops), combine the three layers
below.

> ## Current production status
>
> | Layer | Target | Currently deployed |
> |-------|--------|--------------------|
> | Layer 1 — Polling discipline (client recommendation) | ✅ — | ✅ — |
> | Layer 2 — `request.query.limit` guard in rules | `inventory ≤ 200`, `racks ≤ 50` | 🟡 **Permissive** — guards are NOT in the deployed rules; Cloud Audit Logs track `.limit()` usage to measure how many clients still need to migrate. |
> | Layer 3 — Cloud Logging + alerts | Active | ✅ Audit logs feed BigQuery; per-uid anomaly alerts and "would-be-blocked" counters are dashboarded. |
>
> ### What this means for your client today
>
> - **No request is currently rejected** for missing `.limit()`. Existing
>   apps in the wild keep working.
> - **Build to the TARGET spec anyway** — when enforcement flips, your
>   client should already comply. We give ≥ 1 month notice in the
>   [CHANGELOG](../CHANGELOG.md) before the flip.
> - **Concretely**: always pass `.limit(N)` on list reads (≤ 200 for
>   inventory, ≤ 50 for racks).
>
> ### Why soft rollout instead of immediate enforcement?
>
> Tens of users still run older Tiger Studio Manager / mobile app
> versions that issue unbounded list reads. Hard-flipping to strict
> rules would brick those clients overnight. We monitor real traffic
> for ~2 weeks, identify the laggard versions, publish a forced-update
> cycle, then flip. The exact cutover date is announced in the CHANGELOG.

---

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

---

## Layer 2 — Bounded list reads (Security Rules)

Without a `limit()` clause, a malicious script can request
`users/{uid}/inventory` and get every doc in one shot. Target rule shape
(see `rules/firestore.rules` for the full target file):

```javascript
match /users/{uid}/inventory/{spoolId} {
  allow get:  if isOwner(uid) || canFriendOrPublicRead(uid);
  allow list: if (isOwner(uid) || canFriendOrPublicRead(uid))
              && request.query.limit != null
              && request.query.limit <= 200;
}
```

Two effects (when enforced):
1. Forces clients to paginate via `nextPageToken` for large inventories.
2. Bounds each individual request to 200 docs — limits the "blast radius"
   of a single leaked token.

### Current status

**🟡 Soft rollout.** The strict guard above is the TARGET; it is NOT
in the currently-deployed rules. The deployed rules accept any list
read that passes the auth/friend check. We monitor query patterns via
Cloud Audit Logs (Firestore `RunQuery` events include the `limit` field)
and will deploy the strict rule once metrics show all client versions
in use are passing `.limit()`.

**Build to spec from day one.** Always pass `.limit(N)` on every list
read in your client. When we flip the cutover (≥ 1 month notice in the
[CHANGELOG](../CHANGELOG.md)), your client is unaffected.

200 docs is plenty for any real user (typical inventory: 30 spools).

---

## Layer 3 — Monitoring & operational response

### Cloud Audit Logs on Firestore reads

Cloud Audit Logs are **enabled** on the Firestore Data Read API. Every
`get`, `list`, and `runQuery` event is recorded with:

- The authenticated user (uid)
- The exact document or collection accessed
- The full query parameters (`limit`, `where`, `orderBy`)
- Timestamp and source IP

Logs end up in Cloud Logging and can be exported to BigQuery for
analysis. We use them to:

- Measure `.limit()` adoption ahead of the Layer 2 cutover
- Detect anomalous patterns (single uid reading 10 000+ docs/h)
- Investigate user-reported issues (replay the exact failed request)

### Anomaly response

When Cloud Logging surfaces an abusive uid, the TigerTag team can:

- Revoke the user's tokens (force a re-sign-in via Firebase Auth admin)
- Add a server-side blacklist entry that the rules check against
- Raise a budget alert if costs spike

### Budget alerts

A Firebase budget alert at €50/month is active. If usage spikes (typically
a runaway client), the team is notified within hours and can act before
the bill grows.

---

## Why we don't use Firebase App Check

App Check is the obvious-looking fourth layer (cryptographic attestation
that a request comes from a legitimate app instance). After evaluation,
**we decided not to enforce it** for TigerTag. Rationale:

| Concern | Verdict |
|---------|---------|
| **Tiger Studio Manager (Electron)** | App Check on Electron is theater. The `apiKey` is bundled in the binary anyway; reCAPTCHA Enterprise needs an authorized domain that Electron's `file://` origin doesn't have; and an attacker can just download the public binary and run it as an "attested" client. Net protection: ~zero. |
| **Mobile Flutter app** | App Check via Play Integrity / DeviceCheck would add real value, but only if we Enforce *project-wide* — and that requires every other client (Tiger Studio, ESP32, third-party tools) to ship App Check too. The cost-benefit doesn't justify forcing every integrator to deal with debug tokens. |
| **Third-party integrators** (HA, OctoPrint, scripts) | They can't natively attest. We'd have to issue + manage debug tokens individually, which is admin-heavy and doesn't scale. |
| **Public-inventory scraping** | The one scenario where App Check could help. We address this differently if/when it becomes a real problem (see below). |

### What we do instead

- **Firestore Security Rules** are the primary defense. The privateKey
  is owner-only, friend access requires the bidirectional friend doc,
  blacklist is enforced. Most attack scenarios are blocked at this layer.
- **`query.limit` cap** (Layer 2 above) limits the blast radius of any
  leaked auth token.
- **Cloud Audit Logs** (Layer 3) detect anomalous patterns after the fact.
- **Per-public-inventory mitigation** stays an option in reserve: if/when
  Cloud Logs show actual scraping of `userProfiles[isPublic=true]`
  inventories, we'd implement a **Cloud Function gate** specifically for
  that endpoint (App Check + per-IP rate limit, surgical) rather than
  enforce App Check project-wide.

This decision will be revisited if traffic patterns change. The CHANGELOG
will record any switch.

### Clients that ship App Check anyway (defense-in-depth)

You **can** still call `firebase.appCheck().activate(...)` in your
client. Firestore will:

- **Ignore** the `X-Firebase-AppCheck` header if it's absent — no impact
- **Read but not act on** the header if it's present — request passes
  normally regardless of the verdict

So shipping App Check today is harmless and **future-proofs** your client:
if TigerTag ever flips to Enforce on a specific endpoint (e.g. for
public-inventory scraping protection), your client is already compliant
with no code change.

**The TigerTag team will give ≥ 1 month notice in the CHANGELOG before
any cutover, so non-attested clients have time to add the integration.**

---

## What about Firestore's built-in quotas?

The free Spark plan includes 50K reads/day and 20K writes/day. The Blaze
(pay-as-you-go) plan has no daily caps but charges per operation. Neither
has a per-user rate limit out of the box — you have to build it yourself.

For a typical TigerTag user (30 spools, 5 friends polled every 5 min), a
day's worth of reads is:

```
288 polls/day × (1 own + 5 friends × 1 list) = 1,728 reads/day
```

Even with 1 000 active users that's < 2M reads/day — well within Blaze
budget at ~$0.06 per 100K reads = $1/day for the whole user base.

The risk is a runaway client polling at 1 Hz × 100 spools × 1 000 users =
8.6M reads/day = $5/day from a single bad actor. The Layer 2 cap and
Layer 3 monitoring catch this.
