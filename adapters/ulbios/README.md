# ulbios adapter

BACnet/IP device and client peer built on
[`github.com/ulbios/bacnet`](https://github.com/ulbios/bacnet), a small MIT
Go library (itself started from kazukiigeta/bacnet). Upstream publishes no
tags or releases; the pin is commit `227d62272ce9cedcfe47c1621a8cb4e0d2470ee0`
(2023-09-10, the default branch), the pseudo-version
`v0.0.0-20230910233229-227d62272ce9` in [`go.mod`](go.mod) with
[`go.sum`](go.sum), the source of truth. The Dockerfile ARG `ULBIOS_COMMIT`
and [versions.yaml](../../versions.yaml) repeat it;
`scripts/check-versions.py` cross-checks them. The binary links ulbios only
(its go.mod also names cobra, pflag, mousetrap and go-cmp, for its examples
and tests).

The library is independent of go-bacnet and of the other peers here. It is
old and small, which is why it is here: it shows how go-bacnet copes with a
peer that encodes and decodes little, and some of it differently.

**Do not import `go-bacnet`.** Assertions live in `go-bacnet/interop`.

## What ulbios can do

From the source at the pin:

| Part | Upstream | Can | Cannot |
|---|---|---|---|
| BVLC | `plumbing/bvlc.go` | Original-Unicast-NPDU (0x0a), Original-Broadcast-NPDU (0x0b) | any other function (no Forwarded-NPDU, no BVLC-Result, no foreign device, no BBMD); the type and length octets are not checked |
| NPDU | `plumbing/npdu.go` | version, control, DNET with DLEN and hop count | DADR octets (DLEN must be 0, the global broadcast), SNET/SADR, network-layer messages |
| APDU | `plumbing/apdu.go` | Confirmed-Request, Unconfirmed-Request, Simple-ACK, Complex-ACK, Error | Segment-ACK, Reject, Abort, segmentation; the max-APDU octet of a request is skipped; the SEG bit is dropped (`b[0] & 0x7`) |
| Tags | `objects/` | one-octet tags with a length of 0–4 (`b & 0x7`); opening and closing tag 3 (dropped when parsing) | extended tag numbers, extended length (5–7), other opening and closing tags |
| Parse | `parsing.go` | Who-Is, I-Am, ReadProperty, WriteProperty, Simple-ACK, Complex-ACK, Error | everything else (`ErrNotImplemented`); no bounds checks, so some input panics |
| Encoders | `encoding.go`, `services/` | `NewWhois` (no range), `NewIAm`, `NewReadProperty`, `NewWriteProperty` (REAL), `NewCACK` (REAL), `NewSACK`, `NewError` | other services, Reject, Abort |
| Values | `objects/primitive.go`, `oid.go` | REAL, NULL (encode), Enumerated (one octet), Unsigned (two octets), object identifier, property identifier (one octet), priority | Boolean, Signed, Double, strings, bit strings, dates, times, constructed values |

Upstream defects the adapter meets (at the pin):

- `objects.DecObjectIdentifier` computes the type as
  `(v & 0xFFC00000) >> 20`, so it returns the object type shifted left by
  two (analog-value,1 decodes as device,1).
- `services.IAmObjects` ignores its instance argument and always encodes
  device 321; `bacnet.NewIAm(id, vendor)` therefore announces device 321.
- `objects.DecNull` checks the tag number against `TagReal` and refuses every
  NULL.
- `ConfirmedWriteProperty.Decode` accepts exactly five tokens, the shape of
  ulbios' own request (a REAL followed by a NULL inside the value, then the
  priority: `services.ConfirmedWritePropertyObjects`), and refuses a request
  with one value, with or without a priority.
- `bacnet.NewCACK`, `NewSACK`, `NewError`, `NewReadProperty` and
  `NewWriteProperty` fix the invoke ID to 1.
- `ComplexACK.UnmarshalBinary` refuses an APDU shorter than 17 octets, the
  length of its own REAL ReadProperty-ACK; an ACK of an Enumerated or a
  Boolean is "too short".
- `DecUnisgnedInteger` and `DecEnumerated` lose the high octet of a
  three-octet value (`uint16` truncation).
- `objects.EncUnsignedInteger16` always encodes two octets (clause 20.2.4
  asks for the fewest).

## Device mode (default)

The adapter loads the fixture (`DEVICE_FIXTURE_FILE`, default
`device-baseline-v2`), listens on `0.0.0.0:47808` (`BACNET_IP_PORT`) and writes
the ready event. Every datagram is decoded by `bacnet.Parse` and every
answer encoded with ulbios' `services` and `objects` types. Adapter code
(`adapter-shim` in [inventory.yaml](../inventory.yaml)):

- **Framing checks** ulbios does not make: BVLC type 0x81, functions 0x0a and
  0x0b only, NPDU version 1, no network-layer message, no SNET, DNET only
  with DLEN 0, no segmented request. Anything else is ignored.
- **Segmented-response-accepted:** `bacnet.Parse` identifies a
  Confirmed-Request by its whole first octet (`combine(b[offset], b[offset+3])`
  in `parsing.go`), so a request with the SA bit (0x02, clause 20.1.2.4)
  set, as go-bacnet and BACnet4J send by default, is `ErrNotImplemented`.
  The adapter clears the bit in a copy before parsing; the answer is never
  segmented anyway. `ULBIOS_KEEP_SA=1` passes the octet unchanged, to show
  ulbios' own behaviour (go-bacnet `TestUlbiosSegmentedResponseAcceptedBit`).
