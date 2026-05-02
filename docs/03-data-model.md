# 03 — Firestore data model

```
publicKeys/
  {XXX-XXX}/                ← discovery code (key = code, doc id is the code)
    uid           string    ← owner uid
    claimedAt     timestamp

userProfiles/                ← public-facing card (signed-in readable)
  {uid}/
    publicKey     string    ← duplicate of users/{uid}.publicKey
    displayName   string    ← user's chosen pseudo
    isPublic      boolean   ← inventory visible to ANY signed-in user
    color_r/g/b   number?   ← avatar color components (optional)

users/                       ← OWNER-ONLY (privateKey, email, full inventory)
  {uid}/
    displayName   string
    googleName    string    ← admin reference, never displayed
    firstName     string
    lastName      string
    email         string
    publicKey     string    ← discovery code
    privateKey    string    ← 40-char hex SECRET — never exposed
    isPublic      boolean
    Debug         boolean?  ← admin-only flag
    roles         string?   ← "admin" | undefined

    inventory/
      {spoolId}/
        uid               string   ← primary RFID UID
        twin_uid          string?
        id_brand          number   ← FK → id_brand.json
        id_material       number   ← FK → id_material.json
        color_name        string
        online_color_list string[] ← optional ["#000","#aaa",…]
        weight_available  number   ← grams
        container_weight  number
        capacity          number
        container_id      string   ← FK → spools_filament.json
        last_update       number   ← Unix ms
        deleted           boolean
        deleted_at        number?
        rack_id           string?  ← if assigned to a rack
        level             number?  ← shelf index (0 = bottom)
        position          number?  ← slot index (0 = leftmost)

    racks/
      {rackId}/
        name           string
        level          number      ← number of shelves (1-15)
        position       number      ← slots per shelf (1-20)
        order          number      ← display order
        lockedSlots    string[]    ← ["lv:pos", …]
        createdAt      timestamp
        lastUpdate     timestamp

    friends/
      {friendUid}/
        displayName    string
        addedAt        timestamp
        key            string      ← friend's privateKey (used by rules)

    friendRequests/
      {requesterUid}/
        displayName    string
        requestedAt    timestamp
        key            string      ← requester's privateKey

    blacklist/
      {blockedUid}/
        displayName    string
        blockedAt      timestamp

    apiKeys/
      {docId}/                     ← legacy Key6 (HTTP API)
        ...

    printers/                      ← per-brand 3D-printer registry
      {brand}/                     ← brand id (see table below)
        devices/                   ← one doc per physical printer
          {deviceId}/
            id              string
            printerName     string
            printerModelId  string?
            isActive        boolean
            updatedAt       number     ← Unix ms
            …brand-specific fields…

    prefs/
      app/
        lang           string

    scales/                        ← TigerScale heartbeats
      {mac}/
        last_seen      timestamp   ← updated every ~30s by the ESP32
        last_spool     string?     ← spoolId of the last weighed spool
        fw_version     string
        ...
```

## Field semantics

### `inventory.{spoolId}.deleted`
Soft-delete flag. Mobile and desktop apps **only honour `deleted: true`** —
they do NOT fall back to checking `deleted_at`. Filter client-side with
`if (deleted === true) hide`.

### `inventory.{spoolId}.weight_available`
Net filament weight in grams. Updated by:
- TigerScale (writes via authenticated session as the owner)
- Desktop app slider (debounced 500ms then writes)
- HTTP `setSpoolWeightByRfid` Cloud Function (legacy, by RFID UID)

When updating manually: also update `last_update = Date.now()`.

### `printers/{brand}/devices/{deviceId}`

The mobile app stores a per-brand registry of the user's 3D printers under
`users/{uid}/printers/{brand}/devices/{deviceId}`. The `{brand}` doc id is
a fixed literal — one of:

