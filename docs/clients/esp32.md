# TigerTag Firebase Integration — Guide for AI / Embedded Clients

This document explains how any client (ESP32, AI agent, backend service) can authenticate against the TigerTag Firebase project, read spool data, and update filament weights after a scale measurement.

---

## 1. Firebase Project Config

Fetch the public config (no credentials needed):

```
GET https://tigertag-cdn.web.app/__/firebase/init.json
```

Response shape:
```json
{
  "apiKey": "...",
  "authDomain": "...",
  "projectId": "tigertag-XXX",
  "storageBucket": "...",
  "messagingSenderId": "...",
  "appId": "..."
}
```

Store `apiKey` and `projectId` — you will need them for every subsequent call.

---

## 2. Authentication

### 2a. Email + Password (works on any HTTP client, including ESP32)

```
POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={apiKey}
Content-Type: application/json

{
  "email": "user@example.com",
  "password": "secret",
  "returnSecureToken": true
}
```

Response:
```json
{
  "localId": "{uid}",
  "idToken": "{JWT — valid 1 hour}",
  "refreshToken": "{long-lived token — never expires unless revoked}"
}
```

Store `localId` (= Firebase UID), `idToken`, and `refreshToken`.

---

### 2b. Google Auth (requires a browser)

Google OAuth requires a browser redirect. On devices with a web interface (e.g. ESP32 serving a local page), use the Firebase JS SDK in the browser and POST the resulting tokens back to the device.

**In the browser page served by the device:**
```html
<script src="https://www.gstatic.com/firebasejs/9.x.x/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/9.x.x/firebase-auth-compat.js"></script>
<script>
async function authenticate() {
  const config = await fetch("https://tigertag-cdn.web.app/__/firebase/init.json").then(r => r.json());
  firebase.initializeApp(config);

  // Google Auth
  const provider = new firebase.auth.GoogleAuthProvider();
  await firebase.auth().signInWithPopup(provider);
  // OR: await firebase.auth().signInWithEmailAndPassword(email, password)

  const user  = firebase.auth().currentUser;
  const idToken      = await user.getIdToken();
  const refreshToken = user.refreshToken;

  // POST tokens to the local device
  await fetch("/auth", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uid: user.uid, idToken, refreshToken })
  });
}
</script>
```

The device receives `uid`, `idToken`, and `refreshToken` on its local `/auth` endpoint and stores them in persistent storage (NVS on ESP32).

---

### 2c. Refresh the idToken (run every ~55 minutes, or on 401 error)

```
POST https://securetoken.googleapis.com/v1/token?key={apiKey}
Content-Type: application/json

{
  "grant_type": "refresh_token",
  "refresh_token": "{refreshToken}"
}
```

Response:
```json
{
  "id_token": "{new JWT}",
  "refresh_token": "{new refreshToken — replace the stored one}",
  "user_id": "{uid}"
}
```

Always replace both `idToken` and `refreshToken` with the new values.

If this call returns `TOKEN_EXPIRED` or `USER_DISABLED`, erase stored credentials and re-run the setup flow.

---

## 3. Firestore Data Structure

```
users/
  {uid}/                          ← Firebase Auth UID of the account owner
    displayName    string          ← user's chosen pseudo
    inventory/
      {spoolId}/                  ← document ID (auto-generated)
        uid               string  ← RFID tag UID (primary tag)
        twin_uid          string? ← RFID UID of the linked second tag (if any)
        weight_available  number  ← net filament weight in grams (what you write)
        container_weight  number  ← tare/container weight in grams (what you read)
        capacity          number  ← total spool capacity in grams
        container_id      string  ← references spools_filament.json
        id_brand          number
        id_material       number
        color_name        string
        last_update       number  ← Unix timestamp in milliseconds (what you write)
        deleted           boolean
```

---

## 4. Finding a Spool by Scanned RFID UID

The scale scans a physical RFID tag. Its UID maps to the `uid` field (primary) or `twin_uid` field (secondary) in an inventory document.

### Firestore REST — structured query

