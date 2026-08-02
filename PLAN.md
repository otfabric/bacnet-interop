# bacnet-interop — Plan

Single source of truth for **bacnet-interop**-owned deliverables. Consumer
assertions and scenario matrices live in [`go-bacnet`](https://github.com/otfabric/go-bacnet)
(`INTEROP.md`, `interop/`, `PLAN.md`).

Peer set: **bacnet-stack**, **BACpypes3**, **BACnet4J**, and **Worldiety**.
Topology aid: **bip-router** (not a product router or peer oracle).

Status labels: `done` · `partial` · `open`.

**Latest published release:** [`v0.6.0`](https://github.com/otfabric/bacnet-interop/releases/tag/v0.6.0)
@ `f4ea3de` (File / Create-Delete / NC list adapters + digests). Consumed by
[`go-bacnet` v0.2.3](https://github.com/otfabric/go-bacnet/releases/tag/v0.2.3).

## Competing-stack policy

> For every client family, activate every pinned peer that already has native
> support. Mark genuine upstream absence or deviation as `unsupported-upstream`
> / `upstream-deviation`. Do **not** implement or patch missing functionality
> inside a competing stack merely to manufacture evidence.

Details: [EVIDENCE.md](EVIDENCE.md). Open work: [BLOCKERS.md](BLOCKERS.md).
Network inventory: [docs/NETWORK_PEER_SURFACE.md](docs/NETWORK_PEER_SURFACE.md).

## Evidence-driven release targets

| Release | Focus | Status |
|---|---|---|
| `v0.5.0` | Worldiety peer + digests | **published** @ `5bff134` |
| `v0.6.0` | File R/W, Create/Delete, NC list; closes B8/B9/B7a/B7b | **published** @ `f4ea3de` |
| `v0.7.0` | B3a–d event/COV audits + B7d semantic messaging harness; enable all newly found native handlers; explicit unsupported matrix | Batches A+B done locally; tag when digests published |
| `v0.8.0` | Native router/BBMD maximization (B5 / B5a–d); expand topology-v2 / bbmd-v2 only on native paths | open |

Consumer follow-up after `v0.7.0` digests: **`go-bacnet` v0.2.4** only if needed
for pin bump, expanded live tests, harness changes, or correctness fixes found
by those tests. **No new BACnet client APIs.**

## Suggested execution batches

| Batch | Focus |
|---|---|
| A | **done** — B3a live-multi-peer; B3b BACnet4J live + others unsupported; B3c/d all peers unsupported → family `codec-only` |
| B | **done** — operation JSONL harness + messaging receipt on BACnet4J / BACpypes3 / bacnet-stack (B7d) |
| C | **done** — B7f live-multi-peer; B7e1 bacnet-stack live; B7e2–e4 / B7g codec-only / unsupported |
| D | B5 network inventory → bacnet-stack router; Worldiety/BBMD only for native APIs |

## What is already done

| Area | Status |
|---|---|
| Fixture schema + manifest + codec goldens | done |
| Device baselines v1 (frozen) … v8 authored | done |
| `topology-v2` / `bbmd-v2` fixtures authored | done (execution = B5) |
| Adapters: stack, BACpypes3, BACnet4J, Worldiety device, bip-router | done for v2 baseline |
| BACnet4J + bacnet-stack File / Create-Delete / NC list | **done** live-multi-peer |
| BACnet4J + bacnet-stack GetAlarmSummary | **done** live-multi-peer |
| BACnet4J GetEnrollmentSummary | **done** live-single-peer (other peers unsupported-upstream) |
| COV-multiple (Subscribe + NotificationMultiple) | **done** audit — all peers unsupported-upstream; family codec-only |
| Messaging semantic receipt (v6) | **done** live-multi-peer where native; see EVIDENCE B7d matrix |
| Who-Am-I / You-Are (v7) | **done** bacnet-stack live-single-peer; others unsupported-upstream |
| LifeSafetyOperation (v8) | **done** live-multi-peer BACnet4J + bacnet-stack |
| Audit / AuthRequest / VT (v7/v8) | **done** audit — codec-only / unsupported-upstream at current pins |
| Ready/smoke contract | done |

## Adapter ownership

- Fixtures + adapters here; **all client assertions in go-bacnet**.
- Worldiety role is **server peer only** until go-bacnet has a server.
- Do not add application-service shims to Worldiety **router** mode.
- Do not count `bip-router` as peer-native evidence.
