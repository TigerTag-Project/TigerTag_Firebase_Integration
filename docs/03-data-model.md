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

| Brand | Sensitive fields |
|-------|------------------|
| bambulab | `password`, `serialNumber` |
| creality | `account`, `password` |
| elegoo | `mqttPassword`, `sn` |
| flashforge | `password`, `serialNumber` |
| snapmaker | _(none)_ |

#### Why these fields are dangerous

These are **not** Firebase tokens — they are the equivalent of a Wi-Fi
password for the printer itself. Anyone holding a `password` + `broker`/`ip`
pair can, on the user's LAN:

- Connect directly to the printer's MQTT / WebSocket / HTTP control endpoint
- Start, pause, or cancel a print
- Change bed / nozzle temperature
- Send arbitrary G-code (which can physically damage the machine)

The Firebase auth + Firestore Rules protect the **data at rest**. Nothing
protects the data **once your client has read it** — it's your job to keep
it inside your process and never leak it.

#### The classic trap

A common mistake when wiring up a Home Assistant entity:

```python
class PrinterSensor(SensorEntity):
    @property
    def extra_state_attributes(self):
        return self._raw_doc        # ← BOOM
```

Now every Firestore field is exposed on the entity, including the password.
That data automatically flows into:

- The **HA frontend** — anyone with dashboard access sees it
- The **HA logs** — frequently shared on forums when debugging
- The **HA REST API** — any add-on or external app reads it
- **Backups** — uploaded to Nabu Casa / cloud / external drives
- **Automation templates / notifications** — can leak via Telegram, email, etc.

A user who pastes a debug log on a forum, or a stolen backup, instantly
exposes the printer-control credentials to anyone on the same network.

#### Rules for third-party clients

- ✅ **READ these fields** if and only if you actually need to connect to
  the printer on the user's behalf.
- ✅ **Hold them in process memory** for the lifetime of the connection,
  then discard.
- ❌ **NEVER include them in entity attributes**, sensor states, log lines,
  error messages, status dashboards, or any value the user can `print()`.
- ❌ **NEVER transmit them outside the user's local network** — not to your
  cloud, not in telemetry, not in automatic bug reports. If you ship metrics
  or crash dumps, redact these keys before sending.
- ❌ **NEVER store them in plaintext config files** — for HA specifically,
  this means **don't** drop them in `configuration.yaml`. Always use a
  `ConfigEntry` (`hass.config_entries.async_update_entry(...)`), which is
  written to `.storage/core.config_entries` and encrypted at rest on HA OS.
- ❌ **NEVER read them on a friend's account.** The rules make this
  impossible (`printers` is owner-only) but be defensive — log a clear
  error rather than blindly retrying.

#### If you only need to LIST printers

For a dashboard that just shows *"User has 3 printers: Atelier X1C, Salon
K2, Garage AD5M"*, **you don't need any sensitive field**. Project to a
safe subset before processing:

```python
SAFE_FIELDS = {"id", "printerName", "printerModelId", "isActive", "updatedAt", "sortIndex"}

def list_printers_safely(brand_collection):
    safe = []
    for doc in brand_collection:
        safe.append({k: v for k, v in doc.items() if k in SAFE_FIELDS})
    return safe
```

If the secrets never enter your client's address space, they can't leak.

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
