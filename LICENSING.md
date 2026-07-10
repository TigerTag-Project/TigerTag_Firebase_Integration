# Licensing

This repository exists to be **copied**. It is the reference for third-party clients that connect
to a user's TigerTag account — an ESP32, a Home Assistant dashboard, a Python script, a home-built
scale, a Spoolman bridge.

So the licensing has one job: get out of your way.

If you only read one line, read this one:

> **Copy the examples. Ship them. You owe us nothing.**

---

## What is under what

This repository holds two kinds of material, and they are not under the same licence.

| Material | Licence |
|---|---|
| **Documentation** — `README.md`, `docs/**`, `examples/**/README.md`, `CHANGELOG.md`, `CONTRIBUTING.md` | [**CC-BY-4.0**](LICENSES/CC-BY-4.0.txt) |
| **Code** — `rules/*.rules`, and every code snippet inside the documentation | [**Apache-2.0**](LICENSES/Apache-2.0.txt) |

Documentation is a document, so it carries a document licence. Code is code, so it carries a code
licence — Apache-2.0, the same as the [JavaScript](https://github.com/TigerTag-Project/TigerTag-SDK-JS)
and [Python](https://github.com/TigerTag-Project/TigerTag-SDK-Python) SDKs. Its express patent grant
is what a manufacturer's legal team needs before embedding this in a product.

---

## Code snippets: no attribution required

Every snippet in these pages — the ESP32 sketch, the Home Assistant YAML, the Python CLI, the
Firestore rules — is Apache-2.0, and we waive the attribution notice for snippets pasted into your
own project.

You should not have to reason about copyright to paste eight lines of YAML. Take them.

If you redistribute a substantial portion of this repository as a whole, keep the licence and the
notice. That is the only case where it matters.

---

## What this licence does **not** cover

- **The TigerTag name and logo.** See [`TRADEMARK.md`](https://github.com/TigerTag-Project/TigerTag-RFID-Guide/blob/main/TRADEMARK.md)
  in the protocol repository. You may say your project is *"compatible with TigerTag"*. You may not
  put our logo on a product as a mark of authenticity without written authorization.
- **The TigerTag service itself** — the Firebase project, the API and the catalogue are operated by
  TigerTag Corp. This repository documents how to talk to them; it does not license them.
- **The TigerTag+ signature.** Anyone may *verify* a signature offline. Only TigerTag Corp may
  *issue* one — we hold the private key.

---

## The protocol

The TigerTag RFID protocol itself lives in
[`TigerTag-RFID-Guide`](https://github.com/TigerTag-Project/TigerTag-RFID-Guide). It is **CC-BY-4.0**,
and it carries an **irrevocable, worldwide, royalty-free right to implement it** in any product, open
source or proprietary, without asking anyone.

See [`LICENSING.md`](https://github.com/TigerTag-Project/TigerTag-RFID-Guide/blob/main/LICENSING.md).
