# AGENTS.md — bacnet-interop

## What this is

Independent BACnet/IP implementations (bacnet-stack, BACpypes3, BACnet4J, System.IO.BACnet, worldiety/bacnet) and two routers in containers, with deterministic device fixtures, used as peer oracles by go-bacnet. Assertions live in go-bacnet, not here. Profile: **interoperability**.

## Organisation standards

This repository follows **otfabric/engineering policy 1.2**, profile **interoperability** (`.otfabric/policy.yaml`, mode `enforce`). Where this file and the organisation standards disagree, this file wins here — say so in your report.

## Where the truth lives

| Question | Source |
|---|---|
| Image output, fixtures, capabilities | docs/CONTAINER_CONTRACT.md |
| Pins | versions.yaml, checked by `make validate-fixtures` |
| What each peer can do | adapters/inventory.yaml, PEER_SUPPORT.md |
| Fixtures | fixtures/manifest.json, fixtures/schema/ |
| What is done and what is next | PLAN.md |
| Open blockers | BLOCKERS.md |

## Hard rules

1. Nothing floats: upstreams by commit or exact version, base images by digest.
2. The adapters never patch an upstream stack; what a stack lacks is supplied in adapter code and marked `adapter-shim` in adapters/inventory.yaml.
3. `unsupported` is never reported as a pass.
4. `adapter_version` in adapters/inventory.yaml, `interop_version` in versions.yaml, RELEASE.md and the tag agree.
5. Licences: every redistributed component in THIRD_PARTY_NOTICES.md.

## Commands

| When you change… | Run |
|---|---|
| anything | `make validate-fixtures` |
| an adapter | `make build-<name> smoke` |
| codec vectors | `make dissect-fixtures` (needs tshark) |
| everything | `make ci` |

## Git and releases

Branches and PRs. Do not push to `main`, push tags or publish images unless the maintainer asks in the session.
