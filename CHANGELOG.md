# Changelog

All notable changes to the TigerTag Firebase integration surface are
documented here. This file is the canonical record for third-party
integration developers.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project adheres loosely to [Semantic Versioning](https://semver.org)
on its public contract:

- **Major** (`X.0.0`) — incompatible changes to existing collections,
  field names, or auth flows. Always preceded by a ≥ 3-month deprecation
  cycle.
- **Minor** (`x.Y.0`) — new collections, new fields, new endpoints, new
  documented client recipes. Backwards-compatible.
- **Patch** (`x.y.Z`) — doc clarifications, errata, formatting.

The first public release of this repository is **`0.1.0`**. Major version
`1.0.0` will be cut once the contract has stabilised over a few release
cycles in the wild.

---

## [Unreleased]

### Added
- **`docs/clients/tigerscale.md`** — full TigerScale ESP32 firmware contract.
  Covers Firebase Auth flow (idToken refresh from NVS-stored refreshToken),
  the two write paths (`scales/{mac}` heartbeat every 30 s, `inventory/{spoolId}`
  weight + last_update), and the twin-tag self-healing decision matrix
  (§6.1 — six-case table for what to do when 2 RFID tags are detected:
  already-paired, asymmetric link, brand-new pair, conflict, etc.).
  Defines the `weight_available` (number, grams, net) and `last_update`
  (number, Unix ms) format expected by every TigerTag client. Includes a
  10-point compliance checklist and a §11 addendum on reading rack +
  position from `inventory.{spoolId}.rack_id` / `level` / `position` so
  the scale's display can show "Rack 4 · A3" by doing one extra read on
  `racks/{rack_id}`.
- **Walk-through of "find a friend by code"** in `docs/03-data-model.md` —
  end-to-end example showing the 6 reads/writes that flow across
  `publicKeys/`, `userProfiles/`, `users/{uid}/friendRequests/`, and
  `users/{uid}/friends/`. Explains why the `key` field stored on a
  friend doc is the OWNER's privateKey (not the friend's) and how
  privateKey rotation invalidates all friendships at once.

### Changed
- **`docs/03-data-model.md` rewritten** for clarity. The schema content is
  identical, but the structure is now pedagogical: starts with an
  "At a glance" map of the 3 top-level collections, then a per-collection
  section with field tables AND a concrete filled-in JSON example for
  every doc type (`publicKeys/{code}`, `userProfiles/{uid}`, `users/{uid}`,
  `inventory/{spoolId}`, `racks/{rackId}`, `scales/{mac}`, `friends/{uid}`,
  `friendRequests/{uid}`, `blacklist/{uid}`, `apiKeys/{docId}`,
  `printers/{brand}/devices/{deviceId}`, `prefs/app`). New sections on
  twin-tag handling, racks/scales reading patterns for embedded clients,
  and the privateKey-as-friendship-capability mechanism. All
  field-semantics and sensitive-fields content from the previous version
  is preserved verbatim.

---

## [0.1.3] — 2026-05-02

### Changed
- **App Check is no longer part of the recommended security model.**
  After evaluation, we decided not to enforce Firebase App Check
  project-wide. Rationale (full version in `docs/05-rate-limiting.md`):
  - On Electron (Tiger Studio Manager), App Check is theater — the
    `apiKey` is bundled in the public binary anyway, and reCAPTCHA
    Enterprise can't validate the `file://` origin used by Electron.
  - On mobile, App Check has real value via Play Integrity / DeviceCheck,
    but enforcing it project-wide would force every other client (Tiger
    Studio, ESP32, third-party integrations) to also ship attestation,
    which doesn't scale via debug tokens.
  - For third-party clients (HA, OctoPrint, scripts), there's no
    cryptographic attestation provider that works natively — we'd have
    to manually issue and revoke debug tokens, admin-heavy and unfriendly.
  - The actual abuse vector worth defending (scraping of public
    inventories) is better addressed surgically with a Cloud Function
    gate when/if it materialises, not by enforcing App Check globally.
- `docs/05-rate-limiting.md` rewritten:
  - Layer 3 (App Check) section removed from the recommended layers.
  - New section "Why we don't use Firebase App Check" with the rationale
    and the alternative we'd take for public-inventory scraping if needed.
  - New section "Clients that ship App Check anyway (defense-in-depth)"
    clarifying that App Check tokens sent by clients are silently ignored
    — clients consciencieux are not penalised, and they're future-proof
    if we ever flip a specific endpoint.
