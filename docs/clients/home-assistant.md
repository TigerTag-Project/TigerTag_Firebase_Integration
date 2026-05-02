# AGENTHA.md — Home Assistant integration for TigerTag

This document is a **complete reference** for building a Home Assistant
integration (or any Python / REST client) that reads a user's TigerTag
filament inventory **and** the inventories of their friends.

It is meant to be read by an AI agent or a developer with no prior context —
it includes every endpoint, every Firestore collection path, every auth
quirk, and a working HA component sketch at the bottom.

The goal is parity with the desktop app **Tiger Studio Manager**: a user
signs in with their TigerTag account, sees their own spools, sees their
friends' spools (read-only). Nothing more, nothing less.

---

## 1. High-level architecture

TigerTag uses **Firebase Authentication** (email/password) and **Firestore**
as its backing store. There is **no custom REST API** in front of it — every
client (mobile app, desktop app, this HA integration) talks directly to
Firestore using the user's own ID token. Access is gated by **Firestore
Security Rules** evaluated server-side.

```
                 ┌──────────────────────────┐
                 │   HA component (Python)  │
                 └────────────┬─────────────┘
                              │  email + password
                              ▼
                 ┌──────────────────────────┐
                 │  Firebase Identity API   │   → returns idToken (1h JWT)
                 └────────────┬─────────────┘     + refreshToken
                              │
              idToken (Bearer) │
                              ▼
                 ┌──────────────────────────┐
                 │   Firestore REST API     │   ← Security Rules enforce
                 │   (or Admin SDK clone)   │     "I am Alice / Alice is
                 └──────────────────────────┘     friend of Bob" checks
```

You do **not** need a service account key. Each user authenticates as
themselves with their existing TigerTag credentials, and Firestore rules
do the rest.

---

## 2. Firebase project config

Fetch the public client config (no auth required):

```http
GET https://tigertag-cdn.web.app/__/firebase/init.json
```

Returns:

```json
{
  "apiKey":            "AIzaSy…",
  "authDomain":        "tigertag-XXX.firebaseapp.com",
  "projectId":         "tigertag-XXX",
  "storageBucket":     "tigertag-XXX.appspot.com",
  "messagingSenderId": "…",
  "appId":             "…"
}
```

Cache `apiKey` and `projectId` — they are needed for every subsequent call.

The `apiKey` is **public** by design (this is standard Firebase). It does
**not** grant any data access on its own — Firestore Security Rules enforce
permissions based on the authenticated user.

---

## 3. Authentication

### 3.1 Sign-in (email / password)

```http
POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={apiKey}
Content-Type: application/json

{
  "email":             "user@example.com",
  "password":          "the-user-password",
  "returnSecureToken": true
}
```

Response:

```json
{
  "localId":      "abc123…",     // Firebase UID — store this
  "idToken":      "eyJ…",        // JWT, valid 1 hour
  "refreshToken": "AGqA…",       // long-lived, never expires unless revoked
  "expiresIn":    "3600"
}
```

Store all three. `localId` is the user's **`uid`** (you'll use this
everywhere in Firestore paths).

> **Google Sign-In does NOT work in HA** — it requires a browser redirect.
> Ask your users to set a password in the desktop / mobile app first, then
> sign in to the HA integration with email + password.

### 3.2 Refresh the idToken (every ≤ 55 minutes)

```http
POST https://securetoken.googleapis.com/v1/token?key={apiKey}
Content-Type: application/json

{
  "grant_type":    "refresh_token",
  "refresh_token": "{refreshToken}"
}
```

Response:

```json
{
  "id_token":      "new-jwt",
  "refresh_token": "new-refreshToken",   // REPLACE stored value
  "user_id":       "abc123…"
}
```

Replace **both** tokens in storage. If the call returns `TOKEN_EXPIRED`,
`USER_DISABLED`, or `INVALID_REFRESH_TOKEN`, the user must sign in again.

