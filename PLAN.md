# Plan

## Current release

[v0.9.0](https://github.com/otfabric/bacnet-interop/releases/tag/v0.9.0)
@ `180006f` publishes peer images with the BBMD/FDT documentation corrections
and Write-BDT peer limits recorded in [PEER_SUPPORT.md](PEER_SUPPORT.md)
(bacnet-stack / BACpypes3 Write-BDT NAK; BACnet4J Write-BDT live; Worldiety
BBMD/router unavailable; no packaged multi-homed native router).

## Ongoing

- Keep peer pins deliberate and reproducible.
- Add fixtures when go-bacnet adds or corrects BACnet client behaviour.
- Prefer native upstream behaviour.
- Record unsupported behaviour without reimplementing peer stacks.
- Package bacnet-stack `apps/router` only if native BIP↔BIP router evidence
  is needed beyond the `bip-router` topology aid.
