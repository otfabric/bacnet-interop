# Worldiety adapter

Fixture-driven BACnet/IP device server built on
[`github.com/worldiety/bacnet`](https://github.com/worldiety/bacnet) at commit
`3cb2aa80efbb8a489abb9978c7f6e5dc603535a7`.

## Role

```text
go-bacnet client → Worldiety fixture-driven server
```

Worldiety owns BVLC, NPDU, APDU dispatch, confirmed transactions, segmented
confirmed-request receive, and segmented ComplexACK send. This adapter owns the
fixture object model and service payload handlers (RP/RPM/WP/WPM/ReadRange,
Who-Is/Who-Has).

**Do not import `go-bacnet`.** Assertions live in `go-bacnet/interop`.

## Evidence classification

| Layer | Evidence |
|---|---|
| bvlc | native |
| npdu | native |
| apdu_dispatch | native |
| confirmed_transactions | native |
| segmented_request_receive | native |
| segmented_complex_ack_send | native |
| fixture_object_model | adapter-shim |
| service_payload_handlers | adapter-shim |

## Fixture

The image ships `device-baseline-v1`–`v8` and serves v2 by default:

- Device 1234 `InteropDevice`
- AnalogValue 1 `AV-1` (21.5)
- BinaryValue 1 `BV-1` (inactive)
- TrendLog 0 `TL-0` (36 seeded Log_Buffer records; see "Trend Log" below)

## Behaviour to know

All of this is the adapter's fixture object model, not upstream behaviour:

- A ReadProperty of the Device wildcard `device,4194303` is answered with
  Error object/unknown-object.
- A write to a read-only property is refused with Error
  property/write-access-denied.
- Who-Is is answered with a unicast I-Am, whether it arrived by
  subnet-directed or by limited broadcast.
- **WritePropertyMultiple:** the writes are executed in order; the first one
  that fails ends the request with a WritePropertyMultiple-Error naming it.
  Writes before it stay applied. A write to a property the adapter does not
  model, or to a read-only one, is property/write-access-denied; a value of
  the wrong type property/value-out-of-range. Up to 0.9.0 the
  `firstFailedWriteAttempt` was encoded with the property identifier nested
  one level too deep, which a client cannot decode as a
  BACnetObjectPropertyReference.

Upstream behaviour: continuation segments of a segmented ConfirmedRequest or
ComplexACK omit the service choice, which go-bacnet treats as a protocol
violation; the scenarios run against this peer are unsegmented.

## Trend Log

Adapter code throughout: the records, and the range selection of ReadRange.
The upstream stack contributes the transport and the tag codec the request is
decoded with.

Up to 0.9.0 the seed was four records (`2024-01-01 12:00`–`12:03`, REAL
20–23), `Record_Count` was answered under property 140 instead of 141, and a
bySequenceNumber or byTime request was answered with the whole buffer. Since
0.10.0 the seed is the one the BACnet4J adapter uses:

| | |
|---|---|
| `Record_Count` (141) / `Total_Record_Count` (145) | 36 |
| Record at position *k* (1-based) | time stamp `2024-01-01 00:00:00` + (*k*−1) × 15 min (day of week unspecified), logDatum real-value 20 + (*k*−1), no statusFlags, sequence number *k* |

- byPosition: a reference outside the buffer is Error
  property/invalid-array-index.
- bySequenceNumber: a reference that is not the sequence number of a record
  selects nothing (item count 0, result flags clear).
- byTime, positive count: records strictly after the reference time; negative
  count: records strictly before it. A reference time with an unspecified
  field is Error property/datatype-not-supported.
- A negative count returns the records up to and including the reference,
  oldest first (up to 0.9.0 it was treated as a positive count).
- bySequenceNumber and byTime replies that hold a record carry
  `firstSequenceNumber`; byPosition replies do not.
- MORE_ITEMS is never set: every selection fits one reply.

## Build / smoke

From repository root:

```bash
make build-worldiety
SMOKE_ONLY=worldiety make smoke
```

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `DEVICE_FIXTURE_FILE` | `/fixtures/device/device-baseline-v2.json` | Fixture path |
| `ADAPTER_VERSION` | build-arg / `dev` | Ready `version` |
| `WORLDIETY_COMMIT` | `3cb2aa80…` | Ready `peer_version` |
| `FIXTURE` | from JSON | Ready `fixture` |

## Ready event

```json
{"event":"ready","adapter":"worldiety","version":"0.11.1","fixture":"device-baseline-v2","address":"0.0.0.0:47808","peer_version":"3cb2aa80…"}
```

## BBMD / router

Peer-as-BBMD and native multi-homed BIP routing are **not** available through
this adapter (`ClientRuntime` does not wire upstream BBMD/router helpers).
See [PEER_SUPPORT.md](../../PEER_SUPPORT.md) for the global peer matrix.

