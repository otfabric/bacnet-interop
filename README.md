# bacnet-interop — BACnet/IP Interoperability Testing with Docker

**bacnet-interop** provides reproducible BACnet/IP interoperability
testing infrastructure using multiple independent BACnet protocol
implementations.

It offers Dockerized BACnet devices, deterministic device fixtures,
BACnet object models, BBMD and routed-network scenarios, codec test
vectors, and automated protocol compatibility testing.

Reference implementations include BACnet Stack (C), BACpypes3
(Python), BACnet4J (Java), System.IO.BACnet (C#), and Worldiety
(Go).

The infrastructure is independently maintained and can be used
by any BACnet client implementation.

[OTFabric go-bacnet](https://github.com/otfabric/go-bacnet)
consumes these reference images to validate its own BACnet protocol
implementation.

**Latest images:** [v0.10.0](https://github.com/otfabric/bacnet-interop/releases/tag/v0.10.0)
([what changed](#changes-in-v0100)).

## Peers

| Image | Upstream | Role |
|---|---|---|
| `bacnet-interop-bacnet-stack` | bacnet-stack 1.6.1 (C) | Device oracle (+ BBMD) |
| `bacnet-interop-bacpypes3` | BACpypes3 0.0.110 (Python) | Device oracle (+ BBMD) |
| `bacnet-interop-bacnet4j` | BACnet4J 6.1.1 (Java) | Device oracle (+ BBMD) |
| `bacnet-interop-worldiety` | worldiety/bacnet `3cb2aa80` (Go) | Native transport and APDU layer; the adapter supplies the object model |
| `bacnet-interop-sysiobacnet` | System.IO.BACnet, NuGet `BACnet` 4.0.0 (C#) | Device oracle; the stack behind YABE (new in 0.10.0) |
| `bacnet-interop-bacnet-stack-router` | bacnet-stack 1.6.1 `apps/router` (C) | Native BACnet/IP ↔ BACnet/IP router (new in 0.10.0) |
| `bacnet-interop-bip-router` | none (Python, written for the tests) | Topology aid for routed scenarios; not evidence about any stack |

What each peer can execute, and where a peer behaves differently from the
others: [PEER_SUPPORT.md](PEER_SUPPORT.md). Per-image details, environment
variables and observed behaviour: `adapters/<name>/README.md`.

The adapters never patch an upstream stack. They load a fixture, start the
stack's own server, and where a stack has no object or service of its own
supply it in adapter code, which the capability matrix marks as such.

## Fixtures

Device models under `fixtures/device/`, selected with `DEVICE_FIXTURE_FILE`
and `FIXTURE`:

| Fixture | Adds | Served by |
|---|---|---|
| v1 | Device, Analog Value, Binary Value (frozen) | all device peers |
| v2 | Trend Log (default) | all device peers (BACpypes3 skips the Trend Log) |
| v3 | Notification Class, Event Enrollment, alarms | bacnet-stack, BACnet4J; System.IO.BACnet with an adapter-supplied alarm model |
| v4 | File objects | bacnet-stack, BACnet4J, System.IO.BACnet |
| v5 | Object lifecycle and list mutation | bacnet-stack, BACnet4J |
| v6 | Messaging and time synchronization | bacnet-stack, BACpypes3, BACnet4J |
| v7 | Identity (Who-Am-I / You-Are) | bacnet-stack |
| v8 | Life safety | bacnet-stack, BACnet4J |
| v9 | Large object model: 40 more objects, an Object_List that does not fit a 50-octet APDU | bacnet-stack only (new in 0.10.0) |

`fixtures/codec/` holds wire vectors for go-bacnet's codec tests,
`fixtures/topology/` and `fixtures/bbmd/` the routed and BBMD scenarios. See
[fixtures/README.md](fixtures/README.md), including what a hand-written vector
does and does not prove.

## Build and check

```bash
make validate-fixtures   # manifest, schemas, fixture metadata
make dissect-fixtures    # codec vectors against Wireshark's dissector (needs tshark)
make build               # all adapter images as bacnet-interop-<name>:local
make smoke               # ready event (and a Who-Is probe) per image
make ci                  # validate-fixtures + build + smoke
```

`make build-<name>` builds one image. Images are built for the host
architecture; the release workflow publishes linux/amd64 and linux/arm64.

The Upstream workflow checks every pin daily against the latest upstream
(`scripts/latest-upstream.py <stack>`) and the base-image digests. A stack
that is behind is built and smoke-tested at the latest upstream
(`make candidate-<stack> CANDIDATE_VERSION=… [CANDIDATE_SHA=…]`); the
result goes to the issue "Upstream releases: pins behind the latest". Pins
are never changed by it.

To run the go-bacnet assertions, from a go-bacnet checkout next to this one:

```bash
make interop-pinned   # against the published images pinned in interop/bacnet-interop-pin.json
make interop          # against the :local images built here
```

## Consumer contract

Every image writes JSON Lines to stdout. The first line is the ready event,
written once the BACnet/IP socket is bound:

```json
{"event":"ready","adapter":"bacnet-stack","version":"0.10.0","fixture":"device-baseline-v2","address":"0.0.0.0:47808","peer_version":"bacnet-stack-1.6.1"}
```

`version` is the adapter release (a commit for a local build), `peer_version`
the upstream stack. Some adapters then write
`{"event":"operation","adapter":…,"operation":…,"result":…}` lines for requests
that have no observable reply. Diagnostics go to stderr. The two routers add
`networks` and `addresses` to the ready event.

A consumer pins the images by digest (go-bacnet:
`interop/bacnet-interop-pin.json`), taken from the release's `manifest.json`:

```bash
# by tag, for a quick local run
BACNET_STACK_IMAGE=ghcr.io/otfabric/bacnet-interop-bacnet-stack:v0.10.0
# by digest, for CI
BACNET_STACK_IMAGE=ghcr.io/otfabric/bacnet-interop-bacnet-stack@sha256:<digest>
```

## Changes in v0.10.0

- **New peer `sysiobacnet`:** System.IO.BACnet 4.0.0 (C#), a fifth stack of
  independent lineage.
- **New image `bacnet-stack-router`:** upstream bacnet-stack `apps/router`,
  so routed scenarios can run through a real stack's router.
- **bacnet-stack:** upstream 1.6.0 → 1.6.1 (it now refuses a file request
  with the access method the file does not have, instead of executing it);
  fixture `device-baseline-v9` (large object model); up to
  64 Analog Value and 64 Binary Value objects per fixture; the Trend Log is
  frozen at upstream's seed, which makes ReadRange by sequence number and by
  time assertable.
- **BACpypes3:** upstream 0.0.106 → 0.0.110; DeviceCommunicationControl wired in (upstream mixin);
  `BACNET_DCC_PASSWORD`; the device now has a subnet broadcast address and
  answers a broadcast Who-Is; a GetEnrollmentSummary handler on the stack's
  own request and ACK types.
- **BACnet4J:** upstream 6.1.0 → 6.1.1; `BACNET_DCC_PASSWORD`; a deterministic
  36-record Trend Log, which makes ReadRange by sequence number and by time
  assertable; `BACNET_EMIT_COV_MULTIPLE=1` emits COVNotificationMultiple with
  the stack's own encoder.
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
  `service-get-event-information-ack`). A consumer that asserts byte-identical
  re-encoding of these vectors needs encoders that produce the corrected
  bytes: go-bacnet from v0.4.0.
- **`make dissect-fixtures`:** every codec vector is checked against
  Wireshark's dissector, also in CI.
- **Release workflow:** refuses a tag that is not on `main` or whose version
  differs from `adapters/inventory.yaml`.

## Releasing

1. Write the notes of the release in [RELEASE.md](RELEASE.md), set
   `adapter_version` in `adapters/inventory.yaml` and the version in the
   documents to the release, and commit to `main`.
2. Push `main`. Then tag **that commit** `vX.Y.Z` and push the tag. Do not
   amend or rebase `main` afterwards: v0.8.0 and v0.9.0 were tagged on commits
   that were later rewritten, so their tags are not on `main`.
3. The release workflow checks the notes and validates the fixtures, builds
   every adapter for both architectures, publishes the images and attaches
   `manifest.json` with the digests. The body of the GitHub release is the
   section of the tag in RELEASE.md (up to its `---` line), followed by the
   image digests.
4. Update the pin in the consuming repository from that manifest.

Open work: [BLOCKERS.md](BLOCKERS.md). Forward plan: [PLAN.md](PLAN.md).

## Repository layout

```text
bacnet-interop/
├── README.md
├── RELEASE.md             release notes (the body of each GitHub release)
├── PEER_SUPPORT.md        capability matrix and peer behaviour
├── BLOCKERS.md            open work
├── PLAN.md                forward plan
├── Makefile
├── scripts/               fixture validation, dissector check, smoke test, release notes,
│                          upstream check and candidates
├── fixtures/
│   ├── codec/             wire vectors + manifest.json
│   ├── device/            device models v1–v9
│   ├── topology/, bbmd/   routed and BBMD scenarios
│   └── schema/
└── adapters/
    ├── inventory.yaml     build/release input (not public truth)
    ├── bacnet-stack/
    ├── bacnet-stack-router/
    ├── bacpypes3/
    ├── bacnet4j/
    ├── worldiety/
    ├── sysiobacnet/
    └── bip-router/
```

## License

See [LICENSE](LICENSE). Peer upstream licenses remain their own; adapters run in
containers and are not linked into go-bacnet.
