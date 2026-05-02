# Spoolman bridge

[Spoolman](https://github.com/Donkie/Spoolman) is a popular self-hosted
filament inventory tracker that integrates with slicers (OrcaSlicer,
PrusaSlicer, Klipper, OctoPrint, etc.). Many users want to keep their
TigerTag inventory in sync with their Spoolman instance so the slicer
sees the same spool data.

This document describes a one-way bridge: **TigerTag → Spoolman**.
It reads from Firebase, maps the TigerTag schema to Spoolman entities,
and upserts via Spoolman's REST API.

---

## 1. Architecture

```
┌────────────────────────┐      read         ┌────────────────────┐
│ TigerTag (Firestore)   │ ◄───────────────  │  Bridge process    │
│  users/{uid}/inventory │                   │  (Python / Node /  │
│  users/{uid}/printers  │                   │   anything)        │
└────────────────────────┘                   └─────────┬──────────┘
                                                       │ upsert
                                                       ▼
                                            ┌────────────────────┐
                                            │  Spoolman (HTTP)   │
                                            │  /api/v1/vendor    │
                                            │  /api/v1/filament  │
                                            │  /api/v1/spool     │
                                            └────────────────────┘
```

Run the bridge:

- as a **cron job** (every 5 min for "good enough" sync)
- as a **systemd service** with a sleep loop (1 min)
- as a **Docker sidecar** to your existing Spoolman container
- as a **Home Assistant Add-on** alongside your HA integration

The bridge is read-only on the TigerTag side. Updates flow only one way.

---

## 2. Spoolman API at a glance

Spoolman runs on `http://<host>:<port>` and exposes a REST API at `/api/v1`.
**No authentication** is required by default (it's expected to be on a
trusted LAN — protect it with a reverse proxy if you want auth).

The three entities you need:

| Spoolman entity | Represents | TigerTag equivalent |
|-----------------|------------|---------------------|
| `vendor` | Brand / manufacturer | `id_brand` (resolved via `data/id_brand.json`) |
| `filament` | A specific filament product (brand + material + color) | combination of `id_brand` + `id_material` + `color_name` |
| `spool` | Physical instance of a filament (a real spool) | one TigerTag inventory doc |

Endpoints used by the bridge:

```
GET    /api/v1/vendor                  list all vendors
POST   /api/v1/vendor                  create vendor
PATCH  /api/v1/vendor/{id}             update vendor

GET    /api/v1/filament                list all filaments
POST   /api/v1/filament                create filament
PATCH  /api/v1/filament/{id}           update filament

GET    /api/v1/spool                   list all spools
GET    /api/v1/spool?filter={...}      filter (e.g. by extra fields)
POST   /api/v1/spool                   create spool
PATCH  /api/v1/spool/{id}              update spool
```

Full reference: https://github.com/Donkie/Spoolman/blob/master/docs/api/v1.md

---

## 3. Field mapping

### Vendor (= TigerTag brand)

| Spoolman field | Source |
|----------------|--------|
| `name` | `id_brand` resolved through `data/id_brand.json` (e.g. `12 → "Bambu Lab"`) |
| `external_id` | `tigertag:brand:{id_brand}` (used to find the vendor on next sync) |

### Filament (= TigerTag brand × material × color)

A "filament" in Spoolman is a SKU-like entity: each unique `(brand,
material, color)` combination is one filament. Multiple physical spools
can share the same filament (e.g. you have 3 physical spools of "Bambu
PLA Galaxy Black" → 1 filament + 3 spools).

| Spoolman field | Source |
|----------------|--------|
| `name` | `"{brand} {material} {color_name}"` |
| `vendor.id` | the vendor created above |
| `material` | `id_material` resolved (e.g. `1 → "PLA"`) |
| `color_hex` | `online_color_list[0]` if mono color; computed average otherwise |
| `multi_color_hexes` | `online_color_list` if length > 1 |
| `density` | from material lookup if available, else `1.24` (PLA default) |
| `diameter` | resolved from `id_diameter` (typically `1.75`) |
| `weight` | TigerTag `capacity` (e.g. `1000`) |
| `spool_weight` | TigerTag `container_weight` |
| `external_id` | `tigertag:filament:{id_brand}:{id_material}:{slug(color_name)}` |

### Spool (= TigerTag inventory document)

| Spoolman field | Source |
|----------------|--------|
| `filament.id` | the filament created above |
| `remaining_weight` | TigerTag `weight_available` |
| `initial_weight` | TigerTag `capacity` |
| `last_used` | ISO 8601 from `last_update` (Unix ms) |
| `archived` | `deleted` from TigerTag |
| `extra.tigertag_uid` | TigerTag inventory doc id (for upsert lookup) |
| `extra.tigertag_rfid` | TigerTag `uid` field (NFC tag UID) |
| `extra.tigertag_twin` | TigerTag `twin_uid` if present |
| `comment` | (optional) `"Synced from TigerTag · last update: …"` |

The `extra.*` fields let the bridge look up an existing Spoolman spool on
re-sync without creating duplicates.

### TigerTag fields that don't have a Spoolman equivalent

- `rack_id`, `level`, `position` → physical storage location, no equivalent
  in Spoolman. You can stuff them into `comment` or `extra.tigertag_rack`
  if you want.
- `online_color_list[1..]` → only relevant for multicolor; mapped via
  `multi_color_hexes`.
- `container_id` → resolves to a container model name; Spoolman tracks the
  spool weight numerically (`spool_weight`), not the model — drop it.

---

## 4. Sync algorithm

```
1. Sign in to Firebase (email + password)
2. Read TigerTag own inventory + lookup tables
3. List Spoolman vendors / filaments / spools (one round-trip each)
4. Build a (brand_id → vendor_id) map: for each unique TigerTag brand,
   ensure a vendor exists; create if missing.
5. Build a (brand_id, material_id, color_name) → filament_id map: for
   each unique combination, ensure a filament exists; create if missing.
6. For each TigerTag spool:
     - Find the matching Spoolman spool by extra.tigertag_uid
       (= the TigerTag inventory doc id)
     - If not found → POST a new Spoolman spool
     - If found → PATCH only the fields that changed (weight_available,
       last_update, archived)
7. (Optional) For Spoolman spools that no longer have a TigerTag match,
   PATCH archived=true. This handles deletions without removing data.
```

**Safeguards:**

- Always upsert by `extra.tigertag_uid`, never by `name` or `comment` —
  user might rename things.
- Never delete spools / filaments / vendors. Only `archived: true`.
- Run with a dry-run flag first to print intended changes.
- Rate-limit Spoolman writes to ~5/sec to be polite to a Pi.

---

## 5. Complete Python example

```python
"""
TigerTag → Spoolman bridge.
Run via cron every 5 min, or as a long-lived loop.

pip install pyrebase4 requests python-slugify
"""

import os, time, logging, requests, pyrebase
from slugify import slugify

# ── Config ──────────────────────────────────────────────────────────
TIGERTAG_EMAIL    = os.environ["TIGERTAG_EMAIL"]
TIGERTAG_PASSWORD = os.environ["TIGERTAG_PASSWORD"]
SPOOLMAN_URL      = os.environ.get("SPOOLMAN_URL", "http://localhost:7912")
DRY_RUN           = os.environ.get("DRY_RUN", "0") == "1"
TIGERTAG_REPO_RAW = "https://raw.githubusercontent.com/TigerTag-Project/TigerTag_Studio_Manager/main/data"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("bridge")

# ── Lookup tables (cached in memory) ────────────────────────────────
def fetch_lookup(name):
    return requests.get(f"{TIGERTAG_REPO_RAW}/{name}.json").json()

BRANDS    = {int(b["id"]): b["name"] for b in fetch_lookup("id_brand")}
MATERIALS = {int(m["id"]): m["name"] for m in fetch_lookup("id_material")}
DIAMETERS = {int(d["id"]): float(d["value"]) for d in fetch_lookup("id_diameter")}

# ── TigerTag client (minimal subset) ───────────────────────────────
class TigerTag:
    def __init__(self, email, password):
        cfg = requests.get("https://tigertag-cdn.web.app/__/firebase/init.json").json()
        self.cfg = cfg
        self.firebase = pyrebase.initialize_app({
            "apiKey": cfg["apiKey"], "authDomain": cfg["authDomain"],
            "projectId": cfg["projectId"], "databaseURL": "",
            "storageBucket": cfg["storageBucket"],
        })
        self.user = self.firebase.auth().sign_in_with_email_and_password(email, password)
        self.uid = self.user["localId"]

    def own_inventory(self):
        url = (f"https://firestore.googleapis.com/v1/projects/"
               f"{self.cfg['projectId']}/databases/(default)/documents/users/{self.uid}/inventory")
        r = requests.get(url, headers={"Authorization": f"Bearer {self.user['idToken']}"})
        r.raise_for_status()
        return [self._doc(d) for d in r.json().get("documents", [])
                if not self._doc(d).get("deleted")]

    @staticmethod
    def _decode(f):
        for k in ("stringValue", "booleanValue", "timestampValue"):
            if k in f: return f[k]
        if "integerValue" in f: return int(f["integerValue"])
        if "doubleValue"  in f: return float(f["doubleValue"])
        if "arrayValue" in f:
            return [TigerTag._decode(v) for v in f["arrayValue"].get("values", [])]
        return None

    @staticmethod
    def _doc(d):
        out = {k: TigerTag._decode(v) for k, v in d.get("fields", {}).items()}
        out["_id"] = d["name"].rsplit("/", 1)[-1]
        return out

# ── Spoolman client ─────────────────────────────────────────────────
class Spoolman:
    def __init__(self, base):
        self.base = base.rstrip("/")
    def _req(self, method, path, **kw):
        if DRY_RUN and method != "GET":
            log.info(f"[DRY] {method} {path} {kw.get('json', '')}")
            return {}
        r = requests.request(method, f"{self.base}/api/v1{path}", timeout=10, **kw)
        r.raise_for_status()
        return r.json() if r.content else {}
    def list_vendors(self):   return self._req("GET", "/vendor")
    def list_filaments(self): return self._req("GET", "/filament")
    def list_spools(self):    return self._req("GET", "/spool")
    def create_vendor(self, body):     return self._req("POST",  "/vendor", json=body)
    def create_filament(self, body):   return self._req("POST",  "/filament", json=body)
    def create_spool(self, body):      return self._req("POST",  "/spool", json=body)
    def patch_spool(self, sid, body):  return self._req("PATCH", f"/spool/{sid}", json=body)

# ── Mapping ─────────────────────────────────────────────────────────
def vendor_external_id(brand_id):
    return f"tigertag:brand:{brand_id}"

def filament_external_id(brand_id, material_id, color_name):
    return f"tigertag:filament:{brand_id}:{material_id}:{slugify(color_name or 'unknown')}"

def color_hex(spool):
    cl = spool.get("online_color_list") or []
    if cl: return cl[0]
    return "#888888"

# ── Main sync routine ───────────────────────────────────────────────
def sync():
    tt = TigerTag(TIGERTAG_EMAIL, TIGERTAG_PASSWORD)
    sm = Spoolman(SPOOLMAN_URL)
    inv = tt.own_inventory()
    log.info(f"TigerTag: {len(inv)} active spools")

    sm_vendors    = {v.get("external_id"): v for v in sm.list_vendors()}
    sm_filaments  = {f.get("external_id"): f for f in sm.list_filaments()}
    sm_spools     = {(s.get("extra") or {}).get("tigertag_uid"): s for s in sm.list_spools()}

    # 1. Vendors
    brands_seen = {s.get("id_brand") for s in inv if s.get("id_brand") is not None}
    vendor_id_by_brand = {}
    for bid in brands_seen:
        ext = vendor_external_id(bid)
        if ext in sm_vendors:
            vendor_id_by_brand[bid] = sm_vendors[ext]["id"]
        else:
            v = sm.create_vendor({
                "name":        BRANDS.get(bid, f"Brand #{bid}"),
                "external_id": ext,
            })
            vendor_id_by_brand[bid] = v.get("id")
            log.info(f"  + vendor: {BRANDS.get(bid)}")

    # 2. Filaments
    fil_id_by_key = {}
    for s in inv:
        bid = s.get("id_brand"); mid = s.get("id_material")
        if bid is None or mid is None: continue
        cname = s.get("color_name") or ""
        ext = filament_external_id(bid, mid, cname)
        if ext in sm_filaments:
            fil_id_by_key[ext] = sm_filaments[ext]["id"]
            continue
        body = {
            "name":        f"{BRANDS.get(bid,'?')} {MATERIALS.get(mid,'?')} {cname}".strip(),
            "vendor_id":   vendor_id_by_brand[bid],
            "material":    MATERIALS.get(mid, "Unknown"),
            "color_hex":   color_hex(s),
            "weight":      s.get("capacity") or 1000,
            "spool_weight":s.get("container_weight") or 0,
            "diameter":    1.75,
            "external_id": ext,
        }
        cl = s.get("online_color_list") or []
        if len(cl) > 1: body["multi_color_hexes"] = cl
        f = sm.create_filament(body)
        fil_id_by_key[ext] = f.get("id")
        log.info(f"  + filament: {body['name']}")

    # 3. Spools
    for s in inv:
        sid = s["_id"]
        bid = s.get("id_brand"); mid = s.get("id_material")
        if bid is None or mid is None: continue
        ext_fil = filament_external_id(bid, mid, s.get("color_name") or "")
        body = {
            "filament_id":      fil_id_by_key[ext_fil],
            "remaining_weight": s.get("weight_available") or 0,
            "initial_weight":   s.get("capacity") or 1000,
            "extra": {
                "tigertag_uid":   sid,
                "tigertag_rfid":  s.get("uid") or "",
                "tigertag_twin":  s.get("twin_uid") or "",
            },
        }
        existing = sm_spools.get(sid)
        if existing:
            # Only patch if remaining weight changed
            if existing.get("remaining_weight") != body["remaining_weight"]:
                sm.patch_spool(existing["id"], {"remaining_weight": body["remaining_weight"]})
                log.info(f"  ~ spool {sid}: {existing.get('remaining_weight')} → {body['remaining_weight']}g")
        else:
            sm.create_spool(body)
            log.info(f"  + spool {sid}: {body['remaining_weight']}g")

    log.info("Done.")

if __name__ == "__main__":
    sync()
```

Run:

```bash
export TIGERTAG_EMAIL=you@example.com
export TIGERTAG_PASSWORD=yourpassword
export SPOOLMAN_URL=http://192.168.1.10:7912
export DRY_RUN=1                                  # remove for real sync
python3 sync.py
```

---

## 6. Cron / systemd setup

### Cron (every 5 min)

```cron
*/5 * * * *  cd /opt/tigertag-bridge && /usr/bin/python3 sync.py >> /var/log/tigertag-bridge.log 2>&1
```

### systemd service (loop with sleep)

`/etc/systemd/system/tigertag-bridge.service`:

```ini
[Unit]
Description=TigerTag → Spoolman bridge
After=network-online.target

[Service]
Type=simple
User=spoolman
WorkingDirectory=/opt/tigertag-bridge
EnvironmentFile=/opt/tigertag-bridge/.env
ExecStart=/usr/bin/python3 /opt/tigertag-bridge/loop.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

`loop.py`:
```python
import time, sync
while True:
    try: sync.sync()
    except Exception as e: print("error:", e)
    time.sleep(300)
```

### Docker (alongside Spoolman compose)

```yaml
services:
  spoolman:
    image: ghcr.io/donkie/spoolman:latest
    ports: ["7912:7912"]
    volumes: ["./data:/home/app/.local/share/spoolman"]

  tigertag-bridge:
    build: ./bridge
    environment:
      TIGERTAG_EMAIL: ${TIGERTAG_EMAIL}
      TIGERTAG_PASSWORD: ${TIGERTAG_PASSWORD}
      SPOOLMAN_URL: http://spoolman:7912
    depends_on: [spoolman]
    restart: unless-stopped
```

---

## 7. Caveats & ideas

- **One-way only.** This bridge does not push Spoolman weight changes back
  to TigerTag. If you want bidirectional sync, that's a separate project —
  conflicts (both sides modified between syncs) get tricky. The
  `setSpoolWeightByRfid` HTTP endpoint can be used for the reverse path
  if needed.
- **Polling, not realtime.** Firestore exposes a `listen` long-poll API —
  for true realtime sync, swap `requests` for `google-cloud-firestore-async`.
  The complexity bump is significant; cron is enough for 99% of cases.
- **Friend inventories.** You CAN extend the bridge to sync a friend's
  read-only inventory into a separate Spoolman vendor (e.g. prefix
  `external_id` with `friend:{friend_uid}:`). Useful if you and your
  housemate share a printer pool. Always project to non-sensitive fields
  only when reading friends' data.
- **Lookup tables drift.** Re-fetch them weekly from the TigerTag GitHub
  raw URLs. Adding a new brand to TigerTag won't auto-appear in your
  bridge until you refresh.

---

## 8. Going further

Same architecture works for any inventory destination — replace step 7
(Spoolman API calls) with:

- **Home Assistant** REST sensors (PUT to a `tigertag_*` entity helper)
- **InfluxDB / Grafana** for historical weight curves
- **Custom CSV / Google Sheets** for bookkeeping
- **A 3D-printable QR-code label printer** that prints "spool name + colour
  + remaining %" on demand

---

**Verified against:** Tiger Studio Manager v1.4.3 · TigerTag mobile (Flutter) latest · Firestore Rules deployed 2026-05-02 · Spoolman API v1
**Contract version:** [v0.1.3](https://github.com/TigerTag-Project/TigerTag_Firebase_Integration/blob/main/CHANGELOG.md)
**Drift?** Open an issue: https://github.com/TigerTag-Project/TigerTag_Firebase_Integration/issues
