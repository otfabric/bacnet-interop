# BACpypes3 adapter

Containerized [BACpypes3](https://github.com/JoelBender/BACpypes3) peer for [`bacnet-interop`](../..).

**Status:** device-server image available. Pin: `bacpypes3==0.0.110` (`BACPYPES3_VERSION` in Dockerfile).

## Role

Primary **readable** Python semantic oracle for BACnet/IP interop:

- Independently implemented BACnet application layer for semantic cross-checks
- BACnet/IP device server built from the fixture JSON: Device, commandable
  Analog Value, Binary Value and Analog Input objects. The image ships
  `device-baseline-v1`–`v8`; object types without a local BACpypes3
  implementation the adapter can use (trend-log, notification-class,
  event-enrollment, file, audit-log, life-safety) are skipped with a note on
  stderr
- Who-Has / I-Have, WPM (**adapter-shim**), ReinitializeDevice warmstart SimpleACK
- DeviceCommunicationControl: upstream `DeviceCommunicationControlServices` mixed
  into the adapter's Application, which acknowledges enable, disable and
  disable-initiation and checks the password. Upstream 0.0.110 does **not
  enforce** the state: a "disabled" device keeps answering every request (see
  "DeviceCommunicationControl" below)
- Optional UnconfirmedEventNotification emit via `BACNET_EMIT_EVENT=1` (**adapter-shim**)
- Messaging / time / WriteGroup `do_*` sinks for `device-baseline-v6` emit
  `{"event":"operation",...}` JSONL (**adapter diagnostic**)
- Decode-evidence handlers for VT-Open / VT-Data / VT-Close,
  SubscribeCOVPropertyMultiple and AuditLogQuery, and audit notifications via
  `BACNET_EMIT_AUDIT=1` (**adapter diagnostic**, see "Decode and encode
  evidence" below)
- GetEnrollmentSummary (**adapter-shim**): upstream has the request and ACK
  types but no handler; see "GetEnrollmentSummary" below
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
| Peer-as-BBMD | `BACNET_BBMD=1` | Same server with BBMD + FDT; Read-BDT/FDT + Delete-FDT executable; Write-BDT NAK |
| EventNotification emit | `BACNET_EMIT_EVENT=1` | Emit one UnconfirmedEventNotification after first ReadProperty |
| Audit notification emit | `BACNET_EMIT_AUDIT=1` | Emit one Unconfirmed and one ConfirmedAuditNotification after first ReadProperty |

## Readiness contract

Same stdout contract as the bacnet-stack adapter:

```json
{"event":"ready","adapter":"bacpypes3","version":"0.10.0","fixture":"device-baseline-v2","address":"0.0.0.0:47808","peer_version":"0.0.110"}
```

Consumers can swap peers by image name without changing wait logic.

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
| `BACNET_DEVICE_ADDRESS` | BACpypes3 address (default: the primary IPv4 address with the prefix length of its interface, e.g. `172.19.0.3/16:47808`, so the device listens on its subnet broadcast address). An address given without a prefix gets the interface prefix added |
| `BACNET_MAX_APDU` | Small `maxApduLengthAccepted` for segmented-response stress |
| `BACNET_BBMD=1` | Enable BBMD with a BDT entry for the device's own address |
| `BACNET_EMIT_EVENT=1` | Emit one UnconfirmedEventNotification after first ReadProperty (**adapter-shim**) |
| `BACNET_EMIT_AUDIT=1` | Emit one UnconfirmedAuditNotification and one ConfirmedAuditNotification (two notifications each) after first ReadProperty (**adapter-shim**) |
| `BACNET_NETWORK` | Optional local BACnet network number |
| `BACNET_DCC_PASSWORD` | DeviceCommunicationControl password (unset = upstream checks none) |
| `ADAPTER_VERSION` / `BACPYPES3_VERSION` | Ready-event version fields |

## Behaviour to know

- **Broadcasts:** BACpypes3 opens a broadcast socket only when its address
  carries a prefix length. Since 0.10.0 the adapter adds the prefix of the
  container's interface, so the device answers a subnet-directed Who-Is. Up
  to 0.9.0 it was started as `host:47808` and heard unicast only. It answers
  a Who-Is with a unicast I-Am to the requester.
- **Device wildcard:** a ReadProperty of `device,4194303` is answered with
  Error object/unknown-object.
- **Writes are permissive:** a WriteProperty to an Analog Value's
  `Object_Type` or to the Device `Object_Identifier` is accepted.
- **No handler** for ReadRange, File, CreateObject, list elements, alarm
  summary and event services, or SubscribeCOVProperty.

## GetEnrollmentSummary

BACpypes3 decodes the request (`GetEnrollmentSummaryRequest`) and encodes the
ACK (`GetEnrollmentSummaryACK`); it has no handler and no Event Enrollment
objects, and without the adapter answers Reject unrecognized-service. The
adapter's handler lists one fixed enrollment per Analog Value (out-of-range,
priority 100, notification class 1) and per Binary Value (change-of-state,
priority 200, notification class 2) of the fixture, all in event state normal
and acknowledged, applies the request's five filters to that list, and writes
an operation line `get-enrollment-summary`. The enrollments are not backed by
any event logic: the point is that every filter a client encodes is decoded
by a second implementation.

## WritePropertyMultiple

Stock BACpypes3 raises `NotImplementedError`; the adapter's shim loops
`write_property`. The writes before a failing one stay applied. A failure is
answered with a plain Error, not with the stack's
`WritePropertyMultipleError`, so the client does not learn which write
failed; a write to a property the object does not have ends in Error
device/operational-problem. Both are shortcomings of the shim, not of the
stack.

## Decode and encode evidence (not service execution)

The handlers below run a BACpypes3 decoder on the request and write the
decoded fields in the `operation` line
(`{"event":"operation","adapter":"bacpypes3","operation":…,"result":"accepted","decoder":…,"fields":{…}}`).
None of them executes the service: there is no VT session, no COV-multiple
subscription and no Audit Log object.

BACpypes3 0.0.110 has APDU classes for the VT services only. For
SubscribeCOVPropertyMultiple and the audit services they have the Clause 21
data types but no service class, so the **adapter declares the service
frame** (the context-tagged fields around the upstream type) and the
structured parameters inside are decoded and encoded by the upstream type.
Evidence from those is partial: upstream for the nested parameters,
adapter-declared for the frame.

| Request | `operation` | Decoder | `fields` | Reply |
|---|---|---|---|---|
| VT-Open | `vt-open` | `bacpypes3.apdu.VTOpenRequest` | `vt_class`, `local_vt_session_identifier` | `VTOpenACK`, remote session = local + 100 (mod 256) |
| VT-Data | `vt-data` | `bacpypes3.apdu.VTDataRequest` | `vt_session_identifier`, `vt_new_data_hex`, `vt_data_flag` | `VTDataACK` all-new-data-accepted TRUE, accepted-octet-count = length (BACpypes3 requires the optional count) |
| VT-Close | `vt-close` | `bacpypes3.apdu.VTCloseRequest` | `remote_vt_session_identifiers` | SimpleACK |
| SubscribeCOVPropertyMultiple | `subscribe-cov-property-multiple` | adapter frame + `basetypes.COVMultipleSubscriptionList` | `subscriber_process_identifier`, `issue_confirmed_notifications`, `lifetime`, `max_notification_delay` (null when absent), `cov_subscription_specifications[]` = `monitored_object_identifier{type,instance}`, `cov_references[]` = `property_identifier`, `property_array_index`, `cov_increment`, `timestamped` | SimpleACK; no notification follows (BACpypes3 has no COVNotificationMultiple type) |
| AuditLogQuery | `audit-log-query` | adapter frame + `basetypes.AuditLogQueryParameters` | `audit_log{type,instance}`, `start_at_sequence_number`, `requested_count`, and `by_target{…}` or `by_source{…}` (`operations` = numbers of the bits set) | `AuditLogQuery-ACK` (adapter frame) with two `basetypes.AuditLogRecordResult` records numbered from start-at-sequence-number (100 when absent): log-status {buffer-purged}, then the full audit notification; `no-more-items` TRUE |

With `BACNET_EMIT_AUDIT=1` the first ReadProperty is answered and then
followed by one UnconfirmedAuditNotification and one
ConfirmedAuditNotification to the requester (adapter frame
`notifications [0] SEQUENCE OF`, each `basetypes.AuditNotification`). Both
carry the same two notifications: one with every field set (the content the
bacnet-stack adapter reports, with result property/write-access-denied) and
one with only source-device, operation general and target-device, the target
given as a BACnetAddress (network 7, MAC `0a000001bac0`). Operation lines:
`emit-unconfirmed-audit-notification` (`"result":"sent"`), then
`confirmed-audit-notification-ack` (`"result":"simple-ack"`) when the
requester's SimpleACK completes the transaction.

Not covered: the `time-change` record alternative (BACpypes3 declares it
without its context tag `[2]`), AuthRequest (no upstream type; BACpypes3 has
only the removed Authenticate service) and COVNotificationMultiple (no
upstream type).

## DeviceCommunicationControl

The upstream mixin needs two things from the adapter: it writes its state to
`self.smap`, which `Application` does not have (the adapter aliases it to
`app.asap`; without that every request ends in Error
device/operational-problem), and it reads the password from the private
`device_object._dcc_password`, which `BACNET_DCC_PASSWORD` sets.

What 0.0.110 then does, as asserted by go-bacnet (0.0.106 behaved the same):

| Request | Result |
|---|---|
| enable, disable-initiation, disable (with or without duration) | SimpleACK |
| after "disable" | ReadProperty, WriteProperty, Who-Is and ReinitializeDevice are all still answered and executed |
| password configured, missing or wrong password | Error security/password-failure |
| no password configured | a password in the request is ignored |

The state never takes effect because upstream compares the decoded
enumeration with strings (`apdu.enableDisable == "enable"`), which is never
true. The adapter does not correct that: the point of the image is the
stack's own behaviour.

## Fixture notes

Default `/fixtures/device/device-baseline-v2.json` (`device-baseline-v1`
frozen); select another with `DEVICE_FIXTURE_FILE` and `FIXTURE`. The adapter
constructs a commandable Analog Value (`present-value` 21.5, COV-capable) and
a Binary Value (`inactive`) from the JSON. Stock BACpypes3 raises
`NotImplementedError` for WritePropertyMultiple; the adapter installs a
**shim** that loops `write_property`. Upstream gaps are recorded in
[`PEER_SUPPORT.md`](../../PEER_SUPPORT.md).

## Capability tracking

Update [`PEER_SUPPORT.md`](../../PEER_SUPPORT.md) and [`inventory.yaml`](../inventory.yaml) when additional modes become smoke-tested.
