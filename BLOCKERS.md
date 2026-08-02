# Blockers

Tracked separately from PLAN status. Clear an entry only when verified locally
(or in CI after a human tag). Evidence-classification limits (adapter-shim vs
upstream-native) live in [EVIDENCE.md](EVIDENCE.md), not here.

## Open

| ID | Priority | Closure condition |
|---|---:|---|
| B8 | P0 | **Wire + live-multi-peer green locally** (BACnet4J + bacnet-stack AtomicRead/Write); close when `go-bacnet` `v0.2.3` + next image pin ship in CI |
| B9 / B7c | P0 | **Create/Delete live-multi-peer green locally**; close when next image pin + CI are green |
| B7a | P0 | Atomic file stream/record **read + write** live-multi-peer locally (closes with B8) |
| B7b | P1 | **Add/RemoveListElement live-multi-peer green locally** (NC Recipient_List); close with next image pin + CI |
| B3 | P1 | GetAlarmSummary live on BACnet4J locally; remainder = COV-multiple + second-peer summaries |
| B7d | P1 | Private/text/time/group live with **semantic** operation diagnostics (harness currently discards stdout after ready) |
| B5 | P2 | Worldiety router and BBMD modes execute `topology-v2` / `bbmd-v2` |
| B6 | P2 | Worldiety patched/upstream fixed; both segmentation directions green |
| B7e | P2 | Audit/identity live on BACnet4J; Who-Am-I/You-Are second peer; audit may remain single-peer |
| B7f | P2 | LifeSafetyOperation live against fixture life-safety objects |
| B7g | P2 | VT-Open / VT-Data / VT-Close session lifecycle live |

## Cleared

| ID | Resolution |
|---|---|
| B1 | [`v0.5.0`](https://github.com/otfabric/bacnet-interop/releases/tag/v0.5.0) @ `5bff134` published; go-bacnet pin includes Worldiety digests |
| B2 | Reclassified — not a blocker. Worldiety shim growth is an evidence constraint; see [EVIDENCE.md](EVIDENCE.md) |
| B4 | Subsumed into **B7e** (honest single-peer audit + identity second peer) |
| B7 | Split into **B7a–B7g** (was too broad for execution) |

## Local evidence (pending publish)

Verified on Docker Desktop against `:local` images (not yet a published digest):

- B8 / B7a — AtomicReadFile + AtomicWriteFile stream/record on BACnet4J + bacnet-stack
- B9 / B7c — CreateObject / DeleteObject on BACnet4J (`object_lifecycle`) + bacnet-stack handlers
- B7b — AddListElement / RemoveListElement on NC-1 Recipient_List (both peers)
- B3 partial — GetAlarmSummary after AV-1 Out_Of_Range on BACnet4J; COV-multiple still blocked upstream

## Notes

- Do **not** weaken `go-bacnet` for Worldiety segmentation (B6); patch upstream or pin a reviewed fork.
- Prefer evidence labels `codec-only` / `live-single-peer` / `live-multi-peer` over silent skips.
- Skipped go-bacnet interop scenarios must cite a blocker ID in the skip reason.
