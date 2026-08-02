# Blockers

Tracked separately from PLAN status. Items here block a planned deliverable
until resolved. Clear an entry only when verified locally (or in CI after a
human tag).

## Open

| ID | Phase | Blocker | Impact | Mitigation |
|---|---|---|---|---|
| B1 | Phase 0 / v0.5.0 | Human tag + GHCR publish of `bacnet-interop` **v0.5.0** (no commits/tags by agents unless requested) | go-bacnet cannot digest-pin `ghcr.io/otfabric/bacnet-interop-worldiety@sha256:…` for CI | Local `:local` image (`make build-worldiety`) for development |
| B2 | Phase 1+ | Worldiety upstream has no native object model / COV / event / file / list services | Adapter-shim surface must grow with each fixture generation; some services stay `unsupported` until upstream or shim exists | Extend adapter-shim only where fixture contract requires; mark evidence honestly |
| B3 | Phase 1 | `device-baseline-v3` event/COV completeness not yet on ≥2 peers with live go-bacnet assertions | GetAlarmSummary / EnrollmentSummary / COV-multiple live interop incomplete | BACnet4J now loads AI/NC/EE + AV intrinsic Out_Of_Range; BACpypes3/stack still partial; client codecs landed |
| B4 | Phase 5 | Audit / identity often `interop-single-peer` (BACnet4J) | Cannot claim multi-peer until a second executable peer exists | Document evidence state `interop-single-peer` |
| B5 | Parallel topology/bbmd | Worldiety router / BBMD fixture modes not implemented | `topology-v2` / `bbmd-v2` fixtures defined but not executable | Keep bip-router for topology-v1; bbmd-v1 via `BACNET_BBMD=1` |
| B6 | Phase 0 segmentation interop | Worldiety `3cb2aa80` omits service choice on APDU continuation segments | Segmented WPM send and segmented RPM receive vs Worldiety fail | Skip those go-bacnet scenarios; unsegmented Worldiety evidence retained |
| B7 | Phase 2–6 adapters | List / messaging / audit / life-safety adapters not fixture-complete on ≥2 peers | Client codecs/APIs + codec goldens exist; live interop incomplete | BACnet4J serves v3 objects + v4 File objects; extend Create/Delete/messaging next |
| B8 | Phase 2 files | BACnet4J returns Error `services/10` (and record CHOICE warnings) on go-bacnet `AtomicReadFile` | Live AtomicRead/WriteFile interop skipped despite File objects being created from `device-baseline-v4` | Fix request encoding / BACnet4J FileAccess interaction; keep codec goldens green |
| B9 | Phase 3 lifecycle | BACnet4J rejects DeleteObject (`object/23`) and needs creatable-type config for CreateObject | Live Create/DeleteObject interop skipped; v5 objects load | Mark AV-100 deletable / register creatable types in adapter; then unskip go-bacnet test |

## Cleared this iteration

| ID | Resolution |
|---|---|
| — | Worldiety adapter builds, smokes ready + directed Who-Is against `device-baseline-v2` locally |
| — | go-bacnet Worldiety peer scenarios (unsegmented) green against `:local` (`-tags=interop`) |
| — | Fixture generations `device-baseline-v3`…`v8`, `topology-v2`, `bbmd-v2` authored |
| — | go-bacnet typed client/codecs for Phase 1–6 services + ≥90% coverage (`make check`) |
| — | Codec goldens for alarm/enrollment/COV-multiple/file/list/messaging/audit/life-safety/VT (+ malformed) in `fixtures/codec` + corpus consumer |
| — | BACnet4J loads `device-baseline-v3` (AI/NC/EE after initialize + AV intrinsic highLimit=80) and `device-baseline-v4` File stream/record objects |
