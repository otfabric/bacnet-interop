# BACnet4J adapter

Containerized [BACnet4J](https://github.com/RadixIoT/BACnet4J) peer for [`bacnet-interop`](../..).

**Status:** fixture-driven device-server image. Pin: `bacnet4j==6.1.1` (`BACNET4J_VERSION` in Dockerfile / pom).

## Role

Primary **Java** peer oracle for fixture-driven interop:

- Independently implemented BACnet application layer (BACnet4J / RadixIoT)
- Default fixture `device-baseline-v2` (device + AV-1 + BV-1 + TrendLog)
- Also loads `device-baseline-v3` (AI/NC/EE + AV intrinsic Out_Of_Range highLimit=80) and
  `device-baseline-v4` (File stream/record objects seeded from fixture JSON)
- Who-Has / I-Have, WPM, ReadRange byPosition / bySequenceNumber / byTime (upstream), ReinitializeDevice warmstart
- DeviceCommunicationControl (upstream, no adapter code): enable, disable,
  disable-initiation, time-duration, optional password. "disable" really
  mutes the device (see "DeviceCommunicationControl" below)
- SubscribeCOVProperty with COV increment (upstream)
- GetEventInformation and AcknowledgeAlarm (upstream; v3 fixture)
- Optional `BACNET_EMIT_EVENT=1` UnconfirmedEventNotification emit (**adapter-shim**)
- Optional peer-as-BBMD (`BACNET_BBMD=1`) and small MaxAPDU for segmentation stress
- Rejects segmented confirmed-request receive (registered gap vs BACpypes3)
- AtomicReadFile / AtomicWriteFile, stream and record access (v4 fixture)
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
| COVNotificationMultiple emit | `BACNET_EMIT_COV_MULTIPLE=1` | After each SubscribeCOVPropertyMultiple, send the requester an unconfirmed and a confirmed COVNotificationMultiple (see "COV-multiple" below) |

## Readiness contract

```json
{"event":"ready","adapter":"bacnet4j","version":"0.10.0","fixture":"device-baseline-v2","address":"<bind-ipv4>:47808","peer_version":"6.1.1"}
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
| `BACNET_DEVICE_ADDRESS` | Bind IP (default: primary IPv4; the subnet mask is taken from that interface) |
| `BACNET_MAX_APDU` | Override `maxApduLengthAccepted` (keeps segmentedBoth) |
| `BACNET_BBMD=1` | Enable BBMD with BDT self-entry |
| `BACNET_EMIT_EVENT=1` | Emit one UnconfirmedEventNotification after first ReadProperty (**adapter-shim**) |
| `BACNET_NETWORK` | Optional local BACnet network number |
| `BACNET_DCC_PASSWORD` | `LocalDevice` password, checked by upstream for DeviceCommunicationControl and ReinitializeDevice (unset = requests must carry no password) |
| `ADAPTER_VERSION` / `BACNET4J_VERSION` | Ready-event version fields |

## Behaviour to know

- **Broadcasts:** as configured by the adapter, the device answers a Who-Is
  sent to 255.255.255.255 and does not answer one sent to the subnet-directed
  broadcast address. (bacnet-stack is the other way round; a client that
  wants to find both has to send both.)
- **Device wildcard:** a ReadProperty of `device,4194303` is answered with the
  device's own identifier.
- **Segmented requests** are rejected; segmented responses are sent.
- **AcknowledgeAlarm** with a time stamp that does not match the event is
  answered with Error services/invalid-time-stamp.
- The Device `Object_Identifier` is writable; an Analog Value's `Object_Type`
  is not (Error property/write-access-denied).
- WriteGroup, COV-multiple, VT, Who-Am-I / You-Are and the audit services are
  not implemented upstream.
- **WritePropertyMultiple** (upstream):
  - A failing write is answered with a WritePropertyMultiple-Error naming the
    first failed element. Writes before it stay applied, writes after it are
    not executed.
  - A write to an object that does not exist is Error **property**/unknown-object
    (the other peers answer object/unknown-object).
  - A write to a property the object does not have is **accepted**: the
    property is created and reads back.
  - A value of the wrong datatype for a known property (BOOLEAN for a REAL
    Present_Value, for example) makes the request fail while it is decoded
    (`ArrayIndexOutOfBoundsException` under `PropertyValue`); it is answered
    with an ordinary Error services/operational-problem carrying error-choice
    127 instead of 16, and none of its writes is executed.
- **AtomicReadFile / AtomicWriteFile** with the access method the File object
  does not have: Error services/invalid-file-access-method.

## DeviceCommunicationControl

Upstream behaviour, as asserted by go-bacnet. It is the same in the 0.9.0
image; only the configured-password case needs `BACNET_DCC_PASSWORD` (0.10.0).

| Request | Result |
|---|---|
| enable | SimpleACK |
| disable-initiation | SimpleACK; ReadProperty and Who-Is are still answered |
| disable | SimpleACK; after it a ReadProperty gets no answer |
| enable after disable | SimpleACK; the device answers again |
| no password configured, request carries one | Error security/password-failure |
| password configured, missing or wrong password | Error security/password-failure, also while disabled |

While disabled the device still answers Who-Is with I-Am, still returns an
Error for a request that fails (an unknown object, for example) and still
acknowledges ReinitializeDevice. A WriteProperty is **executed but not
acknowledged**: the client sees no answer and the value has changed. With
`BACNET_DCC_PASSWORD` set, ReinitializeDevice needs the same password.

## Fixture notes

Default `/fixtures/device/device-baseline-v2.json` (`device-baseline-v1` frozen).
Override with `DEVICE_FIXTURE_FILE=/fixtures/device/device-baseline-v3.json` (or v4–v8).
This adapter constructs commandable COV-capable AV-1, commandable BV-1, and a
seeded TrendLogObject (see "Trend Log" below). For v3 it also creates AnalogInput,
NotificationClass, EventEnrollment (after `initialize()`), and enables AV
intrinsic reporting. For v4 it seeds File stream/record content under `/tmp`.
For v5 it honors `object_lifecycle`: creatable_types (AV/BV CreateObject
factories), precreated_deletable (e.g. AV-100), and protected core objects.
(alignment: `full-object-graph`).

## COV-multiple

BACnet4J has classes for the three COV-multiple services and executes none
of them: `SubscribeCOVPropertyMultipleRequest.handle` throws
`NotImplementedException` after parsing, which the stack answers with Reject
unrecognized-service (or, when exactly one of issue-confirmed-notifications
and lifetime is present, with Error services/inconsistent-parameters, sent
with error-choice 127). The adapter does not change that answer and
subscribes nothing. It adds two things:

**Parse evidence (always).** For every SubscribeCOVPropertyMultiple the stack
parsed, an operation line with the fields its parser extracted:

```json
{"event":"operation","adapter":"bacnet4j","operation":"subscribe-cov-property-multiple","result":"parsed","fields":{"subscriber_process_identifier":1,"issue_confirmed_notifications":true,"lifetime":300,"max_notification_delay":5,"cov_subscription_specifications":[{"monitored_object_identifier":{"type":2,"instance":1},"cov_references":[{"property_identifier":85,"property_array_index":null,"cov_increment":0.5,"timestamped":true}]}]}}
```

An absent optional parameter is `null`.

**Notification emit (`BACNET_EMIT_COV_MULTIPLE=1`).** About 200 ms after such
a request the adapter sends the requester one
UnconfirmedCOVNotificationMultiple and then one
ConfirmedCOVNotificationMultiple, built with
`UnconfirmedCovNotificationMultipleRequest` /
`ConfirmedCovNotificationMultipleRequest` and encoded by them. This is an
adapter trigger for the stack's encoder, not a subscription: there is one
pair per request and no notification on a later change of value.

| Notification field | Value |
|---|---|
| subscriber-process-identifier | from the request |
| initiating-device-identifier | the device |
| time-remaining | the request's lifetime (0 when absent) |
| timestamp | the device's clock |
| list-of-cov-notifications | per specification of the request the monitored object, and per reference the property with its current value; a reference with `timestamped` TRUE carries the timestamp's time as time-of-change, the others none. An object or property the device cannot read is left out |

The confirmed notification is sent for a peer Max_APDU of 480 without
segmentation (the requester is not in BACnet4J's remote-device cache, for
which `LocalDevice.send` would assume 50).

Operation lines, in this order:

| `operation` | `result` | `fields` |
|---|---|---|
| `emit-unconfirmed-cov-notification-multiple` | `sent` | what was sent: `subscriber_process_identifier`, `initiating_device_identifier`, `time_remaining`, `timestamp` {year, month, day, weekday, hour, minute, second, hundredths}, `cov_notifications` [{`monitored_object_identifier`, `values` [{`property_identifier`, `property_array_index`, `value` (BACnet4J's text form), `time_of_change`}]}] |
| `emit-confirmed-cov-notification-multiple` | `sent` | the same |
| `confirmed-cov-notification-multiple-ack` | `simple-ack` when BACnet4J received the requester's SimpleACK; `refused: …` for an Error, Reject or Abort; `failed: …` for a timeout | none |

## Trend Log

`trend-log:0` is seeded once at start and never samples (`Enable` false). Up
to 0.9.0 the seed was four time-change records, all stamped with the start
time and without sequence numbers, which only byPosition could address. Since
0.10.0:

| | |
|---|---|
| `Record_Count` / `Total_Record_Count` | 36 |
| `Buffer_Size` | 100 |
| Record at position *k* (1-based) | time stamp `2024-01-01 00:00:00` + (*k*−1) × 15 min (day of week Monday, hundredths 0), logDatum real-value 20 + (*k*−1), statusFlags present and all clear, sequence number *k* |
| Newest record | `2024-01-01 08:45:00`, REAL 55, sequence number 36 |

The records are put into the buffer directly, with the sequence numbers
upstream's `TrendLogObject` would have assigned (it numbers a record with the
new `Total_Record_Count`). The range selection is upstream's
`ReadRangeRequest`:

- A reply holds at most 200 records, so the whole seed fits one reply.
- Every reply that holds a record carries `firstSequenceNumber`, also a
  byPosition reply.
- bySequenceNumber: the reference must be the sequence number of a record in
  the buffer. Any other reference (0, 37) is answered with an empty reply:
  item count 0, all result flags clear. It is not moved to the nearest record
  (bacnet-stack moves a reference before the oldest record up to it).
- byTime, positive count: records with a time stamp strictly after the
  reference. Negative count: records strictly before it. A reference time
  with an unspecified field is Error property/datatype-not-supported.
- A negative count returns the records up to and including the reference
  (bySequenceNumber, byPosition), oldest first.
- MORE_ITEMS is clear on a reply that holds what the request asked for, also
  when the log has more; LAST_ITEM is set only on a reply that contains the
  newest record.

## Capability tracking

Update [`PEER_SUPPORT.md`](../../PEER_SUPPORT.md) and [`inventory.yaml`](../inventory.yaml) when modes change.
