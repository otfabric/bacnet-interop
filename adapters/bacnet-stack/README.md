# bacnet-stack adapter

Containerized [bacnet-stack](https://github.com/bacnet-stack/bacnet-stack) peer for [`bacnet-interop`](../..).

**Status:** fixture-driven device-server image. Pin: `bacnet-stack-1.6.0` (`BACNET_STACK_SHA` in Dockerfile).

## Role

Primary **executable** C device oracle for BACnet/IP interop:

- Custom `device_server` linked against pinned bacnet-stack (not stock `bacserv`)
- Object graph loaded from fixture JSON (device + AV/BV + optional File + NC + TrendLog)
- Who-Is / I-Am, Who-Has / I-Have, ReadProperty, RPM, WriteProperty, WPM,
  SubscribeCOV, ReadRange byPosition, DeviceCommunicationControl enable,
  ReinitializeDevice warmstart
- AtomicReadFile / AtomicWriteFile (`device-baseline-v4`; posix relative paths)
- CreateObject / DeleteObject (`device-baseline-v5`; AV/BV creatable/deletable)
- AddListElement / RemoveListElement on Notification Class `Recipient_List`
  (NC instances 0..MAX after `Notification_Class_Init`; used with v3 NC-1)
- GetAlarmSummary / GetEventInformation / AcknowledgeAlarm handlers registered
  when `INTRINSIC_REPORTING` is enabled; AV intrinsic Out_Of_Range configured for
  `device-baseline-v3` (main loop calls `Device_local_reporting`)
- GetEnrollmentSummary is **unsupported-upstream** (no stack handler / EE object)
- Messaging (v6): TimeSynchronization / UTC / UnconfirmedPrivateTransfer / WriteGroup
  registered; emits `{"event":"operation",...}` JSONL on stdout (bridged by
  `run_server.py`). TextMessage and ConfirmedPrivateTransfer unsupported-upstream

`go-bacnet` must never link against bacnet-stack. The peer runs only as a separate image under its upstream license; distribution must preserve that license and corresponding source obligations.

## Layout

| Path | Purpose |
|---|---|
| `device_server.c` | Slim BACnet/IP server: Device + Network Port + AV + BV + File + NC + TrendLog |
| `Makefile` | Builds `device_server` against a bacnet-stack source tree |
| `run_server.py` | Loads fixture JSON, starts `device_server`, emits `event=ready` after UDP bind |
| `entrypoint.sh` | `exec python3 run_server.py` |
| `Dockerfile` | Multi-stage build: compile against pinned SHA, minimal runtime |

## Target image

```text
bacnet-interop-bacnet-stack:local
ghcr.io/otfabric/bacnet-interop-bacnet-stack:<version>
ghcr.io/otfabric/bacnet-interop-bacnet-stack@sha256:<digest>
```

## Readiness contract

Stdout is a single JSON Lines ready event after the BACnet/IP UDP socket is bound:

```json
{"event":"ready","adapter":"bacnet-stack","version":"0.9.0","fixture":"device-baseline-v2","address":"0.0.0.0:47808","peer_version":"bacnet-stack-1.6.0"}
```

`device_server` diagnostics go to stderr. See [`PLAN.md`](../../PLAN.md).

## Build

```bash
# from bacnet-interop root
make build-bacnet-stack
docker run --rm -p 47808:47808/udp bacnet-interop-bacnet-stack:local
```

Environment overrides: `BACNET_IP_PORT`, `DEVICE_FIXTURE_FILE`, `FIXTURE`, `ADAPTER_VERSION`, `BACNET_STACK_VERSION`.

## Fixture notes

Images ship `device-baseline-v1`–`v8`. Default runtime fixture is v2
(`device-baseline-v1` remains frozen for historical digests).

- **v4 File:** `run_server.py` materializes stream/record payloads under a
  temp cwd and passes relative paths (bacfile-posix rejects absolute paths).
- **v5 lifecycle:** multiple AV instances (including AV-100); Create/Delete
  handlers registered. AV `Object_Name` is not writable via CreateObject
  initial values on this stack — tests create bare then read Object_Name.
- **v3 NC list:** Notification Class objects are always present after init
  (instances 0 and 1 with default `MAX_NOTIFICATION_CLASSES=2`); Add/Remove
  ListElement target property `Recipient_List` (102).
- Segmentation of ComplexACK is still limited by bacnet-stack TSM behaviour
  (oversized responses Abort with segmentation-not-supported). Reject for
  unrecognized confirmed services is supported and asserted by `go-bacnet/interop`.

Routed RP uses this image as the remote device behind [`bip-router`](../bip-router/README.md).

**BBMD:** `device_server` is built with `BBMD_ENABLED` / `BBMD_CLIENT_ENABLED`.
Upstream `dlenv` seeds a self BDT entry and accepts foreign-device registration
by default (no `BACNET_BBMD` env required). Executable BVLC cells: Read-BDT,
Read-FDT (after FD), Delete-FDT. Write-BDT is NAK at Protocol Revision ≥ 17
(asserted by go-bacnet). Upstream `apps/router` is not packaged in this image.

Environment overrides: `BACNET_IP_PORT`, `DEVICE_FIXTURE_FILE`, `FIXTURE`,
`ADAPTER_VERSION`, `BACNET_STACK_VERSION`, plus upstream BIP envs such as
`BACNET_BDT_ADDR_N` when seeding additional BDT peers.

## Capability tracking

Update [`PEER_SUPPORT.md`](../../PEER_SUPPORT.md) and [`inventory.yaml`](../inventory.yaml) when modes change.