### 3.3 Token freshness — important for friend reads

The `idToken` is a JWT signed by Google with a **1 h TTL**. Every Firestore
request must carry it as `Authorization: Bearer {idToken}`.

When a request reaches Firestore with a token that is close to expiry **or
has just been issued without full propagation**, the rules engine may briefly
see `request.auth == null` and reject reads with `permission-denied`. This
is a known Firebase quirk that surfaces on **friend** reads (not on own-data
reads) because the friend rules are more complex.

**Mitigation pattern (port directly from the desktop app):**

1. **Refresh proactively** when entering a friend view, but throttle to once
   every 30 min (avoid hammering the auth backend).
2. **Retry once on permission-denied**: force a hard refresh and retry the
   exact same read. If it fails again, surface the error.

Pseudo-code:

```python
LAST_REFRESH = 0
THROTTLE_S   = 30 * 60

async def prewarm_token(force=False):
    if not force and time.time() - LAST_REFRESH < THROTTLE_S:
        return
    refresh_id_token()             # → calls securetoken.googleapis.com
    LAST_REFRESH = time.time()

async def read_friend_collection(friend_uid, sub):
    await prewarm_token()
    try:
        return await firestore_get(f"users/{friend_uid}/{sub}")
    except PermissionDenied:
        await prewarm_token(force=True)
        return await firestore_get(f"users/{friend_uid}/{sub}")
```

---

## 4. Firestore data structure

Everything lives under `users/{uid}/…`. The key paths an HA integration
will read:

```
users/
  {uid}/
    displayName    string             ← user's chosen pseudo
    googleName     string             ← admin reference only, never display
    email          string
    publicKey      string              ← discovery code "XXX-XXX"
    privateKey     string              ← 40-char hex access token (SECRET — never log)
    isPublic       boolean             ← if true, inventory is world-readable
    Debug          boolean             ← admin-only
    roles          string?             ← "admin" | undefined

    inventory/
      {spoolId}/                       ← one doc per spool
        uid               string       ← primary RFID UID
        twin_uid          string?      ← linked tag UID (factory pair)
        id_brand          number       ← FK → data/id_brand.json
        id_material       number       ← FK → data/id_material.json
        color_name        string       ← e.g. "Galaxy Black"
        online_color_list string[]     ← optional ["#000", "#aaa", ...]
        weight_available  number       ← grams of filament left
        container_weight  number       ← spool container weight (tare)
        capacity          number       ← total spool capacity (grams)
        container_id      string       ← FK → data/container_spool/spools_filament.json
        last_update       number       ← Unix ms
        deleted           boolean      ← soft-delete flag
        rack_id           string?      ← if assigned to a rack
        level             number?      ← shelf index in rack (0 = bottom)
        position          number?      ← slot index in shelf (0 = leftmost)

    racks/
      {rackId}/                        ← one doc per storage rack
        name           string          ← e.g. "Rack 2"
        level          number          ← shelves (1-15)
        position       number          ← slots per shelf (1-20)
        order          number          ← display order in the UI
        lockedSlots    string[]        ← e.g. ["0:0","0:1"] — "lv:pos" keys
        createdAt      timestamp
        lastUpdate     timestamp

    friends/
      {friendUid}/
        displayName    string
        addedAt        timestamp
        key            string          ← friend's privateKey at accept time
                                          (used by Firestore rules to grant
                                           cross-account read access)

    friendRequests/
      {requesterUid}/
        displayName    string
        requestedAt    timestamp
        key            string          ← requester's privateKey

    blacklist/
      {blockedUid}/
        displayName    string
        blockedAt      timestamp

    prefs/
      app/
        lang           string          ← "en" | "fr" | "de" | …

publicKeys/
  {key}/                              ← key = "XXX-XXX" public code
    uid            string              ← owner uid
    claimedAt      timestamp

userProfiles/
  {uid}/                              ← public-facing profile (legacy)
    publicKey      string
    displayName    string
    isPublic       boolean
```

