# bacnet-interop-otfabric

[go-bacnet](https://github.com/otfabric/go-bacnet), OT Fabric's own BACnet/IP
stack, behind the [container contract](../../docs/CONTAINER_CONTRACT.md) and the
[client-driver contract](../../docs/CLIENT_DRIVER_CONTRACT.md). Other stacks can
test against it. You can use this image wherever you use a
`bacnet-interop-<adapter>` image. It is not a reference, though: its tags are
go-bacnet versions, and no harness release or `manifest.json` contains it.

**For testing only.** It runs an unauthenticated BACnet/IP device, which
answers WriteProperty, DeviceCommunicationControl and ReinitializeDevice. Do
not expose it to a network you do not control. Old images stay available, so
check the [go-bacnet advisories](https://github.com/otfabric/go-bacnet/security/advisories)
for the version you pull.

**Not an independent implementation.** The image declares
`upstream.independentEngine: false`, its ready line says
`"independent_engine": false`, and `results.json` records
`independent: false`. When OT Fabric produces a result against this image, it
is not independent evidence about go-bacnet: it is at most **Tested**. If you
publish a result that names your implementation and its version, that is
independent evidence, and we would like to hear about it.

## Use

```sh
docker run --rm -p 47808:47808/udp ghcr.io/otfabric/bacnet-interop-otfabric:<tag>
docker run --rm --network host ghcr.io/otfabric/bacnet-interop-otfabric:<tag> \
  client --target 192.0.2.10:47808 --device 1234 --scenarios /scenarios/server-baseline-v1.json
```

`<tag>` is either a go-bacnet version such as `v0.8.0`, or `latest`, the newest
one published. A rebuild of a version replaces its tag, so pin the digest if you
need an exact build. The digest is in the summary of the
[workflow run](https://github.com/otfabric/bacnet-interop/actions/workflows/own-go-bacnet.yml).
`docker run --rm <image> version` prints the versions, and
`print-capabilities` prints them as JSON.

| | |
|---|---|
| Upstream | go-bacnet, the latest release when the image was built |
| Licence | MIT; the licence of every module is in the image under `/licenses` |
| Adapter name | `otfabric` |
| Language | Go |
| Protocol engine | OT Fabric's own (`server`, `server/object`, `bbmd`, `client`) |
| Roles | device (the default), BBMD (`BACNET_BBMD=1`), client (`client`) |

### Device mode

The device mode is the default command. Its environment variables are those of
the other device images:

| Variable | Default | |
|---|---|---|
| `FIXTURE` | `device-baseline-v2` | a file under `/fixtures/device/` |
| `DEVICE_FIXTURE_FILE` | from `FIXTURE` | a fixture path; overrides `FIXTURE` |
| `BACNET_IP_PORT` | `47808` | UDP port |
| `BACNET_BBMD` | unset | `1`: also a BBMD, with itself in its BDT |
| `BACNET_DCC_PASSWORD` | unset | the password DeviceCommunicationControl and ReinitializeDevice require |

It serves device-baseline-v1, -v2, -v4, -v5, -v6, -v9 and device-server-v1.
device-baseline-v3 (Event Enrollment), -v7 (Audit Log) and -v8 (Life Safety
Point and Zone) name object types that go-bacnet's `server/object` has no
constructor for. Loading one of them fails at start, so the image never serves
part of a fixture. The fixtures that predate the `commandable` field (v1 to v9)
are served with commandable Analog Values, because server-baseline-v1 writes
and relinquishes AV-1 at priority 8.

A request that has no reply to observe is reported as an `operation` line.
These are TimeSynchronization, UTCTimeSynchronization, the private transfers,
the text messages and WriteGroup.

### Client mode

`client --target --device --scenarios [--only] [--broadcast] [--bbmd --fd-ttl]`
runs every scenario file in `/scenarios`, with `BACNET_CLIENT_TIMEOUT_MS`
(3000) and `BACNET_CLIENT_RETRIES` (1). Most requests are made with the typed
methods of go-bacnet's `client`. The SubscribeCOV services and the list-element
services use `InvokeConfirmed` with go-bacnet's service encoders, because the
scenarios set fields that the typed methods do not take. The COV notifications
are observed by a wrapper around the transport.

A scenario is reported `unsupported` when go-bacnet refuses to send its request.
The only such scenario today is `reinit.undefined-state`:
`service.EncodeReinitializeDevice` refuses state 9 because it is outside the
states go-bacnet defines (0 to 7, `service.ReinitializedStateOfDevice`).

## Why it is apart from the other adapters

Nothing under `adapters/`, `fixtures/`, `schemas/` or `scripts/`, and nothing in
the top-level `Makefile`, may know a library under test. The CI job *No
reference to a library under test* enforces this. This directory and
`.github/workflows/own-go-bacnet.yml` are the one exception. The scripts take
the image through `ADAPTER_IMAGE_otfabric`:

- `scripts/smoke-test.sh` smoke-tests every `ADAPTER_IMAGE_<adapter>`;
- `scripts/client-matrix.py` adds it as a client and a device. With
  `--gate otfabric`, every pair that includes it gates, and its expected
  differences come from `--extra-differences` ([expected-differences.json](expected-differences.json)).

No release loop can form (`otfabric/engineering` ADR-0012):

- The image is built by hand from the latest go-bacnet release, and the build
  commits nothing: this repository has no go-bacnet pin to bump.
- No release or required check of go-bacnet needs the image, and go-bacnet
  commits no pin of it.
- It is not in a harness release or in `manifest.json`.

## Publishing

Run the **Own stack (go-bacnet)** workflow by hand, from `main`. It finds the
latest go-bacnet release and the latest harness release, and prints them. On
both architectures it then:

1. builds the image (`go test` runs inside the build);
2. checks out the self-tests of that harness release;
3. pulls that release's client images by the digest in its `manifest.json`;
4. runs the smoke test and the cross-stack self-test.

Last, it publishes `:<go-bacnet version>` and `:latest`. Run from a branch, the
workflow stops before publishing. Nothing runs it automatically, so after a
go-bacnet release the image stays on the old version until someone runs it.

From the repository root:

```sh
make -f own/go-bacnet/Makefile image smoke matrix IMAGE=bacnet-interop-otfabric:local
```
