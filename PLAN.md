# bacnet-interop — Plan

Single source of truth for **bacnet-interop**-owned deliverables. Consumer
assertions and scenario matrices live in [`go-bacnet`](https://github.com/otfabric/go-bacnet)
(`INTEROP.md`, `interop/`, `PLAN.md`).

Horizon 1 peer set: **bacnet-stack**, **BACpypes3**, and **BACnet4J**. Topology
aid: **bip-router** (not a product router or peer oracle).

Status labels: `done` · `partial` · `open`.

---

## Phase 0 — Repository bootstrap

| Deliverable | Status |
|---|---|
| Ownership docs (`README.md`) | done |
| Fixture provenance schema + manifest | done |
| Adapter documentation | done |
| Makefile validate/build/smoke | done |
| CI fixture validation | done |
| Capability matrix (`COVERAGE.md`) | done (live; not a skeleton) |

---

## Phase 1 — Fixture contract and goldens

| Deliverable | Status |
|---|---|
| Codec goldens under `fixtures/codec/` with provenance | done |
| `fixtures/manifest.json` authoritative index | done |
| Device model `fixtures/device/device-baseline-v1.json` | done |
| Consumed by `go-bacnet/internal/fixtures` | done |
| Full executable semantics for all fixtures | done (consumer go-bacnet; includes service-layer negatives) |
| Strict `deterministic_reencode_equal` / expected error layer | done (consumer + malformed APDU/NPDU/service goldens) |

Equality flags (set per fixture):

| Flag | Meaning |
|---|---|
| `expect.semantic_decode_equal` | Decoded semantic form must match the sidecar / declared structure |
| `expect.deterministic_reencode_equal` | Encode(decode(input)) must equal a deterministic canonical encoding |
| `expect.original_bytes_equal` | Round-trip must preserve original wire bytes (strict; use sparingly) |

Prefer `license.status: independently-generated` or carefully sanitized `capture`.
Reject undocumented vendor dumps.

---

## Phase 2 — Adapter images

| Deliverable | Status |
|---|---|
| bacnet-stack fixture-driven `device_server` | done (`bacnet-stack-1.3.8`) |
| BACpypes3 `device_server.py` | done (`bacpypes3==0.0.98`) |
| BACnet4J `DeviceServer.java` | done (`bacnet4j==6.1.0`) |
| BIP↔BIP topology router (`bip-router`) | done (interop fixture) |
| `device-baseline-v1` shared by all three peers | done |
| `make build` / `make smoke` | done (stack + bacpypes3 + bacnet4j + bip-router) |

### bacnet-stack (`adapters/bacnet-stack`)

- Multi-stage Dockerfile pinning `BACNET_STACK_SHA`.
- Custom `device_server` (not stock `bacserv`) + `run_server.py`.
- Object graph from `device-baseline-v1.json` (alignment: `full-object-graph`).
- Ready event after UDP bind; diagnostics on stderr.

### BACpypes3 (`adapters/bacpypes3`)

- Python image pinning `BACPYPES3_VERSION`.
- Serves device + AV-1 + BV-1 from `device-baseline-v1`.
- Optional `BACNET_MAX_APDU`, `BACNET_BBMD=1` (numeric CIDR BDT), `BACNET_NETWORK`.
- Same readiness / stdout contract as bacnet-stack so `go-bacnet/interop` can
  swap peers by image name.

### BACnet4J (`adapters/bacnet4j`)

- Java image pinning `BACNET4J_VERSION` (Maven artifact from RadixIoT).
- Fixture-driven Device + AV-1 + BV-1; optional BBMD / max-APDU.
- Same readiness / stdout contract as the other peers.

### bip-router (`adapters/bip-router`)

- Dual-homed BACnet/IP router for routed interop topology (nets `1`/`2` by default).
- Who-Is-Router / I-Am-Router, DNET forward, hop decrement, return-path assist.
- Not a product BBMD or general-purpose router.
- Evidence phrasing: validates go-bacnet routed addressing via this topology aid
  with independent endpoint stacks behind it — **not** “proven with independent
  BACnet routers” until a second router implementation or hardware is added.

Fixed-sequence JSON Lines **client probe** adapters remain future work.

---

## Phase 3 — Readiness JSON Lines contract

Freeze the server ready event:

```json
{"event":"ready","adapter":"bacnet-stack","version":"0.1.0","fixture":"device-baseline-v1","address":"0.0.0.0:47808","peer_version":"bacnet-stack-1.3.8"}
```

Required fields:

| Field | Description |
|---|---|
| `event` | Always `"ready"` |
| `adapter` | `bacnet-stack`, `bacpypes3`, `bacnet4j`, or `bip-router` |
| `version` | Adapter image version (`ADAPTER_VERSION` build arg; default `dev`) |
| `fixture` | Fixture revision (`device-baseline-v1` or `topology-router-v1`) |
| `address` | Bind address advertised for consumers (host:port) |

Optional: `peer_version`, and for `bip-router` also `networks` / `addresses`.

Rules:

- Stdout is JSON Lines only; diagnostics on stderr.
- Ready must be emitted **after** the UDP bind / application is live.
- Optional later: `--capabilities` / `--version` one-shot events (mms-interop M1 pattern).

---

## Phase 4 — Horizon 1 live scenarios (consumed by go-bacnet)

Adapter support for scenarios asserted in `go-bacnet/INTEROP.md`:

| Scenario | Status |
|---|---|
| Who-Is / I-Am (directed) | done (all three peers) |
| ReadProperty / RPM / WriteProperty | done (all three peers) |
| Error / Reject / Abort paths | done (Reject: bacnet-stack + BACnet4J; Abort: bacnet-stack + BACpypes3) |
| COV subscribe / notify / cancel (+ renew on BACpypes3) | done |
| Routed remote device (via `bip-router`) | done (all three peers; topology evidence caveat above) |
| Peer-as-BBMD + foreign-device registration aid | done (BACpypes3 + BACnet4J) |
| Segmentation / small max-APDU stress | done (BACpypes3 + BACnet4J) |

Update `COVERAGE.md` as cells change. Known upstream gaps become explicit
limitation rows, never silent passes. See `go-bacnet/INTEROP.md` for the
assertion matrix.

---

## Phase 5 — Publish and pin

| Deliverable | Status |
|---|---|
| Publish all four GHCR images (stack, bacpypes3, bacnet4j, bip-router) | done (`v0.1.0`) |
| Native amd64/arm64 release runners (no QEMU) | done |
| Release `manifest.json` + digests for all peers + topology | done |
| `go-bacnet` CI pins release digests + fixture tag | done (see go-bacnet `interop.yml`) |
| Local `make smoke` ready-event check | done |

First tagged release: [`v0.1.0`](https://github.com/otfabric/bacnet-interop/releases/tag/v0.1.0).

---

## Phase 6 — Evidence integrity (post-review)

This repository validates its own infrastructure only: fixture schema/manifest,
adapter builds, and smoke readiness. It must **never** check out, build, or
test against `go-bacnet`. Consumer assertions, fixture corpus execution, and
peer scenario matrices are owned exclusively by
[`go-bacnet`](https://github.com/otfabric/go-bacnet) (see `interop.yml`).

| Deliverable | Status |
|---|---|
| CI builds **all** adapters via `PLATFORM=linux/amd64 make build` | done |
| CI smoke with `BIP_ROUTER_REQUIRED=1` | done |
| Capture build provenance as CI artifacts | done |
| No CI / Makefile / release path depends on `go-bacnet` | done |
| Single machine-readable adapter inventory (Makefile/CI/release/smoke) | open |

---

## Non-goals

- Checking out, building, or asserting against `go-bacnet` from this repo
  (inverted ownership; forbidden).
- Go library assertions or `-tags=interop` tests (belong in `go-bacnet`).
- Linking peer stacks into MIT Go binaries.
- Vendor hardware claims without recorded evidence.
- Full BBMD/BDT **product** server behaviour in Horizon 1 (peer-as-BBMD for
  FD registration tests is in scope; multi-BBMD failover is not).
- Claiming independent BACnet **router** interoperability from `bip-router` alone.