- `README.md` core principles updated: App Check is no longer in the list
  of recommended layers; defense relies on Security Rules + query-limit
  caps + Cloud Audit Logs.

### Removed
- **All "you must include `X-Firebase-AppCheck`" instructions** from
  third-party client docs. Clients that previously read v0.1.1 and
  started preparing App Check integration: that work is now optional
  defense-in-depth rather than required.

### Added
- **Cloud Audit Logs on Firestore Data Reads** is now active in
  production. The `Firestore/Datastore API` service has the "Data Read"
  audit type enabled in Cloud Console → IAM & Admin → Audit Logs. Every
  `RunQuery`, `get`, and `list` event is logged with the authenticated
  uid, target document/collection, full query parameters (including
  `limit`), and source IP. The TigerTag team uses these logs to:
  - Measure `.limit()` adoption ahead of the Layer 2 cutover (see v0.1.2).
  - Detect anomalous patterns (single uid reading 10 000+ docs/h, etc.).
  - Investigate user-reported issues by replaying the exact failed request.

---

## [0.1.2] — 2026-05-02

### Changed
- **Soft rollout for Layer 2 + Layer 3** instead of hard cutover.
  Previous v0.1.1 release described `request.query.limit` guards and
  App Check enforcement as already deployed. They are **not** — both are
  in soft-rollout / Monitor mode to avoid bricking older client versions
  still in the wild.
- `rules/firestore.rules`: kept as the TARGET state with explicit header
  comment clarifying that the deployed rules are currently more
  permissive, and pointing readers to the rollout schedule.
- `docs/05-rate-limiting.md`: status callout split into "Target" vs
  "Currently deployed" columns. Layer 2 marked as 🟡 **Permissive** in
  prod with Cloud Audit Logs measuring violations. Layer 3 marked as
  🟡 **Monitor mode** in App Check (logging unverified requests but
  not blocking).
- Layer 2 and Layer 3 sections rewritten in present tense reflecting
  Monitor / soft rollout, not Enforce.

### Added
- Explicit "Why soft rollout" rationale in `docs/05-rate-limiting.md`
  explaining that we wait for unverified-request count to drop to ~zero
  across all client versions before flipping to Enforce.
- Cloud Audit Logs are now active and feed BigQuery — per-uid anomaly
  alerts and "would-be-blocked" counters are dashboarded.

### Notes for third-party integrators
- **Build to the TARGET spec from day one.** Always pass `.limit(N)` on
  list reads, always include the `X-Firebase-AppCheck` header. The
  cutover to Enforce will be announced ≥ 1 month ahead in this
  changelog.
- Today, your client is **not rejected** for missing those — but it
  will be after cutover.

---

## [0.1.1] — 2026-05-02

### Security
- **`request.query.limit` guards** added to inventory and racks list
  operations:
  - `users/{uid}/inventory` list reads must specify `.limit(N)` with
    N ≤ 200. Unbounded list reads are rejected with `permission-denied`.
  - `users/{uid}/racks` list reads cap at 50.
  - Single-doc reads (`get`) are unaffected.
- **App Check enforcement** enabled on Firestore. Every request must
  carry a valid `X-Firebase-AppCheck` header.
  - Web clients use reCAPTCHA Enterprise.
  - iOS uses DeviceCheck / App Attest.
  - Android uses Play Integrity.
  - Third-party clients (Home Assistant, ESP32, scripts) request a debug
    token from the TigerTag team and embed it in the App Check header.
- **Cloud Logging** anomaly detection: per-uid read counters are watched;
  pathological patterns (> 5k reads/h sustained) trigger investigation
  and may result in token revocation.

### Changed
- `docs/05-rate-limiting.md` "Current production status" callout updated
  to reflect all four layers as active. The historical rollout plan is
  preserved for reference.
- `rules/firestore.rules` (public mirror) updated with the new `list`
  guards. The deployed file is the source of truth — the public mirror
  matches.

### Notes for third-party integrators
- **Pin to v0.1.1+** if your client makes list reads. Old clients that
  did `.get()` without `.limit(N)` will now receive `permission-denied`
  on list operations.
- **Request a debug token** by opening an issue with: client name,
  intended purpose, expected request volume, contact email. Tokens are
  individually revocable.

---

## [0.1.0] — 2026-05-02

Initial public release. Establishes the source-of-truth contract for
third-party integrations.

