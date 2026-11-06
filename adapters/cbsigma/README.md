# cB-Sigma adapter

BACnet/IP device peer built on two Apache-2.0 Go modules by cB-Sigma, pinned
by tag in [`go.mod`](go.mod) (the source of truth; the Dockerfile ARGs and
[versions.yaml](../../versions.yaml) repeat it):

| Role (`CBSIGMA_ROLE`) | Upstream | Pin |
|---|---|---|
| `device` (default) | [`github.com/cB-Sigma/bacnet`](https://github.com/cB-Sigma/bacnet) package `device` | `v0.2.0` (`43314a7b`) |
| `sim` | [`github.com/cB-Sigma/bacnet-sim`](https://github.com/cB-Sigma/bacnet-sim) package `sim` | `v0.1.0` (`8ca57e10`), on bacnet `v0.2.0` |

Both are written from ANSI/ASHRAE 135-2024 by one author and share the codec
of `cB-Sigma/bacnet`; they are independent of go-bacnet and of the other
peers here. The upstream README of bacnet-sim calls it "a test device, not a
conformant BACnet server".

```text
go-bacnet client → cB-Sigma device role   (Device object, object-list, names)
go-bacnet client → cB-Sigma simulator     (ReadRange, alarms, BBMD, fault switches)
```

**Do not import `go-bacnet`.** Assertions live in `go-bacnet/interop`.

## What the adapter does

It loads the fixture (`DEVICE_FIXTURE_FILE`, default
`device-baseline-v2`), fills the upstream object table, listens on
`0.0.0.0:47808` (`BACNET_IP_PORT`) and writes the ready event. Everything on
the wire (BVLC, NPDU, APDU, segmentation, the services) is upstream code.
Adapter code is limited to:

- the object table from the fixture: present value (REAL for analog,
  enumerated for binary, Unsigned for multistate), units no-units (95) on
  analog objects, event-state normal and out-of-service FALSE; in the device
  role a writable Description;
- the Trend Log seed of the BACnet4J and Worldiety adapters: 36 records, one
  every 15 minutes from 2024-01-01 00:00:00 UTC, real values 20–55, sequence
  numbers 1–36, no status flags (simulator role only);
- with `CBSIGMA_EVENTS=1` the bodies of the GetAlarmSummary and
  GetEventInformation answers (one alarm: the first analog object in
  high-limit, to-offnormal not acknowledged), which the simulator serves as
  given;
- `{"event":"operation",…}` lines on stdout for what the upstream code
  recorded without an observable reply: `write-property`,
  `time-synchronization`, `utc-time-synchronization`,
  `unconfirmed-text-message`, `unconfirmed-private-transfer`, `write-group`,
  `unconfirmed-event-notification`, `device-communication-control`,
  `reinitialize-device`, `acknowledge-alarm`, `register-foreign-device`.

## Environment

| Variable | Role | Default | Effect |
|---|---|---|---|
| `CBSIGMA_ROLE` | both | `device` | `device` or `sim` |
| `DEVICE_FIXTURE_FILE`, `FIXTURE` | both | v2 | the fixture (v1–v9 are in the image) |
| `BACNET_IP_PORT` | both | 47808 | UDP port |
| `CBSIGMA_MAX_APDU` | both | 1476 | largest APDU sent unsegmented; smaller forces segmented answers |
| `CBSIGMA_WINDOW` | both | 4 | proposed window of segmented answers |
| `BACNET_BBMD=1` | sim | off | BBMD: Register-Foreign-Device, Distribute-Broadcast-To-Network |
| `CBSIGMA_FD_NAK=1` | sim | off | refuse Register-Foreign-Device (Result NAK) |
| `CBSIGMA_FORWARD=1` | sim | off | every reply as a Forwarded-NPDU |
| `CBSIGMA_DROP_SEG=k` | sim | -1 | leave reply segment *k* out, once |
| `CBSIGMA_STALL_SEG=k` | sim | -1 | stop a segmented reply before segment *k*, once |
| `CBSIGMA_REJECT_RPM=1`, `CBSIGMA_REJECT_WPM=1` | sim | off | Reject unrecognized-service |
| `CBSIGMA_REJECT_SEQ=1` | sim | off | ReadRange by sequence number: Error services/optional-functionality-not-supported |
| `CBSIGMA_EVENTS=1` | sim | off | GetAlarmSummary and GetEventInformation with one alarm |

## Device role

`github.com/cB-Sigma/bacnet/device`: Device object (object-list, vendor 999,
protocol revision 24, segmentation both), ReadProperty and
ReadPropertyMultiple (ALL, REQUIRED, OPTIONAL, array indexes),
WriteProperty and WritePropertyMultiple with priority arrays on commandable
objects and datatype checks, SubscribeCOV (confirmed and unconfirmed,
lifetimes, cancellation, an initial notification), Who-Is, Who-Has by name
or identifier, segmented answers and reassembly of segmented requests.
Every other confirmed service is rejected (unrecognized-service): no
ReadRange (the Trend Log is listed with its counters only), files, alarms or
device management.

## Simulator role

`github.com/cB-Sigma/bacnet-sim/sim`. Upstream behaviour to know:

- **No Device object** ("Not simulated: a Device object", upstream README):
  a read of the Device or of any object-name is Error object/unknown-object
  or property/unknown-property. Who-Is is answered from the I-Am the adapter
  sets (fixture instance, vendor 999, Max APDU 1476, segmentation both).
- Who-Has is answered only for the upstream demo object (`OATemp`,
  analog-input 3), not for the fixture's objects.
- Properties: present-value, status-flags, out-of-service, units,
  number-of-states, state-text, record-count, total-record-count. Writes
  only to present-value of outputs and values.
- **Segmentation fault switches:** a dropped segment is never resent and a
  stalled answer is never resumed; the simulator gives up after 2 s without
  a Segment-ACK. A client sees a timeout in both cases.
- DeviceCommunicationControl and ReinitializeDevice are acknowledged and
  recorded, never enforced; a password containing `wrong` is answered with
  Error security/password-failure.
- The trend log keeps at most 50 records.

## Not in scope

BACnet/IPv6 and BACnet/SC: cB-Sigma/bacnet has both, but go-bacnet is a
BACnet/IP (IPv4) client, so the image serves BACnet/IP only. MS/TP is not
simulated upstream.
