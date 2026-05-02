# TigerScale — Firestore integration contract

This document is the **authoritative contract** for any TigerScale (or TigerScale-compatible) device that reports filament weights into the TigerTag Firebase project. Following this contract guarantees plug-and-play interoperability with **TigerTag Studio Manager** (desktop) and the **TigerTag mobile app**, both of which read these values in read-only mode through real-time Firestore listeners.

If your firmware respects every rule below, your scale will appear in the user's UI with a green "online" indicator, the displayed remaining weight will update live as the user puts a spool on the platform, and twin-tag spools will stay perfectly in sync without any manual intervention.

---

## 1. TL;DR

The scale writes **directly into Firestore** as the authenticated owner. There is **no Cloud Function** involved on the heartbeat / weight write path — neither now nor planned. (Some legacy HTTP endpoints exist for API-key-based weight updates, but the canonical path is direct Firestore.)

Two writes to perform:

1. **Heartbeat** every 30 s → `users/{uid}/scales/{mac}`
2. **Weight update** on every stable RFID + weight reading → `users/{uid}/inventory/{spoolId}` (and its twin doc, if applicable)

Both writes happen as the authenticated user. Firestore Security Rules grant `read, write` on these two paths only to the document owner — any third party gets denied at the rules layer.

---

## 2. Architecture

```
                  ┌─────────────────────────────────────┐
                  │ Firestore (tigertag-connect)        │
                  │                                     │
                  │  users/{uid}/                       │
   ┌────────┐     │    scales/{mac}      ◀──── heartbeat
   │ESP32   │     │    inventory/{tag1} ◀──── weight + twin
   │scale   │────▶│    inventory/{tag2} ◀──── weight + twin
   │(client)│     │                                     │
   └────────┘     └─────────────────┬───────────────────┘
                                    │ onSnapshot listeners
                                    ▼
                       ┌─────────────────────────┐
                       │ TigerTag Studio Manager │  (read-only)
                       │ TigerTag mobile app     │  (read + manual edit)
                       └─────────────────────────┘
```

The scale is **purely a writer**. The Studio and the mobile app are **listeners** — they re-render their UI within ~50 ms of any Firestore write.

---

## 3. Authentication

The ESP32 must authenticate to Firebase Auth as the owner of the inventory it writes to. Any standard Firebase Auth method works (email/password, Google sign-in token, Apple sign-in token), but the recommended flow for an embedded scale is:

1. **Pairing** (one-time, via the mobile app or a setup web page served by the ESP32): the user signs in with their TigerTag credentials, the firmware obtains an `idToken` + `refreshToken`, and stores `refreshToken` + `uid` + `projectId` in NVS.
2. **Boot** (every cold start): exchange `refreshToken` against `https://securetoken.googleapis.com/v1/token` to get a fresh `idToken` (valid 1 h).
3. **Loop**: refresh `idToken` every ~55 min or whenever a Firestore call returns 401.

Once authenticated, the `idToken` goes into the `Authorization: Bearer …` header of every Firestore REST request, or is consumed by your Firebase SDK of choice.

The Firebase project config (apiKey, projectId, etc.) is published at **`https://tigertag-cdn.web.app/__/firebase/init.json`** — fetch it once and cache it. The `apiKey` is intentionally public; security is enforced by Firestore Rules + per-user authentication.

---

## 4. Heartbeat document

### Path
```
users/{uid}/scales/{mac}
```

- `{uid}` — Firebase Auth UID of the owner (the user logged in on the scale).
- `{mac}` — the ESP32's WiFi MAC address, lowercase, **no separators**. Example: `8c4f0023a1bc`.

