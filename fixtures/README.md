# Fixtures

Corpus and provenance for BACnet interoperability and codec goldens.

`bacnet-interop` owns the bytes, semantic sidecars, and metadata. [`go-bacnet`](https://github.com/otfabric/go-bacnet) owns how those fixtures are asserted (unit tests, fuzz seeds, and `-tags=interop` scenarios).

## Layout

| Path | Role |
|---|---|
| `schema/fixture.schema.json` | Draft 2020-12 schema for per-fixture provenance metadata |
| `manifest.json` | Authoritative index of **codec** goldens (`schemaVersion` + `fixtures[]`) |
| `codec/` | Independently generated wire goldens (BVLC/NPDU/APDU/service/malformed) |
| `device/` | Live adapter device model (`device-baseline-v1.json`); not in the codec manifest |
| *(future)* `captures/` | Sanitized packet captures |

Horizon 1 Gate 3 uses `fixtures/codec/*` (via `go-bacnet/internal/fixtures`) and
`fixtures/device/device-baseline-v1.json` (via adapter containers and
`go-bacnet/interop`). Set `BACNET_INTEROP_ROOT` if the sibling checkout is not at
`../bacnet-interop`.

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

Live adapter device models live under `fixtures/device/` (e.g. `device-baseline-v1.json`)
and are baked into peer images. They are **not** codec goldens and are excluded from
the manifest orphan check. Codec goldens under `fixtures/codec/` remain the
provenance-tracked wire corpus consumed by `go-bacnet` unit tests.