```
POST https://firestore.googleapis.com/v1/projects/{projectId}/databases/(default)/documents:runQuery
Authorization: Bearer {idToken}
Content-Type: application/json

{
  "structuredQuery": {
    "from": [{ "collectionId": "inventory" }],
    "where": {
      "fieldFilter": {
        "field": { "fieldPath": "uid" },
        "op": "EQUAL",
        "value": { "stringValue": "{scanned_rfid_uid}" }
      }
    },
    "limit": 1
  }
}
```

**Base path** for the query:
```
/v1/projects/{projectId}/databases/(default)/documents/users/{uid}:runQuery
```

This searches only within the authenticated user's inventory.

If no document is found with `uid == scanned_rfid_uid`, run the same query with `twin_uid` instead:
```json
"field": { "fieldPath": "twin_uid" },
"value": { "stringValue": "{scanned_rfid_uid}" }
```

A successful response returns an array; the first element has a `document` key containing the full document with its `name` path and `fields`.

---

## 5. Weight Calculation

```
weight_available = measured_raw_weight - container_weight
```

- `measured_raw_weight` — total weight read from the scale (spool + filament + container), in grams
- `container_weight` — read from `fields.container_weight.integerValue` (or `doubleValue`) in the Firestore document
- `weight_available` — net filament mass to write back, in grams (minimum 0)

```
weight_available = max(0, measured_raw_weight - container_weight)
```

---

## 6. Updating Weight in Firestore

```
PATCH https://firestore.googleapis.com/v1/projects/{projectId}/databases/(default)/documents/users/{uid}/inventory/{spoolId}?updateMask.fieldPaths=weight_available&updateMask.fieldPaths=last_update
Authorization: Bearer {idToken}
Content-Type: application/json

{
  "fields": {
    "weight_available": { "integerValue": 450 },
    "last_update":      { "integerValue": 1714500000000 }
  }
}
```

- `{spoolId}` — the document ID extracted from the `name` field of the query result (last path segment)
- `last_update` — current Unix timestamp in **milliseconds** (`Date.now()` equivalent)
- Use `updateMask` to avoid overwriting other fields

---

## 7. Complete Scale Logic — 1 or 2 RFID Tags

```
SCALE READS 1 or 2 RFID UIDs
          │
          ▼
For each scanned UID:
  Query inventory where uid == scanned_uid
    └─ Not found? Query where twin_uid == scanned_uid
  → Resolve to spoolDocument + spoolId
          │
          ▼
┌─────────────────────────────────────────────────────┐
│  CASE A — 2 UIDs scanned                           │
│                                                     │
│  UID_1 → spoolDoc_1  (weight_available_1 = W - CW1)│
│  UID_2 → spoolDoc_2  (weight_available_2 = W - CW2)│
│                                                     │
│  If UID_1 and UID_2 resolve to the SAME document   │
│  (primary + twin of the same spool):               │
│    → write once, use the document's container_weight│
│                                                     │
│  If they resolve to 2 different documents:         │
│    → write each independently                       │
│    (two separate spools on the scale simultaneously)│
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  CASE B — 1 UID scanned                            │
│                                                     │
│  UID_1 → spoolDoc                                   │
│  weight_available = W - spoolDoc.container_weight   │
│  → PATCH spoolDoc (weight_available + last_update)  │
│                                                     │
│  spoolDoc.twin_uid is set?                          │
│    └─ YES → Query inventory where uid == twin_uid   │
│             → Resolve twinDoc + twinSpoolId         │
│             → PATCH twinDoc with same               │
│               weight_available + last_update        │
└─────────────────────────────────────────────────────┘
```

### Twin tag — resolving the linked document

If only one tag was scanned but `twin_uid` is present in the resolved document:

```
GET https://firestore.googleapis.com/v1/projects/{projectId}/databases/(default)/documents/users/{uid}/inventory:runQuery
Authorization: Bearer {idToken}

→ structuredQuery where uid == {twin_uid from spoolDoc}
→ resolve twinSpoolId
→ PATCH same weight_available + last_update
```

---

## 8. Alternative — TigerTag CDN API (simpler, no Firestore auth needed)

If you only need to update weight by RFID UID and have an API key:

