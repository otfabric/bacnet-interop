# bacnet-interop

Interoperability **infrastructure** for [`go-bacnet`](https://github.com/otfabric/go-bacnet).

This repository owns adapter images, fixture corpora, and provenance metadata. It does **not** own assertions about the Go library. Interoperability scenarios, pass/fail decisions, and compatibility claims live in [`go-bacnet/interop`](https://github.com/otfabric/go-bacnet/tree/main/interop) and consume the infrastructure published here.

**Ownership direction is one-way:** `go-bacnet` depends on `bacnet-interop`. This repository must never check out, build, import, or CI-test against `go-bacnet`.

```text
               bacnet-interop
          containers + fixtures + provenance
                     |
                     v
                 go-bacnet
                  interop/
           owns -tags=interop assertions
```

Same ownership split as [`mms-interop`](https://github.com/otfabric/mms-interop) relative to `go-mms` / `go-iec61850`.

## Purpose

- Publish reproducible peer adapter images for **bacnet-stack** (C), **BACpypes3** (Python), and **BACnet4J** (Java).
- Provide a dual-homed **bip-router** topology aid for routed BACnet/IP interop.
- Hold golden packet fixtures with explicit provenance and license classification.
- Define the adapter readiness / JSON Lines output contract that consumers wait on.
- Keep peer implementations out of the MIT-licensed Go tree: oracles run in containers, never linked into `go-bacnet`.

## Horizon 1 scope

Aligned with the [`go-bacnet`](https://github.com/otfabric/go-bacnet) Horizon 1 client foundation and current supervisory / H2 peer surface:

| In scope | Deferred |
|---|---|
| BACnet/IP over IPv4/UDP | BACnet/IPv6, MS/TP, BACnet/SC |
| Who-Is / I-Am discovery peers | Full device/server product model |
| Who-Has / I-Have | Product BBMD / BDT management |
| ReadProperty / ReadPropertyMultiple / WriteProperty / WritePropertyMultiple | BTL certification itself |
| ReadRange byPosition (TrendLog; bacnet-stack + BACnet4J) | Vendor hardware claims without evidence |
| Confirmed-request / segmentation stress peers | Multi-BBMD failover |
| EventNotification emit (BACpypes3 / BACnet4J via `BACNET_EMIT_EVENT`) | |
| DeviceCommunicationControl enable (bacnet-stack) | |
| ReinitializeDevice warmstart | |
| Routed network peer (IP↔remote via `bip-router`) | |
| COV subscribe + notifications | |
| Peer-as-BBMD + foreign-device registration aid | |

Do not claim vendor or BTL interoperability from this repository alone. Evidence is produced by `go-bacnet` interop runs against pinned adapter digests.

## Repository structure

```text
bacnet-interop/
├── README.md
├── PLAN.md
├── COVERAGE.md                 # Adapter capability matrix
├── Makefile
├── LICENSE
├── scripts/
│   ├── validate-fixtures.py    # Manifest + schema checks
│   └── smoke-test.sh           # Ready-event smoke for images
├── fixtures/
│   ├── README.md               # Provenance and licensing rules
│   ├── manifest.json           # Codec fixture index + schema version
│   ├── schema/
│   │   └── fixture.schema.json
│   ├── codec/                  # Wire goldens
│   └── device/                 # Live adapter device model (device-baseline-v2; v1 frozen)
└── adapters/
    ├── inventory.yaml          # Peer pins + capability evidence types
    ├── bacnet-stack/           # Fixture-driven C device-server image
    ├── bacpypes3/              # BACpypes3 device-server image (+ optional BBMD)
    ├── bacnet4j/               # BACnet4J device-server image (+ optional BBMD)
    ├── worldiety/              # Worldiety Go peer (fixture-driven; no go-bacnet import)
    └── bip-router/             # Dual-homed BIP↔BIP topology router
```

## Ownership boundary

| Repository | Owns |
|---|---|
| **bacnet-interop** | Docker/adapter images, fixture bytes and semantics, provenance metadata, readiness contract, capability matrix |
| **go-bacnet/interop** | Scenario selection, assertions, skip policy, digest pins, `make interop`, compatibility claims |

Consumer repositories pin a version tag for local use and a digest for CI once images exist:

```bash
# Local development — version tag (once published)
BACNET_STACK_IMAGE=ghcr.io/otfabric/bacnet-interop-bacnet-stack:v0.4.1 make interop

# CI — digest-pinned
BACNET_STACK_IMAGE=ghcr.io/otfabric/bacnet-interop-bacnet-stack@sha256:<digest> make interop
```

## Peers and topology aids

| Image | Role | Upstream / notes |
|---|---|---|
| **bacnet-stack** | Primary executable C oracle (fixture-driven `device_server`) | [bacnet-stack](https://github.com/bacnet-stack/bacnet-stack) |
| **BACpypes3** | Primary readable Python semantic oracle (optional peer-as-BBMD) | [BACpypes3](https://github.com/JoelBender/BACpypes3) |
| **BACnet4J** | Primary readable Java semantic oracle (optional peer-as-BBMD) | [BACnet4J](https://github.com/RadixIoT/BACnet4J) |
| **Worldiety** | Pure-Go peer oracle (native segmentation; fixture payload shims) | [worldiety/bacnet](https://github.com/worldiety/bacnet) @ `3cb2aa80…` |
| **bip-router** | Dual-homed BIP↔BIP topology aid for routed scenarios | Interop fixture only — not a product router |

Additional peers may be added later without changing ownership rules. Worldiety
is a **server peer only** until `go-bacnet` has a server for the reverse direction.

Licensing note: peer stacks retain their upstream licenses inside adapter images. `bacnet-interop` original code and independently generated fixtures are MIT (OT Fabric). Captured or vendor-restricted material must declare `license.status` in fixture metadata and must not be redistributed beyond that classification.

## Adapter contract (target)

Each server-mode adapter emits a single JSON Lines readiness event on stdout before accepting BACnet/IP traffic:

```json
{"event":"ready","adapter":"bacnet-stack","version":"0.4.1","fixture":"device-baseline-v2","address":"0.0.0.0:47808","peer_version":"bacnet-stack-1.6.0"}
```

- Stdout is JSON Lines only (ready events; optional future probe results).
- Diagnostics go to stderr.
- `adapter` is one of `bacnet-stack`, `bacpypes3`, `bacnet4j`, `worldiety`, or `bip-router`.
- Consumers wait for `event=ready`, exercise `go-bacnet`, then stop the container.
- No pre-running compose stack is required for automated interop.
- `bip-router` uses fixture `topology-router-v1` and may include `networks` / `addresses`.

Fixed-sequence JSON Lines **client probe** adapters (mms-interop style) are not packaged yet.

## Fixtures

Fixtures are provenance-tracked corpus entries: hex input and/or semantic sidecars plus metadata describing source implementation, capture context, standard baseline, and equality expectations. See [`fixtures/README.md`](fixtures/README.md) and [`fixtures/schema/fixture.schema.json`](fixtures/schema/fixture.schema.json).

[`fixtures/manifest.json`](fixtures/manifest.json) indexes codec goldens. Live adapter device semantics are documented in [`fixtures/device/device-baseline-v2.json`](fixtures/device/device-baseline-v2.json) (not part of the codec manifest). `device-baseline-v1` remains frozen for historical digests.

## Local commands

```bash
make help               # List targets
make validate-fixtures  # Schema / manifest checks (no Docker)
make build              # Build stack, bacpypes3, bacnet4j, worldiety, bip-router
make smoke              # Start each image, assert ready + Who-Is, stop
```

`SMOKE_ONLY=<adapter>` limits smoke to one peer (used by the candidate
workflow). `SMOKE_WHOIS=0` skips the directed Who-Is probe.

## Upstream candidate probe

Weekly (and `workflow_dispatch`) [Upstream candidates](.github/workflows/candidate.yml)
resolves each peer pin vs latest upstream, builds a candidate image, smokes it
(ready JSON + fixture + directed Who-Is), and writes a **Decision table** Job
Summary (same pattern as `snap7-interop` / `mms-interop`). Release pins are
never mutated.

| Job | Resolves / builds / smokes |
|---|---|
| `bacnet-stack` | newest `bacnet-stack-X.Y.Z` tag on [bacnet-stack/bacnet-stack](https://github.com/bacnet-stack/bacnet-stack) |
| `bacpypes3` | latest [bacpypes3](https://pypi.org/project/bacpypes3/) on PyPI |
| `bacnet4j` | Maven `<release>` from the RadixIoT ias-release repo |
| `Decision table` | pin vs latest + build / ready / Who-Is outcomes |

Build and smoke steps use `continue-on-error` so a broken upstream does not fail
the run. Smoke logs are uploaded as artifacts. Consumer interop stays in
`go-bacnet`. Pin bumps remain a deliberate release decision.

Single-adapter local smoke (candidate mode):

```bash
SMOKE_ONLY=bacnet-stack BACNET_STACK_IMAGE=bacnet-interop-bacnet-stack:candidate \
  ./scripts/smoke-test.sh
```

## Consuming from go-bacnet

Interop tests live under `go-bacnet` with `//go:build interop`. Typical lifecycle:

1. Start adapter container (`docker run`).
2. Wait for the readiness JSON Line on stdout.
3. Exercise the Go client under test.
4. Assert results in `go-bacnet/interop`.
5. Stop the container; retain logs on failure.

```bash
# from bacnet-interop
make build

# from go-bacnet (sibling checkout)
make interop
```

## Prerequisites

- Make
- `python3` for fixture validation
- Docker (for `make build` / `make smoke`)

## License

Original code and documentation in this repository are MIT-licensed unless otherwise noted. See [LICENSE](LICENSE).

Third-party source code, Docker images, and captured fixtures retain their respective upstream licenses and declared `license.status` classifications.
