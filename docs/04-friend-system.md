# 04 — Friend system

This is the part most third-party developers misunderstand. Read carefully.

## TL;DR

When Alice accepts Bob's friend request, **two Firestore docs** are written
in one batch:

```
users/alice/friends/bob   ← Alice keeps a record of Bob (incl. Bob's privateKey)
users/bob/friends/alice   ← Bob   keeps a record of Alice
```

When Alice tries to read Bob's `inventory`, the Firestore rule checks:

```
exists(users/bob/friends/alice)
```

If yes → Alice is in Bob's friends list → access granted. If Bob unfriends
Alice (deletes the doc) → access immediately denied.

That's the whole system.

## The actors

```
publicKey   "4X7-K3M"        ← shareable discovery code, owner-defined
privateKey  "a1b2c3...40hex" ← SECRET access token, never displayed
```

Each user has both. The `publicKey` is the human-friendly code you give a
friend ("Hey, my code is 4X7-K3M, add me!"). The `privateKey` is a 40-char
hex string the user never sees — it lives only in their `users/{uid}` doc
(owner-only readable) and gets copied into friends' lists when relationships
form.

## The flow

### 1. Discovery
Alice wants to add Bob. Bob shares his `publicKey` ("4X7-K3M").

### 2. Lookup
Alice's client reads `publicKeys/4X7-K3M` → gets `{ uid: "bob_uid" }`.
This collection is signed-in readable — anyone can resolve a code.

### 3. Friend request
Alice writes:
```
users/{bob_uid}/friendRequests/{alice_uid} = {
  displayName:  "Alice",
  requestedAt:  serverTimestamp(),
  key:          alice.privateKey,   ← used at acceptance time
}
```
Firestore rule allows this if Alice is **not blacklisted** by Bob.

### 4. Acceptance (or refusal)
Bob's app shows the incoming request. If Bob accepts, two writes happen
in one batch:

```
// Bob writes Alice's data into his own friends list
users/{bob_uid}/friends/{alice_uid} = {
  displayName: "Alice",
  addedAt:     serverTimestamp(),
  key:         alice.privateKey,    ← copied from the request
}

// Bob also writes Alice's reciprocal entry on her side
users/{alice_uid}/friends/{bob_uid} = {
  displayName: "Bob",
  addedAt:     serverTimestamp(),
  key:         bob.privateKey,      ← Bob's own privateKey
}
```
Then `users/{bob_uid}/friendRequests/{alice_uid}` is deleted.

The rule that allows Bob to write into Alice's friends list:
```javascript
match /users/{userId}/friends/{friendId} {
  allow create: if request.auth != null
    && request.auth.uid == friendId
    && exists(/databases/$(db)/documents/users/$(request.auth.uid)/friendRequests/$(userId));
}
```
Translation: "Bob (auth.uid) can write into Alice's friends list IF Alice
has a pending friend request from Bob." Without that pending request, Bob
can't self-add to anyone.

### 5. Read access
Alice now wants to read Bob's spools:
```
GET users/{bob_uid}/inventory
```
The rule:
```javascript
match /users/{userId}/inventory/{itemId} {
  allow read: if isOwner(userId)
    || get(/databases/$(db)/documents/userProfiles/$(userId)).data.isPublic == true
    || (request.auth != null
        && exists(/databases/$(db)/documents/users/$(userId)/friends/$(request.auth.uid)));
}
```
Alice's request: `request.auth.uid == alice_uid`, `userId == bob_uid`. The
existence check `users/bob/friends/alice` is true → access granted.

### 6. Removal
Either party can remove the friendship. Symmetrically the rule allows:
```javascript
match /users/{userId}/friends/{friendId} {
  allow delete: if isOwner()
    || (request.auth != null && request.auth.uid == friendId);
}
```
Alice can delete `users/{bob}/friends/{alice}` (= remove herself from Bob's
list) or `users/{alice}/friends/{bob}` (= remove Bob from her own list).
Removing one side stops her access; for full bidirectional cleanup the
client should delete both.

## Why is the `key` field stored in friends/{uid}?

Historical / defense-in-depth. The current Security Rules use the simpler
`exists(...)` check — they don't actually compare keys. So `key` is mostly
informational: it lets the friend's client know "this is the privateKey
that authorized me at accept time" if a future stricter rule needs it.

If the team decides later to strengthen rules (e.g. "key must equal current
privateKey, so rotating your privateKey kicks all friends"), the data is
already in place. For now: treat `key` as opaque, never display it, never
trust it for anything client-side.

## Public inventory (no friendship)

Users can flip a global "make my inventory public" toggle. This sets
`userProfiles/{uid}.isPublic = true`. The rule then allows ANY signed-in
user to read their inventory without a friend request. Useful for public
makers / community sharing.

Your client should respect `userProfiles/{uid}.isPublic`:
- True → show inventory in a "discover" view
- False → require explicit friend acceptance

## What you CANNOT do as a friend

Read access only. You cannot:

- Update / delete a friend's spool
- Modify their racks
- See their `users/{uid}` root doc (privateKey, email — owner-only)
- Read their `friendRequests` (private to them)
- Read their `blacklist`
- Read their `prefs`
- See their `apiKeys`

If your client tries any of the above on a friend's account, Firestore
returns `permission-denied`.

## Common edge cases

- **Friendship just accepted, immediately try to read** — the bidirectional
  doc may not have propagated yet. Handle with one retry after 1 s.
- **Friend deletes their account** — your `users/{me}/friends/{friendUid}`
  doc still exists (orphan), but their data is gone. Reading their inventory
  returns 404 / empty.
- **You're blacklisted after being friends** — blacklist doesn't auto-revoke
  friendship. The other party must explicitly delete the friend doc for
  access to drop. (Or your client can offer a "block + unfriend" combined
  action, which most apps do.)
