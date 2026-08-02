# Network peer surface inventory

Short inventory of **native** router / BBMD capabilities at current pins.
Not a compatibility framework. Fill cells by inspecting public APIs and demo
apps at the pinned revision — never invent forwarding or BDT/FDT services in
adapters.

Legend: `native` · `configurable` · `inspect` · `unsupported-upstream` ·
`topology-aid` · `n/a`

| Capability | BACnet4J 6.1.0 | BACpypes3 0.0.106 | bacnet-stack 1.6.0 | Worldiety `3cb2aa80` |
|---|---|---|---|---|
| peer-as-BBMD | native (`BACNET_BBMD=1`) | native (`BACNET_BBMD=1`) | inspect | inspect (B5b) |
| FDR registration target | native | native | inspect | inspect |
| Read-BDT | inspect | inspect | inspect | inspect |
| Write-BDT | inspect | inspect | inspect | inspect |
| Read-FDT | inspect | inspect | inspect | inspect |
| Delete-FDT-Entry | inspect | inspect | inspect | inspect |
| Router discovery (Who-Is-Router / I-Am-Router) | inspect | inspect | native demos (router / router-ip) | inspect (B5a) |
| DNET forwarding | inspect | inspect | native router apps | inspect (B5a/B5c) |
| Multi-homed BIP router mode | inspect | inspect | inspect | inspect |

## Topology aid (not peer-native)

| Capability | bip-router |
|---|---|
| Dual-homed BIP↔BIP forward | `topology-aid` |
| Who-Is-Router / I-Am-Router | `topology-aid` |
| Counted as independent peer evidence | **no** |

## Preferred scenario matrix (targets)

| Scenario | Preferred native peers |
|---|---|
| Routed BACnet/IP endpoint | bacnet-stack; Worldiety if natively configurable |
| Router discovery | bacnet-stack + Worldiety where available |
| DNET forwarding | bacnet-stack + Worldiety where available |
| BBMD / FDR | BACpypes3 + BACnet4J + Worldiety/bacnet-stack where available |
| BDT/FDT management | whichever pinned stacks natively expose it |
| Deterministic dual-net aid | `bip-router` (retained; not peer-native) |

## Adapter work rule

**Allowed:** set network numbers, bind interfaces, populate BDT/FDT config,
start native router/BBMD modes, map fixture addresses into native config.

**Not allowed:** implement missing router forwarding or BDT/FDT services inside
a peer adapter; patch/fork a peer; count `bip-router` as peer-native evidence.

Tracked under blockers **B5** / **B5a–d**. Update this table as audits complete.
