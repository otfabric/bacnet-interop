# AGENTS.md — bacnet-interop

## What this is

Independent BACnet/IP implementations (bacnet-stack, BACpypes3, legacy BACpypes, BACnet4J, System.IO.BACnet, worldiety/bacnet, cB-Sigma bacnet and bacnet-sim, ulbios/bacnet, @bacnet-js/client) and two routers in containers, with deterministic device fixtures, used as peer oracles by go-bacnet. Assertions live in go-bacnet, not here. Profile: **interoperability**.

## Organisation standards

This repository follows **otfabric/engineering policy 1.6**, profile **interoperability** (`.otfabric/policy.yaml`, mode `enforce`). Where this file and the organisation standards disagree, this file wins here — say so in your report.

## Where the truth lives

| Question | Source |
|---|---|
| Image output, fixtures, capabilities | docs/CONTAINER_CONTRACT.md |
| Pins | versions.yaml, checked by `make validate-fixtures` |
| What each peer can do | adapters/inventory.yaml, PEER_SUPPORT.md |
| Fixtures | fixtures/manifest.json, fixtures/schema/ |
| What is done and what is next | PLAN.md |
| Open blockers | BLOCKERS.md |
| Our own stack's image (not a reference) | own/go-bacnet/README.md |

## Hard rules

1. Nothing floats: upstreams by commit or exact version, base images by digest.
2. The adapters never patch an upstream stack; what a stack lacks is supplied in adapter code and marked `adapter-shim` in adapters/inventory.yaml.
3. `unsupported` is never reported as a pass.
4. `adapter_version` in adapters/inventory.yaml, `interop_version` in versions.yaml, RELEASE.md and the tag agree.
5. Licences: every redistributed component in THIRD_PARTY_NOTICES.md.
6. Nothing under adapters/, fixtures/, schemas/, scripts/ or the Makefile names a library under test (CI enforces it); own/ and its workflow are the exception, built by hand and never part of a release (own/go-bacnet/README.md).

## Commands

| When you change… | Run |
|---|---|
| anything | `make validate-fixtures` |
| an adapter | `make build-<name> smoke` |
| codec vectors | `make dissect-fixtures` (needs tshark) |
| everything | `make ci` |

## Git and releases

Branches and PRs. Do not push to `main`, push tags or publish images unless the maintainer asks in the session.
