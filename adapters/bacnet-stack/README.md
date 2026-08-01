# bacnet-stack adapter

Containerized [bacnet-stack](https://github.com/bacnet-stack/bacnet-stack) peer for [`bacnet-interop`](../..).

**Status:** fixture-driven device-server image. Pin: `bacnet-stack-1.6.0` (`BACNET_STACK_SHA` in Dockerfile).

## Role

Primary **executable** C oracle for Horizon 1:

- Custom `device_server` linked against pinned bacnet-stack (not stock `bacserv`)
- Object graph loaded from `device-baseline-v1.json` (device + AV-1 + BV-1)
- Who-Is / I-Am, ReadProperty, ReadPropertyMultiple, WriteProperty, SubscribeCOV

`go-bacnet` must never link against bacnet-stack. The peer runs only as a separate image under its upstream license; distribution must preserve that license and corresponding source obligations.

## Layout

| Path | Purpose |
|---|---|
| `device_server.c` | Slim BACnet/IP server: Device + Network Port + AV + BV only |
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

Stdout is a single JSON Lines ready event after the BACnet/IP UDP socket is bound:

```json
{"event":"ready","adapter":"bacnet-stack","version":"0.1.0","fixture":"device-baseline-v1","address":"0.0.0.0:47808","peer_version":"bacnet-stack-1.6.0"}
```

`device_server` diagnostics go to stderr. See [`PLAN.md`](../../PLAN.md).

## Build

```bash
# from bacnet-interop root
make build-bacnet-stack
docker run --rm -p 47808:47808/udp bacnet-interop-bacnet-stack:local
```

Environment overrides: `BACNET_IP_PORT`, `DEVICE_FIXTURE_FILE`, `FIXTURE`, `ADAPTER_VERSION`, `BACNET_STACK_VERSION`.

## Fixture notes

`/fixtures/device/device-baseline-v1.json` is the runtime source of truth. This adapter constructs only the objects listed there (alignment: `full-object-graph` with BACpypes3). Segmentation of ComplexACK is still limited by bacnet-stack TSM behaviour (oversized responses Abort with segmentation-not-supported). Reject for unrecognized confirmed services is supported and asserted by `go-bacnet/interop`.

Routed RP uses this image as the remote device behind [`bip-router`](../bip-router/README.md). BBMD/foreign-device peer mode is not implemented here (BACpypes3 only).

## Capability tracking

Update [`COVERAGE.md`](../../COVERAGE.md) when modes change.