### Lookup tables (NOT in Firestore — bundled with each client)

The desktop app ships these as static JSON files. You should bundle the same
files into your HA integration (or fetch them from the GitHub repo at build
time):

| File | Resolves |
|------|----------|
| `data/id_brand.json` | `id_brand` (number) → brand name (string) |
| `data/id_material.json` | `id_material` → material name |
| `data/id_aspect.json` | `id_aspect` → finish/aspect name |
| `data/id_type.json` | `id_type` → product type ("Filament", "Resin", …) |
| `data/id_diameter.json` | `id_diameter` → diameter in mm |
| `data/id_measure_unit.json` | unit code → label |
| `data/container_spool/spools_filament.json` | `container_id` → container metadata (weight, image) |

Source of truth (always up to date):

```
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_brand.json
https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data/id_material.json
…etc
```

---

## 5. Reading the signed-in user's own data

### 5.1 Own inventory (list all spools)

```http
GET https://firestore.googleapis.com/v1/projects/{projectId}/databases/(default)/documents/users/{uid}/inventory
Authorization: Bearer {idToken}
```

Returns:

```json
{
  "documents": [
    {
      "name":   "projects/.../documents/users/{uid}/inventory/{spoolId}",
      "fields": {
        "uid":              { "stringValue": "04A1B2C3D4E5F6" },
        "id_brand":         { "integerValue": "12" },
        "id_material":      { "integerValue": "1" },
        "color_name":       { "stringValue": "Galaxy Black" },
        "weight_available": { "integerValue": "750" },
        "capacity":         { "integerValue": "1000" },
        "deleted":          { "booleanValue": false }
        …
      }
    },
    …
  ],
  "nextPageToken": "…"        // paginate if > 100 docs
}
```

Filter `deleted == true` client-side.

### 5.2 Own racks

```http
GET https://firestore.googleapis.com/v1/projects/{projectId}/databases/(default)/documents/users/{uid}/racks
Authorization: Bearer {idToken}
```

Sort client-side by `order` (fallback `createdAt.seconds`).

### 5.3 Own user profile (publicKey, etc.)

```http
GET https://firestore.googleapis.com/v1/projects/{projectId}/databases/(default)/documents/users/{uid}
Authorization: Bearer {idToken}
```

You'll typically read this once at sign-in to grab `displayName`, `publicKey`,
and `isPublic`.

---

## 6. The friend system

This is the part most people get wrong. Read carefully.

### 6.1 Mental model

Each user has a **`privateKey`** (40-char hex token) stored in their own
`users/{uid}` doc. This token is **secret** — never log it, never display
it, never share it.

When two users **become friends** (one accepts a request from the other),
a single Firestore batch writes **bidirectionally**:

```
users/alice/friends/bob.key  =  bob.privateKey      ← Alice keeps Bob's key
users/bob/friends/alice.key  =  alice.privateKey    ← Bob keeps Alice's key
```

That's it. Each user keeps a copy of the other's `privateKey` in their own
"friends" sub-collection.

When **Alice tries to read Bob's inventory**, the Firestore rule (server-side)
evaluates:

```
get(/users/bob/friends/alice).key  ==  get(/users/alice).privateKey
```

In English: *"the key Bob stored for Alice must equal Alice's current
privateKey."* If it matches → access granted. If it doesn't (Bob unfriended
Alice → doc deleted, or Alice rotated her privateKey → no match) → denied.

Important consequences:

- Removing a friend = deleting the bidirectional friend docs. Access revokes
  immediately on the next read.
- Rotating your own `privateKey` is a global "kick everyone out" — every
  friend must re-add you.
- The `privateKey` in `users/{uid}` is **never readable by anyone other than
  the owner**. The friend doesn't know your privateKey directly — they only
  see the value Firestore wrote into their `friends/{yourUid}.key` field.

### 6.2 Listing the signed-in user's friends

