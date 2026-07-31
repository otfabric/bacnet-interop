# BIP↔BIP topology router

Minimal dual-homed BACnet/IP router for Horizon 1 interop topology tests in
[`go-bacnet/interop`](https://github.com/otfabric/go-bacnet).

**Not** a product BBMD or general-purpose BACnet router. Scope is intentional:

- Who-Is-Router-To-Network → I-Am-Router-To-Network
- Forward Original-Unicast / Original-Broadcast NPDUs with DNET
- Hop-count decrement
- Return-path assist for peers that reply without reverse DNET/DADR
- Local-broadcast forward with SNET (I-Am toward the originating network)

## Image

```text
bacnet-interop-bip-router:local
```

Built by `make build-bip-router` / `make build` from the repository root
(`BIP_ROUTER_IMAGE`, default `bacnet-interop-bip-router:local`). Included in
`make smoke`.

## Run (dual docker networks)

```bash
# from bacnet-interop root
make build-bip-router

docker network create bacnet-net-a
docker network create bacnet-net-b
docker create --name bip-router --network bacnet-net-a \
  -e ADAPTER_VERSION=dev -e BACNET_NETWORKS=1,2 \
  bacnet-interop-bip-router:local
docker network connect bacnet-net-b bip-router
docker start -a bip-router
```

`entrypoint.sh` waits for `eth0`/`eth1` IPv4 addresses, then binds UDP/47808 on
both. Network numbers default to `1,2` (`BACNET_NETWORKS`).

Environment: `ADAPTER_VERSION`, `BACNET_IP_PORT`, `BACNET_NETWORKS`.

## Readiness

Stdout JSON Lines:

```json
{"event":"ready","adapter":"bip-router","version":"...","fixture":"topology-router-v1","address":"...","networks":[1,2],"addresses":["...","..."]}
```

Consumed by `go-bacnet/interop` routed topology tests (`BIP_ROUTER_IMAGE`).
See [`COVERAGE.md`](../../COVERAGE.md) and [`go-bacnet/INTEROP.md`](https://github.com/otfabric/go-bacnet/blob/main/INTEROP.md).
