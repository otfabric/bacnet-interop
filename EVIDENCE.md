# Evidence classification

How adapter and peer evidence is labelled. Open execution gaps that still need
adapter/fixture work live in [BLOCKERS.md](BLOCKERS.md). This file owns labels,
policy, and **non-blocker** upstream absence / deviation records.

## Labels

| Label | Meaning |
|---|---|
| `upstream-native` | Peer stack implements the behaviour; adapter only configures/binds |
| `adapter-shim` | Peer stack carries the wire; adapter supplies service/object semantics |
| `unsupported-upstream` | Pinned peer genuinely lacks the capability; do not invent it in the adapter |
| `upstream-deviation` | Peer implements a conflicting behaviour; keep required scenarios elsewhere; do not weaken go-bacnet or fork the peer |
| `topology-aid` | Not a peer oracle (e.g. `bip-router`) |
| `codec-only` | Hermetic fixture / unit evidence only |
| `live-single-peer` | Executable live scenario on one peer |
| `live-multi-peer` | Same logical scenario on ≥2 independent peers |
| `patched-upstream` | **Discouraged.** Only if an upstream project itself publishes a corrected revision we choose to pin later |

## Competing-stack policy

Three situations:

1. **Native capability exists but is not wired** — actionable adapter work
   (register handlers, load fixture objects).
2. **Native capability exists; fixture configuration missing** — actionable
   (object tables, NC config, life-safety objects, VT/audit seed state, router/BBMD
   startup flags). Adapter configures; does not reimplement the service.
3. **Pinned stack lacks or misimplements the capability** — **not** an adapter
   blocker. Record `unsupported-upstream` or `upstream-deviation` and exclude
   that peer from required scenarios.

Goal: maximum compatibility **with the stacks as they exist**.

## Upstream deviations

### B6 — Worldiety segmented APDU service choice (`upstream-deviation`)

Worldiety `3cb2aa80`: segmented ConfirmedRequest and ComplexACK continuation
segments omit ServiceChoice. This conflicts with go-bacnet, BACpypes3, and
BACnet4J behaviour.

| Rule | Action |
|---|---|
| Required Worldiety scenarios | Unsegmented only |
| Segmented confirmed send / ComplexACK reassembly | BACpypes3 and/or BACnet4J where supported |
| go-bacnet | Never weaken for this quirk |
| Fork / adapter patch | Never pin solely to make Worldiety pass |
| Skips | Keep with reason citing B6 / this section |
| Optional | Negative characterization test proving the incompatibility remains understood |

Worldiety remains a required **unsegmented** peer. Segmentation ASE quality is
orthogonal; continuation ServiceChoice is the documented deviation.

## Unsupported at current pins