```http
GET https://firestore.googleapis.com/v1/projects/{projectId}/databases/(default)/documents/users/{uid}/friends
Authorization: Bearer {idToken}
```

Returns one document per friend, with `displayName`, `addedAt`, and `key`
(don't expose `key` in HA UI — it's an access secret).

For each friend, the doc ID is the friend's `uid` — you'll use it directly
to read their data.

### 6.3 Reading a friend's inventory

Once you know `friend_uid` from the friends list, the request is identical
in shape to your own inventory read — just swap the path:

```http
GET https://firestore.googleapis.com/v1/projects/{projectId}/databases/(default)/documents/users/{friend_uid}/inventory
Authorization: Bearer {idToken}
```

The `idToken` is still YOUR token (Alice's). Firestore rules check whether
`users/{friend_uid}/friends/{your_uid}` exists with the right `key` — if yes,
you get all the inventory docs. If no, you get `permission-denied`.

**Apply the prewarm + retry pattern** (see §3.3) on this call. Without it,
~5–10 % of requests at the auth-token-near-expiry boundary will fail spuriously.

### 6.4 Reading a friend's racks

Same pattern, swap the sub-collection:

```http
GET https://firestore.googleapis.com/v1/projects/{projectId}/databases/(default)/documents/users/{friend_uid}/racks
Authorization: Bearer {idToken}
```

If permission-denied here even with retry → the friend hasn't enabled rack
sharing (some users have stricter rules) or the rule rejects sub-collection
reads other than `inventory`. In that case, fall back gracefully to "no
racks shown".

### 6.5 Reading public inventories (no friendship needed)

If `users/{otherUid}.isPublic == true`, anyone authenticated can read their
inventory. Use this for "discover" features — though the current desktop app
doesn't expose a discovery UI. To check the flag:

```http
GET https://firestore.googleapis.com/v1/projects/{projectId}/databases/(default)/documents/users/{otherUid}
Authorization: Bearer {idToken}
```

Read `fields.isPublic.booleanValue`. The `users/{otherUid}` doc is
world-readable for authenticated users (only `privateKey` is masked by
field-level rules — you'll get `null` for it).

### 6.6 Looking up a user by their public code (`XXX-XXX`)

When an HA user types a friend's discovery code (e.g. `4X7-K3M`), look up
the corresponding `uid`:

```http
GET https://firestore.googleapis.com/v1/projects/{projectId}/databases/(default)/documents/publicKeys/{XXX-XXX}
Authorization: Bearer {idToken}
```

Returns `{ "fields": { "uid": { "stringValue": "..." } } }` if it exists,
404 otherwise.

Note: the HA integration should NOT send / accept friend requests on its
own — keep that flow in the desktop / mobile app. HA reads only.

---

## 7. Caveats & best practices

### 7.1 Rate limits

Firestore allows ~1 read per second per document for sustained traffic, but
short bursts of dozens are fine. For a typical HA install (1–10 friends, a
few dozen spools each), you'll be far below any limit.

**Recommended polling interval: 5 minutes minimum.** Filament inventories
don't change often. Faster polling wastes Firestore reads (which the
TigerTag project pays for) and burns the user's battery on mobile.

### 7.2 Pagination

Inventory lists with > 100 spools require pagination via `nextPageToken`.
Most users have < 50 spools, but write the loop defensively:

```python
def list_all(url, headers):
    docs = []
    while True:
        r = requests.get(url, headers=headers).json()
        docs.extend(r.get("documents", []))
        token = r.get("nextPageToken")
        if not token:
            return docs
        url_with_page = f"{url}?pageToken={token}"
        url = url_with_page
```

### 7.3 Field decoding

Firestore REST returns fields in a typed wrapper (`stringValue`,
`integerValue`, `booleanValue`, `arrayValue`, `mapValue`, `timestampValue`).
Write a decoder:

```python
def decode(field):
    if "stringValue"  in field: return field["stringValue"]
    if "integerValue" in field: return int(field["integerValue"])
    if "doubleValue"  in field: return float(field["doubleValue"])
    if "booleanValue" in field: return field["booleanValue"]
    if "nullValue"    in field: return None
    if "timestampValue" in field: return field["timestampValue"]
    if "arrayValue" in field:
        return [decode(v) for v in field["arrayValue"].get("values", [])]
    if "mapValue" in field:
        return {k: decode(v) for k, v in field["mapValue"].get("fields", {}).items()}
    return None

def doc_to_dict(doc):
    return {k: decode(v) for k, v in doc.get("fields", {}).items()}
```

### 7.4 Never use `firebase-admin` SDK

The Admin SDK requires a service account JSON file with full database
access — that file would have to be shipped with the integration, breaking
every user's privacy. Always use the **client REST API** (or `pyrebase4`)
with the user's own credentials.

### 7.5 Storing tokens

Use Home Assistant's `aiohttp_client` and persist tokens in the integration's
config entry (`config_entry.data`). Don't write them to a YAML file.

```python
hass.config_entries.async_update_entry(
    entry,
    data={**entry.data, "id_token": new_token, "refresh_token": new_refresh},
)
```

Encrypt at rest if you're paranoid (HA does NOT encrypt config entries by
default).

