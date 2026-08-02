# Plan

## Current release

[v0.8.0](https://github.com/otfabric/bacnet-interop/releases/tag/v0.8.0)
records the native router/BBMD audit against unchanged upstream peer pins
(bacnet-stack / BACpypes3 / BACnet4J peer-as-BBMD; Worldiety BBMD/router
unavailable; no packaged multi-homed native router). See
[PEER_SUPPORT.md](PEER_SUPPORT.md).

## Ongoing

- Keep peer pins deliberate and reproducible.
- Add fixtures when go-bacnet adds or corrects BACnet client behaviour.
- Prefer native upstream behaviour.
- Record unsupported behaviour without reimplementing peer stacks.
- Package bacnet-stack `apps/router` only if native BIP↔BIP router evidence
  is needed beyond the `bip-router` topology aid.
