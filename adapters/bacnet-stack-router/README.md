# bacnet-stack native router

Upstream [bacnet-stack](https://github.com/bacnet-stack/bacnet-stack)
`apps/router`, built unpatched at the commit the
[`bacnet-stack`](../bacnet-stack/README.md) adapter pins
(`bacnet-stack-1.6.1`, `BACNET_STACK_SHA` in both Dockerfiles: move them
together).

## Role

A real stack's BACnet router between two BACnet/IP networks, for routed
client tests in [`go-bacnet/interop`](https://github.com/otfabric/go-bacnet).
Unlike [`bip-router`](../bip-router/README.md) (a topology aid written for
the tests) it does nothing to help a device that cannot route its reply: the
device behind it must answer through the router itself.

Why `apps/router` and not the other upstream candidates:

| Upstream app | What it is | Verdict |
|---|---|---|
| `apps/router` | Multi-port BACnet/IP ↔ BACnet/IP / MS/TP router, ports bound per interface | **Used**: routes between two Docker networks as is |
| `apps/router-ipv6` | BACnet/IP ↔ BACnet/IPv6 | Other datalink |
| `apps/router-mstp` | BACnet/IP ↔ MS/TP | Needs a serial line |
| `apps/gateway`, `apps/gateway2` | One device with virtual routed devices behind it | No second network, no forwarding between real peers |

`go-bacnet` must never link against bacnet-stack. The router runs only as a
separate image under its upstream license (`apps/router` is MIT).

## What it does (observed)

- Answers Who-Is-Router-To-Network (local broadcast or unicast) with an
  I-Am-Router-To-Network sent as Original-Broadcast-NPDU to UDP 47808, NPDU
  `01 a0 ff ff 00 ff 01 <net>`: a client must listen on 47808 to hear it.
- Forwards an NPDU with DNET = a directly connected network to the DADR
  station, adding SNET/SADR of the sender and dropping DNET.
- Forwards a global broadcast (DNET 0xFFFF) to the other port as a broadcast
  to that subnet's broadcast address, keeping DNET 0xFFFF and adding
  SNET/SADR. A device behind it must receive subnet broadcasts.
- Does **not** decrement the hop count.
- Does **not** send Reject-Message-To-Network. For an unknown DNET it
  broadcasts Who-Is-Router-To-Network on both ports and drops the message;
  that Who-Is-Router carries the DLEN/DADR of the dropped message next to
  DNET 0xFFFF (`01 a0 ff ff 01 01 ff 00 00 63` for DNET 99, DADR `01`),
  which is not a valid NPDU.
- Every NPDU without DNET it receives (a local broadcast, for example)
  triggers the same Who-Is-Router-To-Network search for network 0.
- No BBMD, no foreign-device registration.

## Layout

| Path | Purpose |
|---|---|
| `Dockerfile` | Builds upstream `apps/router` at the pinned SHA; minimal runtime |
| `run_router.py` | Finds the interface for each address, writes the router config, starts `bacnet-router`, emits `event=ready` |
| `entrypoint.sh` | `exec python3 run_router.py` |

Build configuration (no source patch): `-DBACNET_IP_BROADCAST_USE_INADDR_ANY`
(upstream switch; without it each port socket is bound to the interface's
unicast address and Linux never delivers the broadcasts that carry
Who-Is-Router-To-Network, Who-Is and I-Am), `-DDEBUG_LEVEL=2` (upstream
diagnostics on stderr), `-O1` (upstream notes an `fd_set` failure with `-Os`).

## Image

```text
bacnet-interop-bacnet-stack-router:local
ghcr.io/otfabric/bacnet-interop-bacnet-stack-router:<version>
```

Built by `make build-bacnet-stack-router` / `make build`
(`BACNET_STACK_ROUTER_IMAGE`). Included in `make smoke`
(`SMOKE_ONLY=bacnet-stack-router`, `BACNET_STACK_ROUTER_REQUIRED=1` to fail
when the image is missing).

## Run (dual docker networks)

```bash
make build-bacnet-stack-router

docker network create --subnet 10.230.1.0/24 bacnet-net-a
docker network create --subnet 10.230.2.0/24 bacnet-net-b
docker create --name bacnet-router --network bacnet-net-a --ip 10.230.1.2 \
  -e BACNET_NETWORKS=1,2 \
  -e BACNET_ADDR_NET1=10.230.1.2 -e BACNET_ADDR_NET2=10.230.2.2 \
  bacnet-interop-bacnet-stack-router:local
docker network connect --ip 10.230.2.2 bacnet-net-b bacnet-router
docker start -a bacnet-router
```

`apps/router` binds its ports by interface name. Docker does not keep
eth0/eth1 in connect order, so set `BACNET_ADDR_NET1` / `BACNET_ADDR_NET2`:
the entrypoint looks up the interface that carries each address. Without
them it falls back to eth0 = first network, eth1 = second.

The container runs as root: `SO_BINDTODEVICE` needs `CAP_NET_RAW` (in Docker's
default capability set).

Environment: `ADAPTER_VERSION`, `BACNET_IP_PORT` (default 47808, both ports),
`BACNET_NETWORKS` (default `1,2`), `BACNET_ADDR_NET1`, `BACNET_ADDR_NET2`,
`BACNET_STACK_VERSION`.

## Readiness

One JSON line on stdout once both UDP sockets are bound. Same contract as
`bip-router`, plus `interfaces`:

```json
{"event":"ready","adapter":"bacnet-stack-router","version":"...","fixture":"topology-router-v1","address":"10.230.1.2:47808","networks":[1,2],"addresses":["10.230.1.2:47808","10.230.2.2:47808"],"interfaces":["eth0","eth1"],"peer_version":"bacnet-stack-1.6.1"}
```

`address` is the network-1 side. Router diagnostics go to stderr.

Consumed by `go-bacnet/interop` `TestBacnetStackNativeRouter`
(`BACNET_STACK_ROUTER_IMAGE`).