### 7.6 Privacy

Read-only is read-only. The HA integration should **never** write to the
friend's collections, even though some Firestore rules might technically
allow it (e.g. acceptance flow). Clearly document this in the README and
refuse to expose any `set` / `update` button for friend data.

---

## 8. Reference Python implementation (Pyrebase4)

Pyrebase4 wraps the REST API and handles token refresh for you.

```bash
pip install pyrebase4
```

```python
import pyrebase
import requests
import time

CONFIG_URL = "https://tigertag-cdn.web.app/__/firebase/init.json"

def fetch_config():
    return requests.get(CONFIG_URL).json()

def init_firebase():
    cfg = fetch_config()
    return pyrebase.initialize_app({
        "apiKey":            cfg["apiKey"],
        "authDomain":        cfg["authDomain"],
        "projectId":         cfg["projectId"],
        "databaseURL":       "",
        "storageBucket":     cfg["storageBucket"],
    })

class TigerTagClient:
    def __init__(self, email, password):
        self.firebase = init_firebase()
        self.auth = self.firebase.auth()
        self.user = self.auth.sign_in_with_email_and_password(email, password)
        self.uid = self.user["localId"]
        self._last_refresh = time.time()

    def _ensure_token(self, force=False):
        if not force and time.time() - self._last_refresh < 30 * 60:
            return
        self.user = self.auth.refresh(self.user["refreshToken"])
        self._last_refresh = time.time()

    def _firestore_get(self, path):
        self._ensure_token()
        cfg = fetch_config()
        url = (f"https://firestore.googleapis.com/v1/projects/"
               f"{cfg['projectId']}/databases/(default)/documents/{path}")
        h = {"Authorization": f"Bearer {self.user['idToken']}"}
        r = requests.get(url, headers=h)
        if r.status_code == 403:
            # permission-denied — force-refresh and retry once
            self._ensure_token(force=True)
            h = {"Authorization": f"Bearer {self.user['idToken']}"}
            r = requests.get(url, headers=h)
        r.raise_for_status()
        return r.json()

    # ── decoders ───────────────────────────────────────────────────────
    @staticmethod
    def _decode_field(f):
        for k in ("stringValue","booleanValue","timestampValue"):
            if k in f: return f[k]
        if "integerValue" in f: return int(f["integerValue"])
        if "doubleValue"  in f: return float(f["doubleValue"])
        if "nullValue"    in f: return None
        if "arrayValue"   in f:
            return [TigerTagClient._decode_field(v)
                    for v in f["arrayValue"].get("values", [])]
        if "mapValue" in f:
            return {k: TigerTagClient._decode_field(v)
                    for k,v in f["mapValue"].get("fields", {}).items()}
        return None

    @staticmethod
    def _doc(d):
        out = {k: TigerTagClient._decode_field(v)
               for k,v in d.get("fields", {}).items()}
        out["_id"] = d["name"].rsplit("/",1)[-1]
        return out

    # ── public API ─────────────────────────────────────────────────────
    def own_inventory(self):
        r = self._firestore_get(f"users/{self.uid}/inventory")
        return [self._doc(d) for d in r.get("documents", [])
                if not self._doc(d).get("deleted")]

    def own_racks(self):
        r = self._firestore_get(f"users/{self.uid}/racks")
        return sorted(
            (self._doc(d) for d in r.get("documents", [])),
            key=lambda x: (x.get("order", 999), x.get("createdAt", "")))

    def list_friends(self):
        r = self._firestore_get(f"users/{self.uid}/friends")
        return [{"uid": self._doc(d)["_id"],
                 "displayName": self._doc(d).get("displayName")}
                for d in r.get("documents", [])]

    def friend_inventory(self, friend_uid):
        r = self._firestore_get(f"users/{friend_uid}/inventory")
        return [self._doc(d) for d in r.get("documents", [])
                if not self._doc(d).get("deleted")]

    def friend_racks(self, friend_uid):
        try:
            r = self._firestore_get(f"users/{friend_uid}/racks")
            return [self._doc(d) for d in r.get("documents", [])]
        except requests.HTTPError:
            return []
```

