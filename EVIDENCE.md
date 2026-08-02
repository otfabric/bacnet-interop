# Evidence classification

How adapter and peer evidence is labelled. This is **not** a blocker list —
see [BLOCKERS.md](BLOCKERS.md) for open execution gaps.

## Labels

| Label | Meaning |
|---|---|
| `upstream-native` | Peer stack implements the behaviour; adapter only configures/binds |
| `adapter-shim` | Peer stack carries the wire; adapter supplies service/object semantics |
| `patched-upstream` | Behaviour requires a reviewed pin/fork/patch (cite commit) |
| `topology-aid` | Not a peer oracle (e.g. `bip-router`) |
| `codec-only` | Hermetic fixture / unit evidence only |
| `live-single-peer` | Executable live scenario on one peer |
| `live-multi-peer` | Same logical scenario on ≥2 independent peers |

## Worldiety (constraint, not blocker)

Worldiety provides strong native transport / NPDU / APDU / segmentation
evidence. It does **not** ship a full fixture object model. Under the
fixture-driven strategy:

| Layer | Evidence |
|---|---|
| UDP / BVLC | `upstream-native` |
| NPDU / routing | `upstream-native` (router mode when B5 closes) |
| APDU dispatch / confirmed transactions | `upstream-native` |
| Segmentation | `upstream-native` after B6; until then unsegmented only |
| Service payload decoding | `adapter-owned` where the fixture requires it |
| Fixture object model / state transitions | `adapter-owned` |

Only open a blocker when a missing upstream API genuinely prevents executing a
required fixture. Growing the Worldiety adapter-shim surface is expected work,
not B2.

## BACnet4J / BACpypes3 / bacnet-stack

Prefer `upstream-native` when the peer implements the service. Document
`adapter-shim` explicitly for WPM execute, EventNotification emit assists, and
any fixture-only diagnostics (`operation` JSON events).

### Local multi-peer surface (pending `v0.6.0` image pin)

| Scenario | Peers | Evidence |
|---|---|---|
| AtomicReadFile / AtomicWriteFile | BACnet4J, bacnet-stack | `live-multi-peer` / `upstream-native` |
| CreateObject / DeleteObject | BACnet4J, bacnet-stack | `live-multi-peer` / `upstream-native` (+ BACnet4J `object_lifecycle` config) |
| Add/RemoveListElement (NC Recipient_List) | BACnet4J, bacnet-stack | `live-multi-peer` / `upstream-native` |
| GetAlarmSummary (AV Out_Of_Range) | BACnet4J | `live-single-peer` / `upstream-native` |
| File / Create-Delete | BACpypes3, Worldiety | `unsupported` at current pins |
