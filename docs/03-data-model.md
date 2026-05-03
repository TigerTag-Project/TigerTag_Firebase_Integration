# 03 — Firestore data model

Single source of truth for the TigerTag Firestore schema. Read this first if you're integrating any third-party client (web, mobile, ESP32, Home Assistant, IoT bridge, AI agent, scraper, etc.).

The whole project lives in **one Firebase project** (`tigertag-connect`) with **one Firestore database** (`(default)`). The public Firebase config (apiKey + projectId) is fetched at runtime from `https://tigertag-cdn.web.app/__/firebase/init.json` — see [01-firebase-config.md](./01-firebase-config.md).

---

## At a glance — three top-level collections

Everything lives under exactly three root collections. Knowing what each one is for makes the rest of this doc trivial to skim.

| Collection | Who can read | Who can write | Role |
|---|---|---|---|
| **`publicKeys/{XXX-XXX}`** | Any signed-in user | Owner only (atomic claim) | Tiny lookup table mapping a discovery code → uid |
| **`userProfiles/{uid}`** | Any signed-in user | Owner only | Public-facing "business card" (pseudo, avatar colour, isPublic flag) |
| **`users/{uid}`** | Owner only at root level; some sub-collections opened to friends | Owner only | Private vault — inventory, racks, scales, friends, etc. |

```
┌─────────────────────────┐
│  publicKeys/{XXX-XXX}   │   ← lookup table "code → uid"
└────────────┬────────────┘
             │  uid
             ▼
┌─────────────────────────┐
│  userProfiles/{uid}     │   ← business card "who is this uid?"
└────────────┬────────────┘
             │  same uid
             ▼
┌─────────────────────────────────────────────────────────────┐
│  users/{uid}/                                               │
│    ├── inventory/{spoolId}        ← spools (RFID + position)│
│    ├── racks/{rackId}             ← storage shelves         │
│    ├── scales/{mac}               ← TigerScale heartbeats   │
│    ├── friends/{friendUid}        ← accepted friendships    │
│    ├── friendRequests/{requesterUid} ← pending invites      │
│    ├── blacklist/{blockedUid}     ← blocked users           │
│    ├── apiKeys/{docId}            ← legacy HTTP tokens      │
│    ├── printers/{brand}/devices/  ← 3D printers             │
│    └── prefs/app                  ← user preferences        │
└─────────────────────────────────────────────────────────────┘
```

The two flat collections (`publicKeys`, `userProfiles`) exist so a stranger can find a user without already having read access to that user's private data — the `users/{uid}` doc itself is locked down.

---

## How a typical "find a friend by code" flow works

This single example walks through almost every collection at once:

```
Alice gives Bob her code "4X7-K3M".
Bob types it into his app.

  1. App reads  publicKeys/4X7-K3M           → returns { uid: "alice123", … }
  2. App reads  userProfiles/alice123        → returns { displayName: "Alice", color: "#FF7A18", isPublic: true }
  3. App writes users/alice123/friendRequests/bob456
                with { displayName: "Bob", requestedAt: now, key: bob.privateKey }

  Alice sees the request, accepts. Two writes happen atomically:
  4. users/alice123/friends/bob456    = { displayName: "Bob",   addedAt: now, key: alice.privateKey }
  5. users/bob456/friends/alice123    = { displayName: "Alice", addedAt: now, key: bob.privateKey }

  Now both can read each other's inventory:
  6. Bob reads users/alice123/inventory      → allowed by the rules because
                                                 users/alice123/friends/bob456 exists
                                                 AND its `key` field matches Bob's privateKey.
```

