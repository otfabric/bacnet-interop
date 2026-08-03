# Open work

No open adapter execution items for go-bacnet BDT/FDT/FDR cells on
bacnet-stack, BACpypes3, or BACnet4J.

Residual (not blockers — recorded in [PEER_SUPPORT.md](PEER_SUPPORT.md)):

- Package bacnet-stack upstream `apps/router` if native BIP↔BIP router evidence
  is desired (today routed tests use `bip-router`).
- Worldiety peer-as-BBMD / router remain unavailable until upstream exposes a
  live server path the adapter can configure without inventing forwarding.
- bacnet-stack Write-BDT remains NAK at Protocol_Revision ≥ 17 (asserted by
  go-bacnet; not an adapter defect).
- BACpypes3 Write-BDT returns BVLC NAK 0x0010 at the current pin (Read-BDT /
  FDT / Delete-FDT remain executable).
