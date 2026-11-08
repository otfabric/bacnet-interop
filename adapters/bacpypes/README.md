# Legacy BACpypes adapter

Containerized [BACpypes](https://github.com/JoelBender/bacpypes) peer for
[`bacnet-interop`](../..): PyPI `bacpypes` 0.19.0, the asyncore code base that
[BACpypes3](../bacpypes3) replaced. It is **not** BACpypes3: adapter id
`bacpypes`, image `ghcr.io/otfabric/bacnet-interop-bacpypes`, consumer variable
`BACPYPES_IMAGE` (BACpypes3 is `bacpypes3` / `BACPYPES3_IMAGE`).

**Status:** device server (default), BBMD role (`BACNET_BBMD=1`) and client
mode (`client`, [docs/CLIENT_DRIVER_CONTRACT.md](../../docs/CLIENT_DRIVER_CONTRACT.md)).

## Pin and provenance

| | |
|---|---|
| Package | `bacpypes==0.19.0`, installed with `pip --require-hashes --only-binary=:all: --no-deps` ([requirements.txt](requirements.txt)) |
| Wheel | `bacpypes-0.19.0-py3-none-any.whl`, sha256 `317fbe440474845978dab134f8aefb5f45a41a13926cbdf87b9b8afe6e79131b`, uploaded 2025-01-22; the release has no other file and no dependencies |
| Source | Untagged on GitHub (the last tag is `v0.18.6`, `27ab4f1`, 2022-02-02). The wheel's `bacpypes/` is byte-identical to `py34/bacpypes` at `86288e6` ("trap exceptions raised for bad values", 2025-01-21 23:26 -0500, before the upload), and unchanged at `a7f2f41` and at master `e59ea3c` (2026-01-22); the later commits change only `requirements.txt` |
| Licence | MIT (`LICENSE` in the wheel, installed as `/opt/venv/lib/python3.11/site-packages/bacpypes-0.19.0.dist-info/LICENSE`; the wheel METADATA also carries a BSD classifier) |
| Base image | `debian:bookworm-slim@sha256:7b140f37…5818`, the digest of the other Debian images. Python 3.11.2: BACpypes 0.x needs `asyncore`, which Python 3.12 removed; the build fails when it is missing |
| User | `adapter` (uid/gid 10001) |

How independent it is: BACpypes and BACpypes3 have the same author (Joel
Bender) and the same object model vocabulary; BACpypes3 is a separate
repository and package, rewritten for asyncio, not an import of this code
base. They are not independent in the sense of two unrelated teams reading the
standard; agreement between the two is weaker evidence than agreement between
either and bacnet-stack, BACnet4J or cB-Sigma.

## Device mode

Upstream services, mixed into one Application (`device_server.py`
`DeviceApplication`):

| Service | Source |
|---|---|
| Who-Is / I-Am, Who-Has / I-Have | upstream `WhoIsIAmServices`, `WhoHasIHaveServices` |
| ReadProperty, ReadPropertyMultiple, WriteProperty | upstream `ReadWritePropertyServices`, `ReadWritePropertyMultipleServices` |
| SubscribeCOV, SubscribeCOVProperty | upstream `ChangeOfValueServices` |
| AtomicReadFile, AtomicWriteFile | upstream `FileServices`; the contents are adapter subclasses of the abstract `LocalStreamAccessFileObject` / `LocalRecordAccessFileObject` |
| DeviceCommunicationControl | upstream `DeviceCommunicationControlServices`, enforced in the `StateMachineAccessPoint` |
| WritePropertyMultiple | **adapter-shim**: upstream ships `do_WritePropertyMultipleRequest` commented out (`service/object.py`). The shim answers WritePropertyMultiple-Error with firstFailedWriteAttempt and maps a failed cast to property/invalid-data-type |
| ReadRange by position and by sequence number | **adapter-shim**: upstream has the APDU, no handler |
| ReinitializeDevice | **adapter-shim**: password checked, SimpleACK, operation line, no restart |
| TimeSynchronization, UTCTimeSynchronization, Unconfirmed/ConfirmedTextMessage, Unconfirmed/ConfirmedPrivateTransfer, WriteGroup | **adapter-shim**: upstream decodes them; the adapter's sinks emit `{"event":"operation",...}` and answer the confirmed ones |

Every other confirmed service (CreateObject, DeleteObject, Add/RemoveListElement,
GetAlarmSummary, GetEnrollmentSummary, GetEventInformation,
AcknowledgeAlarm, …) gets upstream's Reject unrecognized-service.

Objects built from the fixture: Device (`LocalDeviceObject`), commandable
Analog Value and Binary Value (`AnalogValueCmdObject`, `BinaryValueCmdObject`,
registered for vendor 999 as upstream's `samples/CommandableMixin.py` does;
unregistered they are read-only), Analog Input, Notification Class (empty
Recipient_List), Trend Log (its `log_buffer` as REAL records), File (stream
and record), Life Safety Point and Zone. Event Enrollment and Audit Log have
no upstream class and are skipped with a note on stderr.

### Environment

| Variable | Default | Effect |
|---|---|---|
| `DEVICE_FIXTURE_FILE`, `FIXTURE` | `device-baseline-v2` | fixture to serve |
| `BACNET_IP_PORT` | 47808 | UDP port |
| `BACNET_DEVICE_ADDRESS` | the container's address | address the stack binds (`ip/prefix`, which also opens the broadcast socket) |
| `BACNET_MAX_APDU` | 1024 (upstream default) | Max_APDU_Length_Accepted |
| `BACNET_MAX_SEGMENTS` | 16 | Max_Segments_Accepted |
| `BACNET_SEGMENT_WINDOW` | 2 (upstream default) | the SMAP `proposedWindowSize`; the actual window is the smaller of this and the peer's |
| `BACNET_DCC_PASSWORD` | none | password for DeviceCommunicationControl and ReinitializeDevice |
| `BACNET_BBMD` | off | `1`: run upstream `BIPBBMD` with its own BDT entry (mask 255.255.255.255) and accept foreign devices |

The ready line is
`{"event":"ready","adapter":"bacpypes","version":…,"fixture":…,"address":"0.0.0.0:47808","peer_version":"0.19.0"}`.

### Behaviour to know

- **Wrong datatype:** WriteProperty of a value of the wrong datatype gets
  Reject invalid-tag (upstream casts while decoding), not Error
  property/invalid-data-type.
- **DeviceCommunicationControl:** "disable" is acknowledged and enforced:
  only DeviceCommunicationControl, ReinitializeDevice and Who-Is are
  processed until "enable" or the duration ends. Under disable-initiation
  the device keeps answering requests, an I-Am that answers a Who-Is
  included (clause 16.1.1.3.1).
- **SubscribeCOVProperty** does not check the monitored property: a
  subscription to a property the object does not have is accepted and
  reports Present_Value and Status_Flags.
- **BBMD:** Register-Foreign-Device is always accepted and the FDT entry's
  remaining time is TTL + 5 (clause J.5.2.3 has a 30-second grace period).
  Write-BDT is always NAKed with 0x0010; Delete-FDT of an absent entry with
  0x0050. From the source (not exercised): Distribute-Broadcast-To-Network is
  accepted from any sender, registered or not (`bvllservice.py` `BIPBBMD`).
- **Capabilities must be direct bases:** upstream's `Collector` finds
  capabilities with a lazy `map()` that Python 3 never runs, so a capability
  more than one level below the instantiated class is never initialised
  (DCC then fails with AttributeError `_dcc_enable_task`).

## Client mode

`docker run … bacnet-interop-bacpypes:local client --target HOST:PORT --device N --scenarios /scenarios/<file>.json [--bbmd HOST:PORT --fd-ttl S] [--only ids] [--broadcast HOST:PORT]`

The asyncore core runs in the main thread, the scenarios in a worker thread
that hands each request to the core with `deferred()` (upstream
`samples/ThreadedReadProperty.py`). Requests are upstream APDU classes sent
through `request_io` with an IOCB. `BACNET_CLIENT_TIMEOUT_MS` (3000) and
`BACNET_CLIENT_RETRIES` (1) set the transaction timeout and retries.

- Every service of the four scenario files has an upstream request APDU
  except SubscribeCOVPropertyMultiple (`unsupported`: `apdu.py` registers no
  confirmed service 30).
- With `--bbmd` the client is a `BIPForeign`. Upstream takes every
  BVLC-Result from the BBMD as its registration status, so Read-BDT,
  Read-FDT and Write-BDT go out on a second `AnnexJCodec`/`UDPMultiplexer`
  on port 47809 (upstream `samples/ReadWriteBBMD.py`).
- Upstream's ASAP replaces an answer it cannot decode with an Error; the
  driver decodes a copy of every answer and reports a failed decode itself
  (**adapter-shim**). No answer of the go-bacnet server failed to decode.
- Enumeration names come from camel case; the driver converts them to the
  hyphenated names of the scenario files.

## Build

```bash
make build-bacpypes
make smoke SMOKE_ONLY=bacpypes
```

Upstream candidate: `make candidate-bacpypes CANDIDATE_VERSION=<version> CANDIDATE_SHA=<wheel sha256>`
(`scripts/latest-upstream.py bacpypes` prints both).

Capabilities per service: [adapters/inventory.yaml](../inventory.yaml);
results: [PEER_SUPPORT.md](../../PEER_SUPPORT.md#legacy-bacpypes-bacpypes).
