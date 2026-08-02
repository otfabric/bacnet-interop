# Fixtures

Corpus and provenance for BACnet interoperability and codec goldens.

`bacnet-interop` owns the bytes, semantic sidecars, and metadata.
[`go-bacnet`](https://github.com/otfabric/go-bacnet) owns how those fixtures are
asserted (unit tests, fuzz seeds, and `-tags=interop` scenarios).

## Layout

| Path | Role |
|---|---|
| `schema/fixture.schema.json` | Draft 2020-12 schema for per-fixture provenance metadata |
| `manifest.json` | Authoritative index of **codec** goldens |
| `codec/` | Independently generated wire goldens |
| `device/` | Live adapter device models (`device-baseline-v1`…`v8`) |
| `topology/` | Router/topology fixtures |
| `bbmd/` | BBMD management fixtures |

## Device fixture generations

| Fixture | Adds | Executable notes (see [PEER_SUPPORT.md](../PEER_SUPPORT.md)) |
|---|---|---|
| v1 | Basic Device, AV and BV | Frozen historical |
| v2 | Trend Log | Default baseline; all four peers |
| v3 | Notification Class, Event Enrollment, alarms | GetAlarmSummary multi-peer; GetEnrollmentSummary BACnet4J; COV-multiple codec-only |
| v4 | File objects | AtomicRead/Write multi-peer (BACnet4J + bacnet-stack) |
| v5 | Object lifecycle and list mutation | Create/Delete multi-peer (BACnet4J + bacnet-stack) |
| v6 | Messaging and synchronization | Semantic receipt via `operation` JSONL |
| v7 | Identity | Who-Am-I/You-Are live on bacnet-stack; audit/AuthRequest codec-only |
| v8 | Life safety | LifeSafetyOperation multi-peer (BACnet4J + bacnet-stack); VT codec-only |

Current peer images and go-bacnet interop default to
`fixtures/device/device-baseline-v2.json`. Set `BACNET_INTEROP_ROOT` if the
sibling checkout is not at `../bacnet-interop`.

## Provenance requirements

Every fixture metadata document **must** include:

1. **`id`** — stable kebab-case identifier, unique in the manifest.
2. **`source`** — `implementation`, `version`, and `image_digest` (`sha256:…` or `none`).
3. **`capture`** — `direction`, `transport`, and sanitized `original_endpoint`.
4. **`standard.base`** — normative baseline (default: `ANSI/ASHRAE 135-2024`).
5. **`expect`** — booleans for `semantic_decode_equal`, `deterministic_reencode_equal`, `original_bytes_equal`.
6. **`license.status`** — one of `independently-generated`, `capture`, `malformed-constructed`, `standards-boundary`, `vendor-restricted`.

At least one of `input_hex` or `semantic_file` is required.

## Licensing and hygiene

- Prefer **independently-generated** vectors. Do not copy GPL peer source into fixtures.
- **Captures** must be sanitized.
- **`vendor-restricted`** material must not be committed publicly.
- Never commit secrets, private keys, or live operational dumps.

## Manifest contract

`make validate-fixtures` enforces `fixtures/manifest.json` against the schema.
Codec fixtures under `fixtures/codec/` are indexed there; device/topology/bbmd
trees are outside the codec manifest.
