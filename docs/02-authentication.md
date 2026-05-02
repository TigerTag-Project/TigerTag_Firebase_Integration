# 02 — Authentication

TigerTag uses Firebase Authentication. End users sign in with their email +
password (the same credentials they use in the desktop / mobile app).

## Sign-in: email + password

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
  "localId":      "abc123…",     // Firebase UID
  "idToken":      "eyJ…",        // 1-hour JWT
  "refreshToken": "AGqA…",       // long-lived, never expires unless revoked
  "expiresIn":    "3600"
}
```

Store all three:

- `localId` is the user's UID — used everywhere in Firestore paths
  (`users/{uid}/inventory`, etc.)
- `idToken` is sent on every Firestore request as `Authorization: Bearer …`
- `refreshToken` is used to obtain a new `idToken` when the current one
  expires

## Google Sign-In

Google OAuth requires a browser redirect, so it is **not usable directly
from HA, ESP32, or Python scripts**. If your users have only ever signed
in with Google, ask them to set a password on their account first (via the
desktop / mobile app's "Forgot password" flow → reset to a known value).

## Refreshing the idToken

The `idToken` is a JWT signed by Google with a **1-hour TTL**. Refresh it
proactively, or you'll start getting `permission-denied` errors at the
expiry boundary.

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
  "refresh_token": "new-refreshToken",
  "user_id":       "abc123…"
}
```

**Always replace BOTH stored tokens** — the refresh token may rotate.

If the call returns `TOKEN_EXPIRED`, `USER_DISABLED`, or
`INVALID_REFRESH_TOKEN`, erase stored credentials and re-prompt the user
for their password.

## The `permission-denied → retry succeeds` quirk

Even with valid tokens, you may occasionally see a transient
`permission-denied` on the **first** read — especially after a friendship
was just accepted, or right at the 60-min token boundary. This is a Firebase
Auth propagation race.

**Recommended pattern** (used by Tiger Studio Manager v1.4.3+):

```python
LAST_REFRESH = 0
THROTTLE_S   = 30 * 60   # 30 min

def prewarm_token(force=False):
    global LAST_REFRESH
    if not force and time.time() - LAST_REFRESH < THROTTLE_S:
        return
    refresh_id_token()
    LAST_REFRESH = time.time()

def firestore_read(path):
    prewarm_token()
    try:
        return get(path)
    except PermissionDenied:
        prewarm_token(force=True)   # hard refresh
        return get(path)            # retry once
```

Without this, a small percentage of friend reads will fail spuriously and
the user has to "leave and come back".

## Sign-out

There is no explicit sign-out endpoint for the REST API. Just **delete the
stored tokens** locally — that's it. The refresh token will continue to
work until manually revoked from the Firebase Console; if you want hard
revocation, the user must change their password via the mobile/desktop app.
