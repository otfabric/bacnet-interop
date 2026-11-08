# bacnet-js adapter

BACnet/IP peer built on [`@bacnet-js/client`](https://github.com/bacnet-js/client)
(TypeScript on Node.js, MIT), the maintained successor of `node-bacnet` and
`bacstack`. It is independent of go-bacnet and of the other peers here.

| | |
|---|---|
| Upstream pin | npm `@bacnet-js/client` 3.3.2, gitHead `43fbd922` (tag `v3.3.2` is `27a399a0`, same `src/`) |
| Source of truth | [`package.json`](package.json) with [`package-lock.json`](package-lock.json) (integrity hashes); `ARG BACNETJS_VERSION` in the [Dockerfile](Dockerfile) repeats it, and `make validate-fixtures` fails when they disagree |
| Runtime dependencies | debug 4.4.3, ms 2.1.3, iconv-lite 0.6.3, safer-buffer 2.1.2 (all MIT, from the lock) |
| Base image | `node:24.22.2-bookworm-slim` by digest ([versions.yaml](../../versions.yaml)) |
| Installed with | `npm ci --omit=dev --ignore-scripts`; licences copied to `/licenses/<package>/` |
| Runs as | user `adapter` (uid 10001) |

Upstream is used unmodified. **Do not import `go-bacnet`.** Assertions live in
`go-bacnet/interop`.

```text
go-bacnet client → bacnet-js device mode   (device-baseline-v2, device-server-v1)
bacnet-js client → go-bacnet server         (client mode, the four server-*-v1 files)
```

## Device mode (the default)

One upstream `BACnetClient` bound to UDP 47808 (`BACNET_IP_PORT`) serves a
fixture: `FIXTURE` / `DEVICE_FIXTURE_FILE` (default `device-baseline-v2`;
`device-server-v1` adds the alarming AV-2, the Notification Class, the
Trend Log, three files and creatable Analog Values). It writes the ready
event of [docs/CONTAINER_CONTRACT.md](../../docs/CONTAINER_CONTRACT.md).

What is upstream code: BVLC, NPDU and APDU decoding and encoding, the
confirmed-request transaction state (invoke IDs), reassembly and Segment-ACKs
of segmented requests (`client.ts _processSegment`), the decoder of every
request it maps to a service event, and every answer: `iAmResponse`,
`iHaveResponse`, `simpleAckResponse`, `errorResponse`,
`unconfirmedCOVNotification`, `confirmedCOVNotification`, and for each
ComplexACK `apdu.encodeComplexAck` plus the service's `encodeAcknowledge`.

What is adapter code (`adapter-shim` in
[inventory.yaml](../inventory.yaml)): upstream has no object model, no
dispatch and no service procedures. [`device.js`](device.js) holds the
objects of the fixture and their property tables (Property_List, arrays,
ALL/REQUIRED/OPTIONAL), WriteProperty semantics (data types, write access,
the priority array of the commandable Analog and Binary Values, priority 6
reserved), COV subscriptions with lifetimes and COV increments, intrinsic
OUT_OF_RANGE reporting on AV-2 (Event_State, Event_Time_Stamps,
Acked_Transitions), the Trend Log buffer and the ReadRange selection
(position, sequence number, time; result flags), stream and record files,
CreateObject (Analog Value 100–199) and DeleteObject (created objects
only), GetEventInformation, AcknowledgeAlarm (time stamp checked),
GetAlarmSummary, GetEnrollmentSummary with its filters,
DeviceCommunicationControl and ReinitializeDevice.

Three answers upstream cannot produce are assembled from upstream's
encoders: the WritePropertyMultiple-Error and the CreateObject-Error (an
Error PDU with the constructed `[0]` error and the first failed element,
clause 21; `errorResponse` writes the plain form only), the Reject PDU
(upstream has no encoder), and a WritePropertyMultiple request with more
than one specification is decoded one specification at a time from the raw
datagram, because `WritePropertyMultiple.decode` does not stop at a
specification's closing tag.

A ComplexACK that does not fit the smaller of the requester's max APDU and
1476 is answered with Abort segmentation-not-supported (clauses 5.2, 5.4.5):
upstream cannot send a segmented message. The I-Am says segmented-receive.

Operation lines (`{"event":"operation",…}`): `time-synchronization`,
`utc-time-synchronization`, `unconfirmed-private-transfer`,
`confirmed-private-transfer`, `confirmed-cov-notification` (the requester
acknowledged), `atomic-write-file`, `create-object`, `delete-object`,
`device-communication-control`, `reinitialize-device`, `acknowledge-alarm`,
`event-state-transition`, `reply-too-long`.

### What upstream lacks (device mode)

| Request | What happens | Source |
|---|---|---|
| AddListElement, RemoveListElement, other mapped services without a handler | Error services / reject-unrecognized-service (no listener) | `client.ts _processServiceRequest` |
| SubscribeCOVPropertyMultiple, text messages, WriteGroup | not in the service map in the service map: no answer | `client.ts` service maps |
| GetEnrollmentSummary with an event-state filter | the decoder reads the primitive `[2]` as constructed: offnormal (`29 00`) decodes by accident, normal (`29 02`) throws, no answer | `services/GetEnrollmentSummary.ts` |
| GetAlarmSummary | answered, but `AlarmSummary.encode` writes context tags 12, 9 and 8 where clause 13.10.2 has application tags | `services/AlarmSummary.ts` |
| any request from 127.0.0.1 | ignored by upstream | `client.ts` |
| an undecodable request | no event, no answer | `client.ts _processServiceRequest` |

I-Am carries Max_APDU_Length_Accepted 1482 (`transport.getMaxPayload()`);
the Device object reports 1476.

## Client mode (`client` as the first argument)

[`client.js`](client.js) implements
[docs/CLIENT_DRIVER_CONTRACT.md](../../docs/CLIENT_DRIVER_CONTRACT.md):
`--target`, `--device`, `--scenarios`, `--only`, `--broadcast`, `--bbmd`,
`--fd-ttl`; `BACNET_CLIENT_TIMEOUT_MS` and `BACNET_CLIENT_RETRIES`. Requests
are `BACnetClient` methods wherever one expresses the scenario. These are
assembled from upstream encoders and sent through the client's request
manager (`adapter-shim`): Who-Has (no method), SubscribeCOVProperty with a
lifetime and an increment (`subscribeProperty()` hard-codes lifetime 0),
ReadRange of a property other than Log_Buffer (`readRange()` hard-codes it),
and an AtomicReadFile larger than one APDU (`readFile()` does not set
segmented-response-accepted). Upstream reports a Reject and an Abort alike;
the adapter tells them apart by the PDU on the wire (a raw-datagram tap
decoded with upstream's BVLC, NPDU and APDU decoders).

| Outcome | Scenarios | Reason |
|---|---|---|
| `unsupported` | `ale.*`, `rle.*` | `AddListElement.encode` is application-tagged only; a BACnetDestination cannot be encoded |
| `unsupported` | `co.not-creatable` (type choice) | `CreateObject.encode` always sends the identifier choice |
| `unsupported` | `wg.group1`, `ctm.*`, `utm.normal`, `scovpm.*`, `read-bdt`, `read-fdt.contains-client`, `write-bdt.nak` | no encoder in 3.3.2 |
| `unsupported` | `awf.file3.segmented-request` | no segmented requests (no method sets SEGMENTED_MESSAGE) |
| `unsupported` | `ges.offnormal-filter.*` | `encode` drops filter 0 and wraps the others in constructed tags |
| `known-difference` | `wpm.unknown-object-second`, `wpm.wrong-type` | a WritePropertyMultiple-Error is decoded with the plain Error decoder: no firstFailedWriteAttempt |
| `known-difference` | `ack.av2` when the device stamps a date | `asn1.decodeBacnetDatetime` takes the weekday (`getDay()`) as the day of month, so the time stamp echoed back is wrong |
| `not-tested` | read-backs of an unsupported write | listed in `DEPENDS_ON` in `client.js` |

## Environment

| Variable | Mode | Default | Effect |
|---|---|---|---|
| `FIXTURE`, `DEVICE_FIXTURE_FILE` | device | `device-baseline-v2` | the fixture (`/fixtures/device/*.json`) |
| `BACNET_IP_PORT` | device | 47808 | UDP port |
| `BACNET_CLIENT_TIMEOUT_MS` | client | 3000 | APDU timeout |
| `BACNET_CLIENT_RETRIES` | client | 1 | contract option; upstream never resends, so it only widens how long the tap is searched for the answer |

## Tests

`node --test adapter.test.js` runs in the image build (the model, the
WPM-Error and CreateObject-Error octets, ReadRange selection, argument
parsing) and is removed from the image.
