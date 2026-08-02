# bacnet-interop — Plan

Single source of truth for **bacnet-interop**-owned deliverables. Consumer
assertions and scenario matrices live in [`go-bacnet`](https://github.com/otfabric/go-bacnet)
(`INTEROP.md`, `interop/`, `PLAN.md`).

Peer set: **bacnet-stack**, **BACpypes3**, **BACnet4J**, and **Worldiety**.
Topology aid: **bip-router** (not a product router or peer oracle).

Status labels: `done` · `partial` · `open`.

**Latest published release:** [`v0.5.0`](https://github.com/otfabric/bacnet-interop/releases/tag/v0.5.0)
@ `5bff134` (Worldiety fourth peer + multi-arch digests). Consumed by
[`go-bacnet` v0.2.2](https://github.com/otfabric/go-bacnet/releases/tag/v0.2.2).

**Shift:** fixtures and client APIs for generations v3–v8 already exist.
Releases are now **evidence-driven** (live multi-peer scenarios), not one
fixture generation per tag.

## Evidence-driven release targets

| Release | Focus | Status |
|---|---|---|
| `v0.5.0` | Worldiety peer + digests | **published** @ `5bff134` |
| `v0.6.0` | Publish adapter evidence already green locally: File R/W, Create/Delete, NC Add/RemoveListElement, GetAlarmSummary (BACnet4J); close B8/B9/B7a/B7b in CI | **local green — pending tag** |
| `v0.7.0` | B3 remainder (COV-multiple) + B7d semantic diagnostics + B7e–g | open |
| `v0.8.0` | Independent network infrastructure: Worldiety router/BBMD + B6 patch (B5/B6) | open |

File / CreateObject / AtomicWriteFile ACK wire corrections land with consumer
`go-bacnet` `v0.2.3`; interop image pin bump (`v0.6.0`) publishes the adapter
surface (stack NC + list handlers, BACnet4J `object_lifecycle`, File materialization).

## Guiding rule

> No additional service breadth in adapters until existing fixture generations
> have live peer execution. Classify single-peer honestly; do not silently skip.

## Open blockers

See [BLOCKERS.md](BLOCKERS.md). Evidence labels: [EVIDENCE.md](EVIDENCE.md).
Coverage matrix: [COVERAGE.md](COVERAGE.md).

## What is already done

| Area | Status |
|---|---|
| Fixture schema + manifest + codec goldens | done |
| Device baselines v1 (frozen) … v8 authored | done |
| `topology-v2` / `bbmd-v2` fixtures authored | done (execution = B5) |
| Adapters: stack, BACpypes3, BACnet4J, Worldiety device, bip-router | done for v2 baseline |
| BACnet4J + bacnet-stack File / Create-Delete / NC list | **local live-multi-peer** (close B8/B9/B7a/B7b on next tag) |
| BACnet4J v3 GetAlarmSummary | **local live-single-peer** (B3 partial; COV-multiple open) |
| Ready/smoke contract | done |

## Adapter ownership

- Fixtures + adapters here; **all client assertions in go-bacnet**.
- Worldiety role is **server peer only** until go-bacnet has a server.
- Do not add application-service shims to Worldiety **router** mode.