### Payload
```json
{
  "last_seen":   <serverTimestamp>,
  "last_spool":  "041A2B3C4D5E6F80",
  "fw_version":  "1.0.3",
  "battery_pct": 87,
  "rssi":        -52
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `last_seen` | Firestore `serverTimestamp` | ✅ | Use `FieldValue.serverTimestamp()` so clock skew on the ESP32 doesn't matter. |
| `last_spool` | string \| null | ✅ | UID of the last weighed spool, or `null` when nothing has been weighed since boot. |
| `fw_version` | string | ✅ | Firmware version, semantic versioning recommended. |
| `battery_pct` | number 0–100 | optional | Only if the scale is battery-powered. |
| `rssi` | number (dBm) | optional | WiFi signal strength. |

### Cadence

- **Idle (no spool on platform)**: every **30 s**.
- **Right after a weight write**: send a heartbeat too, so the UI updates `last_seen` within the same render pass.
- **On wake from deep-sleep**: send a heartbeat as the first network call.

### Why it matters

TigerTag Studio Manager and the mobile app both display a "scale connected" indicator computed as:

```
isOnline = (Date.now() - last_seen.toMillis()) < 60_000
```

If you skip heartbeats, the indicator goes red after 60 s of silence even if your weight writes are working perfectly. The cadence of 30 s gives one full grace period before the user sees a disconnect badge.

### Write mode

Always **`set({ ... }, { merge: true })`**, never `set()` without merge. This way, optional fields you don't always send (`battery_pct`, `rssi`) keep their last known value if the scale stops reporting them temporarily.

---

## 5. Weight update document

This is the high-traffic path. Read it carefully.

### Path
```
users/{uid}/inventory/{spoolId}
```

- `{spoolId}` — **the RFID tag UID, formatted as uppercase HEX, no separators**. Example: `041A2B3C4D5E6F80`. The Firestore document ID *is* the tag UID — there is no extra mapping table.

### Fields the scale must write

```json
{
  "weight_available": 247.3,
  "last_update":      1735851623000
}
```

| Field | Type | Format | Notes |
|---|---|---|---|
| `weight_available` | number | grams, **net** | Filament remaining = raw scale reading − container weight. Always ≥ 0. |
| `last_update` | number | Unix milliseconds | `Date.now()` in JavaScript or `millis() + ntp_offset_ms` on ESP32. **NOT** seconds, **NOT** ISO-8601, **NOT** a Firestore Timestamp — it must be a plain number in ms. |

⚠️ **Do NOT touch any other field** — `weight`, `measure_gr`, `container_weight`, `id_brand`, `online_color_list`, `TD`, etc. are written by the mobile app or by the initial tag encoding flow. The scale's job is strictly weight + timestamp.

### Computing `weight_available`

The container weight (empty spool weight + tare) is **already stored in the doc** under `container_weight`. The scale must read the doc first, then write back:

```
raw_grams        = load_cell.read()
container_weight = doc.container_weight  ← read from Firestore
weight_available = max(0, raw_grams - container_weight)
```

Edge cases:
- If `container_weight` is missing or 0: `weight_available = raw_grams` (no tare to subtract).
- If `measure_gr` is set and `weight_available > measure_gr`: clamp to `measure_gr` (the spool can't physically hold more than its design capacity).
- Otherwise clamp to `[0, 100000]` as a sanity bound.

Round to 1 decimal place (`247.3`, not `247.34281`) — Firestore stores doubles, but the UI rounds to 1 decimal anyway, and excess precision wastes write bandwidth.

### When to write

Only on a **stable** measurement. Rule of thumb: write once when the reading has stayed within ±1 g for ≥ 2 s after a tag was placed on the platform. Don't stream every cell-load sample — that floods Firestore and hits free-tier quotas fast.

---

## 6. Twin tags — the rule that matters most

A single physical filament spool can carry **two RFID stickers** (typically: one TD1 inner tag + one TigerTag outer tag, or one factory-encoded tag + one user-replacement tag). In Firestore, each tag is its **own** `inventory` document, but the two are linked via the `twin_tag_uid` field:

```
inventory/041A...80   { uid: "041A...80", twin_tag_uid: "0B2C...A1", weight_available: 247.3, ... }
inventory/0B2C...A1   { uid: "0B2C...A1", twin_tag_uid: "041A...80", weight_available: 247.3, ... }
```

Both docs represent **the same physical spool**, so they MUST always carry the same `weight_available` and the same `last_update`. The scale is responsible for keeping that invariant.

### What the scale must do, by case

| Tags read on the platform | What to write |
|---|---|
| **0 tags** | Nothing in `inventory`. Send a heartbeat with `last_spool: null`. |
| **1 tag — A** | Read `inventory/A`. If `A.twin_tag_uid` is set and non-null → **batch update both docs** (`A` and `A.twin_tag_uid`) with the same payload. If no twin → update `A` only. |
| **2 tags — A and B** | See the decision matrix in §6.1 below. The two tags may or may not already be paired in Firestore. The scale repairs the linkage when it can. |

### 6.1 Decision matrix when 2 tags are detected

This is the **twin-pair self-healing** logic. The scale physically sees two tags within RFID range simultaneously, which is strong evidence that they belong to the same spool. It uses that evidence to repair missing or asymmetric `twin_tag_uid` links in Firestore.

Read both `inventory/A` and `inventory/B` first, then:

| `A.twin_tag_uid` | `B.twin_tag_uid` | Diagnosis | Action |
|---|---|---|---|
| `B` | `A` | ✅ Already paired correctly | Write `weight_available` + `last_update` on both. |
| `B` | `null` or missing | ⚠️ Asymmetric link — B forgot its partner | Write `weight_available` + `last_update` on both **AND** add `twin_tag_uid: "A"` on `B`. |
| `null` or missing | `A` | ⚠️ Asymmetric link — A forgot its partner | Write `weight_available` + `last_update` on both **AND** add `twin_tag_uid: "B"` on `A`. |
| `null` or missing | `null` or missing | 🆕 Brand-new pair discovered | Write `weight_available` + `last_update` on both **AND** set `twin_tag_uid: "B"` on `A` and `twin_tag_uid: "A"` on `B`. |
| `C` (some other UID) | `*` | 🚨 Conflict — A is already paired to a third tag C | **Do NOT touch `twin_tag_uid` on either doc.** Only update weight on `A` and skip `B`. Log a `device_log` warning entry so the user can resolve manually in the app. |
| `*` | `C` (some other UID) | 🚨 Same conflict, mirror | Same: don't write twin_tag_uid, update weight on `B` only, log warning. |

### 6.2 What "weight + last_update" means in batch context

In every twin update, the **identical payload** goes to both docs. Example for the asymmetric case:

```js
const ts = Date.now();
const payload = {
  weight_available: 247.3,
  last_update: ts
};

