# BACnet4J adapter

Containerized [BACnet4J](https://github.com/RadixIoT/BACnet4J) peer for [`bacnet-interop`](../..).

**Status:** fixture-driven device-server image. Pin: `bacnet4j==6.1.0` (`BACNET4J_VERSION` in Dockerfile / pom).

## Role

Primary **Java** peer oracle for fixture-driven interop:

- Independently implemented BACnet application layer (BACnet4J / RadixIoT)
- Default fixture `device-baseline-v2` (device + AV-1 + BV-1 + TrendLog)
- Also loads `device-baseline-v3` (AI/NC/EE + AV intrinsic Out_Of_Range highLimit=80) and
  `device-baseline-v4` (File stream/record objects seeded from fixture JSON)
- Who-Has / I-Have, WPM, ReadRange byPosition, ReinitializeDevice warmstart
- Optional `BACNET_EMIT_EVENT=1` UnconfirmedEventNotification emit (**adapter-shim**)
- Optional peer-as-BBMD (`BACNET_BBMD=1`) and small MaxAPDU for segmentation stress
- Rejects segmented confirmed-request receive (registered gap vs BACpypes3)
- AtomicReadFile/WriteFile live (**live-multi-peer** with bacnet-stack; go-bacnet
  `v0.2.3` request + ACK wire)
- CreateObject/DeleteObject for `device-baseline-v5` via fixture `object_lifecycle`
  (registers AV/BV creators; marks `precreated_deletable`)
- AddListElement / RemoveListElement on NC-1 `recipientList`
- GetAlarmSummary after AV intrinsic Out_Of_Range (v3); GetEnrollmentSummary
  with EE-1 (v3); messaging `operation` JSONL sinks (v6; WriteGroup + COV-multiple
  still upstream `NotImplementedException`)

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
| Peer-as-BBMD | `BACNET_BBMD=1` | Same server with BBMD + BDT self-entry; Read/Write-BDT and Read/Delete-FDT executable |
| EventNotification emit | `BACNET_EMIT_EVENT=1` | Emit one UnconfirmedEventNotification after first ReadProperty |

## Readiness contract

```json
{"event":"ready","adapter":"bacnet4j","version":"0.9.0","fixture":"device-baseline-v2","address":"<bind-ipv4>:47808","peer_version":"6.1.0"}
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

Default `/fixtures/device/device-baseline-v2.json` (`device-baseline-v1` frozen).
Override with `DEVICE_FIXTURE_FILE=/fixtures/device/device-baseline-v3.json` (or v4–v8).
This adapter constructs commandable COV-capable AV-1, commandable BV-1, and a
seeded TrendLogObject for ReadRange byPosition. For v3 it also creates AnalogInput,
NotificationClass, EventEnrollment (after `initialize()`), and enables AV
intrinsic reporting. For v4 it seeds File stream/record content under `/tmp`.
For v5 it honors `object_lifecycle`: creatable_types (AV/BV CreateObject
factories), precreated_deletable (e.g. AV-100), and protected core objects.
(alignment: `full-object-graph`).

## Capability tracking

Update [`PEER_SUPPORT.md`](../../PEER_SUPPORT.md) and [`inventory.yaml`](../inventory.yaml) when modes change.
