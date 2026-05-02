# Python CLI integration

Minimal Python REPL example that signs in, lists own spools, and prints
each friend's spool count.

For a richer reference (HA component with polling + sensor entities), see
[home-assistant.md](home-assistant.md). For ESP32 / Arduino, see
[esp32.md](esp32.md).

## Install

```bash
pip install pyrebase4 requests
```

## Minimal client

```python
# tigertag_client.py
import time, requests, pyrebase

CONFIG_URL = "https://tigertag-cdn.web.app/__/firebase/init.json"

def fetch_config():
    return requests.get(CONFIG_URL).json()

class TigerTagClient:
    def __init__(self, email, password):
        cfg = fetch_config()
        self.cfg = cfg
        self.firebase = pyrebase.initialize_app({
            "apiKey":        cfg["apiKey"],
            "authDomain":    cfg["authDomain"],
            "projectId":     cfg["projectId"],
            "databaseURL":   "",
            "storageBucket": cfg["storageBucket"],
        })
        self.auth = self.firebase.auth()
        self.user = self.auth.sign_in_with_email_and_password(email, password)
        self.uid  = self.user["localId"]
        self._last_refresh = time.time()

    def _ensure_token(self, force=False):
        if not force and time.time() - self._last_refresh < 30 * 60:
            return
        self.user = self.auth.refresh(self.user["refreshToken"])
        self._last_refresh = time.time()

    def _firestore_get(self, path):
        self._ensure_token()
        url = (f"https://firestore.googleapis.com/v1/projects/"
               f"{self.cfg['projectId']}/databases/(default)/documents/{path}")
        h = {"Authorization": f"Bearer {self.user['idToken']}"}
        r = requests.get(url, headers=h)
        if r.status_code == 403:
            self._ensure_token(force=True)
            h = {"Authorization": f"Bearer {self.user['idToken']}"}
            r = requests.get(url, headers=h)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _decode(field):
        for k in ("stringValue","booleanValue","timestampValue"):
            if k in field: return field[k]
        if "integerValue" in field: return int(field["integerValue"])
        if "doubleValue"  in field: return float(field["doubleValue"])
        if "nullValue"    in field: return None
        if "arrayValue" in field:
            return [TigerTagClient._decode(v)
                    for v in field["arrayValue"].get("values", [])]
        return None

    def _doc(self, d):
        out = {k: self._decode(v) for k,v in d.get("fields", {}).items()}
        out["_id"] = d["name"].rsplit("/",1)[-1]
        return out

    def own_inventory(self):
        r = self._firestore_get(f"users/{self.uid}/inventory")
        return [self._doc(d) for d in r.get("documents", [])
                if not self._doc(d).get("deleted")]

    def list_friends(self):
        r = self._firestore_get(f"users/{self.uid}/friends")
        return [{"uid": self._doc(d)["_id"],
                 "displayName": self._doc(d).get("displayName")}
                for d in r.get("documents", [])]

    def friend_inventory(self, friend_uid):
        r = self._firestore_get(f"users/{friend_uid}/inventory")
        return [self._doc(d) for d in r.get("documents", [])
                if not self._doc(d).get("deleted")]

# ── usage ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import os, getpass
    email = input("Email: ")
    pwd   = getpass.getpass("Password: ")
    c     = TigerTagClient(email, pwd)
    own = c.own_inventory()
    print(f"\nYour inventory: {len(own)} spools")
    for s in own[:5]:
        print(f"  · {s.get('color_name')} — {s.get('weight_available')}/"
              f"{s.get('capacity')} g")
    print(f"\nFriends:")
    for f in c.list_friends():
        try:
            spools = c.friend_inventory(f["uid"])
            print(f"  · {f['displayName']}: {len(spools)} spool(s)")
        except Exception as e:
            print(f"  · {f['displayName']}: <unable to read — {e}>")
```

## Run

```bash
python tigertag_client.py
Email:    you@example.com
Password: ********

Your inventory: 27 spools
  · Galaxy Black — 750/1000 g
  · Sapphire Blue — 220/1000 g
  ...

Friends:
  · Bob: 14 spool(s)
  · Charlie: 5 spool(s)
```

## Notes

- Tokens are cached in memory only. For a daemon, persist them to disk
  (encrypted!) and restore on startup.
- This example doesn't paginate. If you have > 100 spools, see
  [03-data-model.md](../03-data-model.md) for the `nextPageToken` pattern.
- Lookup tables (brand names, materials, etc.) are not fetched here —
  bundle the static JSON files at build time.