The `key` field on `friends/{friendUid}` is the privateKey of the **owner of that doc** (i.e., it's `alice.privateKey` on Alice's side, `bob.privateKey` on Bob's side). The Firestore Rules use it as a per-friendship capability token: rotate your privateKey and all your friend access is invalidated in one step.

---

## Top-level collections

### `publicKeys/{code}`

Looking up a uid from a public discovery code.

| Field | Type | Required | Description |
|---|---|---|---|
| `uid` | string | ✅ | Owner's Firebase Auth uid |
| `claimedAt` | timestamp | ✅ | When the code was reserved |

The doc id IS the code (format `XXX-XXX`, alphanumeric uppercase). One uid claims one code; codes are unique across the database. Claim is atomic via `runTransaction()` to prevent races.

**Example doc** — `publicKeys/4X7-K3M`:

```json
{
  "uid": "alice123abcDEF",
  "claimedAt": "2026-01-15T09:23:11.000Z"
}
```

### `userProfiles/{uid}`

Public-facing identity card. Anyone signed in can read this; only the owner can write.

| Field | Type | Required | Description |
|---|---|---|---|
| `publicKey` | string | ✅ | Same code as the `publicKeys/{key}` doc id (denormalised so callers don't need a second read) |
| `displayName` | string | ✅ | User's chosen pseudo |
| `isPublic` | boolean | ✅ | If `true`, ANY signed-in user can read this user's `inventory` (no friendship needed) |
| `color` | string \| null | ⚠️ | Hex avatar colour, e.g. `#FF7A18` |
| `color_r` / `color_g` / `color_b` | number | ⚠️ | Alternate RGB-component form (some clients write one, some the other; always check both) |

**Example doc** — `userProfiles/alice123abcDEF`:

```json
{
  "publicKey": "4X7-K3M",
  "displayName": "Alice",
  "isPublic": false,
  "color": "#FF7A18"
}
```

### `users/{uid}` (root document)

Owner-only. The fields directly on this doc are user-level metadata; everything bulk lives in sub-collections (covered in the next section).

| Field | Type | Required | Description |
|---|---|---|---|
| `displayName` | string | ✅ | User-chosen pseudo (preferred over `googleName` for UI) |
| `googleName` | string | optional | Real name from Google Auth (admin reference; never displayed) |
| `firstName` / `lastName` | string | optional | Split form of `googleName` |
| `email` | string | ✅ | Contact email (Firebase Auth email) |
| `publicKey` | string | ✅ | Discovery code (same as in `publicKeys/{key}` doc id) |
| `privateKey` | string | ✅ | 40-char hex SECRET — used by Firestore Rules as friendship capability. **NEVER expose to other users.** |
| `isPublic` | boolean | ✅ | Mirror of `userProfiles/{uid}.isPublic` |
| `Debug` | boolean | optional | Admin-only: enables debug panel in the desktop app |
| `roles` | string | optional | `"admin"` or undefined |

**Example doc** — `users/alice123abcDEF`:

```json
{
  "displayName": "Alice",
  "googleName": "Alice Martin",
  "firstName": "Alice",
  "lastName": "Martin",
  "email": "alice@example.com",
  "publicKey": "4X7-K3M",
  "privateKey": "ab12cd34ef567890123456789012345678901234",
  "isPublic": false,
  "Debug": false
}
```

---

## User sub-collections

Each of these lives under `users/{uid}/<sub>/`. Read access varies; write is **always** owner-only.

### `users/{uid}/inventory/{spoolId}` — filament spools

The doc id IS the RFID tag UID, formatted as **uppercase HEX, no separators** (e.g. `041A2B3C4D5E6F80`). One doc per RFID-tagged spool.

| Field | Type | Required | Description |
|---|---|---|---|
| `uid` | string | ✅ | Same as the doc id (denormalised for clients reading without the path) |
| `twin_tag_uid` | string \| null | optional | Linked partner tag UID — when ONE physical spool has TWO RFID stickers (e.g. inner TD1 + outer TigerTag). Both docs reference each other. See [tigerscale.md §6](./clients/tigerscale.md) for the self-healing rules. |
| `id_brand` | number | ✅ | FK into [`id_brand.json`](https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_brand.json) |
| `id_material` | number | ✅ | FK into [`id_material.json`](https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_material.json) |
| `id_aspect` | number | optional | FK into [`id_aspect.json`](https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_aspect.json) (matte / silk / glossy / …) |
| `id_type` | number | optional | FK into [`id_type.json`](https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_type.json) (filament / pellets / …) |
| `id_tigertag` | number | optional | TigerTag protocol version — `1` = TigerTag, `2` = TigerTag+ (server-side artwork) |
| `color_name` | string | optional | Human-readable colour name |
| `online_color_list` | string[] | optional | Array of hex colours (`["#FFFFFF"]` for solid, `["#FF0000","#000000","#FFFFFF"]` for multicolour) |
| `weight_available` | number | ✅ | **NET filament weight in grams** (raw scale reading minus container_weight) |
| `container_weight` | number | optional | Empty-spool tare weight in grams |
| `measure_gr` (or `capacity`) | number | optional | Total capacity in grams (e.g. 1000 for a 1 kg spool) |
| `container_id` | string | optional | FK into [`spools_filament.json`](https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/container_spool/spools_filament.json) — identifies which physical spool model |
| `last_update` | number | ✅ | **Unix MILLISECONDS** of the last write (use `Date.now()`) |
| `deleted` | boolean | optional | Soft-delete flag. Clients hide if `deleted === true`. |
| `deleted_at` | number | optional | Unix ms when deleted (informational only) |
| `rack_id` | string \| null | optional | FK → `users/{uid}/racks/{rackId}` if placed on a shelf |
| `level` | number \| null | optional | Shelf row index (1-indexed, 1 = bottom). Convert to letter for UI (1→A, 2→B, …) |
| `position` | number \| null | optional | Slot column index (1-indexed, 1 = leftmost) |
| `series` / `label` / `name` / `sku` / `barcode` | string | optional | Branding fields — present on TigerTag+ encoded tags |
| `info1` / `info2` / `info3` | boolean | optional | Refill / Recycled / Filled badges (TigerTag protocol) |
| `data1`–`data7` | number | optional | Print-temperature data — see [§ data1-data7 fields](#data1-data7--print-parameters) below for the per-field semantics |
| `TD` | number | optional | Filament transmission distance |
| `LinkYoutube` / `LinkMSDS` / `LinkTDS` / `LinkROHS` / `LinkREACH` / `LinkFOOD` | string | optional | External resource URLs |
| `url_img` | string | optional | Server-hosted spool artwork (TigerTag+ only) |

**Example doc** — `users/alice123abcDEF/inventory/041A2B3C4D5E6F80`:

```json
{
  "uid": "041A2B3C4D5E6F80",
  "twin_tag_uid": "0B2C3D4E5F60718A",
  "id_brand": 12,
  "id_material": 3,
  "id_aspect": 1,
  "id_type": 1,
  "id_tigertag": 2,
  "color_name": "Pure White",
  "online_color_list": ["#FFFFFF"],
  "weight_available": 247.3,
  "container_weight": 245,
  "measure_gr": 1000,
  "container_id": "BambuLab_Spool_1KG",
  "last_update": 1735851623000,
  "deleted": false,
  "rack_id": "rack_xyz789",
  "level": 2,
  "position": 3,
  "series": "Basic PLA",
  "data1": 175,
  "data2": 200, "data3": 230,
  "data6": 50,  "data7": 60
}
```

> **Reading hint** — twin tags share the same physical spool, so when a scale or manual edit updates `weight_available`, BOTH docs (the primary and the one referenced by `twin_tag_uid`) must be patched in a single batch with identical values. See [tigerscale.md §6](./clients/tigerscale.md).

### `users/{uid}/racks/{rackId}` — storage shelves

Each rack is a 2D grid of `level × position` slots. Spools reference racks via `inventory.{spoolId}.rack_id` + `level` + `position`.

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | ✅ | User-chosen rack label ("Atelier", "Rack 4") |
| `level` | number | ✅ | Number of shelves / rows (1–15) |
| `position` | number | ✅ | Slots per shelf / columns (1–20) |
| `order` | number | optional | Display sort order (lower = earlier) |
| `lockedSlots` | string[] | optional | Each entry `"<level>:<position>"` (e.g. `"1:3"`). Locked slots block drag-in/drag-out in the UI but are still readable. |
| `createdAt` | timestamp | ✅ | Server timestamp on creation |
| `lastUpdate` | timestamp | optional | Server timestamp on last change |

**Example doc** — `users/alice123abcDEF/racks/rack_xyz789`:

```json
{
  "name": "Atelier",
  "level": 5,
  "position": 9,
  "order": 0,
  "lockedSlots": ["1:3", "1:4", "5:9"],
  "createdAt": "2026-01-10T14:00:00.000Z",
  "lastUpdate": "2026-04-22T10:33:11.000Z"
}
```

> **For TigerScale firmware** — to display "Rack 4 · A3" on the OLED, do TWO reads: first the inventory doc to get `rack_id` + `level` + `position`, then `racks/{rack_id}` to get `name`. Cache the rack-name map on the device (5 min TTL is plenty — racks change rarely). The scale **never writes** these three fields; placement is a pure user / Studio Manager concern.

### `users/{uid}/scales/{mac}` — TigerScale heartbeats

The doc id is the ESP32's WiFi MAC address (lowercase hex, no separators, e.g. `8c4f0023a1bc`).

| Field | Type | Required | Description |
|---|---|---|---|
| `last_seen` | Firestore `serverTimestamp` | ✅ | Updated every ~30 s by the scale. Online = `now − last_seen < 60 s`. |
| `last_spool` | string \| null | ✅ | UID of the last weighed spool, or `null` when nothing on the platform |
| `fw_version` | string | ✅ | Firmware semver |
| `battery_pct` | number 0–100 | optional | If the scale is battery-powered |
| `rssi` | number (dBm) | optional | WiFi signal strength |

**Example doc** — `users/alice123abcDEF/scales/8c4f0023a1bc`:

```json
{
  "last_seen": "2026-05-02T19:45:31.000Z",
  "last_spool": "041A2B3C4D5E6F80",
  "fw_version": "1.0.3",
  "battery_pct": 87,
  "rssi": -52
}
```

Full firmware contract in [tigerscale.md](./clients/tigerscale.md). The scale never writes inventory directly — it's the desktop / mobile / Studio Manager that consume `last_seen` to render the green / red status indicator.

### `users/{uid}/friends/{friendUid}` — accepted friendships

Bidirectional: when Alice accepts Bob's request, two docs are written atomically — `users/alice/friends/bob` AND `users/bob/friends/alice`.

| Field | Type | Required | Description |
|---|---|---|---|
| `displayName` | string | ✅ | Friend's pseudo (denormalised from their `userProfiles`) |
| `addedAt` | timestamp | ✅ | When the friendship was accepted |
| `key` | string | ✅ | The **owner's own** privateKey at time of acceptance — used by Firestore Rules as a friendship capability token. |

**Example doc** — `users/alice123abcDEF/friends/bob456ghiJKL`:

```json
{
  "displayName": "Bob",
  "addedAt": "2026-02-08T17:12:00.000Z",
  "key": "ab12cd34ef567890123456789012345678901234"
}
```

> **Why the `key` field is the OWNER's privateKey, not the friend's** — when Bob reads `users/alice/inventory`, the rule checks `users/alice/friends/bob.key == users/alice.privateKey`. The check is "does this friend doc still hold a CURRENT capability for Alice?". If Alice rotates her privateKey, every friend's access is invalidated until she re-issues new friend docs.

### `users/{uid}/friendRequests/{requesterUid}` — pending invites

| Field | Type | Required | Description |
|---|---|---|---|
| `displayName` | string | ✅ | Requester's pseudo |
| `requestedAt` | timestamp | ✅ | When the request was sent |
| `key` | string | ✅ | The **requester's** privateKey, used on accept to write the bidirectional friend doc |

**Example doc** — `users/alice123abcDEF/friendRequests/bob456ghiJKL`:

```json
{
  "displayName": "Bob",
  "requestedAt": "2026-02-08T17:11:42.000Z",
  "key": "9876543210fedcba9876543210fedcba98765432"
}
```

### `users/{uid}/blacklist/{blockedUid}` — blocked users

| Field | Type | Required | Description |
|---|---|---|---|
| `displayName` | string | ✅ | Blocked user's pseudo at time of blocking |
| `blockedAt` | timestamp | ✅ | When the block was set |

**Example doc** — `users/alice123abcDEF/blacklist/spammer789xyz`:

```json
{
  "displayName": "Annoying Spammer",
  "blockedAt": "2026-03-14T22:00:00.000Z"
}
```

A blocked uid cannot send a `friendRequest` to this user (rules check). Removing from blacklist re-enables requests.

### `users/{uid}/apiKeys/{docId}` — legacy HTTP tokens

Used by older scale firmware that talks to the `setSpoolWeightByRfid` Cloud Function via HTTPS instead of authenticating to Firestore directly. New integrations should authenticate as the user (Firebase Auth) and write to Firestore directly — skip apiKeys entirely.

| Field | Type | Description |
|---|---|---|
| `keyId` | string | The 6-char API key (also used as lookup) |
| `hash` | string | SHA-256 of `keyId + salt` (verification) |
| `salt` | string | Per-key random salt |
| `scopes` | string[] | Granted scopes, e.g. `["update_weight"]` |
| `active` | boolean | Whether the key is enabled |
| `createdAt` | timestamp | Creation time |
| `lastUsedAt` | timestamp | Last use (updated by the Cloud Function) |

### `users/{uid}/printers/{brand}/devices/{deviceId}` — 3D printers

Per-brand registry of physical printers. The `{brand}` doc id is a fixed literal:

| `{brand}` | Used by | Connection |
|-----------|---------|------------|
| `bambulab` | Bambu Lab printers (X1C, P1S, A1, …) | MQTT (LAN broker) |
| `creality` | Creality K-series, Hi, etc. | WebSocket (Klipper / Moonraker) |
| `elegoo` | Elegoo Centauri, etc. | MQTT |
| `flashforge` | FlashForge Adventurer-series, etc. | HTTP polling |
| `snapmaker` | Snapmaker WebSocket-capable models | WebSocket |

Common fields on every device doc:

| Field | Type | Description |
|---|---|---|
| `id` | string | Same as the doc id |
| `printerName` | string | User label ("Living-room X1C") |
| `printerModelId` | string \| null | FK into `printers/<brand>_printer_models.json` (mobile bundle) |
| `isActive` | boolean | Whether this printer is the currently-selected one in the UI |
| `updatedAt` | number | Last change, Unix ms |
| `sortIndex` | number | (bambulab only) display order |

Brand-specific extras:

| Brand | Extra fields |
|-------|--------------|
| **bambulab** | `broker` (MQTT host / IP), `serialNumber`, `password` (MQTT access code) |
| **creality** | `ip`, `account`, `password` (HTTP Basic auth for WS) |
| **elegoo** | `ip`, `sn` (serial), `mqttPassword` (optional, falls back to default) |
| **flashforge** | `ip`, `serialNumber`, `password` |
| **snapmaker** | `ip` |

**Example doc** — `users/alice123abcDEF/printers/bambulab/devices/01S00C123456`:

```json
{
  "id": "01S00C123456",
  "printerName": "Atelier X1C",
  "printerModelId": "x1-carbon",
  "isActive": true,
  "updatedAt": 1735851000000,
  "sortIndex": 0,
  "broker": "192.168.1.42",
  "serialNumber": "01S00C123456",
  "password": "12345678"
}
```

### `users/{uid}/prefs/app` — user preferences

| Field | Type | Required | Description |
|---|---|---|---|
| `lang` | string | optional | Language code: `"en"`, `"fr"`, `"de"`, `"es"`, `"it"`, `"pl"`, `"pt"`, `"pt-pt"`, `"zh"` |

**Example doc** — `users/alice123abcDEF/prefs/app`:

```json
{
  "lang": "fr"
}
```

### `users/{uid}/uidMigrationMap/{decimal_uid}` — legacy-to-canonical UID lookup table

Across the TigerTag stack, RFID UIDs are moving from a **decimal big-endian string** representation (legacy, written by older mobile-app versions) to a **hex uppercase, no-separators** representation (canonical, going forward). Both forms encode the same integer value — `"8307741719072896"` and `"1D895E7C004A80"` decode to the same number — so the choice is representational, not data.

This sub-collection is the **bridge**. Whenever a client that has write access (Tiger Studio Manager today, the new mobile app version once deployed, or any third-party integrator that opts in) sees a decimal-format `inventory/{spoolId}` doc, it migrates the doc to the hex form and writes a corresponding entry here so any other client still holding the old decimal id can resolve it.

#### Doc id

The doc id is the **legacy decimal UID** of the spool, exactly as it appeared on the original inventory doc id (e.g. `"8307741719072896"`).

#### Fields

| Field | Type | Required | Description |
|---|---|---|---|
| `hex_uid` | string | ✅ | The hex uppercase UID that now serves as the new `inventory/{spoolId}` doc id (e.g. `"1D895E7C004A80"`). |
| `migrated_at` | Firestore `Timestamp` | ✅ | Server timestamp when the migration was committed. |
| `migrated_by` | string | optional | Identifier of the client that did the migration — e.g. `"studio-manager"`, `"mobile-app-v2.3"`. Useful for audit. |

#### Example

```json
users/alice123abcDEF/uidMigrationMap/8307741719072896
{
  "hex_uid":     "1D895E7C004A80",
  "migrated_at": "2026-05-03T10:23:11.000Z",
  "migrated_by": "studio-manager"
}
```

#### Reading flow for clients still holding a decimal id

```
1. Try GET users/{uid}/inventory/{decimal_uid}
   ↳ found → use it directly (the user hasn't been migrated yet)
   ↳ 404   → continue

2. GET users/{uid}/uidMigrationMap/{decimal_uid}
   ↳ returns { hex_uid: "..." }
   ↳ 404 → the spool truly does not exist for this user, surface as
           "unknown UID" in your client

3. GET users/{uid}/inventory/{hex_uid}
   ↳ returns the spool data
```

Cost: 2 extra reads per resolution when the doc has been migrated (one 404 + one map lookup). Once your client has been updated to write hex directly, this fallback path is dead code and can be removed in a future release.

#### Migration responsibility — shared across clients

The same algorithm runs in **every TigerTag client that has write access to a user's inventory**:

- **Tiger Studio Manager** (desktop) — runs lazily on every inventory snapshot, drains a queue with ~200 ms politeness gap, idempotent. Implementation: see `maybeMigrateDecimalSpoolIds()` in `renderer/inventory.js`.
- **Mobile app v2+** (post-migration release) — same algorithm, ported.
- **TigerScale firmware** — only writes hex; for any legacy decimal doc it encounters during a weight update, it can rely on Studio / mobile to do the migration later, or do its own atomic rename when it has confidence in the data.
- **Third-party integrations** with write access can opt in but it's not required — they can simply use the read fallback chain above without ever migrating.

Each client follows the same atomic-batch pattern, so concurrent migrations from different devices converge to the same hex doc id with the same data:

```
Atomic batch (one per spool):
  1. SET    inventory/{hex_uid}            = data (with merge:true so a
                                              concurrent partial-stub from
                                              another client doesn't wipe
                                              fields we already migrated)
  2. SET    uidMigrationMap/{decimal_uid}  = { hex_uid, migrated_at, migrated_by }
  3. UPDATE inventory/{T}.twin_tag_uid     = hex_uid
            (for every doc T whose twin_tag_uid currently points at decimal_uid)
  4. DELETE inventory/{decimal_uid}
```

#### Read access — owner + friends

The Firestore Security Rule for this collection grants **read** access to:

- The owner (`isOwner()`)
- Any accepted friend (`exists(users/{userId}/friends/{request.auth.uid})`)

A friend may have a stale decimal UID in their cache (from a past inventory snapshot of the owner) and need to resolve it. **Write** access is owner-only.

---

## Field semantics — important nuances

### `inventory.{spoolId}.deleted`
Soft-delete flag. Mobile and desktop apps **only honour `deleted: true`** — they do NOT fall back to checking `deleted_at`. Filter client-side with `if (deleted === true) hide`. To restore, set `deleted: null` (or `false`) and clear `deleted_at`.

### `inventory.{spoolId}.weight_available`
NET filament weight in grams. Updated by:
- TigerScale firmware (writes via authenticated Firebase Auth session as the owner)
- Desktop app slider (debounced 500 ms then writes)
- HTTP Cloud Function `setSpoolWeightByRfid` (legacy, by RFID UID + API key)

When updating manually, also update `last_update = Date.now()`.

### `inventory.{spoolId}` `level` / `position` / `rack_id`
1-indexed shelf row + slot column. The rack itself defines the grid (`racks.{rackId}.level` × `.position` = total slots). To convert to a human-readable position: row 1→A, 2→B, …; column stays as a number → `"A3"`, `"B5"`, etc.

### `racks.{rackId}.lockedSlots`
Stored as `"<level>:<position>"` string array (e.g. `["1:3", "1:4"]`). Locked slots block drag-in/drag-out in the UI but allow read.

<a id="data1-data7--print-parameters"></a>
### `inventory.{spoolId}` `data1` – `data7` — print parameters

Seven generic numeric slots that the TigerTag firmware encodes onto the RFID chip and that Studio Manager / the mobile app render as filament print parameters. They have a **fixed semantic mapping** — don't confuse the slot index with the parameter:

| Field | Semantic | Type | Example value | Resolved as / displayed in UI |
|---|---|---|---|---|
| `data1` | **Filament diameter** — foreign key into [`id_diameter.json`](https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_diameter.json) | number (id) | `1` (= 1.75 mm) | `"1.75 mm"` after lookup |
| `data2` | **Nozzle temperature minimum** | number (°C) | `200` | `"200–230 °C"` (joined with `data3`) |
| `data3` | **Nozzle temperature maximum** | number (°C) | `230` | (joined with `data2`, see above) |
| `data4` | **Drying / annealing temperature** | number (°C) | `60` | `"60 °C"` |
| `data5` | **Drying duration** | number (hours) | `8` | `"8 h"` |
| `data6` | **Bed temperature minimum** | number (°C) | `50` | `"50–60 °C"` (joined with `data7`) |
| `data7` | **Bed temperature maximum** | number (°C) | `60` | (joined with `data6`, see above) |

**Conventions**

- All seven fields are **optional** — older RFID chips may not carry every value. Treat any missing or `0` as "not set" and fall back to the recommendation table embedded in `id_material.json` if you need a default.
- Values are **plain numbers**, not strings — never write `"200"`, write `200`.
- Temperatures are **°C**. Time is **hours**.
- Only `data1` is a foreign key (into `id_diameter.json`); `data2`–`data7` are direct numeric values.

**Why generic `dataN` slots and not named fields?**

The RFID chip encodes a fixed binary layout that pre-dates the Firestore mirror — the seven numeric slots map 1-to-1 onto offsets `data1`…`data7` in the tag payload. Renaming them to `nozzle_temp_min` / `bed_temp_max` / etc. on the Firestore side would have meant maintaining a separate mapping table. Keeping the wire-level names lets a low-level RFID dump and the cloud doc be diffed byte-for-byte.

**Studio Manager rendering** ([`renderer/inventory.js:466`](https://github.com/TigerTag-Project/TigerTag_Studio_Manager/blob/main/renderer/inventory.js))

```js
diameter: diamLabel(data.data1),       // "1.75 mm"
temps: {
  nozzleMin: data.data2 || null,        // 200
  nozzleMax: data.data3 || null,        // 230
  dryTemp:   data.data4 || null,        // 60
  dryTime:   data.data5 || null,        // 8
  bedMin:    data.data6 || null,        // 50
  bedMax:    data.data7 || null,        // 60
}
```

If you're a third-party integrator, adopt the same mapping verbatim; both the Studio and the mobile app already follow it, so any deviation produces inconsistencies in what the user sees across surfaces.

### Lookup tables (NOT in Firestore)
Brand, material, type, etc. IDs resolve via static JSON files bundled with each client. Source of truth:

```
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_brand.json
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_material.json
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_aspect.json
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_type.json
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_diameter.json
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_measure_unit.json
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/container_spool/spools_filament.json
```

Bundle these at build time, refresh weekly. They are immutable across users.

---

## ⚠️ Sensitive fields — third-party clients

| Brand | Sensitive fields |
|-------|------------------|
| bambulab | `password`, `serialNumber` |
| creality | `account`, `password` |
| elegoo | `mqttPassword`, `sn` |
| flashforge | `password`, `serialNumber` |
| snapmaker | _(none)_ |
| _all users_ | `users/{uid}.privateKey` (40-char hex friendship capability) |

### Why these fields are dangerous

These are **not** Firebase tokens — they are the equivalent of a Wi-Fi password for the printer itself, or in the case of `privateKey` the master capability that grants friend-tier access to your inventory. Anyone holding a `password` + `broker`/`ip` pair can, on the user's LAN:

- Connect directly to the printer's MQTT / WebSocket / HTTP control endpoint
- Start, pause, or cancel a print
- Change bed / nozzle temperature
- Send arbitrary G-code (which can physically damage the machine)

The Firebase auth + Firestore Rules protect the **data at rest**. Nothing protects the data **once your client has read it** — it's your job to keep it inside your process and never leak it.

### The classic trap

A common mistake when wiring up a Home Assistant entity:

```python
class PrinterSensor(SensorEntity):
    @property
    def extra_state_attributes(self):
        return self._raw_doc        # ← BOOM
```

Now every Firestore field is exposed on the entity, including the password. That data automatically flows into:

- The **HA frontend** — anyone with dashboard access sees it
- The **HA logs** — frequently shared on forums when debugging
- The **HA REST API** — any add-on or external app reads it
- **Backups** — uploaded to Nabu Casa / cloud / external drives
- **Automation templates / notifications** — can leak via Telegram, email, etc.

A user who pastes a debug log on a forum, or a stolen backup, instantly exposes the printer-control credentials to anyone on the same network.

### Rules for third-party clients

- ✅ **READ these fields** if and only if you actually need to connect to the printer on the user's behalf.
- ✅ **Hold them in process memory** for the lifetime of the connection, then discard.
- ❌ **NEVER include them in entity attributes**, sensor states, log lines, error messages, status dashboards, or any value the user can `print()`.
- ❌ **NEVER transmit them outside the user's local network** — not to your cloud, not in telemetry, not in automatic bug reports. If you ship metrics or crash dumps, redact these keys before sending.
- ❌ **NEVER store them in plaintext config files** — for HA specifically, this means **don't** drop them in `configuration.yaml`. Always use a `ConfigEntry` (`hass.config_entries.async_update_entry(...)`), which is written to `.storage/core.config_entries` and encrypted at rest on HA OS.
- ❌ **NEVER read them on a friend's account.** The rules make this impossible (`printers` is owner-only) but be defensive — log a clear error rather than blindly retrying.

### If you only need to LIST printers

For a dashboard that just shows *"User has 3 printers: Atelier X1C, Salon K2, Garage AD5M"*, **you don't need any sensitive field**. Project to a safe subset before processing:

```python
SAFE_FIELDS = {"id", "printerName", "printerModelId", "isActive", "updatedAt", "sortIndex"}

def list_printers_safely(brand_collection):
    safe = []
    for doc in brand_collection:
        safe.append({k: v for k, v in doc.items() if k in SAFE_FIELDS})
    return safe
```

If the secrets never enter your client's address space, they can't leak.

---

## Common reads

### List own spools
```
GET /v1/projects/{projectId}/databases/(default)/documents/users/{myUid}/inventory
```

### List own racks
```
GET /v1/projects/{projectId}/databases/(default)/documents/users/{myUid}/racks
```

### List own scales
```
GET /v1/projects/{projectId}/databases/(default)/documents/users/{myUid}/scales
```

### List friends
```
GET /v1/projects/{projectId}/databases/(default)/documents/users/{myUid}/friends
```
Each doc id = friend's uid.

### Read a friend's spools (read-only access via Security Rules)
```
GET /v1/projects/{projectId}/databases/(default)/documents/users/{friendUid}/inventory
```
Authorization is YOUR token. Firestore rules check:
`exists(users/{friendUid}/friends/{yourUid})` AND that doc's `key` field equals `users/{friendUid}.privateKey`.

### Look up a friend by their public code (`XXX-XXX`)
```
GET /v1/projects/{projectId}/databases/(default)/documents/publicKeys/{XXX-XXX}
```
Returns `{ uid: "..." }` or 404.

### Read a public profile
```
GET /v1/projects/{projectId}/databases/(default)/documents/userProfiles/{otherUid}
```
Always readable by signed-in users — no friendship check.

### Live-subscribe to your own inventory (recommended)
Use the Firebase JS SDK or any client library with `onSnapshot()` so the UI updates instantly when a scale writes a new weight, instead of polling.

---

## Common writes (owner only)

| Operation | Path | Example payload |
|-----------|------|-----------------|
| Update spool weight | `users/{me}/inventory/{spoolId}` | `PATCH { weight_available: 247.3, last_update: 1735851623000 }` |
| Place a spool on a rack | `users/{me}/inventory/{spoolId}` | `PATCH { rack_id: "rack_xyz789", level: 2, position: 3, last_update: <ms> }` |
| Soft-delete a spool | `users/{me}/inventory/{spoolId}` | `PATCH { deleted: true, deleted_at: <ms> }` |
| Create a rack | `users/{me}/racks/{newId}` | `SET { name: "Atelier", level: 5, position: 9, order: 0, createdAt: serverTimestamp() }` |
| TigerScale heartbeat | `users/{me}/scales/{mac}` | `SET (merge:true) { last_seen: serverTimestamp(), last_spool: "<UID>", fw_version: "1.0.3" }` |
| Send friend request | `users/{them}/friendRequests/{me}` | `SET { displayName: "<my pseudo>", requestedAt: serverTimestamp(), key: "<my privateKey>" }` |

**You can only write to your own data** (and to `users/{them}/friendRequests/{me}` per the rules). Even if you have read access to a friend's inventory, writes to `users/{friendUid}/...` other than the friend-request path will be rejected.

---

## See also

- [01 — Firebase config](./01-firebase-config.md) — how to fetch the public Firebase init blob.
- [02 — Authentication](./02-authentication.md) — Firebase Auth flow for end-user clients.
- [04 — Friend system](./04-friend-system.md) — full state machine of friend requests, accepts, rotation.
- [05 — Rate limiting](./05-rate-limiting.md) — quotas + "be polite" guidelines.
- [clients/tigerscale.md](./clients/tigerscale.md) — TigerScale ESP32 firmware contract (heartbeat + weight write + twin tags).
- [rules/firestore.rules](../rules/firestore.rules) — public mirror of the deployed Firestore Security Rules.
