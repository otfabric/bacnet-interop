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

Serves `device-baseline-v2` unchanged:

- Device 1234 `InteropDevice`
- AnalogValue 1 `AV-1` (21.5)
- BinaryValue 1 `BV-1` (inactive)
- TrendLog 0 `TL-0` (seeded Log_Buffer for ReadRange)

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
{"event":"ready","adapter":"worldiety","version":"0.8.0","fixture":"device-baseline-v2","address":"0.0.0.0:47808","peer_version":"3cb2aa80…"}
```

See [PEER_SUPPORT.md](../../PEER_SUPPORT.md) for the global peer matrix.

