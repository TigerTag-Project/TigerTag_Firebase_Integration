# 01 — Firebase project config

Every client (HA, ESP32, Python script) starts by fetching the **public
Firebase config**. This is a standard Firebase pattern — the config is meant
to be public, security is enforced server-side via Firestore Rules and App
Check.

## Endpoint

```http
GET https://tigertag-cdn.web.app/__/firebase/init.json
```

Response shape:

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

## What you need from this

| Field | Used for |
|-------|----------|
| `apiKey` | Auth API calls (`identitytoolkit.googleapis.com`, `securetoken.googleapis.com`) |
| `projectId` | Firestore REST URLs (`firestore.googleapis.com/v1/projects/{projectId}/…`) |
| `authDomain` | Browser-based OAuth flows only (Google Sign-In) — irrelevant for HA / ESP32 |

## Caching

Cache the response client-side **for the lifetime of the integration**.
The values are stable — they only change if the TigerTag team migrates
the Firebase project (rare, typically announced months in advance).

A weekly refresh is more than enough.

## Why is this public?

`apiKey` here is **not** a secret. It identifies the project, not the
caller. The actual access control is:

1. **Authentication** — the client must obtain a valid `idToken` by signing
   in as a real user.
2. **Firestore Security Rules** — the rules see `request.auth.uid` and
   decide what the user can read / write.
3. **(App Check is NOT enforced** on this project — see
   [`05-rate-limiting.md § Why we don't use Firebase App Check`](05-rate-limiting.md#why-we-dont-use-firebase-app-check)
   for the rationale.)

Without a valid `idToken`, the `apiKey` alone gives access to nothing.
