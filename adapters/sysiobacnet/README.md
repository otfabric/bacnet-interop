# System.IO.BACnet adapter

Containerized [System.IO.BACnet](https://github.com/ela-compil/BACnet) peer for
[`bacnet-interop`](../..): the C#/.NET stack behind YABE, NuGet package id
`BACnet`.

**Status:** fixture-driven device-server image. Pin: `BACnet` **4.0.0**
(`SYSIOBACNET_VERSION` in the Dockerfile, exact-version reference in
`DeviceServer.csproj`). Upstream licence: MIT.

## Role

A fifth peer of independent lineage (C#), used as a device oracle:

- BVLC, NPDU, APDU, request dispatch, Reject/Abort, segmentation in both
  directions and every service codec are the NuGet package's own.
- The object model is the package's `System.IO.BACnet.Storage.DeviceStorage`
  (the storage its `BasicServer` and `Bacnet.Room.Simulator` examples serve
  from), built from the fixture JSON instead of an XML descriptor.
- The adapter supplies the fixture loading and the handlers between
  `BacnetClient` events and `DeviceStorage`, following the upstream examples.

Nothing of the upstream source is vendored: the package is restored from
nuget.org at build time. `go-bacnet` never links against it.

## Layout

| Path | Purpose |
|---|---|
| `src/Program.cs` | Environment, transport, ready event, shutdown |
| `src/DeviceModel.cs` | Fixture JSON → `DeviceStorage` objects; Trend Log buffer and File contents |
| `src/DeviceServer.cs` | Service handlers (the glue) |
| `src/StderrLogging.cs` | stderr sink for the stack's log output |
| `DeviceServer.csproj`, `nuget.config` | Exact package pins, nuget.org only |
| `Dockerfile` | .NET 10 SDK build stage → .NET 10 runtime image |

## Target image

```text
bacnet-interop-sysiobacnet:local
ghcr.io/otfabric/bacnet-interop-sysiobacnet:<version>
ghcr.io/otfabric/bacnet-interop-sysiobacnet@sha256:<digest>
```

## Readiness contract

```json
{"event":"ready","adapter":"sysiobacnet","version":"0.11.1","fixture":"device-baseline-v2","address":"0.0.0.0:47808","peer_version":"4.0.0"}
```

`peer_version` is read from the loaded `BACnet.dll`, not from a build argument.

`{"event":"operation","adapter":"sysiobacnet","operation":"…","result":"accepted"}`
lines are adapter diagnostics, emitted for `reinitialize-device`,
`time-synchronization`, `utc-time-synchronization` and `acknowledge-alarm`.

## Build

```bash
# from bacnet-interop root
make build-sysiobacnet
docker run --rm -p 47808:47808/udp bacnet-interop-sysiobacnet:local
# EventNotification emit after the first ReadProperty:
docker run --rm -e BACNET_EMIT_EVENT=1 bacnet-interop-sysiobacnet:local
SMOKE_ONLY=sysiobacnet make smoke
```

Environment:

| Variable | Purpose |
|---|---|
| `BACNET_IP_PORT` | UDP port (default 47808) |
| `FIXTURE` / `DEVICE_FIXTURE_FILE` | Fixture id / JSON path |
| `BACNET_DEVICE_ADDRESS` | Bind IPv4 address (default: all interfaces). Required in a container with more than one network: the stack refuses to guess its broadcast interface |
| `BACNET_MAX_APDU` | Max APDU of the transport: 50, 128, 206, 480, 1024 or 1476 (the sizes the stack knows; anything else is refused at start) |
| `ADAPTER_VERSION` | Ready-event `version` |
| `SYSIOBACNET_LOG` | Stack log level on stderr: `trace`, `debug`, `information`, `warning` (default), `error`, `none` |

| `BACNET_EMIT_EVENT=1` | Emit one UnconfirmedEventNotification to the sender of the first ReadProperty (**adapter-shim**, as in the BACpypes3 and BACnet4J adapters) |

`BACNET_BBMD` and `BACNET_NETWORK` are not supported; the adapter refuses to
start when one of them is set. A device behind a router needs neither.

## Fixture notes

Every `device-baseline-v1` … `v8` file loads. Objects are created for
`device`, `analog-value` (commandable, 16-slot Priority_Array),
`binary-value` (commandable), `analog-input`, `trend-log` (four seeded REAL
records, one minute apart from 2024-01-01 00:00:00), `file` (stream and record
access) and `notification-class`. Skipped with a stderr note, because the
package ships no behaviour for them: `event-enrollment`, `audit-log`,
`life-safety-point`, `life-safety-zone`. `device-baseline-v9` is not in the
image (bacnet-stack only).

A fixture with a Notification Class (`device-baseline-v3`) turns on alarms: its
Analog Values report intrinsic out-of-range events against High_Limit 80
(**adapter-shim**). Present_Value above the limit is `high-limit`, otherwise
`normal`; each transition gets a date-time stamp and an
UnconfirmedEventNotification to the peer whose write caused it; only
to-offnormal needs an acknowledgement. A transition that never happened has
time stamp sequence-number 0.

## Native and adapter-supplied behaviour

| Service | Stack (native) | Adapter (shim) |
|---|---|---|
| Who-Is / I-Am | decode, I-Am encode and send (unicast to the requester) | instance-range check |
| Who-Has / I-Have | decode, I-Have encode and send | lookup by identifier or name in `DeviceStorage` |
| ReadProperty | decode, `DeviceStorage.ReadProperty` (array index 0/N, Device wildcard), ACK, segmentation | storage status → Error class/code, Object_List and File_Size values |
| ReadPropertyMultiple | decode, `DeviceStorage.ReadPropertyMultiple` / `ReadPropertyAll` incl. per-property errors, ACK, segmentation | — |
| WriteProperty | decode (default priority 16), `DeviceStorage.WriteCommandableProperty` / `WriteProperty` | writable-property list, datatype check, status → Error |
| WritePropertyMultiple | decode, SimpleACK / Error PDU | loop over the WriteProperty path |
| SubscribeCOV / SubscribeCOVProperty | decode, `DeviceStorage.ChangeOfValue` trigger, confirmed and unconfirmed notification encode/send/retry | subscription table, lifetime, initial notification |
| ReadRange | decode, log-record and ACK encode, segmentation | Trend Log buffer and range selection |
| AtomicReadFile / AtomicWriteFile, stream | decode, ACK encode and send, segmentation | file contents |
| AtomicReadFile / AtomicWriteFile, record | decode, record ACK encoders (`Services.Encode…Acknowledge`) | records; sends the ACK itself from the package's NPDU/APDU/service encoders, unsegmented, because `BacnetClient.ReadFileResponse` / `WriteFileResponse` are stream-only |
| GetEventInformation | decode, ACK encode and send | which objects are reported, from the adapter's alarm state |
| AcknowledgeAlarm | decode | state and time-stamp check, Error codes, SimpleACK |
| UnconfirmedEventNotification (emit) | encode and send | when, to whom, and the out-of-range parameters |
| ReinitializeDevice | decode | SimpleACK without a restart, `operation` line |
| TimeSynchronization / UTC | decode | `operation` line |
| Unrecognized or unserved confirmed service | Reject unrecognized-service | — |
| Undecodable request | Reject or Abort | — |
| Segmented request receive, segmented ComplexACK send | all of it | — |

Not served (the stack answers Reject unrecognized-service):
DeviceCommunicationControl, CreateObject, DeleteObject, Add/RemoveListElement,
PrivateTransfer, GetAlarmSummary (BacnetClient 4.0.0 rejects it whatever the
application registers), and GetEventInformation / AcknowledgeAlarm on fixtures
without a Notification Class. Confirmed event notifications are not sent.

## Known upstream behaviour (BACnet 4.0.0)

- Both broadcast forms are received (socket bound to 0.0.0.0:47808); the
  adapter answers Who-Is with a unicast I-Am to the requester, through the
  router when the Who-Is was routed.
- Replies to routed requests carry DNET/DADR of the requester and go to the
  router (works behind bacnet-stack's router without return-path assistance).
- Max_APDU_Length_Accepted is announced as 1464 (transport payload minus
  headers), not a standard size.
- Abort PDUs are sent without the SRV bit.
- A commanded Priority_Array slot reads back as a CharacterString (`"77.5"`).
- An array index on a non-array property is answered (0 → 1, 1 → the value).
- The ReadProperty-ACK for the Device wildcard instance echoes `device,4194303`.
- ReadPropertyMultiple cannot encode an empty list: a request covering one
  (the Device's Device_Address_Binding, or `all` of the Device) is aborted.
- A failed WritePropertyMultiple is answered with a plain Error (class, code),
  not a WritePropertyMultiple-Error.
- `required` / `optional` in ReadPropertyMultiple are not expanded.

## Capability tracking

Update [`PEER_SUPPORT.md`](../../PEER_SUPPORT.md) and
[`inventory.yaml`](../inventory.yaml) when modes change.
