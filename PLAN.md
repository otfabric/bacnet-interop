# Plan

## Current state

[v0.16.0](https://github.com/otfabric/bacnet-interop/releases/tag/v0.16.0)
([RELEASE.md](RELEASE.md#v0160)): the licence texts of every upstream under
`/licenses/` in every image, the BACpypes3 wheel pinned by its sha256, each
release image smoke-tested on its architecture before it is pushed, a JSON
Schema for `adapters/inventory.yaml`, and tests that decode the Worldiety
device's answers with Worldiety's own client. No image behaviour changed.

Before it: v0.15.0 added the image of OT Fabric's own stack, go-bacnet (not
a reference, not in a release; [own/go-bacnet/README.md](own/go-bacnet/README.md)),
v0.14.0 the peers ulbios, legacy BACpypes and bacnet-js, v0.13.0 cB-Sigma and
v0.12.0 client mode (container contract 1.1). A release has eleven images:
nine peers and two routers ([adapters/inventory.yaml](adapters/inventory.yaml)).
go-bacnet pins a release in `interop/bacnet-interop-pin.json`.

## Upstream versions

| Stack | Pinned | Newest stable upstream |
|---|---|---|
| bacnet-stack (device and router images) | 1.6.1 | 1.7.0 (not adopted yet) |
| BACpypes3 | 0.0.110 | 0.0.110 (2026-09-24) |
| legacy BACpypes | 0.19.0 | 0.19.0 |
| BACnet4J | 6.1.1 | 6.1.1 |
| Worldiety | `3cb2aa80` | the same commit (HEAD of `main`) |
| System.IO.BACnet | 4.0.0 | 4.0.0 (4.1.0 is a beta) |
| cB-Sigma bacnet (device role) | `v0.2.0` | `v0.2.0` (2026-10-12) |
| cB-Sigma bacnet-sim | `v0.1.0` | `v0.1.0` (2026-10-11) |
| ulbios/bacnet | `227d6227` | the same commit (HEAD; no tags) |
| @bacnet-js/client | 3.3.2 | 3.3.2 |

`scripts/latest-upstream.py` on 2026-11-15. Every pin but bacnet-stack is at
the newest stable upstream; bacnet-stack 1.7.0 is the next candidate
(`make candidate-bacnet-stack`). The last pins moved in v0.10.0, none with an
adapter change:

- **bacnet-stack 1.6.0 → 1.6.1** (`7a53f0a7`, device and router images). One
  behaviour changed: a file request with the access method the file does not
  have is refused with Error services/invalid-file-access-method instead of
  being executed. upstream `main` is ahead of the tag; only tags are pinned.
- **BACpypes3 0.0.106 → 0.0.110.** No visible behaviour change; the
  DeviceCommunicationControl defects are not fixed in it.
- **BACnet4J 6.1.0 → 6.1.1.**

## Principles

- Keep peer pins deliberate and reproducible.
- Never patch an upstream stack. Expose what it does, and record what it does
  not do, instead of repairing it in the adapter.
- Say which behaviour is the stack's and which the adapter's
  ([PEER_SUPPORT.md](PEER_SUPPORT.md)).
- Add fixtures when go-bacnet adds or corrects client behaviour.
- A codec vector needs a second opinion ([fixtures/README.md](fixtures/README.md)).

## Next

- **cB-Sigma (v0.13.0):** client mode (contract 1.1) is not wired for it, and
  `make client-matrix` does not run the reference clients against its
  device; cB-Sigma's bacnet has a client that could serve. BACnet/IPv6 and
  BACnet/SC are out of scope (go-bacnet is IPv4 BACnet/IP only).
- **System.IO.BACnet:** a global Who-Is to it through `bip-router` produces no
  I-Am (it works through `bacnet-stack-router`); not investigated. The
  linux/amd64 image was only partly exercised. CreateObject/DeleteObject,
  PrivateTransfer and the BBMD code of the package are not wired.
- **BACpypes3 WritePropertyMultiple shim:** it answers a failed write with a
  plain Error, and crashes into device/operational-problem for an unknown
  property. It should answer with the stack's `WritePropertyMultipleError`
  naming the failed element.
- **bacnet-stack record files:** a record read of the v4 record file returns
  one empty record; the seeding in `run_server.py` or upstream needs a look.
- **BACnet4J releases:** upstream stopped publishing to the Maven repository
  the pom and `scripts/latest-upstream.py` read ("publish only to GitHub
  Packages"), so the daily Upstream check will not see the next 6.x or 7.x.
  BACnet4J 7.0 (alpha today) adds the audit services and AuthRequest and
  would turn the audit codec evidence into a real service codec.
- **Upstream defects to watch:** BACpypes3 DeviceCommunicationControl never
  takes effect in 0.0.110; when it is fixed the adapter's `smap`
  alias goes and the "not enforced" test changes.
- **Worldiety BBMD and router:** not possible until upstream exposes a server
  path the adapter can configure without inventing forwarding. Upstream HEAD
  is the pinned commit.
- **Services no stack executes** (SubscribeCOVPropertyMultiple,
  COVNotificationMultiple, the audit services, VT sessions, AuthRequest):
  there is codec evidence for all but AuthRequest
  ([PEER_SUPPORT.md](PEER_SUPPORT.md)); a stack that really subscribes, logs
  or opens a session is still missing.
- **Client-driver mode** (contract 1.1, v0.12.0): images run their stack as a
  client against a device under test, for the go-bacnet server. Done:
  scenario and result-line schemas; `server-baseline-v1`,
  `server-services-v1`, `server-bbmd-v1` and `server-extended-v1`
  (segmentation, SubscribeCOVProperty(Multiple), GetAlarmSummary,
  GetEnrollmentSummary, text messages, ConfirmedPrivateTransfer); the
  `device-server-v1` fixture; client mode in six images (bacnet-stack,
  BACnet4J, BACpypes3, legacy BACpypes, ulbios, bacnet-js) and in the
  own-stack image; `make client-matrix` in CI. Next: client mode for
  sysiobacnet, worldiety and cbsigma, and their devices in
  `make client-matrix`, which today runs the reference clients only against
  the devices of the six client images
  ([docs/CLIENT_DRIVER_CONTRACT.md](docs/CLIENT_DRIVER_CONTRACT.md)).
- **Container contract 1.2:** `print-capabilities` and `schemaVersion` in
  every image, and the organisation exit codes, together (the maintainer's
  decision; [docs/CONTAINER_CONTRACT.md](docs/CONTAINER_CONTRACT.md)).