```
GET https://cdn.tigertag.io/setSpoolWeightByRfid?ApiKey={key}&uid={rfid_uid}&weight={grams}
```

- `uid` — RFID tag UID (primary or twin)
- `weight` — **net filament weight** (already subtracted container), in grams
- The API handles twin tag propagation server-side

This does not require Firebase Auth — only the user's TigerTag API key.

---

## 9. Full Boot Sequence (ESP32 / embedded client)

```
1. Boot
2. Connect to WiFi
3. Read NVS: refreshToken, uid, apiKey, projectId
4. NVS empty? → Serve setup page → wait for /auth POST → store tokens → continue
5. POST securetoken.googleapis.com → get fresh idToken
6. Start scale loop:
     a. Read RFID tag(s)
     b. Read scale weight (raw grams)
     c. For each UID → query Firestore → get spoolId + container_weight
     d. Compute weight_available = raw - container_weight (min 0)
     e. PATCH Firestore: weight_available + last_update (now in ms)
     f. If 1 UID and twin_uid present → resolve twin → PATCH twin doc
7. Refresh idToken every 55 min (or on any 401 response)
```

---

## 10. Error Handling

| HTTP status | Meaning | Action |
|-------------|---------|--------|
| `401` | idToken expired | Refresh token → retry |
| `403` | Wrong UID or Security Rules | Check uid matches authenticated user |
| `404` | Document not found | RFID tag not registered in this account |
| `TOKEN_EXPIRED` on refresh | refreshToken invalid | Erase NVS → re-run setup |
| `USER_DISABLED` | Account suspended | Show error to user |
| No WiFi | Can't reach Firebase | Retry loop, do not erase NVS |

---

## 11. Firestore Field Types — Reference

When writing to Firestore REST, integer values must use `integerValue` (string-encoded), floats use `doubleValue`:

```json
{
  "fields": {
    "weight_available": { "integerValue": "450" },
    "last_update":      { "integerValue": "1714500000000" }
  }
}
```

---

## 12. Complete Arduino sketch (ESP32 + ArduinoJson + WiFi)

This is a minimal but complete reference sketch covering: WiFi, sign-in,
token refresh, RFID-UID query, weight write. Tested on an ESP32-WROOM with
PlatformIO.

`platformio.ini`:
```ini
[env:esp32dev]
platform  = espressif32
board     = esp32dev
framework = arduino
lib_deps  =
  bblanchon/ArduinoJson @ ^7.0.4
  knolleary/PubSubClient @ ^2.8       ; only if you also need MQTT
monitor_speed = 115200
```

`src/tigertag_client.h`:
```cpp
#pragma once
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

class TigerTagClient {
public:
  void begin(const char* email, const char* password);
  bool refreshToken();                                        // call when 401 or every ~55 min
  bool getSpoolByRfid(const char* rfidUid, String& spoolId,
                      uint32_t& containerWeight);
  bool patchSpoolWeight(const char* spoolId, uint32_t grams);

private:
  String _apiKey, _projectId, _idToken, _refreshToken, _uid;
  uint32_t _tokenIssuedAt = 0;
  bool _fetchConfig();
  bool _signIn(const char* email, const char* password);
  bool _httpJson(const String& method, const String& url,
                 const String& body, String& outResponse);
};
```

