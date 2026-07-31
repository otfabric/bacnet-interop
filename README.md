# bacnet-interop

Interoperability **infrastructure** for [`go-bacnet`](https://github.com/otfabric/go-bacnet).

This repository owns adapter images, fixture corpora, and provenance metadata. It does **not** own assertions about the Go library. Interoperability scenarios, pass/fail decisions, and compatibility claims live in [`go-bacnet/interop`](https://github.com/otfabric/go-bacnet/tree/main/interop) and consume the infrastructure published here.

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

- Publish reproducible peer adapter images for **bacnet-stack** (C) and **BACpypes3** (Python).
- Hold golden packet fixtures with explicit provenance and license classification.
- Define the adapter readiness / JSON Lines output contract that consumers wait on.
- Keep peer implementations out of the MIT-licensed Go tree: oracles run in containers, never linked into `go-bacnet`.

## Horizon 1 scope

Aligned with the [`go-bacnet`](https://github.com/otfabric/go-bacnet) Horizon 1 client foundation:

| In scope | Deferred |
|---|---|
| BACnet/IP over IPv4/UDP | BACnet/IPv6, MS/TP, BACnet/SC |
| Who-Is / I-Am discovery peers | Full device/server product model |
| ReadProperty / ReadPropertyMultiple / WriteProperty | WritePropertyMultiple unless free |
| Confirmed-request / segmentation stress peers | Alarms, schedules, trends |
| Routed network peer (IP↔remote) | Acting as BBMD / BDT management |
| COV subscribe + notifications | BTL certification itself |
| Forwarded-NPDU receive / optional FD registration | Vendor hardware claims without evidence |

Do not claim vendor or BTL interoperability from this repository alone. Evidence is produced by `go-bacnet` interop runs against pinned adapter digests.

## Repository structure

```text
bacnet-interop/
├── README.md
├── PLAN.md
├── COVERAGE.md                 # Adapter capability matrix (skeleton)
├── Makefile
├── LICENSE
├── scripts/
│   └── validate-fixtures.py    # Manifest + schema checks
├── fixtures/
│   ├── README.md               # Provenance and licensing rules
│   ├── manifest.json           # Fixture index + schema version
│   └── schema/
│       └── fixture.schema.json # Capture / provenance schema
└── adapters/
    ├── bacnet-stack/           # C bacnet-stack adapter (image TBD)
    └── bacpypes3/              # BACpypes3 adapter (image TBD)
```

## Ownership boundary

| Repository | Owns |
|---|---|
| **bacnet-interop** | Docker/adapter images, fixture bytes and semantics, provenance metadata, readiness contract, capability matrix |
| **go-bacnet/interop** | Scenario selection, assertions, skip policy, digest pins, `make interop`, compatibility claims |

Consumer repositories pin a version tag for local use and a digest for CI once images exist:

```bash
# Local development — version tag (once published)
BACNET_STACK_IMAGE=ghcr.io/otfabric/bacnet-interop-bacnet-stack:v0.1.0 make interop

# CI — digest-pinned
BACNET_STACK_IMAGE=ghcr.io/otfabric/bacnet-interop-bacnet-stack@sha256:<digest> make interop
```

## Peers

| Peer | Role | Upstream |
|---|---|---|
| **bacnet-stack** | Primary executable C oracle (server/client/router behaviours) | [bacnet-stack](https://github.com/bacnet-stack/bacnet-stack) |
| **BACpypes3** | Primary readable Python semantic oracle | [BACpypes3](https://github.com/JoelBender/BACpypes3) |

Additional peers (BACnet4J, bacnet-js, …) may be added later without changing ownership rules.

Licensing note: peer stacks retain their upstream licenses inside adapter images. `bacnet-interop` original code and independently generated fixtures are MIT (OT Fabric). Captured or vendor-restricted material must declare `license.status` in fixture metadata and must not be redistributed beyond that classification.

## Adapter contract (target)

Each server-mode adapter emits a single JSON Lines readiness event on stdout before accepting BACnet/IP traffic:

```json
{"event":"ready","adapter":"bacnet-stack","version":"0.1.0","fixture":"device-baseline-v1","address":"0.0.0.0:47808"}
```

- Stdout is JSON Lines only (ready events, operation results).
- Diagnostics go to stderr.
- Consumers wait for `event=ready`, exercise `go-bacnet`, then stop the container.
- No pre-running compose stack is required for automated interop.

Client-mode adapters emit one JSON Line per fixed-sequence operation (`ok`, `operation`, optional `value` / `error`), matching the mms-interop style.

## Fixtures

Fixtures are provenance-tracked corpus entries: hex input and/or semantic sidecars plus metadata describing source implementation, capture context, standard baseline, and equality expectations. See [`fixtures/README.md`](fixtures/README.md) and [`fixtures/schema/fixture.schema.json`](fixtures/schema/fixture.schema.json).

The empty [`fixtures/manifest.json`](fixtures/manifest.json) indexes committed fixtures. Codec and scenario fixtures grow with `go-bacnet` Stages 1–6; device-model fixtures for live adapters land when images exist.

## Local commands

```bash
make help               # List targets
make validate-fixtures  # Schema / manifest checks (no Docker)
make build              # Adapter images TBD (stub)
make smoke              # Adapter smoke TBD (stub)
```

## Consuming from go-bacnet

Interop tests live under `go-bacnet` with `//go:build interop`. Typical lifecycle once adapters ship:

1. Start adapter container (`docker run`).
2. Wait for the readiness JSON Line on stdout.
3. Exercise the Go client under test.
4. Assert results in `go-bacnet/interop`.
5. Stop the container; retain logs on failure.

## Prerequisites

- Make
- `python3` and/or `jq` for fixture validation
- Docker (later, when adapter images exist)

## License

Original code and documentation in this repository are MIT-licensed unless otherwise noted. See [LICENSE](LICENSE).

Third-party source code, Docker images, and captured fixtures retain their respective upstream licenses and declared `license.status` classifications.
