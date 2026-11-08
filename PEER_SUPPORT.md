# Peer support

Which independent BACnet stacks can execute which scenarios with the adapter
images of this repository. Assertions and pass/fail decisions live in
[`go-bacnet`](https://github.com/otfabric/go-bacnet) (`INTEROP.md`, `interop/`).

**Published images:** [v0.13.0](https://github.com/otfabric/bacnet-interop/releases/tag/v0.13.0)
· default device fixture: `device-baseline-v2`

Cells marked ¹ are new in 0.10.0; everything else also holds for the v0.9.0
images.

| Mark | Meaning |
|---|---|
| ✅ | Executed by the upstream peer implementation |
| A | The adapter supplies the service or object semantics; the stack supplies the wire encoding and transport |
| — | Not available in the pinned upstream peer, or not served by the adapter |
| ⚠ | Available, but the behaviour deviates from the standard or from the other peers; the deviation is asserted |
| D | Codec evidence only: the stack's own decoder accepted the client's request and the adapter reported the decoded fields, or the stack's own encoder produced a PDU the client decoded. The service is not executed |
| ○ | Present in the upstream stack but not wired into the adapter |
| not exercised | The adapter serves it or may serve it; no test runs it, so nothing is claimed |

A ✅, A or ⚠ cell is backed by a go-bacnet interop test that runs against the
image. A — cell marked † was established by reading the peer's source or
binary, not by a test.

`bip-router` is a topology aid written for the tests. Never count it as
evidence about a stack. `bacnet-stack-router` is upstream bacnet-stack code
and is.

## Pinned peers

| Peer | Version / commit | Language | Role |
|---|---|---|---|
| bacnet-stack | 1.6.1 | C | Device oracle (+ BBMD) |
| BACpypes3 | 0.0.110 | Python | Device oracle (+ BBMD) |
| BACnet4J | 6.1.1 | Java | Device oracle (+ BBMD) |
| Worldiety | `3cb2aa80` | Go | Native transport and APDU layer; fixture object model |
| System.IO.BACnet ¹ | NuGet `BACnet` 4.0.0 | C# | Device oracle; the stack behind YABE |
| bacnet-stack-router ¹ | bacnet-stack 1.6.1 `apps/router` | C | Native BACnet/IP ↔ BACnet/IP router |
| cB-Sigma (`cbsigma`) | bacnet `v0.2.0` (device role), bacnet-sim `v0.1.0` | Go | Device oracle; simulator with fault switches (new in 0.13.0, [below](#cb-sigma-cbsigma)) |
| bacnet-js | npm `@bacnet-js/client` 3.3.2 (`43fbd922`) | TypeScript (Node.js) | Device oracle and client (unreleased, [below](#bacnet-js-bacnet-js)) |
| bip-router | topology-router-v1 | Python | Dual-homed BIP↔BIP topology aid |

> **Worldiety:** supplies the native BACnet/IP, NPDU and APDU runtime. The
> adapter supplies the fixture object model and the application-service
> semantics, so its A cells say little about the upstream stack.
>
> **System.IO.BACnet:** the object storage (`DeviceStorage`) and every codec
> are the package's own; the adapter connects the stack's request events to
> that storage, as the upstream examples do. A cells are where the adapter
> decides the outcome (subscription table, range selection, file contents).

## Application services

| Service | bacnet-stack | BACpypes3 | BACnet4J | Worldiety | System.IO.BACnet ¹ |
|---|:---:|:---:|:---:|:---:|:---:|
| Who-Is / I-Am (unicast Who-Is) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Who-Is by broadcast | ✅ | ✅ ¹ | ✅ | ✅ | ✅ |
| Who-Has / I-Have | ✅ | ✅ | ✅ | A | A |
| ReadProperty | ✅ | ✅ | ✅ | A | ✅ |
| ReadProperty of the Device wildcard instance (4194303) | ✅ | ⚠ | ✅ | ⚠ | ⚠ |
| ReadPropertyMultiple | ✅ | ✅ | ✅ | A | ✅ |
| WriteProperty | ✅ | ✅ | ✅ | A | ✅ |
| WriteProperty at a priority, relinquish with NULL | — | ✅ | ✅ | not exercised | ✅ |
| WritePropertyMultiple | ✅ | A | ✅ | A | A |
| ReadRange (Trend Log) byPosition | ✅ | — | ✅ | A | A |
| ReadRange bySequenceNumber / byTime | ✅ | — | ✅ ¹ | A ¹ | A |
| COV subscribe / notify / renew | ✅ | ✅ | ✅ | — | A |
| SubscribeCOVProperty | —† | —† | ✅ | — | A |
| EventNotification emit | — | A | A | — | A |
| AtomicRead/WriteFile, stream access | ✅ | — | ✅ | — | A |
| AtomicRead/WriteFile, record access | ✅ | — | ✅ | — | A |
| CreateObject / DeleteObject | ✅ | — | ✅ | — | ○ |
| Add/RemoveListElement (NC) | ✅ | — | ✅ | — | —† |
| GetAlarmSummary | ✅ | — | ✅ | — | — |
| GetEventInformation | ✅ | —† | ✅ | — | A |
| AcknowledgeAlarm | ✅ | —† | ✅ | — | A |
| GetEnrollmentSummary | —† | A ¹ | ✅ | — | —† |
| SubscribeCOVPropertyMultiple | — | D ¹ | D | — | —† |
| COVNotificationMultiple emit | — | — | D ¹ | — | —† |
| TimeSynchronization / UTC | ✅ | ✅ | ✅ | — | ✅ |
| TextMessage | — | ✅ | ✅ | — | —† |
| PrivateTransfer (unconfirmed) | ✅ | ✅ | ✅ | — | ○ |
| PrivateTransfer (confirmed) | — | ✅ | ✅ | — | ○ |
| WriteGroup | ✅ | ✅ | — | — | —† |
| Who-Am-I / You-Are | A | — | — | — | —† |
| LifeSafetyOperation | ✅ | — | ✅ | — | —† |
| Audit notifications (received by the client) | D ¹ | D ¹ | — | — | —† |
| AuditLogQuery | D ¹ | D ¹ | — | — | —† |
| AuthRequest | — | — | — | — | —† |
| VT-Open / Close / Data | — | D ¹ | — | — | —† |
| DeviceCommunicationControl enable | ✅ | ✅ ¹ | ✅ | — | ○ |
| DeviceCommunicationControl disable-initiation | not exercised | ⚠ ¹ | ✅ | — | ○ |
| DeviceCommunicationControl disable | ⚠ | ⚠ ¹ | ✅ | — | ○ |
| DeviceCommunicationControl password | not exercised | ✅ ¹ | ✅ ¹ | — | ○ |
| ReinitializeDevice warmstart | ✅ | A | A | — | A |
| Reject for an unrecognized confirmed service | ✅ | — | ✅ | not exercised | ✅ |

No stable release of any peer executes SubscribeCOVPropertyMultiple,
COVNotificationMultiple, the audit services, AuthRequest or VT. Where a stack
has at least the codecs, the adapter turns them into codec evidence (D):

- **Audit notifications:** with `BACNET_EMIT_AUDIT=1` bacnet-stack and
  BACpypes3 send notifications built by their own `BACnetAuditNotification`
  encoders (bacnet-stack `bacaudit.c`, BACpypes3 `basetypes`) in a frame the
  adapter writes, and the client decodes them; the confirmed one completes on
  the client's SimpleACK. The two encoders agree byte for byte except for
  `result`, which bacnet-stack encodes as a bare enumeration.
- **AuditLogQuery:** BACpypes3 decodes the client's query parameters with its
  own data type and the adapter reports every field; both stacks answer with
  log records from their own record encoders, which the client decodes.
  bacnet-stack has no decoder for the query parameters.
- **SubscribeCOVPropertyMultiple:** BACpypes3 decodes the specification list
  with its own data type (the frame around it is adapter-declared) and
  answers SimpleACK without subscribing. BACnet4J parses the whole request
  with its own class and then answers Reject unrecognized-service, because
  the handler behind the parser is not implemented; a request it finds
  inconsistent gets an Error with error-choice 127.
- **VT:** BACpypes3 decodes VT-Open, VT-Data and VT-Close with its own APDU
  classes and answers with its own VT-Open and VT-Data ACKs. No session
  exists behind them. bacnet-stack and BACnet4J answer Reject.
- **AuthRequest:** nothing. Only a BACnet4J pre-release (7.0.0-alpha) and
  Wireshark know the service.
- **COVNotificationMultiple:** only BACnet4J has an encoder. With
  `BACNET_EMIT_COV_MULTIPLE=1` the adapter answers a parsed
  SubscribeCOVPropertyMultiple by sending one unconfirmed and one confirmed
  notification built with BACnet4J's own classes; the client decodes both and
  BACnet4J sees the SimpleACK. Nothing is subscribed: the trigger is the
  adapter's.
- **GetEnrollmentSummary:** BACnet4J executes it. BACpypes3 has the request
  and ACK types but no handler; the adapter supplies one over a fixed list of
  enrollments (A), so every filter the client encodes is decoded by a second
  implementation. bacnet-stack has no codec for the service at all.

For everything a stack cannot check, go-bacnet compares its request layout
with Wireshark's dissector (`make -C ../go-bacnet dissector`; `make dissect-fixtures`
here for the codec vectors).

Notes on individual cells:

- **Who-Is by broadcast:** the peers differ in which broadcast address their
  socket receives. bacnet-stack answers the subnet-directed broadcast only;
  BACnet4J, as the adapter configures it, the limited broadcast
  255.255.255.255 only; Worldiety and System.IO.BACnet both. BACpypes3 opens a broadcast socket
  only when its address has a prefix length, which the adapter supplies since
  0.10.0 (up to 0.9.0 it heard unicast only). A client that wants to find all
  of them sends both forms.
- **Device wildcard:** BACpypes3 and the Worldiety adapter answer Error
  object/unknown-object. System.IO.BACnet answers with the right value, but
  the object identifier of its ACK echoes `device,4194303` instead of naming
  the real instance.
- **Who-Am-I / You-Are (bacnet-stack):** the adapter registers handlers that
  call the upstream decoders and write an `operation` line. That shows the
  request decodes in bacnet-stack; there is no upstream behaviour or reply.
- **DeviceCommunicationControl disable:**
  - bacnet-stack refuses it with Error services/service-request-denied
    ("disable" was removed from the standard at Protocol_Revision 20; the
    adapter builds revision 28).
  - BACpypes3 acknowledges it and then keeps answering everything: upstream
    0.0.110 compares the decoded enumeration with strings, so the state never
    takes effect. Not corrected in the adapter.
  - BACnet4J acknowledges it and stops answering. While disabled it still
    answers Who-Is, still returns an Error for a failing request, still
    acknowledges ReinitializeDevice, and **executes a WriteProperty without
    acknowledging it**.
- **DeviceCommunicationControl password:** set with `BACNET_DCC_PASSWORD`
  (0.10.0). Both stacks answer a missing or wrong password with Error
  security/password-failure. Without a configured password BACpypes3 ignores
  a password in the request; BACnet4J refuses a request that carries one.
- **System.IO.BACnet A cells:** the package decodes the request and encodes
  the reply; what the reply contains is decided by the adapter. For the alarm
  services that includes the whole alarm model (an out-of-range limit on the
  v3 Analog Value, the acknowledgement rules, the notification recipient);
  for record-access files the adapter sends the ACK through the package's
  public encoders because the package's own response helper is stream-only.
  GetAlarmSummary cannot be served: the package rejects it before any
  handler runs. DeviceCommunicationControl is decoded by the package but its
  example only acknowledges and ignores it, so the adapter does not wire it
  and the stack answers Reject.
- **ReadRange bySequenceNumber / byTime (bacnet-stack):** the Trend Log is
  frozen at upstream's seed since 0.10.0 (1000 records, sequence numbers
  9001–10000, one every 15 minutes from 2009-01-01 00:00:00, values 0–999);
  the 0.9.0 image served the same records. See the adapter README.

## cB-Sigma (`cbsigma`)

New in 0.13.0. One image, two upstream codes, both by cB-Sigma (Go,
Apache-2.0, written from ANSI/ASHRAE 135-2024 and sharing one codec):
`CBSIGMA_ROLE=device` (default) is the `device` package of
[bacnet](https://github.com/cB-Sigma/bacnet) `v0.2.0`, `CBSIGMA_ROLE=sim`
[bacnet-sim](https://github.com/cB-Sigma/bacnet-sim) `v0.1.0`. Environment and
behaviour: [adapters/cbsigma/README.md](adapters/cbsigma/README.md).

The cells are asserted by go-bacnet's `interop/cbsigma_test.go`
([go-bacnet#12](https://github.com/otfabric/go-bacnet/pull/12)) against the
v0.13.0 image, with go-bacnet v0.6.0.

| Scenario | device | sim |
|---|:---:|:---:|
| Who-Is / I-Am (unicast) | ✅ | ✅ |
| Who-Has by name → I-Have | ✅ | — (answers only its demo object) |
| ReadProperty: Device object-name, object-list | ✅ | — (no Device object: object/unknown-object) |
| ReadProperty; unknown object / unknown property errors | ✅ | ✅ |
| ReadPropertyMultiple with a per-property error | ✅ | ✅ |
| ReadPropertyMultiple, segmented answer (client Max APDU 50) | ✅ | not exercised |
| WriteProperty at a priority, relinquish with NULL | ✅ | ✅ (write) |
| WriteProperty to object-name → property/write-access-denied | ✅ | not exercised |
| WritePropertyMultiple | ✅ | ✅ |
| Segmented confirmed request (client segments for a 50-octet peer) | ✅ | ✅ |
| COV subscribe / notify / cancel | ✅ | ✅ |
| ReadRange byPosition, bySequenceNumber, byTime, paged | — | ✅ |
| ReadRange bySequenceNumber refused (`CBSIGMA_REJECT_SEQ=1`) | — | ✅ services/optional-functionality-not-supported |
| Segmented ReadRange answer (`CBSIGMA_MAX_APDU=128`), client receive window 1 and 4 | — | ✅ |
| Segmented RPM answer, client receive window 1, 2, 4 and 16 | ✅ | not exercised |
| A segment left out once (`CBSIGMA_DROP_SEG=2` or `3`) | — | ⚠ inside a window the client NAKs and the simulator resends (✅ at window 4); at the end of a window (always at window 1) the simulator never resends on its own and the client aborts (tsm-timeout); the next request succeeds |
| A segmented answer stopped (`CBSIGMA_STALL_SEG=2`) | — | ✅ the client aborts (tsm-timeout), the next request succeeds |
| RPM / WPM rejected (`CBSIGMA_REJECT_RPM=1`, `CBSIGMA_REJECT_WPM=1`) | — | ✅ Reject unrecognized-service |
| GetAlarmSummary, GetEventInformation (`CBSIGMA_EVENTS=1`) | — | A (the adapter encodes the answer) |
| GetAlarmSummary empty, GetEventInformation rejected (default) | — | ✅ |
| AcknowledgeAlarm | — | ✅ |
| Foreign-device registration, Who-Is via Distribute-Broadcast-To-Network, ReadProperty as FD (`BACNET_BBMD=1`) | — | ✅ |
| Register-Foreign-Device NAK (`CBSIGMA_FD_NAK=1`) | — | ✅ the client stays unregistered |
| ReinitializeDevice; DCC with a wrong password → security/password-failure | — | ✅ |
| Time synchronization, UTC time synchronization, UnconfirmedTextMessage, UnconfirmedPrivateTransfer (operation lines) | — | ✅ |
| ConfirmedTextMessage | — | ✅ Reject unrecognized-service |
| Read-BDT / Read-FDT, files, WriteGroup, Forwarded-NPDU replies (`CBSIGMA_FORWARD=1`) | — | not exercised |
| BACnet/IPv6, BACnet/SC | out of scope | out of scope |

BACnet/IPv6 and BACnet/SC are out of scope because go-bacnet is a BACnet/IP
(IPv4) client; cB-Sigma's bacnet has both, so this is not an upstream gap.

Found with this peer: with `client.WithSegmentWindow(n)`, n > 1, go-bacnet
up to v0.5.x sent no Segment-ACK for the first segment of a segmented answer,
so every segmented answer timed out (BACpypes3 0.0.110 showed the same).
Fixed in go-bacnet v0.6.0; its `TestSegmentedAnswerWithReceiveWindow` keeps
it fixed against cbsigma and BACpypes3.

## bacnet-js (`bacnet-js`)

Not in a release yet. [@bacnet-js/client](https://github.com/bacnet-js/client)
3.3.2 (MIT), the maintained successor of node-bacnet and bacstack, unmodified,
in device mode (default) and client mode. Upstream supplies BVLC, NPDU, APDU,
the request decoders and the answer encoders; it has no object model and no
service procedures, so those are adapter code (A).
Environment, what is upstream and what is adapter, and the upstream defects:
[adapters/bacnet-js/README.md](adapters/bacnet-js/README.md).

The device cells are asserted by go-bacnet's `interop/bacnetjs_test.go` against
an image built from this branch (go-bacnet branch `test/bacnet-js`).

| Scenario | bacnet-js device |
|---|:---:|
| Who-Is / I-Am (unicast, range), Who-Has by name and by identifier | ✅ (I-Am Max_APDU 1482, the Device object says 1476) |
| ReadProperty, object-list (whole, [0], invalid index), wildcard Device instance | A |
| ReadProperty unknown object / unknown property / not an array / Log_Buffer read-access-denied | A |
| ReadPropertyMultiple with per-property errors, ALL | A |
| WriteProperty at a priority, relinquish with NULL, wrong type, object-name write-access-denied | A |
| WritePropertyMultiple, two specifications, WritePropertyMultiple-Error with first failed write | A (upstream's decoder overruns a specification; the adapter decodes each one alone) |
| Segmented confirmed request (client segments for a 50-octet peer) | ✅ |
| Reply larger than the client's max APDU | ✅ Abort segmentation-not-supported (no segmented send upstream) |
| SubscribeCOV confirmed and unconfirmed, initial notification; SubscribeCOVProperty with increment; errors | A |
| ReadRange by position (also negative count), by sequence number, by time, paged; errors | A |
| AtomicReadFile / AtomicWriteFile stream and record, append, errors | A |
| CreateObject (identifier choice), DeleteObject, errors | A |
| GetEventInformation, GetEnrollmentSummary (no filter), AcknowledgeAlarm, errors | A |
| GetEnrollmentSummary with an event-state filter | ⚠ offnormal decodes by accident; normal: no answer (upstream decoder throws) |
| GetAlarmSummary with an alarm | ⚠ context tags 12, 9, 8 where clause 13.10.2 has application tags: go-bacnet refuses the ACK |
| DeviceCommunicationControl, ReinitializeDevice | A |
| TimeSynchronization, UTCTimeSynchronization, Confirmed/UnconfirmedPrivateTransfer | ✅ (operation lines) |
| AddListElement, RemoveListElement | ✅ Error services/reject-unrecognized-service |
| ConfirmedTextMessage | — no answer (not in upstream's service map) |
| BBMD, COV-multiple, WriteGroup, event notifications | — |

## Transport and network

| Capability | bacnet-stack | BACpypes3 | BACnet4J | Worldiety | System.IO.BACnet ¹ |
|---|:---:|:---:|:---:|:---:|:---:|
| BACnet/IP UDP | ✅ | ✅ | ✅ | ✅ | ✅ |
| Segmented confirmed-request receive | — | ✅ | ⚠ | ⚠ | ✅ |
| Segmented ComplexACK send | — | ✅ | ✅ | ⚠ | ✅ |
| Routed remote via bip-router | ✅ | ✅ | ✅ | — | ✅ |
| Routed remote via bacnet-stack-router ¹ | ✅ | ✅ | not exercised | — | ✅ |
| Peer-as-BBMD / FDR target | ✅ | ✅ | ✅ | — | ○ |
| Read-BDT | ✅ | ✅ | ✅ | — | ○ |
| Read-FDT (after FD registration) | ✅ | ✅ | ✅ | — | ○ |
| Delete-FDT entry | ✅ | ✅ | ✅ | — | ○ |
| Write-BDT (BVLC) | ⚠ | ⚠ | ✅ | — | ○ |

- **Segmentation:** bacnet-stack cannot segment and answers Abort
  segmentation-not-supported when a reply does not fit. BACnet4J rejects a
  segmented confirmed request. Worldiety segments in both directions but
  omits the service choice on continuation segments, which go-bacnet treats
  as a protocol violation; its scenarios stay unsegmented.
- **Write-BDT:** bacnet-stack (Protocol_Revision ≥ 17) and BACpypes3 answer
  with a BVLC NAK, which go-bacnet asserts.
- **BBMD cells** need deterministic adapter state: Read-FDT after a
  foreign-device registration; Delete-FDT with the address from Read-FDT (not
  the client's bind address).

### Routers

| | bip-router | bacnet-stack-router ¹ |
|---|---|---|
| What it is | Python program written for the tests | Upstream bacnet-stack `apps/router`, unpatched |
| Who-Is-Router-To-Network → I-Am-Router-To-Network | yes | yes (as a broadcast to UDP 47808) |
| Forwards unicast and broadcast NPDUs between two BACnet/IP networks | yes | yes |
| Decrements the hop count | yes | no |
| Helps a device that cannot route its reply | yes (return-path assist) | no |
| Reject-Message-To-Network for an unknown network | no | no (it searches with Who-Is-Router-To-Network and drops the message) |

Through `bacnet-stack-router` a global Who-Is reaches the far network as a
subnet broadcast, so a device behind it must receive subnet broadcasts. The
I-Am of a bacnet-stack device comes back as a broadcast carrying both DNET
65535 and SNET/SADR; BACpypes3 and System.IO.BACnet devices answer the
requester directly, with SNET/SADR only. A global Who-Is through `bip-router`
is not asserted for System.IO.BACnet (it produced no I-Am; not investigated).

### Network notes

- **bacnet-stack:** `BBMD_ENABLED` is compiled into `device_server`; the BDT
  self-seeds and foreign-device registration is accepted by default.
- **BACpypes3 / BACnet4J:** peer-as-BBMD with `BACNET_BBMD=1`. Neither is a
  multi-homed router.
- **Worldiety:** the module has BBMD table helpers and `npdu/router`, but
  `ClientRuntime` and the adapter do not wire them: no peer-as-BBMD, no
  router. `bbmd-v2` and `topology-v2` stay pending for this peer.
- **System.IO.BACnet:** the package has BVLC BBMD code that the adapter does
  not wire; it refuses to start with `BACNET_BBMD` or `BACNET_NETWORK` set.
  On a host with more than one IPv4 interface it needs
  `BACNET_DEVICE_ADDRESS`. Behind a router it addresses its replies to the
  requester's network through the router, and answers a routed global Who-Is
  with a unicast I-Am (SNET/SADR, no DNET).

## Known peer behaviour

Each of these is asserted by a go-bacnet test, so a change in a peer is
noticed.

- **Writable identity:** bacnet-stack, BACpypes3 and BACnet4J accept a
  WriteProperty to the Device `Object_Identifier`. BACpypes3 also accepts a
  write to an Analog Value's `Object_Type`; bacnet-stack, BACnet4J and
  Worldiety refuse it with Error property/write-access-denied.
- **Priority_Array:** the bacnet-stack adapter's Analog Value has none
  (Error property/unknown-property). BACpypes3, BACnet4J and System.IO.BACnet
  serve a commandable Analog Value; System.IO.BACnet reads a commanded slot
  back as a CharacterString.
- **AcknowledgeAlarm with a stale time stamp:** BACnet4J answers Error
  services/invalid-time-stamp; bacnet-stack answers Abort (reason other).
- **ReadRange result flags:** every peer clears MORE_ITEMS on a reply that
  holds all the items the request asked for, also when the log has more. A
  client must page until LAST_ITEM. bacnet-stack returns at most 66 Trend Log
  records per reply at Max APDU 1476.
- **ReadRange seeds:** bacnet-stack 1000 records (upstream's own seed);
  BACnet4J and Worldiety 36 records since 0.10.0, one every 15 minutes from
  2024-01-01 00:00:00 with values 20–55 and sequence numbers 1–36;
  System.IO.BACnet 4 records.
- **ReadRange by sequence number:** for a reference before the oldest record
  bacnet-stack starts at the oldest; BACnet4J answers an empty reply with no
  flags. BACnet4J puts firstSequenceNumber into every reply that carries a
  record, also a byPosition one. By time, both return the records strictly
  after (positive count) or strictly before (negative count) the reference.
- **WritePropertyMultiple failing on a later element:** every peer applies
  the writes before the failing one and none after it; none rolls back.
  bacnet-stack, BACnet4J and Worldiety name the failed element in a
  WritePropertyMultiple-Error; the BACpypes3 adapter's shim and
  System.IO.BACnet answer a plain Error. BACnet4J reports an unknown object
  as property/unknown-object, **accepts a write to an unknown property**, and
  answers a value of the wrong datatype with Error
  services/operational-problem under error-choice 127 without executing any
  of the writes.
- **File access method mismatch** (a stream read of a record file, and so
  on): BACnet4J and bacnet-stack 1.6.1 answer Error
  services/invalid-file-access-method. bacnet-stack 1.6.0, in the v0.9.0
  image, executed the request.
- **Record read of the v4 record file:** BACnet4J returns the seeded record;
  bacnet-stack returns one empty record.
- **System.IO.BACnet 4.0.0:** announces Max_APDU_Length_Accepted 1464, which
  is not a standard size; sends Abort without the server bit; answers a
  failed WritePropertyMultiple with a plain Error instead of a
  WritePropertyMultiple-Error, after applying the writes before the failing
  one; answers an array index on a property that is not an array; cannot
  encode an empty list in a ReadPropertyMultiple reply (the request is
  aborted, also for `all` of the Device); does not expand `required` /
  `optional`; answers a malformed request with Reject
  missing-required-parameter or Abort (other).
- **Empty lists:** bacnet-stack, BACpypes3, BACnet4J and System.IO.BACnet all
  answer a ReadProperty of an empty list (Device_Address_Binding, for
  example) with an empty value, `3E 3F`.
- **BACpypes3 0.0.110** has no handler for File, CreateObject, ReadRange,
  GetAlarmSummary, GetEventInformation, AcknowledgeAlarm or
  SubscribeCOVProperty. It answers a known service without a handler with
  Reject unrecognized-service, and an unknown service choice or a malformed
  request with nothing at all.
- **BACnet4J 6.1.1** has no WriteGroup, COV-multiple, Who-Am-I / You-Are,
  audit or VT.
- **bacnet-stack 1.6.1** has no GetEnrollmentSummary, TextMessage,
  ConfirmedPrivateTransfer or COV-multiple.

## Client mode

Peers acting as **clients** against a device under test
([docs/CLIENT_DRIVER_CONTRACT.md](docs/CLIENT_DRIVER_CONTRACT.md)):
bacnet-stack (the upstream command-line tools), BACnet4J (the upstream
`LocalDevice`), BACpypes3 (its upstream Application) and bacnet-js (its
upstream `BACnetClient`), each at its pin, unmodified. The go-bacnet server is the first device under test.

### Clients against the device images

`make client-matrix` (in CI) runs `server-baseline-v1` with every client
image against the device images, on `device-baseline-v2`. The scenario
expectations record bacnet-stack's answers where the standard leaves the
error open, so the bacnet-stack device is the gate: every client passes all
23 scenarios against it (bacnet-js: 21 pass and 2 known-difference, below).
Against the other device images some scenarios differ; CI reports those
pairs (`--all-devices`) without failing on them:

| Client \ device | bacnet-stack | BACnet4J | BACpypes3 | bacnet-js |
|---|---|---|---|---|
| bacnet-stack | 23 pass | 2 pass; no I-Am reaches the client, so the tools cannot bind | 20 pass | 23 pass |
| BACnet4J | 23 pass | 16 pass | 20 pass | 23 pass |
| BACpypes3 | 23 pass | 2 pass; no I-Am reaches the client, so it cannot bind | 20 pass | 23 pass |
| bacnet-js | 21 pass, 2 known-difference | 16 pass, 1 known-difference | 20 pass, 1 known-difference | 21 pass, 2 known-difference |

What the device images do differently:

- **BACnet4J device** (as the adapter binds it, to the container's own
  address): Who-Is and Who-Has get no I-Am or I-Have at the client, so the
  clients that bind by Who-Is (bacnet-stack, BACpypes3) do not run the other
  scenarios (`infra-error`). It accepts a WriteProperty and a
  WritePropertyMultiple of a CharacterString to an Analog Value's
  Present_Value (SimpleACK), and names error class property, not object, for
  an unknown object in WritePropertyMultiple.
- **BACpypes3 device:** a value of the wrong datatype gets Reject
  invalid-tag instead of Error property/invalid-data-type (WriteProperty and
  WritePropertyMultiple), and an unknown object in WritePropertyMultiple gets
  a plain Error (`91 01 91 1f`, object/unknown-object) instead of a
  WritePropertyMultiple-Error naming the first failed write.

### bacnet-stack

Known behaviour of the bacnet-stack tools:

- **`bacrle`** (RemoveListElement) registers its reply handlers for
  AddListElement (apps/remove-list-element/main.c), so it prints nothing for
  the acknowledgement or an error. The scenario result is `known-difference`;
  `server-services-v1` checks the removal by reading Recipient_List back.
- **`bacge`** (GetEventInformation) cannot decode a reply with an empty list
  of event summaries ("Decode of Ack returned length -1"), also from a
  bacnet-stack device. The scenarios read a non-empty list only.
- **`bacscov`** waits for the subscription lifetime before it exits, so the
  scenarios use short lifetimes (5 s).
- **Invoke IDs** are reused across tool runs, from the same source
  address. A device that answers a repeated invoke ID from a cache instead
  of executing it (clause 5.4.5 makes it a new request after the response)
  answers a second DeleteObject with the first one's result.
- **Foreign-device registration:** a tool started with `BACNET_BBMD_*`
  prints its own Register-Foreign-Device result, so the BVLC table tools run
  without registering.
- **No segmentation:** the tools are built without it, so segmented
  transactions have no bacnet-stack client evidence.

### BACnet4J

Known behaviour of the BACnet4J 6.1.1 client:

- **SubscribeCOVPropertyMultiple-Error** is decoded as a CHOICE of
  errorType [0] or firstFailedSubscription [1]
  (`SubscribeCovPropertyMultipleError.choiceOptions`); clause 21 defines a
  SEQUENCE of both. BACnet4J keeps errorType and drops the first failed
  subscription. When class and code match the scenario and only
  `first_failed` is missing, the result is `known-difference`
  (`server-extended-v1` `scovpm.unknown-object-second`); another class or
  code is still a `fail`.
- **COVNotificationMultiple:** decoded, but the stack's `handle()` throws
  `NotImplementedException` (a confirmed one is answered with Reject
  unrecognized-service). The driver reads the decoded request in
  `requestReceived` (adapter-shim); the scenarios use unconfirmed
  notifications.
- **BVLC tables:** no client for Read-BDT, Read-FDT or Write-BDT
  (`IpNetwork` serves them as a BBMD only): `unsupported`.
- **Segmentation:** both directions work; `server-extended-v1` reads and
  writes a 3000-octet file in one request each.

### BACpypes3

BACpypes3 0.0.110 cannot decode some answers; its
ApplicationServiceAccessPoint drops them and the request would time out. The
driver detects the failed decode and reports `known-difference` with the
answer's octets ([adapters/bacpypes3/README.md](adapters/bacpypes3/README.md#client-mode)):

- **ChangeList-Error** (AddListElement, RemoveListElement): `ChangeListError`
  has no `service_choice`, so constructing it raises AttributeError
  (`ale.unknown-object`).
- **Error of SubscribeCOVProperty:** service choice 28 is not in its
  `error_types` ("unrecognized service choice: 28";
  `scovp.unknown-object`, `scovp.unknown-property`).
- **Empty GetAlarmSummary-ACK and GetEnrollmentSummary-ACK:** the list is a
  required element and an empty SEQUENCE OF has no octets
  (`gas.normal`, `gas.av2.after-normal`, `ges.offnormal-filter.normal`).

Other behaviour:

- **SubscribeCOVPropertyMultiple** is `unsupported`: no request APDU and no
  COV-multiple notification type.
- **Foreign mode** takes every BVLC-Result as a registration result: a
  Write-BDT NAK never reaches `BVLLServiceElement` and sets the registration
  status to 0x0010. The BVLC table services run from an unregistered link
  layer.
- **Oversized segments:** a segmented request carries Max APDU octets of
  service data after the 6-octet segment header, so each segment is 1482
  octets for a device that accepts 1476. A device that bounds an APDU by
  its Max_APDU_Length_Accepted drops them; the go-bacnet server accepts
  them.
- **Enumeration names** come from camel case (error code 22 is
  `property-is-not-alist`); the driver compares names without hyphens.

Against the go-bacnet server (go-bacnet `interop/server_clients_test.go`): `server-baseline-v1` 23 of 23 pass; `server-services-v1`
35 pass, 1 known-difference; `server-bbmd-v1` 5 of 5 pass;
`server-extended-v1` 15 pass, 5 known-difference, 3 unsupported.

### bacnet-js

Known behaviour of the @bacnet-js/client 3.3.2 client (source references in
[adapters/bacnet-js/README.md](adapters/bacnet-js/README.md#client-mode-client-as-the-first-argument)):

- **WritePropertyMultiple-Error** is decoded with the plain Error decoder
  (`client.ts _processError`, `services/Error.ts`): no first failed write,
  and the constructed `[0]` is read as if it were application-tagged
  (observed class device, code 1). `wpm.unknown-object-second` and
  `wpm.wrong-type` are `known-difference`.
- **BACnetDateTime decode:** `asn1.decodeBacnetDatetime` uses `getDay()`
  (the weekday) as the day of the month, so an Event_Time_Stamps date echoed
  in AcknowledgeAlarm is wrong and the device answers invalid-time-stamp;
  the result is `known-difference` (`ack.av2` against a device that stamps a
  date; the go-bacnet server stamps a sequence number and passes).
- **Reject and Abort** reach the caller alike ("BacnetAbort - Reason:N"); the
  driver reads the PDU type from the wire.
- **No segmented requests:** `awf.file3.segmented-request` is `unsupported`.
  Segmented answers are reassembled; `readFile()` does not set
  segmented-response-accepted, so the driver sends the 3000-octet read with
  upstream's encoder in a request that does (`arf.file3.segmented-reply`).
- **No encoder** for AddListElement / RemoveListElement of a
  BACnetDestination (application tags only), CreateObject by type,
  WriteGroup, text messages, SubscribeCOVPropertyMultiple, or the BVLC table
  functions: `unsupported`. GetEnrollmentSummary with a filter is
  `unsupported` (`encode` drops filter 0 and wraps the others in constructed
  tags).
- **Against the bacnet-js device**, `arf.file3.segmented-reply` fails: the
  device cannot send a segmented answer and aborts with
  segmentation-not-supported.
