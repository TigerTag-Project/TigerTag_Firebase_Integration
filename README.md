# TigerTag — Firebase Integration Guide

> Public reference for third-party clients (mobile apps, Home Assistant,
> ESP32 firmware, custom scripts) that want to read or update a user's
> filament inventory through the TigerTag Firebase backend.

This repository is **read-only documentation + reference examples**. The
actual TigerTag apps live in their own repos:

- **Tiger Studio Manager** (Electron desktop) — https://github.com/TigerTag-Project/TigerTag_Studio_Manager
- **TigerTag mobile** (Flutter) — _private_
- **TigerTag backend** (Firestore + Cloud Functions) — _private_

---

## What's in this repo

```
.
├── docs/
│   ├── 01-firebase-config.md      ← public Firebase config endpoint
│   ├── 02-authentication.md       ← email/password sign-in + token refresh
│   ├── 03-data-model.md           ← Firestore collections reference
│   ├── 04-friend-system.md        ← how friend access works (privateKey model)
│   ├── 05-rate-limiting.md        ← polling intervals, App Check, quotas
│   └── clients/
│       ├── home-assistant.md      ← full HA component sketch (Python)
│       ├── esp32.md               ← ESP32 / scale firmware integration
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
4. **App Check encouraged.** Production deployments should attest their
   origin via Firebase App Check (reCAPTCHA / DeviceCheck / Play Integrity)
   to prevent generic abuse.

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