`src/tigertag_client.cpp`:
```cpp
#include "tigertag_client.h"

static WiFiClientSecure _tls;            // shared TLS client (handles all hosts)

bool TigerTagClient::_fetchConfig() {
  HTTPClient http;
  _tls.setInsecure();                    // ESP32: bring real CA cert in prod
  http.begin(_tls, "https://tigertag-cdn.web.app/__/firebase/init.json");
  int code = http.GET();
  if (code != 200) { http.end(); return false; }
  StaticJsonDocument<512> doc;
  if (deserializeJson(doc, http.getString())) { http.end(); return false; }
  _apiKey    = doc["apiKey"]    | "";
  _projectId = doc["projectId"] | "";
  http.end();
  return _apiKey.length() > 0 && _projectId.length() > 0;
}

bool TigerTagClient::_signIn(const char* email, const char* password) {
  StaticJsonDocument<256> req;
  req["email"]             = email;
  req["password"]          = password;
  req["returnSecureToken"] = true;
  String body; serializeJson(req, body);

  String url = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + _apiKey;
  String resp;
  if (!_httpJson("POST", url, body, resp)) return false;

  StaticJsonDocument<1024> doc;
  if (deserializeJson(doc, resp)) return false;
  _uid          = doc["localId"]      | "";
  _idToken      = doc["idToken"]      | "";
  _refreshToken = doc["refreshToken"] | "";
  _tokenIssuedAt = millis();
  return _uid.length() > 0;
}

bool TigerTagClient::refreshToken() {
  if (_refreshToken.isEmpty()) return false;
  StaticJsonDocument<256> req;
  req["grant_type"]    = "refresh_token";
  req["refresh_token"] = _refreshToken;
  String body; serializeJson(req, body);

  String url = "https://securetoken.googleapis.com/v1/token?key=" + _apiKey;
  String resp;
  if (!_httpJson("POST", url, body, resp)) return false;

  StaticJsonDocument<1024> doc;
  if (deserializeJson(doc, resp)) return false;
  _idToken      = doc["id_token"]      | _idToken;
  _refreshToken = doc["refresh_token"] | _refreshToken;
  _tokenIssuedAt = millis();
  return true;
}

void TigerTagClient::begin(const char* email, const char* password) {
  if (!_fetchConfig()) { Serial.println("[tt] config FAIL"); return; }
  if (!_signIn(email, password)) { Serial.println("[tt] signin FAIL"); return; }
  Serial.printf("[tt] signed in as %s\n", _uid.c_str());
}

bool TigerTagClient::getSpoolByRfid(const char* rfidUid,
                                    String& spoolId, uint32_t& containerWeight) {
  // Run a structured query: SELECT * FROM users/{uid}/inventory WHERE uid == rfid
  String url = "https://firestore.googleapis.com/v1/projects/" + _projectId +
               "/databases/(default)/documents/users/" + _uid + ":runQuery";

  StaticJsonDocument<512> req;
  JsonObject sq = req.createNestedObject("structuredQuery");
  sq["from"][0]["collectionId"] = "inventory";
  JsonObject where = sq.createNestedObject("where").createNestedObject("fieldFilter");
  where["field"]["fieldPath"] = "uid";
  where["op"] = "EQUAL";
  where["value"]["stringValue"] = rfidUid;
  String body; serializeJson(req, body);

  String resp;
  if (!_httpJson("POST", url, body, resp)) return false;

  // Response is an array of {document: {...}}; we expect 0 or 1 hit
  StaticJsonDocument<2048> doc;
  if (deserializeJson(doc, resp)) return false;
  for (JsonObject row : doc.as<JsonArray>()) {
    if (!row.containsKey("document")) continue;
    JsonObject d = row["document"];
    String name = d["name"] | "";       // .../inventory/{spoolId}
    spoolId = name.substring(name.lastIndexOf('/') + 1);
    JsonObject f = d["fields"];
    containerWeight = f["container_weight"]["integerValue"].as<uint32_t>();
    return true;
  }
  return false;                          // not found
}

bool TigerTagClient::patchSpoolWeight(const char* spoolId, uint32_t grams) {
  String url = "https://firestore.googleapis.com/v1/projects/" + _projectId +
               "/databases/(default)/documents/users/" + _uid + "/inventory/" + spoolId +
               "?updateMask.fieldPaths=weight_available&updateMask.fieldPaths=last_update";

  uint64_t nowMs = (uint64_t) time(nullptr) * 1000ULL;   // requires SNTP synced clock
  StaticJsonDocument<256> req;
  JsonObject f = req.createNestedObject("fields");
  f["weight_available"]["integerValue"] = String(grams);
  f["last_update"]["integerValue"]      = String((unsigned long long)nowMs);
  String body; serializeJson(req, body);

  String resp;
  return _httpJson("PATCH", url, body, resp);
}

bool TigerTagClient::_httpJson(const String& method, const String& url,
                               const String& body, String& outResponse) {
  HTTPClient http;
  _tls.setInsecure();
  http.begin(_tls, url);
  http.addHeader("Content-Type", "application/json");
  if (!_idToken.isEmpty())
    http.addHeader("Authorization", "Bearer " + _idToken);

  int code = http.sendRequest(method.c_str(), (uint8_t*) body.c_str(), body.length());
  outResponse = http.getString();
  http.end();

  if (code == 401) {                      // token expired → refresh + retry once
    Serial.println("[tt] 401, refreshing token");
    if (!refreshToken()) return false;
    http.begin(_tls, url);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Authorization", "Bearer " + _idToken);
    code = http.sendRequest(method.c_str(), (uint8_t*) body.c_str(), body.length());
    outResponse = http.getString();
    http.end();
  }
  return code >= 200 && code < 300;
}
```

