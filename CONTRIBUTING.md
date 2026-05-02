# Contributing

Two audiences contribute to this repo:

- **Third-party integrators** — devs building HA components, scripts, or
  hardware projects on top of TigerTag. They typically file issues / PRs
  to clarify docs or add new client recipes.
- **The TigerTag team** — maintainers of the desktop app, mobile app, and
  Firebase backend. They own the contract this repo documents and are
  responsible for keeping it accurate.

This document covers both, with separate guidance below.

---

## For third-party integrators

### Reporting documentation drift

If you observe a behaviour in production that contradicts what's
documented, **open an issue first** — do not assume the production is
correct and silently work around the docs. We'd rather know about a
regression than have everyone duplicate the same workaround.

Useful information for a drift report:

- Which doc page disagrees (`docs/03-data-model.md`, etc.)
- The exact path you read / wrote
- The actual response (sanitised — strip `idToken`, `privateKey`, etc.)
- Tiger Studio Manager / mobile app version you cross-checked against

### Adding a new client recipe

We welcome guides for any platform. Open a PR adding a new file in
`docs/clients/<your-platform>.md` plus an optional runnable example in
`examples/<your-platform>/`. Please:

- Mirror the structure of existing client docs (auth, schema, mapping,
  full code, deployment).
- Use English. Comments, log lines, examples — all English.
- Don't include any user's real data, screenshots with private codes, or
  hardcoded credentials.
- Sensitive fields (printer passwords, etc.) get the same explicit
  warnings used in `docs/03-data-model.md § printers`.

### Style

- Markdown, tables for schemas, fenced code blocks with a language hint.
- Line wrap at ~80 chars for prose so `git diff` is readable.
- One commit message line ≤ 72 chars; body wrapped at 72.
- No `Co-Authored-By` lines (project convention).

---

## For the TigerTag team

### When you change the contract

A "contract change" is anything visible to a third-party client:

- New / renamed / removed Firestore collection or field
- New / removed / changed Firestore Security Rule
- New / changed authentication flow
- New / removed Cloud Function HTTPS endpoint
- New supported brand in `printers/{brand}/devices`
- Lookup table additions (id_brand, id_material, etc.)

**Process:**

1. Make the code change in the relevant private repo
   (`TigerTag_Firebase_Backend`, `tigertag_connect1`, etc.).
2. **In the same PR / release window**, open a PR here updating:
   - The relevant section of `docs/03-data-model.md`,
     `docs/04-friend-system.md`, etc.
   - The `rules/firestore.rules` snapshot if rules changed.
   - An entry under `[Unreleased]` in `CHANGELOG.md`.
3. Get review (one approver from a different role — backend dev should
   review docs PRs from mobile dev and vice-versa).
4. Merge here **before** deploying the production change. If the change
   is already in prod, merge here within 24 h and tag the release as a
   patch (`x.y.Z`).

### Cutting a release

1. Move all `[Unreleased]` entries into a new `[x.y.z] — YYYY-MM-DD`
   block in `CHANGELOG.md`.
2. Bump the version. Increment **major** for breaking changes (rare),
   **minor** for additive changes, **patch** for doc-only fixes.
3. `git tag vx.y.z && git push origin vx.y.z`.
4. (Optional) Create a GitHub Release with the changelog snippet pasted
   into the description.

### Keeping `rules/firestore.rules` in sync

The deployed source is in `TigerTag_Firebase_Backend/firestore.rules`
(private repo, French comments). The public mirror is here in
`rules/firestore.rules` (English comments).

**Manual sync today**: when the deployed file changes, copy it here, run
the rule logic through review, translate the comments to English, commit.

**Roadmap**: a CI job in this repo that fetches the deployed rules via
`firebase rules:list` (read-only credential), compares to the public
snapshot, and fails the build on drift > 24 h. Track in
[issue #X — "Automate rules drift detection"].

### Verifying docs against a release

Before tagging a Tiger Studio Manager or mobile app release, run the
matching checks here:

| Surface | How to verify |
|---------|---------------|
| Field names in `inventory/{spoolId}` | grep the desktop / mobile sources for the documented field, confirm presence. |
| Friend access works | sign in as 2 test users, accept friendship, confirm the documented read returns 200 not 403. |
| Lookup IDs valid | every brand_id used in production resolves through `data/id_brand.json` in the desktop repo. |
| Rate-limiting recipes still apply | confirm `request.query.limit` works as documented (run the example client against staging). |

Update the "Last verified against" cell in the README's status table
with the new app version.

### Internal vs public

The private rules file (in `TigerTag_Firebase_Backend`) keeps French
comments — that's our internal source. The public mirror keeps English.
Keeping them functionally identical is what matters; the comments diverge
linguistically by design.

If a third-party developer files an issue based on the public file, you
respond by checking the deployed file is the source of truth, then either
fix the public mirror (if it drifted) or open a backend PR (if the rule
was wrong in production).

---

## Code of conduct

This project follows the spirit of the
[Contributor Covenant](https://www.contributor-covenant.org/). Be kind,
assume good faith, and remember that integration developers are usually
trying to make TigerTag more useful — even when their issue starts with
"this is broken."
