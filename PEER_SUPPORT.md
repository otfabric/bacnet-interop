# Peer support

Which independent BACnet stacks can execute which scenarios at the pinned
adapter versions. Assertions and pass/fail decisions live in
[`go-bacnet`](https://github.com/otfabric/go-bacnet) (`INTEROP.md`, `interop/`).

**Published images:** [v0.8.0](https://github.com/otfabric/bacnet-interop/releases/tag/v0.8.0)
@ `34f42dc` · default device fixture: `device-baseline-v2`

Upstream peer pins are unchanged from v0.7.0; this release records the native
router/BBMD audit and corrects bacnet-stack peer-as-BBMD documentation.

| Mark | Meaning |
|---|---|
| ✅ | Executed by the upstream peer implementation |
| A | Fixture adapter supplies the service/object semantics |
| — | Not available in the pinned upstream peer |
| ⚠ | Available but behavior conflicts with the BACnet interpretation used by go-bacnet |

> **Worldiety:** supplies the native BACnet/IP, NPDU and APDU runtime. The
> interop adapter supplies the fixture object model and selected
> application-service semantics.

`bip-router` is a topology aid only — never count it as peer-native evidence.

## Pinned peers

| Peer | Version / commit | Language | Primary role |
|---|---|---|---|
| bacnet-stack | 1.6.0 | C | Executable device oracle |
| BACpypes3 | 0.0.106 | Python | Semantic oracle (+ BBMD) |
| BACnet4J | 6.1.0 | Java | Semantic oracle (+ BBMD) |
| Worldiety | `3cb2aa80` | Go | Native transport/ASE; fixture object model |
| bip-router | topology-router-v1 | Go | Dual-homed BIP↔BIP topology aid |

## Application services

| Service | bacnet-stack | BACpypes3 | BACnet4J | Worldiety |
|---|:---:|:---:|:---:|:---:|
| Who-Is / I-Am | ✅ | ✅ | ✅ | ✅ |
| Who-Has / I-Have | ✅ | ✅ | ✅ | A |
| ReadProperty | ✅ | ✅ | ✅ | A |
| ReadPropertyMultiple | ✅ | ✅ | ✅ | A |
| WriteProperty | ✅ | ✅ | ✅ | A |
| WritePropertyMultiple | ✅ | A | ✅ | A |
| ReadRange (TrendLog) | ✅ | — | ✅ | A |
| COV subscribe / notify | ✅ | ✅ | ✅ | — |
| EventNotification emit | — | A | A | — |
| AtomicRead/WriteFile | ✅ | — | ✅ | — |
| CreateObject / DeleteObject | ✅ | — | ✅ | — |
| Add/RemoveListElement (NC) | ✅ | — | ✅ | — |
| GetAlarmSummary | ✅ | — | ✅ | — |
| GetEnrollmentSummary | — | — | ✅ | — |
| SubscribeCOVPropertyMultiple | — | — | — | — |
| COVNotificationMultiple emit | — | — | — | — |
| TimeSynchronization / UTC | ✅ | ✅ | ✅ | — |
| TextMessage | — | ✅ | ✅ | — |
| PrivateTransfer (unconfirmed) | ✅ | ✅ | ✅ | — |
| PrivateTransfer (confirmed) | — | ✅ | ✅ | — |
| WriteGroup | ✅ | ✅ | — | — |
| Who-Am-I / You-Are | ✅ | — | — | — |
| LifeSafetyOperation | ✅ | — | ✅ | — |
| Audit notification / AuditLogQuery | — | — | — | — |
| AuthRequest | — | — | — | — |
| VT-Open / Close / Data | — | — | — | — |
| DeviceCommunicationControl | ✅ | — | — | — |
| ReinitializeDevice warmstart | ✅ | A | A | — |

Families with all peers `—` (COV-multiple, audit, AuthRequest, VT) are exercised
as codec/unit tests in go-bacnet only.

## Transport and network

| Capability | bacnet-stack | BACpypes3 | BACnet4J | Worldiety |
|---|:---:|:---:|:---:|:---:|
| BACnet/IP UDP | ✅ | ✅ | ✅ | ✅ |
| Segmented confirmed-request receive | — | ✅ | ⚠ | ✅ |
| Segmented ComplexACK send | ⚠ | ✅ | ✅ | ✅ |
| Continuation ServiceChoice on segments | n/a | ✅ | ✅ | ⚠ |
| Routed remote via bip-router | ✅ | ✅ | ✅ | — |
| Peer-as-BBMD / FDR target | ✅ | ✅ | ✅ | — |
| Read-BDT | ✅ | ✅ | ✅ | — |
| Read-FDT (after FD registration) | ✅ | ✅ | ✅ | — |
| Delete-FDT entry | ✅ | ✅ | ✅ | — |
| Write-BDT (BVLC) | — | — | ✅ | — |
| Multi-homed BIP router / DNET forward | — | — | — | — |

Executable go-bacnet cells require deterministic adapter state: Read-FDT after
FD registration; Delete-FDT uses the address from Read-FDT (not the client's
bind address); Write-BDT only where the peer accepts replacement.
bacnet-stack and BACpypes3 Write-BDT NAK at the current pin (asserted).

### Network notes

- **bacnet-stack:** `BBMD_ENABLED` is compiled into `device_server`; BDT self-seeds
  and Accept-FD defaults on. Foreign-device registration is live
  (`TestBacnetStackForeignDeviceWhoIsReadProperty`). BVLC Write-BDT is NAK at
  Protocol_Revision ≥ 17 (pin uses 28). Upstream `apps/router` exists but is
  **not packaged** in the adapter image — routed evidence uses `bip-router`.
- **BACpypes3 / BACnet4J:** peer-as-BBMD via `BACNET_BBMD=1` (live FDR tests).
  Not multi-homed BIP routers.
- **Worldiety:** module has BBMD table helpers and `npdu/router`, but
  `ClientRuntime` / the adapter do not wire them — peer-as-BBMD and native
  router remain unavailable. `bbmd-v2` / `topology-v2` stay pending until
  upstream exposes a live server path the adapter can configure without
  inventing forwarding.

## Known peer limitations

- **Worldiety** segmented ConfirmedRequest / ComplexACK continuations omit
  ServiceChoice — required scenarios stay unsegmented.
- **BACnet4J** rejects segmented confirmed-request receive; no WriteGroup,
  COV-multiple, Who-Am-I/You-Are, audit, or VT at 6.1.0.
- **bacnet-stack** has no GetEnrollmentSummary, TextMessage, ConfirmedPrivateTransfer,
  or COV-multiple at 1.6.0; may Abort some segmented ComplexACK paths.
- **BACpypes3** has no File, CreateObject, ReadRange, GetAlarmSummary,
  GetEnrollmentSummary, or DCC at 0.0.106.
- COV-multiple subscribe/notify, audit family, AuthRequest, and VT have no
  executable peer path at current pins.
- Native multi-homed BIP router appliances are not available from any peer
  image; use `bip-router` as a topology aid only.
