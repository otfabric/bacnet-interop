# Fixtures

Corpus and provenance for BACnet interoperability and codec goldens.

`bacnet-interop` owns the bytes, semantic sidecars, and metadata. [`go-bacnet`](https://github.com/otfabric/go-bacnet) owns how those fixtures are asserted (unit tests, fuzz seeds, and `-tags=interop` scenarios).

## Layout

| Path | Role |
|---|---|
| `schema/fixture.schema.json` | Draft 2020-12 schema for per-fixture provenance metadata |
| `manifest.json` | Authoritative index of **codec** goldens (`schemaVersion` + `fixtures[]`) |
| `codec/` | Independently generated wire goldens (BVLC/NPDU/APDU/service/malformed) |
| `device/` | Live adapter device models (`device-baseline-v1`…`v8`); not in the codec manifest |
| `topology/` | Router/topology fixtures (`topology-v2.json`; v1 remains bip-router env) |
| `bbmd/` | BBMD management fixtures (`bbmd-v2.json`; v1 remains `BACNET_BBMD=1` env) |
| *(future)* `captures/` | Sanitized packet captures |

### Device fixture generations

| Fixture | Goal | Peer status |
|---|---|---|
| `device-baseline-v1` | Frozen historical | published digests |
| `device-baseline-v2` | Current Worldiety / v0.5.0 baseline (AV/BV/TL) | Worldiety + BACnet4J + BACpypes3 + stack |
| `device-baseline-v3` | Alarms/COV (AI/NC/EE + AV trigger) | BACnet4J partial-local; ≥2 peers B3 |
| `device-baseline-v4` | File stream/record | BACnet4J objects ready; AtomicRead wire B8 |
| `device-baseline-v5` | List + Create/DeleteObject | objects load; Create/Delete config B9 |
| `device-baseline-v6` | Private/text/time/group sinks | BACnet4J TimeSync/Text interop + diagnostic events |
| `device-baseline-v7` | Audit + identity | single-peer expected (B4) |
| `device-baseline-v8` | Life safety + VT | adapter-pending (B7) |

Current peer images and `go-bacnet/interop` default to
`fixtures/device/device-baseline-v2.json`. Codec goldens under `fixtures/codec/`
are loaded via `go-bacnet/internal/fixtures`. Set `BACNET_INTEROP_ROOT` if the
sibling checkout is not at `../bacnet-interop`.

## Provenance requirements

Every fixture metadata document **must** include:

1. **`id`** — stable kebab-case identifier, unique in the manifest.
2. **`source`** — `implementation`, `version`, and `image_digest` (`sha256:…` or `none`).
3. **`capture`** — `direction`, `transport`, and sanitized `original_endpoint` (no customer/site hostnames).
4. **`standard.base`** — normative baseline (Horizon 1 default: `ANSI/ASHRAE 135-2024`).
5. **`expect`** — booleans for `semantic_decode_equal`, `deterministic_reencode_equal`, `original_bytes_equal`.
6. **`license.status`** — one of:
   - `independently-generated`
   - `capture`
   - `malformed-constructed`
   - `standards-boundary`
   - `vendor-restricted`

At least one of `input_hex` or `semantic_file` is required. Prefer both when asserting decode + encode behaviour.

## Licensing and hygiene

- Prefer **independently-generated** vectors. Regenerate from peers when needed; do not copy GPL peer source into fixtures.
- **Captures** must be sanitized: strip identifying endpoints, credentials, and unrelated traffic.
- **`vendor-restricted`** material must not be committed to the public repository.
- **`malformed-constructed`** fixtures are first-class: negative decoder tests need explicit license status and honest `expect` flags (usually all equality flags false except possibly semantic error classification in the sidecar).
- Never commit secrets, private keys, or live operational dumps.

## Manifest contract

`fixtures/manifest.json`:

```json
{
  "schemaVersion": "1.0.0",
  "fixtures": [
    {
      "id": "example-id",
      "path": "fixtures/codec/example-id.json"
    }
  ]
}
```

Rules enforced by `make validate-fixtures`:

- Manifest and schema parse as JSON.
- Manifest has `schemaVersion` and a `fixtures` array.
- Each entry with a `path` points at an existing file (when the array is non-empty).

When adding a fixture: write metadata (+ optional hex/sidecar), append a manifest entry, run `make validate-fixtures`.

## Equality flags

| Flag | When true |
|---|---|
| `semantic_decode_equal` | Decode must match the semantic sidecar / declared structure |
| `deterministic_reencode_equal` | Canonical re-encode of the decoded value must be stable |
| `original_bytes_equal` | Round-trip must match `input_hex` exactly |

Do not set `original_bytes_equal` for captures with non-canonical or peer-specific encodings unless the test is specifically about byte identity.

## Relationship to adapters

Live adapter device models live under `fixtures/device/`
(`device-baseline-v2.json` current; `device-baseline-v1.json` frozen) and are
baked into peer images. They are **not** codec goldens and are excluded from
the manifest orphan check. Codec goldens under `fixtures/codec/` remain the
provenance-tracked wire corpus consumed by `go-bacnet` unit tests.