const batch = db.batch();
batch.update(`users/${uid}/inventory/${A}`, payload);
batch.update(`users/${uid}/inventory/${B}`, { ...payload, twin_tag_uid: A });
batch.commit();
```

The `last_update` value MUST be the same on both docs. Don't re-call `Date.now()` between the two updates — generate it once and reuse. Studio Manager uses `last_update` to decide which side is "fresher" in some animations; if the two values differ by even 1 ms, the UI may briefly show a flicker.

### 6.3 Two SEPARATE spools on the platform

If the scale detects two tags `A` and `B` and **neither is the twin of the other** (i.e., they reference different `twin_tag_uid` or none, but not each other), this means **two different physical spools** are sitting on the platform at the same time. The load cell measures the sum, so the scale **cannot attribute a per-spool weight**.

In that case:
- **Do NOT write any weight update.**
- Send a heartbeat with `last_spool: null` and an optional `multi_spool_warning: true` field.
- Optionally: log a `users/{uid}/deviceLogs` entry so the user knows the scale saw an ambiguous reading.

The user is expected to remove one spool to get an unambiguous measurement.

### 6.4 Atomic write — always use a Firestore batch

Every time you touch two docs (weight + twin or weight + twin_tag_uid repair), use a **Firestore WriteBatch** so the two writes commit together or not at all:

```cpp
// pseudocode (REST API)
PATCH https://firestore.googleapis.com/v1/projects/tigertag-connect/databases/(default)/documents:commit
Body:
{
  "writes": [
    { "update": { "name": "...inventory/A", "fields": { ... } }, "updateMask": ... },
    { "update": { "name": "...inventory/B", "fields": { ... } }, "updateMask": ... }
  ]
}
```

This guarantees that a transient WiFi loss between the two requests can't leave the twin pair in an inconsistent state.

---

## 7. Strict format reference

```json
// users/{uid}/scales/{mac}
{
  "last_seen":   <serverTimestamp>,        // Firestore FieldValue.serverTimestamp()
  "last_spool":  "041A2B3C4D5E6F80" | null, // string, uppercase hex, no separators
  "fw_version":  "1.0.3",                  // string, semver recommended
  "battery_pct": 87,                       // number 0..100, optional
  "rssi":        -52                       // number (dBm), optional
}

// users/{uid}/inventory/{spoolId}    ← spoolId = RFID UID, uppercase hex, no separators
{
  "weight_available": 247.3,        // number, grams, ≥ 0, 1 decimal max
  "last_update":      1735851623000, // number, Unix milliseconds (NOT seconds, NOT ISO)
  "twin_tag_uid":     "0B2C...A1"   // string, only ever written by the scale during twin repair (§6.1)
}
```

Type strictness checklist:
- `weight_available` MUST be a JSON `number`. Strings like `"247.3"` will break clients that do numeric formatting.
- `last_update` MUST be in **milliseconds**. The mobile app and Studio Manager parse this with `new Date(value)` — passing seconds gives them a 1970-era date.
- All UIDs (`spoolId`, `last_spool`, `twin_tag_uid`) are **uppercase HEX strings, no `:` or `-` separators**.

---

## 8. How TigerTag Studio Manager consumes these writes (read-side, for context)

You don't need to implement any of this — it's already done in the apps. But understanding what they read makes it clearer why the contract matters.

### Inventory listener
```js
db.collection("users").doc(uid).collection("inventory")
  .onSnapshot({ includeMetadataChanges: true }, snap => {
    snap.forEach(doc => {
      const d = doc.data();
      // Studio reads:
      //   d.weight_available  → fills the gauge / slider
      //   d.last_update       → "updated 3 seconds ago" badge
      //   d.twin_tag_uid      → so the Storage view shows both tags as one entity
      //   d.container_weight  → for the next "raw vs net" toggle in the panel
      //   d.measure_gr        → for the % full computation
    });
  });
