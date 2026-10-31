# bacnet-interop Releases

## How a release is made

1. Write the notes of the version below, and set `adapter_version` in
   `adapters/inventory.yaml` and the version in the documents to it, in the
   same change. `make validate-fixtures` (and CI) fails when RELEASE.md has no
   notes for `adapter_version`.
2. Push `main`. Then tag **that commit** `vX.Y.Z` and push the tag. Do not
   amend or rebase `main` afterwards: v0.8.0 and v0.9.0 were tagged on commits
   that were later rewritten, so their tags are not on `main`.
3. The release workflow refuses a tag that is not on `main`, whose version
   differs from `adapters/inventory.yaml` or that has no notes here. It then
   validates the fixtures, builds every adapter natively on an amd64 and an
   arm64 runner, pushes them by digest to GHCR, joins them into the
   multi-arch `<image>:X.Y.Z` (and `X.Y`, `X`) tags, and creates the GitHub
   release with `manifest.json` (fixture schema, upstream pins and digests)
   and `checksums.txt`.
4. Update the pin in the consuming repository from that manifest.

The notes are the body of the GitHub release, followed by the image digests
and the pin snippet: everything after the heading `## vX.Y.Z` up to the next
line that is exactly `---` (`scripts/release-notes.sh vX.Y.Z` prints it).
This is the format of every otfabric repository and the rule of the shared
release workflow, so: one section per version, newest first, each ending with
a `---` line, and no `---` line inside a section.

Tags are immutable. A fix is a new version.

---

## v0.11.0

**Date:** 2026-10-31
**Previous release:** v0.10.0

### Added

- Adds `results.json` in the interop-result-v1 format.
- Policy 1.2: build output in `bin/` and `release/`, and shared CI at v3.3.0.

---

## v0.10.0

**Date:** 2026-10-10

## Summary

A fifth peer (System.IO.BACnet), a native bacnet-stack router, the large
device model, DeviceCommunicationControl on BACpypes3 and BACnet4J, corrected
codec vectors and a Wireshark check for them. Every upstream pin is at the
newest stable release.

## Changes

