# BACnet4J adapter

Containerized [BACnet4J](https://github.com/RadixIoT/BACnet4J) peer for [`bacnet-interop`](../..).

**Status:** fixture-driven device-server image. Pin: `bacnet4j==6.1.0` (`BACNET4J_VERSION` in Dockerfile / pom).

## Role

Primary **Java** semantic oracle for Horizon 1 / current H2 peer surface:

- Independently implemented BACnet application layer (BACnet4J / RadixIoT)
- BACnet/IP device server aligned with `device-baseline-v2` (device + AV-1 + BV-1 + TrendLog)
- Who-Has / I-Have, WPM, ReadRange byPosition, ReinitializeDevice warmstart
- Optional `BACNET_EMIT_EVENT=1` UnconfirmedEventNotification emit (**adapter-shim**)
- Optional peer-as-BBMD (`BACNET_BBMD=1`) and small MaxAPDU for segmentation stress
- Rejects segmented confirmed-request receive (registered gap vs BACpypes3)

`go-bacnet` must never link against BACnet4J. The peer runs only as a separate
image under its upstream license; distribution must preserve that license.

## Layout

| Path | Purpose |
|---|---|
| `src/main/java/.../DeviceServer.java` | Load fixture, bind UDP, emit `event=ready`, serve |
| `pom.xml` | Maven build; shaded runnable jar |
| `Dockerfile` | Multi-stage: Maven package → JRE runtime |

## Target image

```text
bacnet-interop-bacnet4j:local
ghcr.io/otfabric/bacnet-interop-bacnet4j:<version>
ghcr.io/otfabric/bacnet-interop-bacnet4j@sha256:<digest>
```

## Commands

| Mode | Entrypoint | Purpose |
|---|---|---|
| Device server (default) | `java -jar device_server.jar` | Bind UDP, emit `event=ready`, serve fixture objects |
| Peer-as-BBMD | `BACNET_BBMD=1` | Same server with BBMD + BDT self-entry |
| EventNotification emit | `BACNET_EMIT_EVENT=1` | Emit one UnconfirmedEventNotification after first ReadProperty |

## Readiness contract

```json
{"event":"ready","adapter":"bacnet4j","version":"0.4.1","fixture":"device-baseline-v2","address":"<bind-ipv4>:47808","peer_version":"6.1.0"}
```

## Build

```bash
# from bacnet-interop root
make build-bacnet4j
docker run --rm -p 47808:47808/udp bacnet-interop-bacnet4j:local
# BBMD mode:
docker run --rm -e BACNET_BBMD=1 bacnet-interop-bacnet4j:local
# EventNotification emit:
docker run --rm -e BACNET_EMIT_EVENT=1 bacnet-interop-bacnet4j:local
```

Environment overrides:

| Variable | Purpose |
|---|---|
| `BACNET_IP_PORT` | UDP port (default 47808) |
| `FIXTURE` / `DEVICE_FIXTURE_FILE` | Fixture id / JSON path |
| `BACNET_DEVICE_ADDRESS` | Bind IP (default: primary IPv4) |
| `BACNET_MAX_APDU` | Override `maxApduLengthAccepted` (keeps segmentedBoth) |
| `BACNET_BBMD=1` | Enable BBMD with BDT self-entry |
| `BACNET_EMIT_EVENT=1` | Emit one UnconfirmedEventNotification after first ReadProperty (**adapter-shim**) |
| `BACNET_NETWORK` | Optional local BACnet network number |
| `ADAPTER_VERSION` / `BACNET4J_VERSION` | Ready-event version fields |

## Fixture notes

`/fixtures/device/device-baseline-v2.json` is the shared revision
(`device-baseline-v1` frozen). This adapter constructs commandable COV-capable
AV-1, commandable BV-1, and a seeded TrendLogObject for ReadRange byPosition
(alignment: `full-object-graph`).

## Capability tracking

Update [`COVERAGE.md`](../../COVERAGE.md) and [`inventory.yaml`](../inventory.yaml) when modes change.
