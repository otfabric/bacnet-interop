# Adapter Capability Coverage

Availability of adapter behaviours for Horizon 1 peers. Compatibility claims and
scenario assertions live in [`go-bacnet`](https://github.com/otfabric/go-bacnet)
(`interop/`, `INTEROP.md`).

Update a cell to ✓ only when a command or mode is built, smoke-tested, and
listed in the adapter README. Document upstream gaps in the limitations table —
never skip silently in consumer CI without a registered row.

Adapter version: `unreleased` · Fixture revision: `device-baseline-v1`

| Capability | bacnet-stack | BACpypes3 | BACnet4J | Notes |
|---|:---:|:---:|:---:|---|
| Who-Is / I-Am (server answers) | ✓ | ✓ | ✓ | Directed Who-Is in-network; discovery client may bind `:47808` for broadcast I-Am |
| Who-Is probe (client sequence) | planned | planned | planned | Fixed-sequence JSON Lines client adapter not packaged yet |
| ReadProperty (RP) | ✓ | ✓ | ✓ | Device object-name + AV-1 present-value |
| ReadProperty unknown-property Error | ✓ | ✓ | ✓ | `*bacnet.ErrorResponse` class=property code=unknown-property |
| Reject unrecognized service | ✓ | — | ✓ | BACpypes3 raises instead of Reject (see limitations) |
| Abort (segmentation path) | ✓ | ✓ | — | bacnet-stack/BACpypes3 Abort paths asserted; BACnet4J segments instead |
| ReadPropertyMultiple (RPM) | ✓ | ✓ | ✓ | Success + property-level partial Error |
| WriteProperty (WP) | ✓ | ✓ | ✓ | AV present-value write + readback + restore |
| COV subscribe / notify / cancel | ✓ | ✓ | ✓ | Unconfirmed COV; BACpypes3 also renew |
| COV renew | — | ✓ | — | BACpypes3 only so far |
| Routed remote device | ✓ | ✓ | ✓ | Via `bip-router` dual-net topology; Who-Is-Router→ResolveTarget asserted on BACpypes3 |
| Foreign-device / BBMD (peer as BBMD) | — | ✓ | ✓ | `BACNET_BBMD=1`; client Register-Foreign-Device + DBTN Who-Is + RP |
| Forwarded-NPDU receive (client) | — | ✓ | ✓ | Exercised when BBMD forwards to a registered FD |
| Segmentation / small max-APDU | — | ✓ | ✓ | `BACNET_MAX_APDU`; bacnet-stack does not segment (Abort instead) |
| Readiness JSON Lines (`event=ready`) | ✓ | ✓ | ✓ | After UDP bind / application construct |
| `--capabilities` / `--version` | planned | planned | planned | Optional until M1-style contract |

**Topology aid (not a peer oracle):**

| Capability | bip-router | Notes |
|---|:---:|---|
| Who-Is-Router / I-Am-Router | ✓ | Dual-homed; `BACNET_NETWORKS=1,2` |
| DNET/DADR forward + hop decrement | ✓ | Unicast delivery omits SNET; return-path assist for peers without reverse routing |
| Readiness JSON Lines | ✓ | Fixture `topology-router-v1` |

**Image names (target):**

| Image | Peer / aid | Pin |
|---|---|---|
| `ghcr.io/otfabric/bacnet-interop-bacnet-stack` | [bacnet-stack](https://github.com/bacnet-stack/bacnet-stack) | `bacnet-stack-1.6.0` |
| `ghcr.io/otfabric/bacnet-interop-bacpypes3` | [BACpypes3](https://github.com/JoelBender/BACpypes3) | `0.0.106` |
| `ghcr.io/otfabric/bacnet-interop-bacnet4j` | [BACnet4J](https://github.com/RadixIoT/BACnet4J) | `6.1.0` |
| `ghcr.io/otfabric/bacnet-interop-bip-router` | interop BIP↔BIP router | topology fixture (not a product router) |

**Known limitations (verified upstream gaps):**

| Stack | Version | Direction | Capability | Reason | Consumer skip |
|---|---|---|---|---|---|
| all peers | — | transport | Host UDP to container on Docker Desktop | Bridge IPs are not host-routable; published-port return paths are unreliable for BACnet | `go-bacnet/interop` re-executes tests inside the peer docker network on macOS/Windows; routed tests always re-exec on the client net |
| BACpypes3 | 0.0.106 | bind | `0.0.0.0/0` address | Confirmed-service replies fail; use `host:<port>` (adapter default) or numeric CIDR when `BACNET_BBMD=1` | — |
| BACpypes3 | 0.0.106 | Reject | Unrecognized confirmed service | Application raises `RuntimeError` instead of emitting a Reject PDU | No BACpypes3 Reject assertion; covered by bacnet-stack + BACnet4J |
| bacnet-stack | 1.6.0 | segmentation | Segmented ComplexACK | Stack TSM aborts with segmentation-not-supported rather than segmenting | Assert Abort; segmented reassembly covered by BACpypes3 + BACnet4J |
| bip-router | — | discovery | Remote I-Am observation | Docker broadcast delivery to ephemeral clients is unreliable; RP via DNET/DADR is the hard assertion | Routed Who-Is I-Am is best-effort in `go-bacnet/INTEROP.md` |

**Notes:**

- Device model documentation: `fixtures/device/device-baseline-v1.json`.
- All three peer adapters construct device + AV-1 + BV-1 from that JSON (`full-object-graph`).
- Optional `BACNET_MAX_APDU` on BACpypes3 and BACnet4J overrides `maxApduLengthAccepted`.
- Optional `BACNET_BBMD=1` on BACpypes3 and BACnet4J enables peer-as-BBMD.
- Optional `BACNET_NETWORK` sets the local BACnet network number (BACpypes3 / BACnet4J).
- `bip-router` is dual-homed (`eth0`/`eth1`); `BACNET_NETWORKS=1,2` sets BACnet nets.
- Stdout is JSON Lines; diagnostics go to stderr.
- A skipped `go-bacnet` interop test without a registered limitation must fail CI.
- Codec goldens under `fixtures/codec/` are independent of live adapter availability.
