# Plan

## Current state

[v0.10.0](https://github.com/otfabric/bacnet-interop/releases/tag/v0.10.0),
summarized in the [README](README.md#changes-in-v0100): a fifth peer (System.IO.BACnet), a
native bacnet-stack router, the large device model, DeviceCommunicationControl
on BACpypes3 and BACnet4J, corrected codec vectors and a Wireshark check for
them.

v0.10.0 was a coordinated release with go-bacnet v0.4.0: the corrected codec
vectors need go-bacnet's corrected encoders, and go-bacnet's new peer tests
need the 0.10.0 adapters. Both are released, and go-bacnet's
`interop/bacnet-interop-pin.json` pins v0.10.0, including the two new images.

## Upstream versions

| Stack | Pinned | Newest stable upstream |
|---|---|---|
| bacnet-stack (device and router images) | 1.6.1 | 1.6.1 (2026-08-28) |
| BACpypes3 | 0.0.110 | 0.0.110 (2026-09-24) |
| BACnet4J | 6.1.1 | 6.1.1 |
| Worldiety | `3cb2aa80` | the same commit (HEAD of `main`) |
| System.IO.BACnet | 4.0.0 | 4.0.0 (4.1.0 is a beta) |
| cB-Sigma bacnet (device role) | `v0.2.0` | `v0.2.0` (2026-10-12) |
| cB-Sigma bacnet-sim | `v0.1.0` | `v0.1.0` (2026-10-11) |

Every pin is at the newest stable upstream. Two moved in v0.10.0 beside
BACnet4J (6.1.0 → 6.1.1), both without an adapter change:

- **bacnet-stack 1.6.0 → 1.6.1** (`7a53f0a7`, device and router images). One
  behaviour changed: a file request with the access method the file does not
  have is refused with Error services/invalid-file-access-method instead of
  being executed. upstream `main` is ahead of the tag; only tags are pinned.
- **BACpypes3 0.0.106 → 0.0.110.** No visible behaviour change; the
  DeviceCommunicationControl defects are not fixed in it.

## Principles

- Keep peer pins deliberate and reproducible.
- Never patch an upstream stack. Expose what it does, and record what it does
  not do, instead of repairing it in the adapter.
- Say which behaviour is the stack's and which the adapter's
  ([PEER_SUPPORT.md](PEER_SUPPORT.md)).
- Add fixtures when go-bacnet adds or corrects client behaviour.
- A codec vector needs a second opinion ([fixtures/README.md](fixtures/README.md)).

## Next

- **cB-Sigma (v0.13.0):** go-bacnet's `interop/` has no cbsigma tests yet; the
  scenarios of [PEER_SUPPORT.md](PEER_SUPPORT.md#cb-sigma-cbsigma) were run
  from a local branch of go-bacnet and belong in its suite. BACnet/IPv6 and
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
  `device-server-v1` fixture; bacnet-stack, BACnet4J and BACpypes3 client
  modes; `make client-matrix` in CI. Next: sysiobacnet, worldiety and a new
  bacnet-js image ([docs/CLIENT_DRIVER_CONTRACT.md](docs/CLIENT_DRIVER_CONTRACT.md)).