### Added
- `docs/01-firebase-config.md` — public Firebase config endpoint and
  caching guidance.
- `docs/02-authentication.md` — email/password sign-in, ID token refresh
  policy, the `permission-denied → retry` workaround pattern.
- `docs/03-data-model.md` — full Firestore collection map:
  - `publicKeys/{XXX-XXX}` — discovery codes (signed-in readable)
  - `userProfiles/{uid}` — public-facing profile (signed-in readable)
  - `users/{uid}` — owner-only root doc with `privateKey`, `email`,
    `displayName`, `googleName`, `roles`, `Debug`
  - `users/{uid}/inventory/{spoolId}` — spool documents (`uid`, `twin_uid`,
    `id_brand`, `id_material`, `color_name`, `online_color_list`,
    `weight_available`, `container_weight`, `capacity`, `container_id`,
    `last_update`, `deleted`, `rack_id`, `level`, `position`)
  - `users/{uid}/racks/{rackId}` — storage racks (`name`, `level`,
    `position`, `order`, `lockedSlots`, timestamps)
  - `users/{uid}/friends/{friendUid}` — accepted friends with `key`
  - `users/{uid}/friendRequests/{requesterUid}` — pending requests
  - `users/{uid}/blacklist/{blockedUid}` — blocked users
  - `users/{uid}/printers/{brand}/devices/{deviceId}` — per-brand printer
    registry (bambulab, creality, elegoo, flashforge, snapmaker)
  - `users/{uid}/scales/{mac}` — TigerScale heartbeats
  - `users/{uid}/prefs/app` — language preference
  - `users/{uid}/apiKeys/{docId}` — legacy Key6 HTTP API
- `docs/04-friend-system.md` — explains the bidirectional `privateKey`
  copy pattern that grants cross-account read access.
- `docs/05-rate-limiting.md` — App Check, polling discipline, query
  limits, deployment plan.
- `docs/clients/home-assistant.md` — full HA component sketch with
  config flow + sensors per spool.
- `docs/clients/esp32.md` — ESP32 firmware reference: REST flow + complete
  Arduino/PlatformIO sketch with `TigerTagClient` class.
- `docs/clients/spoolman-bridge.md` — Spoolman one-way sync: architecture,
  field mapping, complete Python implementation, cron/systemd/Docker.
- `docs/clients/python-cli.md` — minimal Python REPL example.
- `rules/firestore.rules` — public snapshot of the deployed Firestore
  Security Rules.
- `examples/` — placeholder folders for runnable sample projects.

### Security
- Confirmed `users/{uid}.privateKey` is owner-only — never readable by
  friends or public.
- Confirmed printer documents (`users/{uid}/printers/...`) are owner-only
  and contain LAN-control secrets that third-party clients must protect.
- Confirmed `inventory` and `racks` are readable by friends (via the
  bidirectional friend-doc existence check) and by anyone if
  `userProfiles/{uid}.isPublic == true`.
- Documented the `permission-denied` retry pattern for auth-token-near-
  expiry conditions.

### Notes
- App Check is currently **OFF** on the Firestore service. Third-party
  clients do not need to send App Check tokens. This may change with at
  least 1 month notice — see `docs/05-rate-limiting.md`.

---

## Release process for the TigerTag team

When merging a change that affects this contract:

1. Update the relevant doc in `docs/`.
2. Add an entry to **[Unreleased]** in this file.
3. When cutting a release: rename `[Unreleased]` to `[x.y.z] — YYYY-MM-DD`
   and start a fresh empty `[Unreleased]`.
4. Tag the release: `git tag vX.Y.Z && git push origin vX.Y.Z`.
5. Cross-link from the Tiger Studio Manager / mobile app changelogs when
   relevant.

---

## Versioning rationale

Why semver on a documentation repo?

Because third-party clients **build code against this contract**. A breaking
change in the data model is functionally identical to a breaking API
change in a library — it can crash a Home Assistant integration, brick
an ESP32 sketch, or silently corrupt a Spoolman sync. Treating it as a
versioned contract makes the impact explicit and lets integrators pin
to a known-good version.

Pin in your client:

```bash
git submodule add https://github.com/TigerTag-Project/TigerTag_Firebase_Integration.git
cd TigerTag_Firebase_Integration && git checkout v0.1.0
```

or just reference a tag in your CI:

```bash
curl -L https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Firebase_Integration/v0.1.0/docs/03-data-model.md
```
