# bacnet-interop

Reproducible BACnet/IP peer images and fixtures for
[`go-bacnet`](https://github.com/otfabric/go-bacnet) interoperability testing.

This repository publishes containers, device/topology fixtures, and provenance
metadata. Pass/fail assertions and compatibility claims live in go-bacnet
(`INTEROP.md`, `interop/`). **Ownership is one-way:** go-bacnet depends on
bacnet-interop; this repository must never import or CI-test against go-bacnet.

**Latest images:** [v0.8.0](https://github.com/otfabric/bacnet-interop/releases/tag/v0.8.0)

## Peers

| Peer | Upstream | Role |
|---|---|---|
| bacnet-stack | 1.6.0 (C) | Device oracle |
| BACpypes3 | 0.0.106 (Python) | Device oracle (+ BBMD) |
| BACnet4J | 6.1.0 (Java) | Device oracle (+ BBMD) |
| Worldiety | `3cb2aa80` (Go) | Native transport/ASE; fixture object model for some services |
| bip-router | topology aid | Dual-homed BIP↔BIP routing only |

Capability matrix: [PEER_SUPPORT.md](PEER_SUPPORT.md).

## Fixture scenarios

Device baselines under `fixtures/device/`:

| Fixture | Adds |
|---|---|
| v1 | Basic Device, AV and BV (frozen) |
| v2 | Trend Log (default) |
| v3 | Notification Class, Event Enrollment, alarms |
| v4 | File objects |
| v5 | Object lifecycle and list mutation |
| v6 | Messaging and synchronization |
| v7 | Identity |
| v8 | Life safety |

Topology and BBMD fixtures: `fixtures/topology/`, `fixtures/bbmd/`. Codec goldens:
`fixtures/codec/` (see [fixtures/README.md](fixtures/README.md)).

## Build and smoke

```bash
make validate-fixtures
make smoke          # ready-event smoke for published/local images
```

Adapter-specific build notes: `adapters/<peer>/README.md`.

## Consumer contract

Adapters emit JSON Lines readiness events. Example:

```json
{"event":"ready","adapter":"bacnet-stack","version":"0.8.0","peer_version":"bacnet-stack-1.6.0"}
```

Pin digests in the consuming repository (go-bacnet
`interop/bacnet-interop-pin.json`):

```bash
# Local — version tag
BACNET_STACK_IMAGE=ghcr.io/otfabric/bacnet-interop-bacnet-stack:v0.8.0

# CI — digest
BACNET_STACK_IMAGE=ghcr.io/otfabric/bacnet-interop-bacnet-stack@sha256:…
```

Open work: [BLOCKERS.md](BLOCKERS.md). Forward plan: [PLAN.md](PLAN.md).

## Repository layout

```text
bacnet-interop/
├── README.md
├── PEER_SUPPORT.md
├── BLOCKERS.md
├── PLAN.md
├── Makefile
├── scripts/
├── fixtures/
└── adapters/
    ├── inventory.yaml    # build/release input (not public truth)
    ├── bacnet-stack/
    ├── bacpypes3/
    ├── bacnet4j/
    ├── worldiety/
    └── bip-router/
```

## License

See [LICENSE](LICENSE). Peer upstream licenses remain their own; adapters run in
containers and are not linked into go-bacnet.
