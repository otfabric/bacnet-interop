# Adapter Capability Coverage

Availability of adapter behaviours for Horizon 1 peers (including the current
supervisory / H2 peer surface). Compatibility claims and scenario assertions
live in [`go-bacnet`](https://github.com/otfabric/go-bacnet) (`interop/`,
`INTEROP.md`).

Update a cell to ✓ only when a command or mode is built, smoke-tested, and
listed in the adapter README. Document upstream gaps in the limitations table —
never skip silently in consumer CI without a registered row.

Adapter version: `v0.5.0` (pending tag) · Fixture revision: `device-baseline-v2`

**Evidence types:** ✓ cells may be **upstream-native** (peer stack handles the
service) or **adapter-shim** (adapter code fills a gap so `go-bacnet` can
exercise the client path). See notes and [`adapters/inventory.yaml`](adapters/inventory.yaml).
Do not treat adapter-shim evidence as proof of upstream peer support.

| Capability | bacnet-stack | BACpypes3 | BACnet4J | Worldiety | Notes |
|---|:---:|:---:|:---:|:---:|---|
| Who-Is / I-Am (server answers) | ✓ | ✓ | ✓ | ✓ | Directed Who-Is in-network; discovery client may bind `:47808` for broadcast I-Am |
| Who-Has / I-Have | ✓ | ✓ | ✓ | ✓ | Object-identifier and object-name forms; Worldiety payload **adapter-shim** |
| Who-Is probe (client sequence) | planned | planned | planned | planned | Fixed-sequence JSON Lines client adapter not packaged yet |
| ReadProperty (RP) | ✓ | ✓ | ✓ | ✓ | Device object-name + AV-1 present-value; Worldiety payload **adapter-shim** |
| ReadProperty unknown-property Error | ✓ | ✓ | ✓ | ✓ | `*bacnet.ErrorResponse` class=property code=unknown-property |
| Reject unrecognized service | ✓ | — | ✓ | — | BACpypes3 raises instead of Reject (see limitations) |
| Abort (segmentation path) | ✓ | ✓ | — | — | bacnet-stack/BACpypes3 Abort paths asserted; BACnet4J segments instead |
| ReadPropertyMultiple (RPM) | ✓ | ✓ | ✓ | ✓ | Success + property-level partial Error; Worldiety payload **adapter-shim** |
| WriteProperty (WP) | ✓ | ✓ | ✓ | ✓ | AV present-value write + readback + restore |
| WritePropertyMultiple (WPM) | ✓ | ✓ | ✓ | ✓ | BACpypes3 / Worldiety **adapter-shim**; bacnet-stack / BACnet4J upstream-native for service body |
| ReadRange byPosition (TrendLog) | ✓ | — | ✓ | ✓ | Fixture TL-0; BACpypes3 has no server ReadRange (`NotImplementedError`) |
| COV subscribe / notify / cancel | ✓ | ✓ | ✓ | — | Unconfirmed COV; BACpypes3 also renew |
| COV renew | — | ✓ | — | — | BACpypes3 only so far |
| EventNotification emit | — | ✓ | ✓ | — | `BACNET_EMIT_EVENT=1`; emit once after first ReadProperty (**adapter-shim**) |
| DeviceCommunicationControl enable | ✓ | — | — | — | bacnet-stack only (empty password) |
| ReinitializeDevice warmstart | ✓ | ✓ | ✓ | — | SimpleACK / no process restart on peers |
| Segmented confirmed-request receive | — | ✓ | — | ✓ | Worldiety / BACpypes3 native ASE; BACnet4J rejects segmented confirmed receive |
| Segmented ComplexACK send | — | ✓ | ✓ | ✓ | Worldiety native ASE |
| Routed remote device | ✓ | ✓ | ✓ | — | Via `bip-router` dual-net topology; Who-Is-Router→ResolveTarget asserted on BACpypes3 |
| Foreign-device / BBMD (peer as BBMD) | — | ✓ | ✓ | — | `BACNET_BBMD=1`; client Register-Foreign-Device + DBTN Who-Is + RP |
| Forwarded-NPDU receive (client) | — | ✓ | ✓ | — | Exercised when BBMD forwards to a registered FD |
| Segmentation / small max-APDU | — | ✓ | ✓ | ✓ | `BACNET_MAX_APDU` on BACpypes3/4J; Worldiety advertises segmented-both |
| Readiness JSON Lines (`event=ready`) | ✓ | ✓ | ✓ | ✓ | After UDP bind / application construct |
| `--capabilities` / `--version` | planned | planned | planned | planned | Optional until M1-style contract |

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
| `ghcr.io/otfabric/bacnet-interop-worldiety` | [worldiety/bacnet](https://github.com/worldiety/bacnet) | `3cb2aa80efbb…` |
| `ghcr.io/otfabric/bacnet-interop-bip-router` | interop BIP↔BIP router | topology fixture (not a product router) |

**Known limitations (verified upstream gaps):**

| Stack | Version | Direction | Capability | Reason | Consumer skip |
|---|---|---|---|---|---|
| all peers | — | transport | Host UDP to container on Docker Desktop | Bridge IPs are not host-routable; published-port return paths are unreliable for BACnet | `go-bacnet/interop` re-executes tests inside the peer docker network on macOS/Windows; routed tests always re-exec on the client net |
| BACpypes3 | 0.0.106 | bind | `0.0.0.0/0` address | Confirmed-service replies fail; use `host:<port>` (adapter default) or numeric CIDR when `BACNET_BBMD=1` | — |
| BACpypes3 | 0.0.106 | Reject | Unrecognized confirmed service | Application raises `RuntimeError` instead of emitting a Reject PDU | No BACpypes3 Reject assertion; covered by bacnet-stack + BACnet4J |
| BACpypes3 | 0.0.106 | ReadRange | Server ReadRange | Upstream `NotImplementedError`; TrendLog objects skipped in adapter | No BACpypes3 ReadRange assertion; covered by bacnet-stack + BACnet4J |
| BACnet4J | 6.1.0 | segmentation | Segmented confirmed-request receive | Rejects segmented confirmed requests (e.g. WPM send path) | Segmented WPM send asserted on BACpypes3 only |
| bacnet-stack | 1.6.0 | segmentation | Segmented ComplexACK | Stack TSM aborts with segmentation-not-supported rather than segmenting | Assert Abort; segmented reassembly covered by BACpypes3 + BACnet4J |
| bip-router | — | discovery | Remote I-Am observation | Docker broadcast delivery to ephemeral clients is unreliable; RP via DNET/DADR is the hard assertion | Routed Who-Is I-Am is best-effort in `go-bacnet/INTEROP.md` |

**Notes:**

- Device model documentation: `fixtures/device/device-baseline-v2.json` (includes TrendLog TL-0). `device-baseline-v1` is frozen for historical digests.
- Fixture generations `v3`–`v8`, `topology-v2`, and `bbmd-v2` are authored under `fixtures/`; peer alignment for those generations is partial/pending (see [BLOCKERS.md](BLOCKERS.md) B3–B7).
- Peer adapters construct device + AV-1 + BV-1 from v2 JSON; bacnet-stack and BACnet4J also serve TrendLog. BACpypes3 skips TrendLog (no server ReadRange).
- BACpypes3/BACnet4J/Worldiety may skip or shim v3+ object types (AI/NC/EE/file/audit/life-safety) until native support exists.
- Optional `BACNET_MAX_APDU` on BACpypes3 and BACnet4J overrides `maxApduLengthAccepted`.
- Optional `BACNET_BBMD=1` on BACpypes3 and BACnet4J enables peer-as-BBMD (bbmd-v1).
- Optional `BACNET_EMIT_EVENT=1` on BACpypes3 and BACnet4J emits one UnconfirmedEventNotification after the first ReadProperty (**adapter-shim**).
- Optional `BACNET_NETWORK` sets the local BACnet network number (BACpypes3 / BACnet4J).
- `bip-router` is dual-homed (`eth0`/`eth1`); `BACNET_NETWORKS=1,2` sets BACnet nets (`topology-router-v1`).
- Stdout is JSON Lines; diagnostics go to stderr.
- A skipped `go-bacnet` interop test without a registered limitation must fail CI.
- Codec goldens under `fixtures/codec/` are independent of live adapter availability.
