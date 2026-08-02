# BACpypes3 adapter

Containerized [BACpypes3](https://github.com/JoelBender/BACpypes3) peer for [`bacnet-interop`](../..).

**Status:** device-server image available. Pin: `bacpypes3==0.0.106` (`BACPYPES3_VERSION` in Dockerfile).

## Role

Primary **readable** Python semantic oracle for Horizon 1 / current H2 peer surface:

- Independently implemented BACnet application layer for semantic cross-checks
- BACnet/IP device server aligned with `device-baseline-v2` (device + AV-1 + BV-1; TrendLog skipped)
- Who-Has / I-Have, WPM (**adapter-shim**), ReinitializeDevice warmstart SimpleACK
- Optional UnconfirmedEventNotification emit via `BACNET_EMIT_EVENT=1` (**adapter-shim**)
- Discovery and property access for dual-peer evidence alongside bacnet-stack

Neither peer is linked into MIT-licensed `go-bacnet`.

## Target image

```text
bacnet-interop-bacpypes3:local
ghcr.io/otfabric/bacnet-interop-bacpypes3:<version>
ghcr.io/otfabric/bacnet-interop-bacpypes3@sha256:<digest>
```

## Commands

| Mode | Entrypoint | Purpose |
|---|---|---|
| Device server (default) | `device_server.py` | Bind UDP, emit `event=ready`, serve fixture objects |
| Peer-as-BBMD | `BACNET_BBMD=1` | Same server with BBMD + foreign-device table (numeric CIDR BDT self-entry) |
| EventNotification emit | `BACNET_EMIT_EVENT=1` | Emit one UnconfirmedEventNotification after first ReadProperty |

## Readiness contract

Same stdout contract as the bacnet-stack adapter:

```json
{"event":"ready","adapter":"bacpypes3","version":"0.4.1","fixture":"device-baseline-v2","address":"0.0.0.0:47808","peer_version":"0.0.106"}
```

Consumers can swap peers by image name without changing wait logic. See [`PLAN.md`](../../PLAN.md).

## Build

```bash
# from bacnet-interop root
make build-bacpypes3
docker run --rm -p 47808:47808/udp bacnet-interop-bacpypes3:local
# BBMD mode (foreign-device registration tests):
docker run --rm -e BACNET_BBMD=1 bacnet-interop-bacpypes3:local
# EventNotification emit:
docker run --rm -e BACNET_EMIT_EVENT=1 bacnet-interop-bacpypes3:local
```

Environment overrides:

| Variable | Purpose |
|---|---|
| `BACNET_IP_PORT` | UDP port (default 47808) |
| `FIXTURE` / `DEVICE_FIXTURE_FILE` | Fixture id / JSON path |
| `BACNET_DEVICE_ADDRESS` | BACpypes3 address (default `host:<port>`) |
| `BACNET_MAX_APDU` | Small `maxApduLengthAccepted` for segmented-response stress |
| `BACNET_BBMD=1` | Enable BBMD; resolves bind to numeric `IP/16:port` for broadcast/BDT |
| `BACNET_EMIT_EVENT=1` | Emit one UnconfirmedEventNotification after first ReadProperty (**adapter-shim**) |
| `BACNET_NETWORK` | Optional local BACnet network number |
| `ADAPTER_VERSION` / `BACPYPES3_VERSION` | Ready-event version fields |

## Fixture notes

`/fixtures/device/device-baseline-v2.json` is the shared revision identifier
(`device-baseline-v1` frozen). This adapter constructs commandable AV-1
(`present-value` 21.5, COV-capable) and BV-1 (`inactive`) from that JSON;
TrendLog is skipped (no server ReadRange). Stock BACpypes3 raises
`NotImplementedError` for WPM — the adapter installs a **shim** that loops
`write_property`. Upstream gaps (Reject, ReadRange, etc.) are recorded in
[`COVERAGE.md`](../../COVERAGE.md).

## Capability tracking

Update [`COVERAGE.md`](../../COVERAGE.md) and [`inventory.yaml`](../inventory.yaml) when additional modes become smoke-tested.
