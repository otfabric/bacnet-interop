# Container contract

Contract version **1.0** (`contract_version` in [versions.yaml](../versions.yaml)). It records what every image does today. Assertions about a library live in the consumer (go-bacnet `interop/`), not here.

## Images

`ghcr.io/otfabric/bacnet-interop-<name>`, one per entry of [adapters/inventory.yaml](../adapters/inventory.yaml), listening on UDP 47808 (`EXPOSE 47808/udp`). A container runs one device or router; it has no client command. Environment variables per image are in `adapters/<name>/README.md`.

## Output

Every image writes JSON Lines to stdout. The first line is the ready event, written once the BACnet/IP socket is bound:

```json
{"event":"ready","adapter":"bacnet-stack","version":"0.10.0","fixture":"device-baseline-v2","address":"0.0.0.0:47808","peer_version":"bacnet-stack-1.6.1"}
```

`version` is the adapter release (a commit for a local build), `peer_version` the upstream stack. The two routers add `networks` and `addresses`. Some adapters then write `{"event":"operation","adapter":…,"operation":…,"result":…}` lines for requests that have no observable reply. Diagnostics go to stderr.

## Fixtures

Fixtures are listed in [fixtures/manifest.json](../fixtures/manifest.json) and validated against [fixtures/schema/fixture.schema.json](../fixtures/schema/fixture.schema.json) by `make validate-fixtures`.

## Capabilities

[adapters/inventory.yaml](../adapters/inventory.yaml) states per peer and capability: `native`, `adapter-shim`, `unsupported` or `topology-aid`. [PEER_SUPPORT.md](../PEER_SUPPORT.md) has the observed behaviour.

## Exit codes

Not specified. The organisation exit codes (`otfabric/engineering` `standards/interoperability.md`) apply when this contract gets its next minor version.

## Pinning

A consumer pins images by digest from the release's `manifest.json` (go-bacnet: `interop/bacnet-interop-pin.json`).