| Capability | Peer | Classification | Notes |
|---|---|---|---|
| File / AtomicRead/WriteFile server | BACpypes3 0.0.106 | `unsupported-upstream` | No File server |
| File object loader | Worldiety pin | `unsupported-upstream` | Loader rejects `file` |
| CreateObject / DeleteObject server | BACpypes3 0.0.106 | `unsupported-upstream` | No `do_CreateObject` |
| CreateObject / DeleteObject server | Worldiety pin | `unsupported-upstream` | No handlers |
| GetEnrollmentSummary | bacnet-stack 1.6.0 | `unsupported-upstream` | No `h_get_enrollment_summary`; no Event Enrollment object |
| GetEnrollmentSummary | BACpypes3 0.0.106 | `unsupported-upstream` | APDU types exist; no `do_GetEnrollmentSummaryRequest` |
| GetEnrollmentSummary | Worldiety pin | `unsupported-upstream` | No service choice / EE object |
| SubscribeCOVPropertyMultiple | BACnet4J 6.1.0 | `unsupported-upstream` | `handle` → `NotImplementedException` |
| SubscribeCOVPropertyMultiple | bacnet-stack 1.6.0 | `unsupported-upstream` | Enum only; no codec/handler ([#1254](https://github.com/bacnet-stack/bacnet-stack/discussions/1254)) |
| SubscribeCOVPropertyMultiple | BACpypes3 0.0.106 | `unsupported-upstream` | `###TODO`; no APDU class / `do_` |
| SubscribeCOVPropertyMultiple | Worldiety pin | `unsupported-upstream` | Choice listed; no server encode/handler |
| COVNotificationMultiple (emit) | BACnet4J 6.1.0 | `unsupported-upstream` | Confirmed/Unconfirmed Multiple `handle` NI; mixin emits single COV only |
| COVNotificationMultiple (emit) | bacnet-stack 1.6.0 | `unsupported-upstream` | Enum only; no Multiple codec/handler |
| COVNotificationMultiple (emit) | BACpypes3 0.0.106 | `unsupported-upstream` | `###TODO`; no APDU / `do_` |
| COVNotificationMultiple (emit) | Worldiety pin | `unsupported-upstream` | Client receive decode only; no peer emit |
| Segmented confirmed-request receive | BACnet4J 6.1.0 | `upstream-deviation` / registered gap | Rejects segmented confirmed (e.g. WPM send) |
| Segmented ComplexACK | bacnet-stack 1.6.0 | registered gap | Aborts segmentation-not-supported |

### GetEnrollmentSummary peer audit (B3b)

| Peer | GetEnrollmentSummary |
|---|---|
| BACnet4J 6.1.0 | **native / executable** — `GetEnrollmentSummaryRequest.handle` + `EventEnrollmentObject`; live `TestBACnet4JGetEnrollmentSummary` |
| bacnet-stack 1.6.0 | **unsupported-upstream** — no request decoder, handler, or EE object |
| BACpypes3 0.0.106 | **unsupported-upstream** — APDU request/ACK codecs only; no application handler (adapter also skips EE) |
| Worldiety pin | **unsupported-upstream** — no enrollment surface |

### COV-multiple family (B3c / B3d)

At current pins every peer is `unsupported-upstream` for SubscribeCOVPropertyMultiple
and for emitting Confirmed/UnconfirmedCOVNotificationMultiple. Honest family
evidence is **`codec-only`** (go-bacnet fixtures + unit/client receive tests).
Worldiety’s unconfirmed-multiple **client receive** decode is not peer emission.

When no pinned peer can execute a family, honest maximum is `codec-only` — that
is not a permanent blocker.

## Worldiety fixture role

Worldiety provides strong native transport / NPDU / APDU evidence. It does
**not** ship a full fixture object model:

| Layer | Evidence |
|---|---|
| UDP / BVLC | `upstream-native` |
| NPDU / routing | Inventory under **B5a–d**; enable only native APIs |
| APDU dispatch / confirmed transactions | `upstream-native` |
| Segmentation (unsegmented paths) | `upstream-native` |
| Segmentation (continuation ServiceChoice) | `upstream-deviation` (B6 above) |
| Service payload decoding | `adapter-shim` where the fixture requires it |
| Fixture object model / state transitions | `adapter-shim` |

Growing the Worldiety adapter-shim surface for fixture objects is expected work,
not a blocker (former B2).

## BACnet4J / BACpypes3 / bacnet-stack

Prefer `upstream-native` when the peer implements the service. Document
`adapter-shim` explicitly for WPM execute, EventNotification emit assists, and
fixture-only diagnostics (`operation` JSON events).

### Published multi-peer surface (`v0.6.0` + go-bacnet `v0.2.3`)

| Scenario | Peers | Evidence |
|---|---|---|
| AtomicReadFile / AtomicWriteFile | BACnet4J, bacnet-stack | `live-multi-peer` / `upstream-native` |
| CreateObject / DeleteObject | BACnet4J, bacnet-stack | `live-multi-peer` / `upstream-native` (+ BACnet4J `object_lifecycle`) |
| Add/RemoveListElement (NC Recipient_List) | BACnet4J, bacnet-stack | `live-multi-peer` / `upstream-native` |
| GetAlarmSummary (AV Out_Of_Range) | BACnet4J | `live-single-peer` / `upstream-native` (superseded below for Batch A) |

### Batch A surface (pre-`v0.7.0`; local adapter + go-bacnet interop)

| Scenario | Peers | Evidence |
|---|---|---|
| GetAlarmSummary (AV Out_Of_Range) | BACnet4J, bacnet-stack | `live-multi-peer` / `upstream-native` |
| GetEnrollmentSummary (EE-1 / NC filter) | BACnet4J | `live-single-peer` / `upstream-native` |
| SubscribeCOVPropertyMultiple | — | `codec-only` (all peers `unsupported-upstream`) |
| COVNotificationMultiple emit | — | `codec-only` (all peers `unsupported-upstream`) |

### Batch B messaging receipt (B7d)

Peer adapters emit diagnostic JSON Lines on stdout:

```json
{"event":"operation","adapter":"…","operation":"time-synchronization","result":"accepted"}
```

go-bacnet `interop` retains these after `ready` (and tees them to an evidence
file for Docker Desktop re-exec). Assertions use `awaitOperation`.

| Capability | BACnet4J | BACpypes3 | bacnet-stack | Worldiety |
|---|---|---|---|---|
| TimeSynchronization | live | live | live | unsupported-upstream |
| UTCTimeSynchronization | live | live | live | unsupported-upstream |
| Unconfirmed/Confirmed TextMessage | live | live | unsupported-upstream | unsupported-upstream |
| Unconfirmed PrivateTransfer | live | live | live | unsupported-upstream |
| Confirmed PrivateTransfer | live | live | unsupported-upstream | unsupported-upstream |
| WriteGroup | unsupported-upstream (`NotImplementedException`) | live | live | unsupported-upstream |

Evidence label for `operation` JSONL is **adapter diagnostic** (fixture-aligned
kebab-case names), not a claim of identical cross-stack object semantics.

### Batch C identity / life-safety / audit / VT (B7e1–4 / B7f / B7g)

| Capability | BACnet4J | BACpypes3 | bacnet-stack | Worldiety | Family evidence |
|---|---|---|---|---|---|
| Who-Am-I / You-Are | unsupported-upstream (no service classes at 6.1.0) | unsupported-upstream | **live** (`TestBacnetStackWhoAmIYouAre`, v7) | unsupported-upstream | `live-single-peer` |
| Audit notification emit | unsupported-upstream | unsupported-upstream | unsupported-upstream | unsupported-upstream | `codec-only` |
| AuditLogQuery | unsupported-upstream (no Audit Log object) | unsupported-upstream | unsupported-upstream (object present in stack zoo; adapter does not seed Audit Log) | unsupported-upstream | `codec-only` |
| AuthRequest (choice 34) | unsupported-upstream | unsupported-upstream | unsupported-upstream (Authenticate 24 ≠ AuthRequest) | unsupported-upstream | `codec-only` |
| LifeSafetyOperation | **live** (LSP/LSZ from v8) | unsupported-upstream | **live** (LSP/LSZ + `handler_lso`) | unsupported-upstream | `live-multi-peer` |
| VT-Open / VT-Close / VT-Data | unsupported-upstream | codec-only / no session objects | unsupported-upstream | unsupported-upstream | `codec-only` |

Who-Am-I / You-Are wire encoding uses application tags (ASHRAE SEQUENCE without
context tags), matching bacnet-stack `whoami` / `youare` codecs.
LifeSafetyOperation `requestingSource` is a context-primitive CharacterString
(`[1]`), matching bacnet-stack `encode_context_character_string` and BACnet4J.
