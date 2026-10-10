# Open work

Nothing is blocking. What is recorded here is known, accepted
and not an adapter defect unless it says so. Peer behaviour is documented in
[PEER_SUPPORT.md](PEER_SUPPORT.md); the forward plan is [PLAN.md](PLAN.md).

## Limits of the peers

- **bacnet-stack** answers a BVLC Write-BDT with a NAK at Protocol_Revision
  ≥ 17, and refuses DeviceCommunicationControl "disable" (removed from the
  standard at revision 20). Both are asserted by go-bacnet.
- **BACpypes3 0.0.110** answers a BVLC Write-BDT with NAK 0x0010, and its
  DeviceCommunicationControl never takes effect: the mixin writes to an
  attribute `Application` does not have (the adapter aliases it) and compares
  the decoded enumeration with strings (not corrected: it is the stack's
  behaviour).
- **Worldiety:** no peer-as-BBMD and no router through the adapter;
  continuation segments omit the service choice.
- **System.IO.BACnet 4.0.0:** a ReadPropertyMultiple reply that would contain
  an empty list is aborted; GetAlarmSummary is rejected by the package before
  a handler can run; see the adapter README for the rest.
- **BACnet4J 6.1.1** throws while decoding a WritePropertyMultiple that
  carries a value of the wrong datatype and answers with error-choice 127;
  it accepts a write to a property the object does not have.
- **No stable stack** has the audit services, AuthRequest, or a handler for
  SubscribeCOVPropertyMultiple or VT. What exists is codec evidence.
- **bacnet-stack-router** does not decrement the hop count and, for an unknown
  network, broadcasts a Who-Is-Router-To-Network that is not a valid NPDU.

## Limits of the fixtures

- `fixtures/topology/topology-v2.json` and `fixtures/bbmd/bbmd-v2.json` mark
  Worldiety as pending, and refer to blocker identifiers ("B5") from an
  earlier version of this file. The statement is still true; the identifiers
  no longer exist.
- `device-baseline-v9` is built into the bacnet-stack image only.
- `device-baseline-v7` contains an `audit-log` object no peer serves.

## Build

- `adapters/bacnet-stack/Dockerfile` and
  `adapters/bacnet-stack-router/Dockerfile` pin the same bacnet-stack commit
  in two places; move them together.
- `adapters/worldiety/Dockerfile` uses `golang:1.26-bookworm` and
  `scripts/smoke-test.sh` uses `python:3.12-alpine` without a digest; every
  other base image is pinned by digest.