```

A successful weight write from your scale propagates to the user's UI in **< 100 ms** (Firestore real-time + WebSocket). The user sees the slider move, the rack-slot fill bar redraw, and the "X minutes ago" timestamp reset to "just now" — without any refresh.

### Scale listener
```js
db.collection("users").doc(uid).collection("scales").doc(mac)
  .onSnapshot(doc => {
    const s = doc.data();
    // Studio reads:
    //   s.last_seen     → online indicator (green if < 60 s)
    //   s.last_spool    → "last weighed: <UID>" tooltip
    //   s.fw_version    → shown in the diagnostics panel
    //   s.battery_pct   → battery icon if present
  });
```

### What Studio NEVER writes back to your paths
- `users/{uid}/scales/{mac}` — **read-only on Studio's side**. The scale is the sole writer.
- `users/{uid}/inventory/{spoolId}.weight_available` — Studio writes here too (manual user override via the slider), but only when the user explicitly types a value or clicks "Update". The scale's writes and Studio's manual writes both flow into the same field; whichever is most recent (by `last_update`) is what the user effectively sees.

This means: **Studio's manual edits cannot fight your scale**. If the user puts a spool on the platform after manually editing the value, the scale's write is more recent and wins. There is no edit-conflict resolution layer; last-write-wins by Firestore's natural semantics.

---

## 9. Failure modes & retries

| Symptom | Likely cause | Fix |
|---|---|---|
| `401 Unauthorized` | `idToken` expired | Refresh via `securetoken.googleapis.com` and retry. |
| `403 Permission denied` | Writing to wrong `{uid}` (not the authenticated user's path) | Check that the path's `uid` segment matches `firebase.auth().currentUser.uid`. |
| `404 Not Found` on `inventory/{spoolId}` | Tag UID not registered in this user's inventory | Skip the write, log to `deviceLogs`, and surface a "tag not registered" status in the heartbeat (`last_spool: null` + custom field `unknown_tag_uid: "..."`). |
| Twin pair never converges to same weight | One side of the batch is silently failing | Always use `WriteBatch.commit()` and check the response — if it returns an error, retry the entire batch. |
| `weight_available` shows as 0 in Studio after a successful write | You wrote a string instead of a number, or you wrote in seconds instead of ms | Verify JSON types with a Firestore data viewer (the Firebase console shows the type next to each field). |

Retry policy: exponential backoff, max 5 retries (1 s, 2 s, 4 s, 8 s, 16 s), then write the failure to `users/{uid}/deviceLogs/{auto}` with `{ ts, op, payload, error }` and move on. Don't block the heartbeat loop on a stuck weight write.

---

## 10. Summary — checklist for a compliant scale

- [ ] Authenticates via Firebase Auth as the owner; refreshes idToken every 55 min.
- [ ] Sends a heartbeat to `users/{uid}/scales/{mac}` every 30 s using `serverTimestamp()` for `last_seen`.
- [ ] Reads `inventory/{spoolId}.container_weight` before each write to compute the net weight.
- [ ] Writes `weight_available` (number, grams) and `last_update` (number, ms) — and **only** these two fields — under normal conditions.
- [ ] On twin pair detection, **batches both updates** with the same payload and same `last_update` value.
- [ ] **Self-heals missing or asymmetric `twin_tag_uid` links** when 2 tags are physically present and currently de-paired in Firestore (matrix in §6.1).
- [ ] **Refuses to write a weight** when 2 tags from 2 different spools are detected simultaneously.
- [ ] Uses Firestore `WriteBatch` for any operation that touches more than one doc.
- [ ] Backs off and logs to `deviceLogs` on persistent failure rather than retrying forever.
- [ ] Treats `users/{uid}/inventory/*` as **append-update only** for `weight_available`, `last_update`, and (during twin repair) `twin_tag_uid`. Never touches anything else.

If every box is ticked, the scale is iso-compliant with TigerTag's data model and will integrate seamlessly with Studio Manager and the mobile app on day one.
