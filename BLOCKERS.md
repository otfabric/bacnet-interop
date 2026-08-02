# Blockers

Tracked separately from PLAN status. Clear an entry only when verified in CI
after a human tag (or locally when noted). Evidence labels and
upstream-deviation / unsupported-upstream matrices live in
[EVIDENCE.md](EVIDENCE.md), not here.

## Policy

For every client family:

1. Discover native peer support at the pinned revision.
2. Configure every native implementation (fixture/object/handler wiring only).
3. Execute the same fixture against all of them.
4. Mark genuine absence as `unsupported-upstream`.
5. Record deviations without repairing, forking, or patching the peer.

Do **not** implement missing BACnet services inside a competing stack merely to
manufacture multi-peer evidence. Do **not** weaken `go-bacnet` for peer quirks.

## Open

| ID | Priority | Closure condition |
|---|---:|---|
| B5a | P2 | Inventory Worldiety native router startup/configuration surface |
| B5b | P2 | Inventory Worldiety native BBMD/BDT/FDT surface |
| B5c | P2 | Execute the subset available at the pinned Worldiety commit |
| B5d | P2 | Mark unavailable Worldiety router/BBMD ops `unsupported-upstream` |
| B5 | P2 | Native router/BBMD surfaces audited across **all** peers and every executable mode enabled (includes bacnet-stack router/BBMD audit; see [docs/NETWORK_PEER_SURFACE.md](docs/NETWORK_PEER_SURFACE.md)) |

## Cleared

| ID | Resolution |
|---|---|
| B1 | [`v0.5.0`](https://github.com/otfabric/bacnet-interop/releases/tag/v0.5.0) @ `5bff134`; go-bacnet pin includes Worldiety digests |
| B2 | Reclassified — Worldiety shim growth is an evidence constraint; see [EVIDENCE.md](EVIDENCE.md) |
| B4 | Subsumed into **B7e1–B7e4** |
| B6 | Reclassified — Worldiety segmentation `upstream-deviation`; see [EVIDENCE.md](EVIDENCE.md). Not a blocker; do not patch/fork |
| B7 | Split into **B7a–B7g** (too broad for execution) |
| B8 / B7a | [`v0.6.0`](https://github.com/otfabric/bacnet-interop/releases/tag/v0.6.0) + [`go-bacnet` v0.2.3](https://github.com/otfabric/go-bacnet/releases/tag/v0.2.3) — AtomicRead/WriteFile live-multi-peer; CI [30766339454](https://github.com/otfabric/go-bacnet/actions/runs/30766339454) |
| B9 / B7c | Same — CreateObject / DeleteObject live-multi-peer |
| B7b | Same — Add/RemoveListElement on NC Recipient_List live-multi-peer |
| B3a | Batch A — GetAlarmSummary **live-multi-peer** BACnet4J + bacnet-stack (`device-baseline-v3`); publish with `v0.7.0` |
| B3b | Batch A — GetEnrollmentSummary **live-single-peer** BACnet4J; bacnet-stack / BACpypes3 / Worldiety `unsupported-upstream` ([EVIDENCE.md](EVIDENCE.md)) |
| B3c | Batch A — SubscribeCOVPropertyMultiple: all pinned peers `unsupported-upstream`; family evidence `codec-only` |
| B3d | Batch A — COVNotificationMultiple emit: no native emitter at current pins; family evidence `codec-only` |
| B7d | Batch B — Messaging/time/private/WriteGroup **semantic** receipt via `operation` JSONL; BACnet4J + BACpypes3 + bacnet-stack native where available; Worldiety + BACnet4J WriteGroup + stack TextMessage/ConfirmedPT `unsupported-upstream` |
| B7e1 | Batch C — Who-Am-I / You-Are **live-single-peer** bacnet-stack (`device-baseline-v7`); BACnet4J / BACpypes3 / Worldiety `unsupported-upstream` |
| B7e2 | Batch C — Audit notification: no native peer emitter; family `codec-only` |
| B7e3 | Batch C — AuditLogQuery: all peers `unsupported-upstream`; family `codec-only` |
| B7e4 | Batch C — AuthRequest (34): all peers `unsupported-upstream`; family `codec-only` |
| B7f | Batch C — LifeSafetyOperation **live-multi-peer** BACnet4J + bacnet-stack (`device-baseline-v8`); BACpypes3 / Worldiety `unsupported-upstream` |
| B7g | Batch C — VT lifecycle: no native peer session; family `codec-only` |

## Notes

- Prefer `codec-only` / `live-single-peer` / `live-multi-peer` / `unsupported-upstream` / `upstream-deviation` over silent skips.
- Skipped go-bacnet interop scenarios must cite a blocker ID **or** an EVIDENCE.md deviation ID in the skip reason.
- `bip-router` is a topology aid, never counted as independent peer-native evidence.
