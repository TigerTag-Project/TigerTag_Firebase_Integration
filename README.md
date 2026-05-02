# TigerTag — Firebase Integration Guide

> **🎯 Source of truth for any third-party integration.** If your client
> talks to the TigerTag Firebase backend (Home Assistant, OctoPrint,
> Spoolman bridge, ESP32 firmware, custom script), **this repo is the
> reference you build against**. Anything that contradicts what's here
> (random forum posts, screenshots, leaked source) is wrong by definition —
> open an issue and we'll fix the doc.
>
> What's documented = what's deployed. We commit to keeping them in sync,
> with a public [`CHANGELOG.md`](CHANGELOG.md) tracking every schema /
> rule / API change.

This repository is **read-only documentation + reference examples**. The
actual TigerTag apps live in their own repos:

- **Tiger Studio Manager** (Electron desktop) — https://github.com/TigerTag-Project/TigerTag_Studio_Manager
- **TigerTag mobile** (Flutter) — _private_
- **TigerTag backend** (Firestore + Cloud Functions) — _private_

If you're building something on top of TigerTag and you find a behaviour
that disagrees with this documentation, **the documentation wins** — it
means we shipped a regression. Please file an issue.

---

## What's in this repo

```
.
├── docs/
│   ├── 01-firebase-config.md      ← public Firebase config endpoint
│   ├── 02-authentication.md       ← email/password sign-in + token refresh
│   ├── 03-data-model.md           ← Firestore collections reference
│   ├── 04-friend-system.md        ← how friend access works (privateKey model)
│   ├── 05-rate-limiting.md        ← polling intervals, query limits, monitoring
│   └── clients/
│       ├── home-assistant.md      ← full HA component sketch (Python)
│       ├── esp32.md               ← ESP32 / scale firmware (REST + Arduino sketch)
│       ├── spoolman-bridge.md     ← Spoolman sync (TigerTag → Spoolman REST)
│       └── python-cli.md          ← minimal Python REPL example
├── rules/
│   └── firestore.rules            ← public copy of the deployed Security Rules
└── examples/
    ├── home-assistant/            ← runnable HA custom component
    ├── esp32-arduino/             ← reference Arduino sketch
    └── python-cli/                ← `pip install -r requirements.txt` and run
```

---

## Quick links

| If you want to… | Read |
|-----------------|------|
| Connect a Python script that reads YOUR own spools | [docs/clients/python-cli.md](docs/clients/python-cli.md) |
| Build a Home Assistant integration (sensors per spool) | [docs/clients/home-assistant.md](docs/clients/home-assistant.md) |
| Wire a custom NFC/scale device to update spool weight | [docs/clients/esp32.md](docs/clients/esp32.md) |
| Sync TigerTag inventory to a Spoolman instance | [docs/clients/spoolman-bridge.md](docs/clients/spoolman-bridge.md) |
| Understand WHY a `permission-denied` error happens | [docs/02-authentication.md](docs/02-authentication.md) |
| See the live Firestore Security Rules | [rules/firestore.rules](rules/firestore.rules) |

---

## Core principles

1. **No service account.** Every client signs in with the **end-user's own
   credentials**. There is no shared admin key, no hidden master token.
2. **Firestore Security Rules** enforce all permissions server-side.
   Read-only access for friends, write access for owners only.
3. **One key per user, one bond per friendship.** When two users become
   friends, a bidirectional Firestore doc is created; either can revoke at
   any time, immediately cutting access.
4. **No App Check enforcement.** After evaluation, we decided not to
   enforce Firebase App Check project-wide — it brings little value on
   Electron / IoT / third-party clients and the integration overhead
   doesn't justify the protection gained. Defense relies on Security
   Rules + query-limit caps + Cloud Audit Logs instead. Clients shipping
   App Check anyway (defense-in-depth) are tolerated; their tokens are
   ignored. See [`docs/05-rate-limiting.md`](docs/05-rate-limiting.md)
   for the full rationale.

---

## Status & versioning

| Component | Version | Last verified against |
|-----------|---------|-----------------------|
| Firebase JS SDK | 9.x compat | Tiger Studio Manager v1.4.3 |
| Firestore Security Rules | rules_version = '2' | 2026-05-02 |
| Auth methods | email/password, Google (browser only) | — |

