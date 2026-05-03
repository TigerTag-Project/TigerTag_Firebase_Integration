# TigerScale — Firestore document schema (v2)

This document is the **authoritative specification** for the shape of the Firestore document a TigerScale firmware must maintain. It complements [`tigerscale.md`](./tigerscale.md) (which covers the auth flow, weight write path, and twin-tag handling) by giving an exhaustive, field-by-field reference for the heartbeat document at:

```
users/{uid}/scales/{mac}
```

The doc id (`{mac}` segment) is the ESP32 WiFi MAC address in **lowercase hex, no separators** — e.g. `34987ab00668`.

> **Convention** — every field in this schema is documented with: type, whether it is required, who writes it (firmware vs user vs Firestore), valid value range, concrete examples, and edge cases.

---

## Table of contents

| # | Field | Type | Required |
|---|---|---|---|
| 1 | [`mac`](#1-mac) | string | ✅ |
| 2 | [`display_name`](#2-display_name) | string | ✅ |
| 3 | [`fw_version`](#3-fw_version) | string | ✅ |
| 4 | [`hardware_revision`](#4-hardware_revision) | string \| null | optional |
| 5 | [`last_heartbeat_at`](#5-last_heartbeat_at) | Firestore Timestamp | ✅ |
| 6 | [`current_spool_uid_1`](#6-current_spool_uid_1) | string \| null | ✅ |
| 7 | [`current_spool_uid_2`](#7-current_spool_uid_2) | string \| null | ✅ |
| 8 | [`wifi_signal_dbm`](#8-wifi_signal_dbm) | number \| null | optional |
| 9 | [`power_source`](#9-power_source-) ⚡ enum | string | ✅ |
| 10 | [`battery_percent`](#10-battery_percent) | number 0–100 \| null | ✅ |
| 11 | [`is_charging`](#11-is_charging) | boolean \| null | ✅ |

---

## 1. `mac`

| | |
|---|---|
| **Type** | `string` |
| **Required** | ✅ always |
| **Written by** | firmware, on every heartbeat |

WiFi MAC address of the ESP32, in **lowercase hex, no separators** — identical to the doc id.

> **Why duplicate it in the document when it's already the doc id?** So that BigQuery exports and "give me all scales" queries return self-contained documents that don't require parsing the path to recover the MAC.

**Valid examples**

```json
"mac": "34987ab00668"
"mac": "8c4f0023a1bc"
```

**Invalid examples**

```json
"mac": "34:98:7A:B0:06:68"   // separators forbidden
"mac": "34-98-7A-B0-06-68"   // idem
"mac": "34987AB00668"        // uppercase forbidden
```

---

## 2. `display_name`

| | |
|---|---|
| **Type** | `string` |
| **Required** | ✅ always |
| **Written by** | firmware (initial value at pairing), then user (via Studio / mobile app) |

Human-friendly label of the scale, what the user sees in the UI.

**Firmware convention** — on the very first write, the firmware sets `"TigerScale-XXXX"` where `XXXX` is the last 4 hex digits of the MAC, **uppercase**. If the user later renames it via the app, the firmware **MUST NOT overwrite** that custom value on subsequent heartbeats — read the field before writing, and only fill it in when empty.

**Examples**

```json
"display_name": "TigerScale-0668"   // default firmware value
"display_name": "Atelier"            // user rename
"display_name": "Cuisine 3D"         // user rename
"display_name": "Garage Bambu"       // user rename
```

---

## 3. `fw_version`

| | |
|---|---|
| **Type** | `string` (semver) |
| **Required** | ✅ always |
| **Written by** | firmware |

Firmware version, in strict SemVer (`MAJOR.MINOR.PATCH`).

**Valid examples**

```json
"fw_version": "1.0.0"
"fw_version": "1.3.0"
"fw_version": "2.0.1-beta"      // pre-release tag allowed
"fw_version": "2.1.0+build.42"  // build metadata allowed
```

---

## 4. `hardware_revision`

| | |
|---|---|
| **Type** | `string \| null` |
| **Required** | ❌ optional (recommended for support / field diagnostic) |
| **Written by** | firmware (read from NVS / efuse at boot) |

PCB revision tag. Short string defined by TigerTag.

**Examples**

```json
"hardware_revision": "R1"
"hardware_revision": "R2"
"hardware_revision": "R2.1"
"hardware_revision": "R2-evt"   // engineering verification test build
"hardware_revision": null        // unknown / not yet configured
```

> **Why a string and not a number?** Because `R2.1` or `R2-evt` are valid revisions. A string keeps the format flexible and self-documenting.

---

## 5. `last_heartbeat_at`

| | |
|---|---|
| **Type** | Firestore `Timestamp` (**not** Unix ms!) |
| **Required** | ✅ always |
| **Written by** | firmware via `serverTimestamp()` / `{ "timestampValue": "REQUEST_TIME" }` (REST) |
| **Cadence** | every 30 s while idle, immediately after every weighing |

This is what TigerTag Studio Manager and the mobile app use to decide if the scale is online vs offline:

```js
isScaleOnline(s) → (Date.now() - last_heartbeat_at.toMillis()) < 90_000
```

**⚠️ NEVER use a local timestamp** (`millis()`, `time(NULL) * 1000`, etc.). The ESP32 clock drifts if NTP is not synchronised, and the scale will appear offline even though it pings correctly. Always let Firestore stamp the time on its own server clock.

**Firestore SDK format**

```js
firebase.firestore.FieldValue.serverTimestamp()
```

**Firestore REST format**

```json
"last_heartbeat_at": { "timestampValue": "REQUEST_TIME" }
```

**Example as read by clients** (Firestore returns ISO 8601):

```json
"last_heartbeat_at": "2026-05-03T00:42:50.123Z"
```

---

## 6. `current_spool_uid_1`

| | |
|---|---|
| **Type** | `string \| null` |
| **Required** | ✅ always present (may be `null`) |
| **Written by** | firmware on every RFID scan cycle (~1–2 Hz) |
| **Value format** | RFID UID in **hex uppercase, no separators** — the new canonical format. See [§ UID format](#-uid-format-hex-canonical-decimal-legacy) below for the read-fallback policy that keeps the firmware compatible with the decimal-format docs already in production. |

UID of the **first** RFID tag detected on the platform, or `null` if nothing.

**Examples**

```json
"current_spool_uid_1": "1D895E7C004A80"      // tag present (hex uppercase, no separators)
"current_spool_uid_1": null                   // platform empty
```

> **⚠️ Always treat the UID as an opaque string** for serialization. Even though it looks like a number when written in decimal, never call `Number(uid)` or `parseInt(uid)` — 7-byte UIDs exceed `Number.MAX_SAFE_INTEGER` (2⁵³ − 1) and would silently lose precision. Hex strings sidestep this trap entirely.

---

## 7. `current_spool_uid_2`

| | |
|---|---|
| **Type** | `string \| null` |
| **Required** | ✅ always present (may be `null`) |
| **Written by** | firmware |
| **Value format** | same as `current_spool_uid_1` (hex uppercase, no separators) |

UID of a **second** RFID tag detected at the same time. This handles the twin-tag case (one physical spool with two RFID stickers — e.g. an inner TD1 + an outer TigerTag) AND the "two spools on the platform simultaneously" case.

### Filling rules

| Tags physically detected | `current_spool_uid_1` | `current_spool_uid_2` |
|---|---|---|
| 0 (empty platform) | `null` | `null` |
| 1 tag | UID of the tag | `null` |
| 2 tags | UID of the first tag | UID of the second tag |

> **Which is the "first" vs the "second"?** No semantic ordering — it's the order in which the RFID reader picked them up, which can vary between scans. Studio Manager and the mobile app treat `_1` and `_2` as an unordered set. To distinguish a twin pair (same physical spool) from two separate spools, the client checks whether one is listed in the other's `twin_tag_uid` field on the inventory document. See [`tigerscale.md §6`](./tigerscale.md) for the full decision matrix.

---

## 🔑 UID format — hex (canonical), decimal (legacy)

### Two formats coexist in the database — and that's OK

For historical reasons, two formats coexist for RFID UIDs across the TigerTag stack:

| Format | Example | Status |
|---|---|---|
| **Hex uppercase, no separators** | `1D895E7C004A80` | ✅ **Canonical going forward** — use this for all new writes |
| **Decimal big-endian, as string** | `8307741719072896` | ⚠️ **Legacy** — older inventory docs in production, still readable |

Both forms decode to the same integer value (`0x1D895E7C004A80 == 8307741719072896`), so it's a representational choice, not a data conflict. New firmware (TigerScale included) writes hex; reads tolerate both via a fallback chain.

### Why a string and not a number?

A 7-byte RFID UID can hold values up to `2⁵⁶ − 1 ≈ 7.2 × 10¹⁶`. JavaScript's `Number.MAX_SAFE_INTEGER` is `2⁵³ − 1 ≈ 9 × 10¹⁵`. Parsing a UID as a `Number` silently loses precision on long tags — two distinct tags can collide. **Always keep the UID as a string** in your firmware, your transport, and your storage. Hex strings make this almost automatic; decimal strings require discipline.

### Producing the hex form from raw RFID bytes (firmware side)

The RFID controller (PN532, MFRC522, etc.) returns the UID as a byte array. Convert to the canonical hex uppercase string:

**Pseudo-code**

```
uid_bytes = [0x1d, 0x89, 0x5e, 0x7c, 0x00, 0x4a, 0x80]   // big-endian: byte[0] is MSB
hex_str = ""
for byte in uid_bytes:
    hex_str += format(byte, "02X")     // 2 hex digits, uppercase, zero-padded
// → "1D895E7C004A80"
```

**Arduino / ESP-IDF (C++)**

```cpp
String bytesToHexUid(const uint8_t* uid_bytes, uint8_t len) {
  String out;
  out.reserve(len * 2);
  for (uint8_t i = 0; i < len; i++) {
    if (uid_bytes[i] < 0x10) out += "0";
    out += String(uid_bytes[i], HEX);
  }
  out.toUpperCase();
  return out;
}
// bytesToHexUid({0x1D, 0x89, 0x5E, 0x7C, 0x00, 0x4A, 0x80}, 7) → "1D895E7C004A80"
```

**Node.js / TypeScript**

```js
function bytesToHexUid(bytes) {
  return Buffer.from(bytes).toString('hex').toUpperCase();
}
// bytesToHexUid([0x1D, 0x89, 0x5E, 0x7C, 0x00, 0x4A, 0x80]) === '1D895E7C004A80'
```

**Python**

```py
def bytes_to_hex_uid(uid_bytes: bytes) -> str:
    return uid_bytes.hex().upper()
# bytes_to_hex_uid(bytes([0x1D, 0x89, 0x5E, 0x7C, 0x00, 0x4A, 0x80])) == '1D895E7C004A80'
```

### Converting between hex and decimal (when the firmware needs to do a fallback lookup)

```js
// Hex → decimal (BigInt-safe, no precision loss)
const decimalUid = BigInt('0x' + hexUid).toString();
// '1D895E7C004A80' → '8307741719072896'

// Decimal → hex (BigInt-safe, returns uppercase)
const hexUid = BigInt(decimalUid).toString(16).toUpperCase();
// '8307741719072896' → '1D895E7C004A80'
```

```cpp
// Arduino: uint64_t works for ≤ 8-byte UIDs, beyond that use a BigInt lib
String hexToDecimalUid(const String& hex) {
  uint64_t value = 0;
  for (char c : hex) {
    value <<= 4;
    if      (c >= '0' && c <= '9') value |= (c - '0');
    else if (c >= 'A' && c <= 'F') value |= (c - 'A' + 10);
    else if (c >= 'a' && c <= 'f') value |= (c - 'a' + 10);
  }
  return String((unsigned long long)value);
}
```

### Endianness

**Big-endian** in both formats: the first byte returned by the RFID controller is the **most significant byte**. This matches the natural reading order of a hex string (left-to-right = most-significant-to-least). Don't reverse the byte order before conversion — that would produce a different (and incorrect) value, which won't match the existing inventory doc ids in either format.

### Where each format appears in the database

| Surface | Format today | Format expected long-term |
|---|---|---|
| `users/{uid}/inventory/{spoolId}` doc id | mostly **decimal** (legacy), some **hex** (newer) | **hex** |
| `inventory.{spoolId}.uid` (denormalised field) | matches the doc id of the same doc | **hex** |
| `inventory.{spoolId}.twin_tag_uid` | matches the doc id of the twin | **hex** |
| `scales/{mac}.current_spool_uid_1` & `_2` | **hex** | **hex** |

**The only invariant clients MUST respect** is intra-pair consistency:

> For any given physical spool, its inventory doc id, its `uid` field, and any `twin_tag_uid` referencing it must all be in the **same** format.

Listing operations (`get()` on a whole inventory collection) handle mixed formats transparently — each doc is iterated regardless of its id form. The format only matters when the client needs to look up a specific doc by UID, which is exactly what the scale does on every weighing cycle.

### TigerScale lookup policy — hex first, decimal fallback

When the firmware detects an RFID tag and needs to find the matching inventory doc to read `container_weight` and the storage location (`rack.id` / `rack.level` / `rack.position` — or the legacy flat `rack_id` / `level` / `position` on older docs):

```
1. Convert the raw RFID bytes to HEX uppercase (canonical)
   hex_uid = bytesToHexUid(raw_bytes)

2. Try the canonical lookup first
   GET users/{uid}/inventory/{hex_uid}
   ↳ if found → use this doc, done

3. If 404, fall back to the legacy decimal form
   decimal_uid = BigInt('0x' + hex_uid).toString()
   GET users/{uid}/inventory/{decimal_uid}
   ↳ if found → use this doc (it's an old decimal-format entry)
                Optionally migrate it to hex (see below)

4. If both 404 → the tag is not registered for this user
   → emit "unknown_tag_uid": "{hex_uid}" in the heartbeat doc
   → surface to the user via Studio's "unknown tag" UI
```

Cost: at most **one extra read per lookup** when the doc is in legacy decimal form; zero extra reads once a doc has been migrated. After all docs migrate, the decimal fallback path becomes dead code and can be deleted in a future firmware release.

### Optional: lazy migration during fallback

If you want to actively migrate legacy decimal docs as you encounter them, the firmware can rewrite the doc with the hex id after a successful decimal lookup:

```
3'. After finding the doc at /inventory/{decimal_uid}:
    a. Read the full doc payload `data`
    b. Write a new doc at /inventory/{hex_uid} with the same `data`
       (also update `uid` and any twin's `twin_tag_uid` to hex)
    c. Delete the old doc at /inventory/{decimal_uid}
    d. Use the new (hex) doc going forward
```

This is **optional** and best done as a deliberate Cloud Function migration job rather than ad-hoc by every embedded client — the on-device version is given here for completeness, not as a recommendation. For most TigerScale firmware versions, just doing read-only fallback (steps 1–4 above) is enough.

### Always-write-in-hex policy

Whatever format the firmware reads the inventory doc in, **all writes from TigerScale go to fields formatted as HEX**:

- `current_spool_uid_1` and `current_spool_uid_2` on `scales/{mac}` → always hex
- Any future scale-initiated write (e.g. weight update on the inventory doc itself) → if it's a NEW doc, write the doc id in hex; if it's an EXISTING doc found via decimal fallback, write into that decimal doc (don't change its id mid-update — that would break twin pairing).

---

## 8. `wifi_signal_dbm`

| | |
|---|---|
| **Type** | `number \| null` |
| **Required** | ❌ optional (recommended) |
| **Written by** | firmware (`WiFi.RSSI()` on ESP-IDF / Arduino) |

WiFi RSSI in dBm. Always negative. Higher = stronger signal.

### Practical scale

| Value | Quality | Practical impact |
|---|---|---|
| ≥ -50 dBm | Excellent | no loss |
| -50 to -65 | Good | OK |
| -65 to -75 | Average | latency, occasional retries |
| -75 to -85 | Weak | frequent packet loss |
| ≤ -85 dBm | Critical | WiFi disconnects |

**Examples**

```json
"wifi_signal_dbm": -52       // strong signal
"wifi_signal_dbm": -78       // borderline
"wifi_signal_dbm": null      // older firmware / not reported
```

---

## 9. `power_source` ⚡ ENUM

| | |
|---|---|
| **Type** | `string` (enum — see allowed values below) |
| **Required** | ✅ always |
| **Written by** | firmware (determined at boot from the hardware design) |

Primary power source of the scale. **Drives whether `battery_percent` and `is_charging` are meaningful.**

### Allowed values (4)

| Value | Meaning | `battery_percent` should be… | `is_charging` should be… |
|---|---|---|---|
| `"ac"` | Plugged into a wall adapter (5 V / 12 V) — no internal battery | `null` | `null` |
| `"battery"` | Running on internal battery only (not plugged in) | `0–100` | `false` |
| `"usb"` | USB connected (data and/or charge) | `null` if no internal battery, OR `0–100` if charging | `false` or `true` |
| `"poe"` | Power over Ethernet | `null` | `null` |

> **Firmware-side detection**
> - If the board has no battery: always `"ac"`, `"usb"`, or `"poe"`
> - If the board has a battery + an external power source plugged in: choose `"battery"` (running on battery) or `"usb"` (charging) depending on the charge state
> - The firmware MUST re-evaluate `power_source` on **every heartbeat** — the user can plug or unplug while the scale is running.

### Concrete examples

**Tabletop scale, AC only (no battery in the design)**

```json
"power_source":    "ac",
"battery_percent": null,
"is_charging":     null
```

**Portable scale, on battery, unplugged**

```json
"power_source":    "battery",
"battery_percent": 87,
"is_charging":     false
```

**Portable scale, USB plugged in, charging in progress**

```json
"power_source":    "usb",
"battery_percent": 65,
"is_charging":     true
```

**Portable scale, USB plugged in, fully charged (charge stopped)**

```json
"power_source":    "usb",
"battery_percent": 100,
"is_charging":     false
```

**Industrial PoE scale**

```json
"power_source":    "poe",
"battery_percent": null,
"is_charging":     null
```

---

## 10. `battery_percent`

| | |
|---|---|
| **Type** | `number 0–100` \| `null` |
| **Required** | ✅ always present (`null` when not applicable) |
| **Written by** | firmware (read from ADC + LiPo discharge curve) |

Battery state of charge, as an **integer percentage** (no decimals).

### Filling rules

| If `power_source` is… | Then `battery_percent` is… |
|---|---|
| `"ac"` | **`null`** (no battery in the system) |
| `"battery"` | **0–100** (current discharge level) |
| `"usb"` | **`null`** if no internal battery, OR **0–100** if there is one |
| `"poe"` | **`null`** |

> **Edge case** — at boot, before the first ADC measurement is reliable, write `null`. Once a stable reading is available, switch to the actual value.

**Valid examples**

```json
"battery_percent": 100      // full
"battery_percent": 87
"battery_percent": 23       // low — Studio can show a warning badge
"battery_percent": 0        // dead (the ESP32 will shut down soon)
"battery_percent": null     // not applicable (AC / PoE)
```

**Invalid examples**

```json
"battery_percent": 200      // no magic sentinel — use power_source instead
"battery_percent": -1       // negative not allowed
"battery_percent": 87.5     // integers only
"battery_percent": "87"     // must be number, not string
```

---

## 11. `is_charging`

| | |
|---|---|
| **Type** | `boolean \| null` |
| **Required** | ✅ always present |
| **Written by** | firmware (read from the charge controller's STAT pin — TP4056, BQ24074, MAX1555, etc.) |

`true` if the battery is **actively charging** at the moment the heartbeat is written.

### Filling rules

| If `power_source` is… | Then `is_charging` is… |
|---|---|
| `"ac"` | **`null`** (no battery) |
| `"battery"` | **`false`** (running on battery — no charge source connected) |
| `"usb"` with internal battery | **`true`** (charging) or **`false`** (full or USB used for data only) |
| `"usb"` without internal battery | **`null`** |
| `"poe"` | **`null`** |

**Valid examples**

```json
"is_charging": true       // actively charging
"is_charging": false      // not charging (discharging or full)
"is_charging": null       // not applicable (no battery / PoE)
```

**Invalid examples**

```json
"is_charging": 1           // must be boolean, not number
"is_charging": "true"      // must be boolean, not string
"is_charging": 0
```

---

## 📋 Full document — fully populated example

```json
users/alice123abcDEF/scales/34987ab00668
{
  "mac":                  "34987ab00668",
  "display_name":         "TigerScale Atelier",
  "fw_version":           "1.3.0",
  "hardware_revision":    "R1",

  "last_heartbeat_at":    "2026-05-03T00:42:50.123Z",

  "current_spool_uid_1":  "1D895E7C004A80",
  "current_spool_uid_2":  null,

  "wifi_signal_dbm":      -52,

  "power_source":         "battery",
  "battery_percent":      87,
  "is_charging":          false
}
```

## 📋 Minimal document — first heartbeat after boot

When the firmware has just booted, hasn't measured the battery ADC yet, and the platform is empty:

```json
{
  "mac":                  "34987ab00668",
  "display_name":         "TigerScale-0668",
  "fw_version":           "1.3.0",
  "hardware_revision":    null,

  "last_heartbeat_at":    "<serverTimestamp>",

  "current_spool_uid_1":  null,
  "current_spool_uid_2":  null,

  "wifi_signal_dbm":      null,

  "power_source":         "battery",
  "battery_percent":      null,
  "is_charging":          null
}
```

Studio Manager handles all the `null`s gracefully — they render as `—` or fall back to muted UI defaults.

---

## 🚨 Firmware compliance checklist

Before tagging a firmware release, verify:

- [ ] `last_heartbeat_at` is **always written via `serverTimestamp()`**, never `millis()` or `time(NULL) * 1000`
- [ ] `mac` (both in the doc id and in the field) is **lowercase, no separators**
- [ ] RFID UIDs in `current_spool_uid_1` / `current_spool_uid_2` are **hex uppercase, no separators**
- [ ] `display_name` is **read before each heartbeat write** so user-renamed labels aren't overwritten
- [ ] `power_source` is **always populated, never omitted**, and re-evaluated on each heartbeat
- [ ] `battery_percent` is an integer; **no magic sentinel** like `200` is used — fall back to `null` and rely on `power_source`
- [ ] `is_charging` is a real boolean (not `0` / `1`, not `"true"`)
- [ ] All `null` values are **explicitly written as `null`** in the JSON — not omitted, not `0`, not `""`
- [ ] Heartbeat cadence is 30 s in idle, immediate after weighing
- [ ] On `display_name` first-time write, default to `"TigerScale-XXXX"` where `XXXX` = last 4 hex of the MAC, uppercase

---

## Migration note for existing firmware

If your firmware already writes the v1 schema (`name`, `last_seen`, `last_spool`, `rssi`, `battery_pct`), here's the rename table:

| v1 field | v2 field | Behaviour change |
|---|---|---|
| `name` | `display_name` | semantically identical |
| `last_seen` | `last_heartbeat_at` | **must switch to Firestore Timestamp** (was a Unix ms number) |
| `last_spool` | `current_spool_uid_1` | semantics shift: was "last weighed UID", now "currently on platform". Studio gets the historical "last weighed" by listening to `inventory.{spoolId}.last_update` instead. |
| _(none)_ | `current_spool_uid_2` | new — fills only when twin tag detected |
| `rssi` | `wifi_signal_dbm` | type & semantics identical |
| `battery_pct` | `battery_percent` | identical, integer |
| `mac` | `mac` | kept |
| _(none)_ | `power_source` | new — required, see §9 |
| _(none)_ | `is_charging` | new — required |
| _(none)_ | `hardware_revision` | new — optional |

TigerTag Studio Manager keeps a 2-week compatibility shim that reads either v1 or v2 names, so a phased rollout (firmware updates first, Studio cutover later) is safe.

---

## See also

- [`tigerscale.md`](./tigerscale.md) — full firmware contract: auth flow, weight write path, twin-tag self-healing decision matrix
- [`03-data-model.md`](../03-data-model.md) — global Firestore schema across all collections
- [`02-authentication.md`](../02-authentication.md) — Firebase Auth flow for embedded clients