Usage:

```python
c = TigerTagClient("alice@example.com", "her-password")
print("Own inventory:", len(c.own_inventory()), "spools")
for f in c.list_friends():
    print(f["displayName"], "→", len(c.friend_inventory(f["uid"])), "spools")
```

---

## 9. Home Assistant integration sketch

A minimal HA component that exposes one `sensor` entity per spool, with the
remaining weight in grams as the state and the rest as attributes.

```
custom_components/tigertag/
├── manifest.json
├── __init__.py
├── config_flow.py
└── sensor.py
```

### `manifest.json`
```json
{
  "domain": "tigertag",
  "name":   "TigerTag",
  "version": "0.1.0",
  "requirements": ["pyrebase4>=4.5.0"],
  "config_flow": true,
  "iot_class": "cloud_polling"
}
```

### `config_flow.py` (skeleton)
```python
from homeassistant import config_entries
import voluptuous as vol

class TigerTagFlow(config_entries.ConfigFlow, domain="tigertag"):
    async def async_step_user(self, info=None):
        if info is not None:
            # Validate by attempting a sign-in
            try:
                client = await self.hass.async_add_executor_job(
                    TigerTagClient, info["email"], info["password"])
            except Exception as e:
                return self.async_show_form(
                    step_id="user", errors={"base": "invalid_auth"})
            return self.async_create_entry(
                title=info["email"], data=info)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("email"):    str,
                vol.Required("password"): str,
            }))
```