`src/main.cpp` (using a fictional `Scale` + `Rfid` API — replace with your hardware lib):
```cpp
#include <Arduino.h>
#include <WiFi.h>
#include <time.h>
#include "tigertag_client.h"

TigerTagClient tt;

void setup() {
  Serial.begin(115200);
  WiFi.begin("MY_SSID", "MY_PASS");
  while (WiFi.status() != WL_CONNECTED) delay(200);

  // Sync clock — required for last_update milliseconds
  configTime(0, 0, "pool.ntp.org");
  while (time(nullptr) < 1700000000) delay(200);

  tt.begin("user@example.com", "password");
}

void loop() {
  // 1. Wait for a tag scan + a stable weight reading
  String rfidUid; uint32_t rawGrams;
  if (!Rfid::read(rfidUid) || !Scale::stableRead(rawGrams)) {
    delay(100); return;
  }

  // 2. Resolve the RFID to a spool document
  String spoolId; uint32_t containerWeight;
  if (!tt.getSpoolByRfid(rfidUid.c_str(), spoolId, containerWeight)) {
    Serial.printf("[tt] tag %s unknown\n", rfidUid.c_str());
    delay(2000); return;
  }

  // 3. Subtract the tare and write back
  int32_t net = (int32_t) rawGrams - (int32_t) containerWeight;
  if (net < 0) net = 0;
  if (tt.patchSpoolWeight(spoolId.c_str(), (uint32_t) net))
    Serial.printf("[tt] %s → %d g\n", spoolId.c_str(), net);
  else
    Serial.println("[tt] PATCH failed");

  delay(2000);                            // debounce: 1 weight per 2 s
}
```

### Notes on the sketch

- **TLS root certificates.** `_tls.setInsecure()` skips certificate
  validation — fine for a hobby project, **never** ship that in production.
  Bake the Google root CA into the firmware instead:
  ```cpp
  _tls.setCACert(google_root_ca);
  ```
- **Heap.** `StaticJsonDocument<2048>` is generous; reduce or use
  `DynamicJsonDocument` if you're tight.
- **NTP.** The `last_update` field is in **milliseconds**. Sync the ESP32
  clock once at boot before any write, otherwise you'll write `last_update`
  values stuck in 1970.
- **Persistence.** Save `_refreshToken` to NVS so you don't re-prompt the
  user for credentials at every reboot. The shown code keeps everything in
  RAM for clarity.
- **Twin tag handling.** If you read a doc with a non-empty `twin_uid`,
  you should query for that twin and PATCH its weight too — see §7 above.

For a higher-level helper, see also the legacy CDN endpoint:

```
GET https://cdn.tigertag.io/setSpoolWeightByRfid?ApiKey={K}&uid={UID}&weight={g}
```

which handles twin propagation server-side and skips Firebase auth — but
requires a separate API key and is RFID-UID based only (no rich metadata).

When reading, check both `integerValue` and `doubleValue` since the field type depends on what was written previously.

---

**Verified against:** Tiger Studio Manager v1.4.3 · TigerTag mobile (Flutter) latest · Firestore Rules deployed 2026-05-02
**Contract version:** [v0.1.3](https://github.com/TigerTag-Project/TigerTag-Firebase-Integration/blob/main/CHANGELOG.md)
**Drift?** Open an issue: https://github.com/TigerTag-Project/TigerTag-Firebase-Integration/issues