- **New peer `sysiobacnet`:** System.IO.BACnet 4.0.0 (C#), a fifth stack of
  independent lineage.
- **New image `bacnet-stack-router`:** upstream bacnet-stack `apps/router`,
  so routed scenarios can run through a real stack's router.
- **bacnet-stack:** upstream 1.6.0 → 1.6.1 (it now refuses a file request
  with the access method the file does not have, instead of executing it);
  fixture `device-baseline-v9` (large object model); up to 64 Analog Value
  and 64 Binary Value objects per fixture; the Trend Log is frozen at
  upstream's seed, which makes ReadRange by sequence number and by time
  assertable.
- **BACpypes3:** upstream 0.0.106 → 0.0.110; DeviceCommunicationControl wired
  in (upstream mixin); `BACNET_DCC_PASSWORD`; the device now has a subnet
  broadcast address and answers a broadcast Who-Is; a GetEnrollmentSummary
  handler on the stack's own request and ACK types.
- **BACnet4J:** upstream 6.1.0 → 6.1.1; `BACNET_DCC_PASSWORD`; a
  deterministic 36-record Trend Log, which makes ReadRange by sequence number
  and by time assertable; `BACNET_EMIT_COV_MULTIPLE=1` emits
  COVNotificationMultiple with the stack's own encoder.
- **Worldiety adapter:** the same 36-record Trend Log; ReadRange by sequence
  number and by time; two adapter defects fixed (Record_Count was served
  under the wrong property, and its WritePropertyMultiple-Error nested the
  property reference one level too deep).
- **Codec evidence for services no stack executes:** with `BACNET_EMIT_AUDIT=1`
  bacnet-stack and BACpypes3 send audit notifications from their own
  encoders; BACpypes3 decodes AuditLogQuery, SubscribeCOVPropertyMultiple and
  the VT requests with its own types and reports the decoded fields.
- **Codec vectors:** five hand-written vectors corrected
  (`service-subscribe-cov-property-multiple`, `service-rpm-ack-partial-error`,
  `service-write-property-multiple-error`, `apdu-error-unknown-property`,
  `service-get-event-information-ack`). A consumer that asserts
  byte-identical re-encoding of these vectors needs encoders that produce the
  corrected bytes.
- **`make dissect-fixtures`:** every codec vector is checked against
  Wireshark's dissector, also in CI.
- **Release workflow:** refuses a tag that is not on `main` or whose version
  differs from `adapters/inventory.yaml`.

---

## v0.9.0

**Date:** 2026-08-03

## Summary

The BBMD table operations, cell by cell. Documentation only; the adapters and
upstream pins are those of v0.8.0.

## Changes

- `PEER_SUPPORT.md` splits the BBMD row into Read-BDT, Read-FDT (after
  foreign-device registration), Delete-FDT and Write-BDT: the first three are
  executable on bacnet-stack, BACpypes3 and BACnet4J.
- Write-BDT is executable on BACnet4J only: bacnet-stack answers NAK at
  Protocol_Revision ≥ 17 and BACpypes3 answers BVLC NAK 0x0010 at the
  current pin. Both are recorded as peer behaviour, not adapter defects.
- The Worldiety README says that peer-as-BBMD and native routing are not
  available through that adapter.

---

## v0.8.0

**Date:** 2026-08-02

## Summary

The native router and BBMD audit, against unchanged upstream pins, and one
capability document instead of three.

## Changes

- **bacnet-stack** is peer-as-BBMD natively (`BBMD_ENABLED` in the device
  server, BDT self-entry, foreign-device registration); BACpypes3 and
  BACnet4J were already. Worldiety BBMD and router stay unavailable; no
  multi-homed native router is packaged yet.
- **`PEER_SUPPORT.md`** replaces `COVERAGE.md`, `EVIDENCE.md` and
  `docs/NETWORK_PEER_SURFACE.md`: what each peer executes and where it
  behaves differently.
- README, PLAN, BLOCKERS and the adapter READMEs rewritten around it.
- The release body says "BACnet/IP peers" instead of "Horizon 1 peers".

---

## v0.7.0

**Date:** 2026-08-02

## Summary

Every native handler the pinned peers have for the event, messaging, identity
and life-safety families is wired in, and what no peer has is recorded as
unsupported upstream instead of being built into an adapter.

## Changes

- **GetAlarmSummary** on bacnet-stack and BACnet4J (`device-baseline-v3`);
  **GetEnrollmentSummary** on BACnet4J.
- **Messaging, time synchronization, PrivateTransfer and WriteGroup:**
  adapters report what they received as `operation` JSON Lines, where the
  stack has the service natively.
- **Who-Am-I / You-Are** on bacnet-stack (`device-baseline-v7`).
- **LifeSafetyOperation** on bacnet-stack and BACnet4J (`device-baseline-v8`).
- SubscribeCOVPropertyMultiple, COVNotificationMultiple, the audit services,
  AuthRequest and the VT services: no pinned peer executes them; codec
  evidence only.
- `EVIDENCE.md` records the competing-stack policy and the unsupported and
  deviation matrices; `docs/NETWORK_PEER_SURFACE.md` inventories the router
  and BBMD surface of every peer.
- The upstream candidates workflow covers Worldiety as well.

---

## v0.6.0

**Date:** 2026-08-02

## Summary

File access, object lifecycle and list mutation on bacnet-stack and BACnet4J.

## Changes

- **AtomicReadFile / AtomicWriteFile**, stream and record, on bacnet-stack and
  BACnet4J (`device-baseline-v4`).
- **CreateObject / DeleteObject** on bacnet-stack and BACnet4J (fixture
  `object_lifecycle`, `device-baseline-v5`).
- **AddListElement / RemoveListElement** on the Recipient_List of a
  Notification Class, on both.
- Codec vectors for the file record write, CreateObject with initial values,
  and three malformed file and CreateObject requests; the file and
  CreateObject vectors corrected.
- `EVIDENCE.md` with the evidence labels (`codec-only`, `live-single-peer`,
  `live-multi-peer`); `BLOCKERS.md` reorganised by priority.

---

## v0.5.0

**Date:** 2026-08-02

## Summary

A fourth peer, Worldiety (Go), and the fixture generations v3 to v8.

## Changes

- **New peer `worldiety`:** worldiety/bacnet `3cb2aa80`, native transport and
  APDU layer; the adapter supplies the object model (Who-Is, Who-Has,
  ReadProperty, ReadPropertyMultiple, WriteProperty,
  WritePropertyMultiple, ReadRange). Image
  `ghcr.io/otfabric/bacnet-interop-worldiety`.
- **Device fixtures v3 to v8:** alarms and event enrollment, File objects,
  object lifecycle and list mutation, messaging and synchronization,
  identity, life safety; plus `topology-v2` and `bbmd-v2`.
- **BACnet4J** loads the v3 objects (Analog Input, Notification Class, Event
  Enrollment, intrinsic Out_Of_Range on the Analog Value) and the v4 File
  objects.
- Codec vectors for alarm and enrollment summaries, COV multiple, file
  access, list mutation, messaging, audit, life safety and VT, with malformed
  variants.
- `BLOCKERS.md` for open work.

---

## v0.4.2

**Date:** 2026-08-02

## Summary

Hygiene: the adapter inventory, evidence types in the coverage matrix, and a
directed Who-Is in the smoke test.

## Changes

- **`adapters/inventory.yaml`:** peer pins and the evidence type of every
  capability (upstream-native or adapter-shim).
- `COVERAGE.md` says which cells are adapter-shim, so they are not read as
  upstream support.
- The smoke test and the upstream candidates workflow send a directed Who-Is
  (`scripts/whois-probe.py`) besides waiting for the ready event.
- Five malformed codec vectors (duplicate or overflowing fields in
  DeviceCommunicationControl, ReadRange, ReinitializeDevice and
  WritePropertyMultiple).
- The Dockerfiles run apt with a tmpfs `/tmp` (Docker Desktop's `/tmp` broke
  signature checks); a committed object file was removed and is ignored.

---

## v0.4.1

**Date:** 2026-08-01

## Summary

BACpypes3 0.0.98 → 0.0.106.

## Changes

- **BACpypes3** upstream 0.0.106; the adapter binds `host:<port>` (BACpypes3
  0.0.106 does not answer confirmed services when bound to `0.0.0.0/0`).
- The upstream candidates workflow writes a decision table (pin, latest,
  candidate build outcome) to the job summary.

---

## v0.4.0

**Date:** 2026-08-01

## Summary

bacnet-stack 1.3.8 → 1.6.0, and a weekly probe of the newest upstreams.

## Changes

- **bacnet-stack** upstream `bacnet-stack-1.6.0`. It answers a segmented
  ComplexACK with an Abort (segmentation-not-supported); segmented
  reassembly stays covered by BACpypes3 and BACnet4J.
- **Upstream candidates workflow** (`candidate.yml`, weekly and on demand):
  builds every peer against the newest upstream without changing the release
  pins.
- **bip-router** takes its addresses from `BACNET_ADDR_NET1` and
  `BACNET_ADDR_NET2`, because Docker does not guarantee the order of `eth0`
  and `eth1`, which swapped the network numbers.

---

## v0.3.1

**Date:** 2026-08-01

## Summary

Republication of v0.3.0: the same tree, rebuilt images.

## Changes

- No change to the adapters, fixtures or documents.

---

## v0.3.0

**Date:** 2026-08-01

## Summary

More services on the three peers, the Trend Log fixture, and the codec
vectors for them.

## Changes

- **Device fixture `device-baseline-v2`:** adds a Trend Log; v1 is frozen.
- **Services:** Who-Has / I-Have, WritePropertyMultiple, ReadRange by
  position, DeviceCommunicationControl, ReinitializeDevice and an
  EventNotification on request (`BACNET_EMIT_EVENT=1`), as far as each peer
  supports them.
- **bip-router** forwards to DNET/DADR with hop count decrement, and helps
  the return path for peers without reverse routing.
- Codec vectors for alarms and events, DeviceCommunicationControl, Who-Has
  and I-Have, ReadRange, ReinitializeDevice and WritePropertyMultiple.

---

## v0.2.1

**Date:** 2026-08-01

## Summary

Malformed codec vectors.

## Changes

- Eight malformed APDU, NPDU and service vectors (reserved bits, an undefined
  max-APDU, a zero window, more-follows without segmentation, a global
  broadcast DADR, an odd I-Am-Router-To-Network, an empty ReadProperty), in
  `fixtures/manifest.json`.

---

## v0.2.0

**Date:** 2026-08-01

## Summary

Routed scenarios work for all three peers, the codec vectors get provenance,
and CI builds every adapter.

## Changes

- **BACnet4J** binds a non-loopback IPv4 address with that interface's
  subnet mask, and its ready event reports that address, so it is reachable
  behind `bip-router`.
- **Codec vectors:** equality flags and provenance on every vector.
- **bip-router** routes to remote devices for all three peers (a topology
  aid, not evidence about a router implementation).
- CI builds all adapters for linux/amd64 and smoke-tests them, including
  `bip-router`, and records the build provenance.

---

## v0.1.0

**Date:** 2026-08-01

## Summary

First release: BACnet/IP peer images and fixtures.

## Changes

- **Peers:** bacnet-stack 1.3.8 (C), BACpypes3 0.0.98 (Python) and BACnet4J
  6.1.0 (Java), each serving `device-baseline-v1` and announcing itself with
  a JSON Lines ready event.
- **Topology aid:** `bip-router`, a BACnet/IP ↔ BACnet/IP router for routed
  scenarios.
- **Fixtures:** codec vectors with `fixtures/manifest.json` and a JSON Schema.
- Multi-arch images (linux/amd64, linux/arm64) built on native runners, and a
  release `manifest.json` with the digests.

---