- **Object model:** the fixture objects with the properties ulbios can
  encode: every object Object_Identifier and Object_Type; the Device
  Object_List (whole, no index), Vendor_Identifier 999,
  Max_APDU_Length_Accepted 1024 and Segmentation_Supported no-segmentation
  (ulbios' `DEFAULT_ACCEPTED_SIZE` and `DEFAULT_SEGMENTATION_SUPPORT`),
  Protocol_Version 1, System_Status operational; Analog and Binary Values
  Present_Value, Event_State normal, Units no-units (analog), and, as
  commandable objects, Priority_Array and Relinquish_Default. There is no
  Object_Name, Status_Flags, Out_Of_Service or Description: ulbios has no
  character-string, bit-string or boolean encoder, so reading them is
  Error property/unknown-property.
- **Dispatch:** Who-Is (the range limits are read from ulbios' tokens),
  ReadProperty (`ConfirmedReadProperty.Decode`, object type shifted back by
  two), WriteProperty (`ConfirmedWriteProperty.Decode` for ulbios' own
  five-token form; for a standard request with one value and an optional
  priority the adapter assigns the tokens and decodes each with
  `objects.Dec*`). The invoke ID of the request is echoed.
- **I-Am:** a unicast Who-Is gets a unicast I-Am (BVLC 0x0a), a broadcast one
  ulbios' own broadcast I-Am (BVLC 0x0b, NPDU DNET 0xFFFF, hop count 255)
  to the local broadcast address; both built like `bacnet.NewIAm` with the
  token of the fixture's device instance in place of device 321.
- **Errors** (clause 15.5 and 15.9): object/unknown-object,
  property/unknown-property, property/write-access-denied (any property
  other than Present_Value), property/invalid-data-type,
  property/value-out-of-range (a binary value above 1).
- **Writes** go to the priority array (priority 16 when the request has
  none); Present_Value is the highest non-NULL slot or Relinquish_Default.
  Each applied write is an `{"event":"operation","operation":"write-property","result":"applied",…}`
  line naming the decoder (`ulbios` or `adapter-shim`).

What the device does not answer: ulbios has no Reject or Abort encoder
(`plumbing.APDU.MarshalTo` has no case for PDU types 6 and 7), so a confirmed
request it cannot decode or answer gets no reply; the client's APDU timer
expires. Clause 18.8 would have a Reject (unrecognized-service for an unknown
service, invalid-tag or missing-required-parameter for what it cannot
decode) and clause 5.4.5 an Abort segmentation-not-supported for a segmented
request or a too long answer. Each such request is reported as
`{"event":"operation","operation":"unanswered","result":"no-reply","service":<choice>,"reason":…}`.
That covers: every service other than ReadProperty and WriteProperty; a
ReadProperty with an array index or a property identifier above 255; a
WriteProperty of NULL (relinquish), of a type with no ulbios decoder, with
an array index or with a priority outside 1..16; segmented requests; and an
answer longer than the client accepts.

## Client mode

`client` as the first argument runs the client-driver contract
([docs/CLIENT_DRIVER_CONTRACT.md](../../docs/CLIENT_DRIVER_CONTRACT.md)) with
every input it defines. The socket is bound to UDP 47808, so broadcast I-Am
answers arrive. `BACNET_CLIENT_TIMEOUT_MS` (default 3000) and
`BACNET_CLIENT_RETRIES` (default 1) set the APDU timeout and retries, which
are adapter code: ulbios has no transaction layer.

| Scenario | Request | Answer decoded with |
|---|---|---|
| `who-is` without limits | `bacnet.NewWhois`, to `--broadcast` or the local broadcast address | `UnconfirmedIAm.Decode` |
| `read-property` | `bacnet.NewReadProperty` (invoke ID 1) | `ComplexACK.Decode` (REAL), `objects.DecEnumerated`, `DecUnisgnedInteger`, `DecObjectIdentifier`; `Error.Decode` |
| `write-property`, REAL without priority or at 16 | `bacnet.NewWriteProperty` (REAL, then NULL, priority 16) | `SimpleACK`, `Error.Decode` |
| `write-property`, other priority, NULL or Enumerated | assembled from `objects.Enc*` (adapter-shim) | as above |

Everything else is `unsupported`: a ranged Who-Is, a property identifier
above 255, an array index, a character-string value, and every other
service. `--bbmd` is accepted and not used (ulbios cannot register as a
foreign device). An answer ulbios cannot decode, or decodes wrongly, is
`known-difference` with the answer's octets and the reason
(PEER_SUPPORT.md, ulbios): `ulbios-short-complex-ack`, `ulbios-no-decoder`,
`ulbios-object-identifier-type`, `ulbios-no-reject-abort`, and
`ulbios-write-real-null`: a device answers property/invalid-data-type to
`bacnet.NewWriteProperty`, whose value [3] holds a REAL followed by a NULL
(clause 15.9.1.1.3 has one value; bacnet-stack and BACnet4J acknowledge it,
BACpypes3 sends Reject invalid-tag, the go-bacnet server the Error). Any
other failure to decode is `fail`.

## Environment

| Variable | Mode | Default | Effect |
|---|---|---|---|
| `DEVICE_FIXTURE_FILE`, `FIXTURE` | device | v2 | the fixture (v1–v9 are in the image) |
| `BACNET_IP_PORT` | device | 47808 | UDP port |
| `BACNET_CLIENT_TIMEOUT_MS` | client | 3000 | APDU timeout |
| `BACNET_CLIENT_RETRIES` | client | 1 | retries after a timeout |
| `ULBIOS_KEEP_SA` | device | unset | `1`: do not clear segmented-response-accepted before `bacnet.Parse` |
| `ADAPTER_VERSION` | both | build arg | the `version` of the ready line |

## Not in scope

MS/TP and BACnet/IPv6: ulbios has BACnet/IP only (upstream README).
