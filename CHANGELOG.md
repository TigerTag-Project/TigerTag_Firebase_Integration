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
- (nothing pending)

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
git submodule add https://github.com/TigerTag-Project/TigerTag-Firebase-Integration.git
cd TigerTag-Firebase-Integration && git checkout v0.1.0
```

or just reference a tag in your CI:

```bash
curl -L https://raw.githubusercontent.com/TigerTag-Project/TigerTag-Firebase-Integration/v0.1.0/docs/03-data-model.md
```
