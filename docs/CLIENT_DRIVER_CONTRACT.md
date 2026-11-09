# Client-driver contract

Status: **part of container contract 1.1 (v0.12.0)**. Released: the
scenario and result-line schemas, `server-baseline-v1`,
`server-services-v1`, `server-bbmd-v1` and `server-extended-v1`, the
`device-server-v1` fixture, and bacnet-stack, BACnet4J and BACpypes3 client
mode; from v0.14.0 also ulbios, legacy BACpypes and bacnet-js client mode. The
other images run a device or router only ([CONTAINER_CONTRACT.md](CONTAINER_CONTRACT.md));
this adds a second mode in which an image runs its upstream stack as a
**client** against a device under test (DUT), so that a server implementation
(first consumer: the go-bacnet server, go-bacnet `docs/SERVER_SUPPORT.md`)
can be tested by independent clients. `contract_version` is 1.1 from v0.12.0,
the first release with client mode.

Contract 1.0 stays valid: an image without client mode is unchanged.

The `otfabric` image (go-bacnet, OT Fabric's own stack) has client mode under this contract too. It is not an independent client: a result with it is at most Tested ([own/go-bacnet/README.md](../own/go-bacnet/README.md)).

## Peers

| Image | Client engine | Notes |
|---|---|---|
| bacnet-stack | Upstream command-line tools at the same pin: `bacwi`, `bacwh`, `bacrp`, `bacrpm`, `bacwp`, `bacwpm`, `bacscov`, `bacrr`, `bacdcc`, `bacrd`, `bacarf`, `bacawf`, `bacale`, `bacrle`, `bacco`, `bacdo`, `bacge`, `bacackalarm`, `bacts`, `bacupt`, `bacwg`, `bacrbdt`, `bacrfdt`, `bacwbdt` | First to implement; a wrapper turns tool output into result lines. Built without segmentation |
| bacnet4j | `LocalDevice` + `RemoteDevice` requests (`ClientDriver.java`) | Implemented. Segmentation, COV, COV-property (multiple), BBMD/FD; no client for the BVLC table functions |
| bacpypes3 | Upstream `Application`: APDU classes sent with `Application.request()` and its `who_is`, `who_has`, `read_property_multiple` helpers | Implemented. Segmentation, COV, SubscribeCOVProperty, alarm and enrollment summaries, text messages, ConfirmedPrivateTransfer, BBMD/FD. No SubscribeCOVPropertyMultiple |
| ulbios | ulbios/bacnet request encoders (`NewWhois`, `NewReadProperty`, `NewWriteProperty`, `objects.Enc*`) and `bacnet.Parse` (`client.go`) | Implemented (0.14.0). Who-Is without limits, ReadProperty, WriteProperty; everything else `unsupported`. Answers its decoders cannot read are `known-difference` (adapters/ulbios/README.md). No transaction layer upstream: the timer and retries are adapter code |
| bacpypes | Legacy BACpypes 0.19.0 (not BACpypes3): upstream APDU classes sent through `ApplicationIOController.request_io` with an IOCB, the asyncore core in the main thread (`samples/ThreadedReadProperty.py`) | Implemented (0.14.0). Segmentation, COV, SubscribeCOVProperty, alarm and enrollment summaries, text messages, ConfirmedPrivateTransfer, BBMD/FD and the BVLC tables (second link layer, `samples/ReadWriteBBMD.py`). No SubscribeCOVPropertyMultiple |
| sysiobacnet | `BacnetClient` | Its native side |
| worldiety | Typed `apdu.Client` | |
| bacnet-js | Upstream `BACnetClient` of `@bacnet-js/client` 3.3.2 (npm, MIT); requests it has no method for are built with its encoders and sent through its request manager (`client.js`) | Implemented (0.14.0). Also a device image (device mode is the default). Segmented answers; no segmented requests, list elements, WriteGroup, text messages, COV-multiple or BVLC table functions. Independent JavaScript lineage (node-bacstack) |

Upstream stays unpatched; the adapter is a driver program next to the stack.

## Invocation

Same image, selected by the first argument (the device remains the default):

```text
docker run --rm --network <net> <image>@sha256:… client \
  --target 10.88.0.10:47808 --device 1234 \
  --scenarios /scenarios/server-baseline-v1.json
```

| Input | Meaning |
|---|---|
| `client` | Selects client mode |
| `--target HOST:PORT` | DUT BACnet/IP endpoint; `--broadcast ADDR` for discovery scenarios |
| `--device N` | DUT device instance |
| `--scenarios FILE` | Scenario file (below); the image ships the published ones under `/scenarios` |
| `--only ID[,ID]` | Run a subset |
| `--bbmd HOST:PORT`, `--fd-ttl S` | Register as a foreign device first |
| Env `BACNET_CLIENT_TIMEOUT_MS`, `BACNET_CLIENT_RETRIES` | APDU timeout and retries (defaults stated in the image README) |

Each scenario is independent; the driver does not stop at the first failure.
Scenarios run in file order, and a write scenario leaves its value behind, so
a file that writes restores what later scenarios read.

Implemented by bacnet-stack: every input above (timeout
default 3000 ms, 1 retry; passed to the tools as `BACNET_APDU_TIMEOUT` and
`BACNET_APDU_RETRIES`).

- `--broadcast ADDR` is where the Who-Is of a `who-is` scenario is sent
  (`bacwi --mac`); without it the tool broadcasts on the container network.
- `--bbmd HOST:PORT` and `--fd-ttl S` (1..65535, default 60) make every
  service tool register as a foreign device first (bacnet-stack dlenv.c:
  `BACNET_BBMD_ADDRESS`, `BACNET_BBMD_PORT`, `BACNET_BBMD_TIMETOLIVE`); its
  broadcasts then go to the BBMD as Distribute-Broadcast-To-Network. The BVLC
  table tools (`bacrbdt`, `bacrfdt`, `bacwbdt`) do not register, because a
  registering tool prints its own registration result instead of the
  answer. A scenario file with `"requires_bbmd": true` without `--bbmd` is a
  usage error (exit 2).

The tools bind to the DUT by Who-Is, on the container's network or through
the BBMD, so the DUT must be reachable that way; the driver checks that the
I-Am came from `--target` and reports `infra-error` otherwise, and a request
to a device that never answered Who-Is is `infra-error` as well. A tool that
crashes is `infra-error`.

Implemented by BACnet4J: every input above, with the same
defaults (`DefaultTransport.setTimeout`, `setRetries`). The device is bound
by a Who-Is sent to `--target` (an I-Am from another address, or none, is
`infra-error`); `--broadcast` is where `who-is` and `who-has` go;
`--bbmd`/`--fd-ttl` register the local device as a foreign device once,
before the first scenario. See adapters/bacnet4j/README.md.

## Scenarios

A versioned JSON file in `fixtures/scenarios/`, validated by
`make validate-fixtures` against a schema like the device fixtures:

```json
{
  "id": "server-baseline-v1",
  "requires_fixture": "device-baseline-v2",
  "scenarios": [
    {"id": "rp.device.object-name", "service": "read-property",
     "object": "device,1234", "property": "object-name",
     "expect": {"value": {"type": "character-string", "value": "InteropDevice"}}},
    {"id": "wp.av1.pv.priority8", "service": "write-property",
     "object": "analog-value,1", "property": "present-value", "priority": 8,
     "value": {"type": "real", "value": 42.0}, "expect": {"ack": true}},
    {"id": "rp.unknown-object", "service": "read-property",
     "object": "analog-value,999", "property": "present-value",
     "expect": {"error": {"class": "object", "code": "unknown-object"}}}
  ]
}
```

- `requires_fixture` names the object model the DUT must serve
  (`device-baseline-vN` or `device-server-vN`). The DUT loads the same
  `fixtures/` files the device images use, so server and peer-device runs
  share one data set. `device-server-v1` adds what the services scenarios
  need: an Analog Value with intrinsic reporting, a Notification Class, a
  Trend Log with a seeded buffer, a stream and a record File, and
  CreateObject for Analog Value instances 100..199.
- `requires_bbmd` marks a file whose scenarios need `--bbmd`.
- `server-extended-v1` covers what the bacnet-stack tools cannot issue:
  a segmented AtomicReadFile-ACK and a segmented AtomicWriteFile request
  (`FILE-STREAM-3`, 3000 octets, in `device-server-v1`),
  SubscribeCOVProperty and SubscribeCOVPropertyMultiple, GetAlarmSummary,
  GetEnrollmentSummary, Confirmed/UnconfirmedTextMessage and
  ConfirmedPrivateTransfer.
- `expect` is one of `value`, `values` (RPM), `ack`, `error` (with
  `first_failed_element` for list services), `reject`, `abort`, `i-am`,
  `i-have`, `subscribed` (with `notification` when the initial COV
  notification must arrive), `records` (ReadRange), `created`, `events`
  (GetEventInformation), `alarms` (GetAlarmSummary), `enrollments`
(GetEnrollmentSummary; `event_type` and `notification_class` compared when
given), `octets_base64` (AtomicReadFile), `recipients`,
  `sent` (an unconfirmed request; the consumer checks what arrived, named by
  `operation`), `bdt`, `fdt` and `bvlc_result`. `error.first_failed` is the
  WritePropertyMultiple or SubscribeCOVPropertyMultiple first failure
  ([fixtures/schema/client-scenarios.schema.json](../fixtures/schema/client-scenarios.schema.json)).
  A BDT entry for the BBMD itself is written `"bbmd"`, because a scenario
  file cannot know its address.
- Scenario ids are stable; a changed expectation is a new fixture version.

## Output

JSON Lines on stdout, like device mode. First line:

```json
{"event":"ready","mode":"client","adapter":"bacnet-stack","version":"0.12.0","peer_version":"bacnet-stack-1.6.1","scenarios":"server-baseline-v1"}
```

Then one line per scenario
([schemas/client-result-line-v1.schema.json](../schemas/client-result-line-v1.schema.json)):

```json
{"event":"result","scenario":"wp.av1.pv.priority8","service":"write-property","outcome":"pass","durationMs":12,"observed":{"ack":true}}
```

`outcome` uses the interop-result-v1 values: `pass`, `fail`, `unsupported`
(the peer's client cannot issue this service), `not-tested`,
`known-difference` (a recorded peer deviation, listed in PEER_SUPPORT.md),
`infra-error` (timeouts before the first reply, socket errors). `observed`
holds what the peer decoded, so a `fail` is diagnosable without a capture.
Last line:

```json
{"event":"done","summary":{"pass":41,"fail":0,"unsupported":3,"not-tested":0,"known-difference":1,"infra-error":0}}
```

The consumer (go-bacnet `interop/`, `//go:build interop`) starts its server,
runs the image, maps result lines into its interop-result-v1 document and
asserts. The image never decides pass/fail for the DUT beyond comparing with
`expect`; assertions about the library stay in the consumer.

## Exit codes

Client mode adopts the organisation exit codes
(`otfabric/engineering` `standards/interoperability.md`): 0 all scenarios
ran (whatever their outcome), non-zero for usage errors or when the driver
could not run (no network, unreadable scenario file). Outcomes are read from
the output, not the exit code.

## Inventory and versions

- `adapters/inventory.yaml` gets a `client_capabilities` block per image
  with the same cell values (`native`, `adapter-shim`, `unsupported`).
- `versions.yaml`: roles gain `client`; bacnet-js is added with its npm pin
  and licence.
- `contract_version` is `1.1` from v0.12.0, the first release with client mode.

## Order of work

1. Schema for scenarios and result lines; `server-baseline-v1`
   (Who-Is, Who-Has, RP, RPM, WP, WPM and their error cases).
2. bacnet-stack client mode (command-line tools).
3. Scenarios for COV, DCC, ReadRange, files, lists, object lifecycle,
   alarms, messaging and foreign-device registration (`server-services-v1`,
   `server-bbmd-v1`; done for bacnet-stack); BACnet4J and BACpypes3 client
   modes for these and for segmentation, SubscribeCOVProperty(Multiple),
   GetAlarmSummary, GetEnrollmentSummary, text messages and
   ConfirmedPrivateTransfer, which the bacnet-stack tools do not cover.
4. sysiobacnet, worldiety, bacnet-js. bacnet-js is done; sysiobacnet and
   worldiety are not started.

Step 1 and 2 were validated against the bacnet-stack device image itself
(client mode of one image against device mode of another, same pin): all 23
scenarios of `server-baseline-v1` pass, every emitted line validates against
the result-line schema, and a run with a device instance that does not exist
gives `infra-error`, not a pass.

The bacnet-stack part of step 3 was run against the go-bacnet server
(go-bacnet `interop/server_clients_test.go`): `server-services-v1` 35 of 36
pass and `rle.nc1` is `known-difference` (`bacrle` prints nothing for the
acknowledgement, see PEER_SUPPORT.md); `server-bbmd-v1` 5 of 5 pass. These
files were not run against the bacnet-stack device image, which does not
serve `device-server-v1`.

BACnet4J client mode was run against the go-bacnet server with all four
files: `server-baseline-v1` 23 of 23 pass, `server-services-v1` 36 of 36,
`server-bbmd-v1` 2 pass and 3 `unsupported` (Read-BDT, Read-FDT,
Write-BDT: no BACnet4J client), `server-extended-v1` 22 of 23 pass and
`scovpm.unknown-object-second` is `known-difference` (BACnet4J decodes
SubscribeCOVPropertyMultiple-Error as a CHOICE, see PEER_SUPPORT.md).
Against the bacnet-stack device image, all 23 scenarios of
`server-baseline-v1` pass, every emitted line validates against the
result-line schema, and a device instance that does not exist gives
`infra-error`.

BACpypes3 client mode implements every input above (same
defaults) and runs all four scenario files against the go-bacnet server; the
results and the BACpypes3 answers that count as `known-difference` are in
PEER_SUPPORT.md.

Legacy BACpypes client mode (`bacpypes`, 0.14.0) implements every
input above (same defaults) and was run against the go-bacnet server with all
four files: `server-baseline-v1` 23 of 23 pass, `server-services-v1` 36 of
36, `server-bbmd-v1` 5 of 5, `server-extended-v1` 20 pass and the 3
`scovpm` scenarios `unsupported` (no SubscribeCOVPropertyMultiple APDU).
Against the bacnet-stack device image all 23 scenarios of
`server-baseline-v1` pass, every emitted line of that run validates against
the result-line schema, and a device instance that does not exist gives
`infra-error`.

bacnet-js client mode implements every input above and runs all four
scenario files against the go-bacnet server: `server-baseline-v1` 21 pass and
2 `known-difference`, `server-services-v1` 29 pass, 5 `unsupported` and 2
`not-tested`, `server-bbmd-v1` 2 pass and 3 `unsupported`,
`server-extended-v1` 13 pass, 9 `unsupported` and 1 `not-tested` (reasons in
PEER_SUPPORT.md and adapters/bacnet-js/README.md). Against the bacnet-stack
device image `server-baseline-v1` gives 21 pass and the same 2
`known-difference`, every emitted line validates against the result-line
schema, and a device instance that does not exist gives `infra-error`.
