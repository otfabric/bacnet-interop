# bacnet-stack adapter

Containerized [bacnet-stack](https://github.com/bacnet-stack/bacnet-stack) peer for [`bacnet-interop`](../..).

**Status:** fixture-driven device-server image. Pin: `bacnet-stack-1.6.1` (`BACNET_STACK_SHA` in Dockerfile).

## Role

Primary **executable** C device oracle for BACnet/IP interop:

- Custom `device_server` linked against pinned bacnet-stack (not stock `bacserv`)
- Object graph loaded from fixture JSON (device + AV/BV + optional File + NC + TrendLog)
- Who-Is / I-Am, Who-Has / I-Have, ReadProperty, RPM, WriteProperty, WPM,
  SubscribeCOV, ReadRange byPosition / bySequenceNumber / byTime,
  DeviceCommunicationControl enable (a "disable" request is refused with
  Error services/service-request-denied: the value was removed from the
  standard at Protocol_Revision 20 and the adapter builds revision 28),
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

Stdout carries JSON Lines. The first line is the ready event, written after
the BACnet/IP UDP socket is bound:

```json
{"event":"ready","adapter":"bacnet-stack","version":"0.10.0","fixture":"device-baseline-v2","address":"0.0.0.0:47808","peer_version":"bacnet-stack-1.6.1"}
```

After it, one `{"event":"operation","adapter":"bacnet-stack","operation":"…","result":"accepted"}`
line is written for each request that has no observable reply
(TimeSynchronization, UTCTimeSynchronization, UnconfirmedPrivateTransfer,
WriteGroup, Who-Am-I, You-Are): evidence that the stack decoded the request.
`device_server` diagnostics go to stderr.

## Build

```bash
# from bacnet-interop root
make build-bacnet-stack
docker run --rm -p 47808:47808/udp bacnet-interop-bacnet-stack:local
```

Environment: `BACNET_IP_PORT`, `DEVICE_FIXTURE_FILE`, `FIXTURE`,
`ADAPTER_VERSION`, `BACNET_STACK_VERSION`, plus the upstream BACnet/IP
variables such as `BACNET_BDT_ADDR_N` for additional BDT peers.

## Behaviour to know

- **Broadcasts:** the stack receives the subnet-directed broadcast only. A
  Who-Is sent to 255.255.255.255 is not answered. Its own I-Am is a
  subnet-directed broadcast to UDP 47808.
- **Device wildcard:** a ReadProperty of `device,4194303` is answered with the
  device's own identifier.
- **No segmentation:** a reply that does not fit the client's Max APDU is
  refused with Abort segmentation-not-supported.
- **Analog Value:** not commandable (`Priority_Array` is an unknown property);
  the Device `Object_Identifier` is writable.
- **AcknowledgeAlarm** with a time stamp that does not match the event is
  answered with Abort (reason other), not with an Error.
- **Who-Am-I / You-Are:** the adapter registers handlers that call the
  upstream decoders and write an `operation` line. There is no upstream
  behaviour behind them.

## Audit evidence (decode / encode evidence, not service execution)

bacnet-stack 1.6.1 ships the audit **data types** in
`src/bacnet/bacaudit.c` (`bacnet_audit_log_notification_encode/_decode`,
`bacnet_audit_log_record_encode/_decode`) but no audit **service**: there is
no codec for the ConfirmedAuditNotification / UnconfirmedAuditNotification /
AuditLogQuery frames, no handler, and no AuditLogQuery parameter decoder. The
adapter writes only those frames (opening and closing tags, sequence numbers,
the boolean) with the stack's primitive encoders; every
BACnetAuditNotification and BACnetAuditLogRecord is produced by the upstream
encoder. There is no Audit Log object behind any of it.

| Trigger | What the adapter does | `operation` lines |
|---|---|---|
| `BACNET_EMIT_AUDIT=1`, then the first ReadProperty | Answers the ReadProperty, then sends the requester one UnconfirmedAuditNotification and one ConfirmedAuditNotification, each `notifications [0] { one BACnetAuditNotification }` with every optional field set | `emit-unconfirmed-audit-notification` and `emit-confirmed-audit-notification` (`"result":"sent"`, `"encoder":"bacnet_audit_log_notification_encode"`, `"service_request_hex"`), then `confirmed-audit-notification-ack` (`"result":"simple-ack"`, `"invoke_id"`) when the requester's SimpleACK arrives |
| AuditLogQuery (confirmed 33) | Reads the `audit-log [0]` identifier only and answers an AuditLogQuery-ACK with three records, sequence numbers 100-102: log-status {buffer-purged}, the audit notification above, time-change 1.5; `no-more-items` TRUE | `audit-log-query` with `"request_decoder":"none"`, `"ack_record_encoder":"bacnet_audit_log_record_encode"`, `"audit_log":"<type>:<instance>"`, `"ack_hex"` |

The notification: source-timestamp sequence 7, target-timestamp
2026-10-10 12:30:00.00, source-device and target-device the Device object,
source-object the Device object, operation write (1), comments
`interop-source` / `interop-target`, invoke-id 5, user id 1001, user role 3,
target-object `analog-value,1`, target-property present-value, priority 8,
target-value REAL 42.5, current-value REAL 21.5, result success.

Two things to know about the upstream encoder: it always encodes every
optional field, and it encodes `result [16]` as a bare enumeration (the error
code) rather than the `Error` sequence BACpypes3 and Wireshark use.

`AuditLogQuery` query parameters are **not** decoded by this adapter: the
operation line says `"request_decoder":"none"`. It is evidence for the ACK
only.

## Fixture notes

Images ship `device-baseline-v1`–`v9`. Default runtime fixture is v2
(`device-baseline-v1` remains frozen for historical digests).

- **v9 large model:** the v2 objects plus `AV-LARGE-101..120` and
  `BV-LARGE-101..120` (up to 64 AV and 64 BV objects per fixture). With the
  adapter's own `network-port:1` and `notification-class:0..1` the
  Object_List has 47 entries (235 octets of identifiers). The stack cannot
  segment: a client advertising Max_APDU 50 gets
  `Abort segmentation-not-supported` for the whole-array ReadProperty and for
  any ReadPropertyMultiple whose reply exceeds 50 octets, while
  `object-list[0]` and single elements are served. Select it with
  `DEVICE_FIXTURE_FILE=/fixtures/device/device-baseline-v9.json`
  `FIXTURE=device-baseline-v9`.

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

## Trend Log seeding

`trend-log:0` (`MAX_TREND_LOGS=1`) is the same in every fixture and on every
run. The records are the ones upstream `Trend_Log_Init()` seeds; the adapter
cannot replace them without patching upstream (the buffer is static to
`trendlog.c`), so it freezes them instead: `device_server` never calls
`trend_log_timer()`, hence no sample is ever taken. (Upstream would not log
either: the seeded `Stop_Time` is 2020-12-22.)

| Property | Value |
|---|---|
| `Record_Count` / `Buffer_Size` | 1000 |
| `Total_Record_Count` | 10000 |
| Sequence numbers | 9001 (oldest) … 10000 (newest) |
| Record at position *k* (1-based) | time stamp `2009-01-01 00:00:00` + (*k*−1) × 15 min, logDatum REAL *k*−1, statusFlags present and all clear |
| Newest record | `2009-01-11 09:45:00`, REAL 999 |

ReadRange behaviour observed with this log (asserted by `go-bacnet/interop`):

- One reply holds at most 66 of these records at the stack's Max_APDU 1476;
  a larger request returns 66 with `MORE_ITEMS`.
- bySequenceNumber: a range starting before 9001 is moved up to 9001; a range
  past 10000 returns `itemCount 0` without `firstSequenceNumber`.
- byTime, positive count: records with a time stamp strictly after the
  reference. Negative count: records strictly before it.
- A client can still change the log (for example writing `Enable` or
  `Record_Count`); each such write inserts a log-status record stamped with
  the wall clock. Tests that need the table above must not write to the log.

Routed RP uses this image as the remote device behind [`bip-router`](../bip-router/README.md)
or behind the native [`bacnet-stack-router`](../bacnet-stack-router/README.md).

**BBMD:** `device_server` is built with `BBMD_ENABLED` / `BBMD_CLIENT_ENABLED`.
Upstream `dlenv` seeds a self BDT entry and accepts foreign-device registration
by default (no `BACNET_BBMD` env required). Executable BVLC cells: Read-BDT,
Read-FDT (after FD), Delete-FDT. Write-BDT is NAK at Protocol Revision ≥ 17
(asserted by go-bacnet). Upstream `apps/router` is packaged as its own image:
[`bacnet-stack-router`](../bacnet-stack-router/README.md).

## Capability tracking

Update [`PEER_SUPPORT.md`](../../PEER_SUPPORT.md) and [`inventory.yaml`](../inventory.yaml) when modes change.