| `{brand}` | Used by | Connection |
|-----------|---------|------------|
| `bambulab` | Bambu Lab printers (X1C, P1S, A1, …) | MQTT (LAN broker) |
| `creality` | Creality K-series, Hi, etc. | WebSocket (Klipper / Moonraker) |
| `elegoo` | Elegoo Centauri, etc. | MQTT |
| `flashforge` | FlashForge Adventurer-series, etc. | HTTP polling |
| `snapmaker` | Snapmaker WebSocket-capable models | WebSocket |

Common fields on every device doc:

| Field | Type | Meaning |
|-------|------|---------|
| `id` | string | Same as the doc id, redundant for clients reading by full doc |
| `printerName` | string | User-defined label ("Living room X1C") |
| `printerModelId` | string? | FK into `assets/db/printers/{brand}_printer_models.json` (mobile bundle) |
| `isActive` | boolean | Whether this printer is the currently-selected one in the UI |
| `updatedAt` | number | Last change time, Unix ms |
| `sortIndex` | number? | (bambulab only) display order |

Brand-specific fields:

| Brand | Extra fields |
|-------|--------------|
| **bambulab** | `broker` (MQTT host / IP), `serialNumber`, `password` (MQTT access code) |
| **creality** | `ip`, `account`, `password` (HTTP Basic auth for WS) |
| **elegoo** | `ip`, `sn` (serial number), `mqttPassword` (optional, falls back to default) |
| **flashforge** | `ip`, `serialNumber`, `password` |
| **snapmaker** | `ip` |

### ⚠️ Sensitive fields — third-party clients

The following fields contain secrets that grant **direct LAN control** of the
user's 3D printer. A client that exposes them (logs, attributes, network
traces) puts the user's printer at risk of remote takeover by anyone on the
local network.

| Brand | Sensitive fields |
|-------|------------------|
| bambulab | `password`, `serialNumber` |
| creality | `account`, `password` |
| elegoo | `mqttPassword`, `sn` |
| flashforge | `password`, `serialNumber` |
| snapmaker | _(none)_ |

**Rules for third-party clients (Home Assistant, scripts, etc.):**

- ✅ **OK** to read these fields if the user is opted in and you connect to
  their printer on their behalf.
- ❌ **Never** include them in entity attributes, log lines, error messages,
  or status pages.
- ❌ **Never** transmit them outside the user's local network.
- ❌ **Never** persist them in plaintext in HA YAML / config files —
  use the integration's encrypted config entry storage.
- ❌ **Never** read them on a friend's account (the rules forbid it anyway —
  `printers` is owner-only — but be defensive).

If your integration only needs to **list** the printers (e.g. show "User
has 3 printers" in a dashboard), read just `printerName`, `printerModelId`,
`isActive`, `updatedAt` and ignore the rest.

### `racks.{rackId}.lockedSlots`
Stored as `["0:0", "0:1", "1:5", …]` strings (`"<level>:<position>"`).
Locked slots block drag-in/drag-out in the UI but allow read.

### Lookup tables (NOT in Firestore)
Brand, material, type, etc. IDs are resolved via static JSON files bundled
with each client. Source of truth:

```
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_brand.json
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_material.json
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_aspect.json
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_type.json
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_diameter.json
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_measure_unit.json
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/container_spool/spools_filament.json
```

Bundle these at build time, refresh weekly.

## Common reads

### List own spools
```
GET /v1/projects/{projectId}/databases/(default)/documents/users/{myUid}/inventory
```

### List own racks
```
GET /v1/projects/{projectId}/databases/(default)/documents/users/{myUid}/racks
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
`exists(users/{friendUid}/friends/{yourUid})` → if yes, allow.

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

## Common writes (owner only)

| Operation | Path |
|-----------|------|
| Update spool weight | `users/{me}/inventory/{spoolId}` (PATCH `weight_available` + `last_update`) |
| Soft-delete spool | same path with `deleted: true` |
| Create rack | `users/{me}/racks/{newId}` |
| Move spool to rack | `users/{me}/inventory/{spoolId}` (PATCH `rack_id` + `level` + `position`) |

**You can only write to your own data.** Even if you have read access to
a friend's inventory, writes to `users/{friendUid}/...` will be rejected.
