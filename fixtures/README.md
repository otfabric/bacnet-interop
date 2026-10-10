# Fixtures

Corpus and provenance for BACnet interoperability and codec goldens.

`bacnet-interop` owns the bytes, semantic sidecars, and metadata.
[`go-bacnet`](https://github.com/otfabric/go-bacnet) owns how those fixtures are
asserted (unit tests, fuzz seeds, and `-tags=interop` scenarios).

## Layout

| Path | Role |
|---|---|
| `schema/fixture.schema.json` | Draft 2020-12 schema for per-fixture provenance metadata |
| `schema/manifest.schema.json` | Schema of `manifest.json` |
| `schema/device.schema.json` | Schema of the device models under `device/` |
| `manifest.json` | Authoritative index of **codec** goldens |
| `codec/` | Wire vectors for codec tests (mostly hand-written; see "Independence of codec vectors") |
| `device/` | Live adapter device models (`device-baseline-v1`…`v9`) |
| `topology/` | Router/topology fixtures |
| `bbmd/` | BBMD management fixtures |

## Device fixture generations

| Fixture | Adds | Executable notes (see [PEER_SUPPORT.md](../PEER_SUPPORT.md)) |
|---|---|---|
| v1 | Basic Device, AV and BV | Frozen historical |
| v2 | Trend Log | Default baseline; every device peer loads it (BACpypes3 skips the Trend Log object). ReadRange by position, by sequence number and by time on bacnet-stack, BACnet4J, Worldiety and System.IO.BACnet (the last two through adapter code) |
| v3 | Notification Class, Event Enrollment, alarms | GetAlarmSummary, GetEventInformation and AcknowledgeAlarm multi-peer (BACnet4J + bacnet-stack; System.IO.BACnet serves the latter two from an adapter-supplied alarm model); GetEnrollmentSummary on BACnet4J (BACpypes3 answers it from an adapter handler on any fixture) |
| v4 | File objects | AtomicRead/Write, stream and record access, multi-peer (BACnet4J, bacnet-stack, System.IO.BACnet) |
| v5 | Object lifecycle and list mutation | Create/Delete multi-peer (BACnet4J + bacnet-stack) |
| v6 | Messaging and synchronization | Semantic receipt via `operation` JSONL |
| v7 | Identity | Who-Am-I/You-Are decoded by bacnet-stack; the `audit-log` object is served by no peer (audit/AuthRequest codec-only) |
| v8 | Life safety | LifeSafetyOperation multi-peer (BACnet4J + bacnet-stack); VT codec-only |
| v9 | Large object model: the v2 objects plus 20 analog-value (`AV-LARGE-101..120`, present-value = instance/2) and 20 binary-value (`BV-LARGE-101..120`, active for even instances) | bacnet-stack image only, since 0.10.0. Its Object_List (47 entries on bacnet-stack) does not fit a 50-octet APDU and bacnet-stack cannot segment: evidence for reading a list element by element and for shrinking ReadPropertyMultiple batches |

Every device image ships v1–v8 under `/fixtures/device/` and serves v2 unless
`DEVICE_FIXTURE_FILE` and `FIXTURE` select another; a peer skips the object
types it has no implementation for. go-bacnet's interop tests read the same
files from this checkout (`BACNET_INTEROP_ROOT`, default `../bacnet-interop`)
to know what to expect.

The Trend Log content is not in the fixture: each peer seeds its own
(bacnet-stack 1000 records, BACnet4J and Worldiety the same 36, System.IO.BACnet
4); see the adapter READMEs.

## Provenance requirements

Every fixture metadata document **must** include:

1. **`id`** — stable kebab-case identifier, unique in the manifest.
2. **`source`** — `implementation`, `version`, and `image_digest` (`sha256:…` or `none`).
3. **`capture`** — `direction`, `transport`, and sanitized `original_endpoint`.
4. **`standard.base`** — normative baseline (default: `ANSI/ASHRAE 135-2024`).
5. **`expect`** — booleans for `semantic_decode_equal`, `deterministic_reencode_equal`, `original_bytes_equal`.
6. **`license.status`** — one of `independently-generated`, `capture`, `malformed-constructed`, `standards-boundary`, `vendor-restricted`.

At least one of `input_hex` or `semantic_file` is required.

## Independence of codec vectors

A vector with `source.implementation: otfabric-handwritten` was written from
the same reading of the standard as the code it tests. It catches regressions;
it is not evidence that the layout is right. Five vectors published up to
v0.9.0 were wrong in exactly that way (SubscribeCOVPropertyMultiple, the three
`Error` vectors and the GetEventInformation ACK) and passed every test.

`make dissect-fixtures` gives each vector a second opinion: it wraps the
vector into a BACnet/IP datagram and has Wireshark's `tshark` dissect it. A
vector fails when Wireshark calls it malformed, or when a label listed for it
in `scripts/dissect-fixtures.py` (`EXPECT`) is not decoded. The labels matter:
Wireshark walks BACnet tags leniently and accepts many wrong layouts without
complaint, but it only assigns a field label when the tag sits where the
standard puts it.

Rules for a new or changed codec vector:

1. Prefer bytes captured from a peer stack (`license.status: capture`) over
   hand-written ones.
2. For a service no pinned peer serves, add `EXPECT` labels for the fields
   whose position defines the layout, and look at the decoded tree
   (`scripts/dissect-fixtures.py --only <id> -v`) before committing.
3. A vector Wireshark only names but does not decode goes into `WEAK` with
   the reason; one it rejects for a reason that is by design goes into
   `KNOWN`. Both lists are printed on every run.

The check runs in CI (`validate-fixtures.yml`) with the tshark of the runner
image; labels are limited to ones that Wireshark 4.2, 4.4 and 4.6 print alike.

## Licensing and hygiene

- Prefer **independently-generated** vectors. Do not copy GPL peer source into fixtures.
- **Captures** must be sanitized.
- **`vendor-restricted`** material must not be committed publicly.
- Never commit secrets, private keys, or live operational dumps.

## Manifest contract

`make validate-fixtures` enforces `fixtures/manifest.json` against the schema.
Codec fixtures under `fixtures/codec/` are indexed there; device/topology/bbmd
trees are outside the codec manifest.