### `sensor.py` (skeleton)
```python
from datetime import timedelta
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator, CoordinatorEntity)

SCAN_INTERVAL = timedelta(minutes=5)

async def async_setup_entry(hass, entry, async_add_entities):
    client = await hass.async_add_executor_job(
        TigerTagClient, entry.data["email"], entry.data["password"])

    async def _refresh():
        own = await hass.async_add_executor_job(client.own_inventory)
        friends = await hass.async_add_executor_job(client.list_friends)
        per_friend = {}
        for f in friends:
            per_friend[f["uid"]] = await hass.async_add_executor_job(
                client.friend_inventory, f["uid"])
        return {"own": own, "friends": per_friend, "friend_meta": friends}

    coord = DataUpdateCoordinator(
        hass, name="tigertag", update_method=_refresh,
        update_interval=SCAN_INTERVAL)
    await coord.async_config_entry_first_refresh()

    entities = []
    for spool in coord.data["own"]:
        entities.append(SpoolSensor(coord, spool, owner="me"))
    for f_uid, spools in coord.data["friends"].items():
        owner_name = next((m["displayName"] for m in coord.data["friend_meta"]
                          if m["uid"] == f_uid), "friend")
        for spool in spools:
            entities.append(SpoolSensor(coord, spool, owner=owner_name))
    async_add_entities(entities)

class SpoolSensor(CoordinatorEntity, SensorEntity):
    _attr_native_unit_of_measurement = "g"
    _attr_icon = "mdi:printer-3d-nozzle"

    def __init__(self, coord, spool, owner):
        super().__init__(coord)
        self._id    = spool["_id"]
        self._owner = owner
        self._attr_unique_id = f"tigertag_{owner}_{self._id}"
        self._attr_name = f"{owner} · {spool.get('color_name') or self._id}"

    @property
    def native_value(self):
        for spool in self._all_spools():
            if spool["_id"] == self._id:
                return spool.get("weight_available")
        return None

    @property
    def extra_state_attributes(self):
        for spool in self._all_spools():
            if spool["_id"] == self._id:
                return {
                    "owner":      self._owner,
                    "uid":        spool.get("uid"),
                    "twin_uid":   spool.get("twin_uid"),
                    "id_brand":   spool.get("id_brand"),
                    "id_material":spool.get("id_material"),
                    "color_name": spool.get("color_name"),
                    "capacity":   spool.get("capacity"),
                    "rack_id":    spool.get("rack_id"),
                    "level":      spool.get("level"),
                    "position":   spool.get("position"),
                }
        return {}

    def _all_spools(self):
        d = self.coordinator.data
        if self._owner == "me":
            return d["own"]
        for fm in d["friend_meta"]:
            if fm["displayName"] == self._owner:
                return d["friends"][fm["uid"]]
        return []
```

The user adds the integration once with their email/password, and HA
auto-creates one `sensor.tigertag_*` entity per spool (own + every friend's,
read-only). Each sensor's state is the remaining weight in grams; brand,
material, color, rack location are exposed as attributes ready for use in
automations or dashboards.

---

## 10. Glossary / common pitfalls

| Term | Meaning |
|------|---------|
| `uid` (Firebase) | The 28-char Firebase Auth user ID. Your account's primary key. |
| `uid` (RFID) | The hex UID of a physical NFC tag (different from above — both happen to be called "uid"). |
| `idToken` | Short-lived JWT proving who you are. Send as `Bearer` on every Firestore request. |
| `refreshToken` | Long-lived token used to obtain a new `idToken`. Treat as a password. |
| `privateKey` | 40-char hex token tying friendships. Never log, never display. |
| `publicKey` | Human-friendly `XXX-XXX` discovery code. Safe to share. |
| `permission-denied` | Either: (a) you're not allowed at all, or (b) your token is stale → see §3.3. |
| `last_update` | Unix milliseconds. Anything after now-30 days is "stale" but not invalid. |
| `deleted: true` | Soft-deleted spool. Hide from UI; the user can restore from the desktop app. |

---

## 11. Going further

- **Push updates** instead of polling: Firestore exposes a long-poll listen
  endpoint (`v1/.../documents:listen`) that streams snapshot updates. Pyrebase
  doesn't support this natively, but `google-cloud-firestore-async` does.
  Trade-off: more complex, but updates land within a second.
- **Mobile app pairing**: extract `idToken` + `refreshToken` from the
  TigerTag mobile app via a shared QR code instead of asking the user for
  their password. Out of scope for v1.
- **Lookup table cache**: download the seven `data/*.json` files at first
  install and refresh them weekly. Resolve `id_brand` → "Bambu Lab" etc.
  for friendly entity names.

---

**Last updated:** 2026-05-02 — for Tiger Studio Manager v1.4.3
**Repo:** https://github.com/TigerTag-Project/TigerTag_Studio_Manager