Rules in `rules/firestore.rules` mirror what's deployed on the TigerTag
Firebase project. The single source of truth is the live deployment — this
file is a snapshot for review and PRs.

---

## Stability guarantees for third-party integrations

We treat this repo as a **public contract**. Concretely:

### What WILL NOT change without notice (stable surface)

- **Document paths.** `users/{uid}/inventory/{spoolId}`,
  `users/{uid}/racks/{rackId}`, `users/{uid}/friends/{friendUid}` etc.
- **Field names** of every documented field in
  [`docs/03-data-model.md`](docs/03-data-model.md). Adding new fields is
  always allowed; renaming or removing existing ones requires a deprecation
  cycle (≥ 3 months notice in the CHANGELOG).
- **Field semantics.** `weight_available` will always be net grams,
  `last_update` will always be Unix milliseconds, `deleted: true` will
  always mean "soft-deleted, hide from UI", etc.
- **Friend access model.** The `users/{me}/friends/{them}` doc-existence
  pattern that grants read access on inventory + racks won't be replaced
  by a different mechanism without a migration path.
- **Authentication endpoints.** `identitytoolkit.googleapis.com` and
  `securetoken.googleapis.com` are Google's URLs — they're as stable as
  Firebase Auth itself.
- **`apiKey` and `projectId`** in the public init.json. They only change
  if we migrate the entire Firebase project (announced ≥ 6 months in
  advance via the CHANGELOG).

### What MAY change (be defensive)

- **Lookup table contents.** `id_brand.json`, `id_material.json`, etc.
  gain new entries as TigerTag adds support for more filaments. Numeric
  IDs are append-only; never reused for a different brand/material.
- **Cloud Functions HTTPS endpoints** at `cdn.tigertag.io/*`
  (e.g. `setSpoolWeightByRfid`). These are convenience wrappers; their
  request/response shapes can evolve. Pin a version-tagged release if
  you need lock-in.
- **App Check status.** App Check is OFF and we don't plan to enforce
  it project-wide (rationale in `docs/05-rate-limiting.md`). If we ever
  introduce it on a specific endpoint (e.g. public-inventory scraping
  protection), we'll announce it ≥ 1 month in advance.
- **New collections / new sub-fields.** Always additive — if you ignore
  unknown fields, you stay forward-compatible.

### The CHANGELOG

Every release that affects third-party clients gets an entry in
[`CHANGELOG.md`](CHANGELOG.md), categorised as:

- **Added** — new collections, new fields, new endpoints
- **Changed** — backwards-compatible tweaks (e.g. clarified semantics)
- **Deprecated** — fields/paths scheduled for removal, with a target date
- **Removed** — the field is gone (only after a deprecation cycle)
- **Fixed** — bug or doc errata
- **Security** — Firestore Rules updates

Follow this repo's releases on GitHub to get notified.

---

## Source of truth — how it stays accurate

The TigerTag team commits to:

1. **Update this repo on every breaking change** to Firestore data model,
   Security Rules, or auth flow — same PR, same release. Internal code
   changes that affect external clients are *not* merged until this repo
   is updated.
2. **Mirror `rules/firestore.rules`** to whatever is actually deployed.
   The public copy is regenerated from the deployed file (currently
   manually; a CI job to enforce parity is on the roadmap — see
   [CONTRIBUTING.md](CONTRIBUTING.md)).
3. **Verify each release** of Tiger Studio Manager and the mobile app
   against the docs before tagging. The footer of every doc indicates
   the latest verified version.

If you spot drift — a field that exists in production but isn't here, a
behaviour that doesn't match — please open an issue. We treat doc bugs
with the same priority as code bugs.

---

## Contributing

Found a typo, an outdated example, or want to add a client integration
(e.g. Node-RED, Domoticz, OpenHAB) ? PRs welcome on `docs/` and `examples/`.

For changes to **the Security Rules**, open an issue first — those are
deployed by the TigerTag team after review.

---

## License

Documentation & examples — MIT.
The TigerTag service itself is operated by the TigerTag team and not
covered by this license.
