#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""BACpypes3 client mode (docs/CLIENT_DRIVER_CONTRACT.md).

Runs one upstream BACpypes3 Application, unmodified, as a client against a
device under test (DUT) and turns what BACpypes3 decoded into result lines.
Every request is an upstream BACpypes3 APDU class sent with
Application.request(), or one of the Application's own client helpers
(who_is, who_has, read_property_multiple, read_range); every answer is
decoded by BACpypes3. The adapter only builds the requests from the scenario
file and compares the decoded answers with the expectation.

The Application binds to the DUT by a unicast Who-Is to --target before the
first confirmed request, so that BACpypes3 knows the DUT's maximum APDU
length and segmentation; a DUT that does not answer is infra-error. With
--bbmd the Application's network port is a foreign device (upstream
IPMode.foreign) that registers with the BBMD before the first scenario; the
BVLC table services (Read-BDT, Read-FDT, Write-BDT) are sent from a second,
unregistered upstream normal-mode link layer with BACpypes3's
BVLLServiceElement, because in foreign mode BACpypes3 0.0.110 consumes every
BVLC-Result as its own registration result (PEER_SUPPORT.md).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import datetime as dt
import json
import math
import os
import re
import socket
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from bacpypes3.apdu import (
    APCISequence,
    AbortPDU,
    AbortReason,
    AcknowledgeAlarmRequest,
    AddListElementRequest,
    AtomicReadFileACK,
    AtomicReadFileRequest,
    AtomicWriteFileRequest,
    ConfirmedPrivateTransferACK,
    ConfirmedPrivateTransferRequest,
    ConfirmedTextMessageRequest,
    CreateObjectACK,
    CreateObjectRequest,
    DeleteObjectRequest,
    DeviceCommunicationControlRequest,
    ComplexAckPDU,
    ErrorPDU,
    ErrorRejectAbortNack,
    GetAlarmSummaryACK,
    GetAlarmSummaryRequest,
    GetEnrollmentSummaryACK,
    GetEnrollmentSummaryRequest,
    GetEventInformationACK,
    GetEventInformationRequest,
    ReadPropertyACK,
    ReadPropertyRequest,
    ReadRangeACK,
    ReadRangeRequest,
    ReinitializeDeviceRequest,
    RejectPDU,
    RejectReason,
    RemoveListElementRequest,
    SimpleAckPDU,
    SubscribeCOVPropertyRequest,
    SubscribeCOVRequest,
    TimeSynchronizationRequest,
    UnconfirmedPrivateTransferRequest,
    UnconfirmedTextMessageRequest,
    UTCTimeSynchronizationRequest,
    WhoIsRequest,
    WriteGroupRequest,
    WritePropertyMultipleRequest,
    WritePropertyRequest,
)
from bacpypes3.app import Application
from bacpypes3.basetypes import (
    AtomicReadFileRequestAccessMethodChoice,
    AtomicReadFileRequestAccessMethodChoiceStreamAccess,
    AtomicWriteFileRequestAccessMethodChoice,
    AtomicWriteFileRequestAccessMethodChoiceStreamAccess,
    ChannelValue,
    CreateObjectRequestObjectSpecifier,
    DateTime,
    DaysOfWeek,
    Destination,
    DeviceCommunicationControlRequestEnableDisable,
    EventState,
    GetEnrollmentSummaryRequestAcknowledgmentFilterType,
    GetEnrollmentSummaryRequestEventStateFilterType,
    EventTransitionBits,
    GroupChannelValue,
    PropertyValue,
    Range,
    RangeByPosition,
    RangeBySequenceNumber,
    Recipient,
    ReinitializeDeviceRequestReinitializedStateOfDevice,
    TimeStamp,
    WriteAccessSpecification,
)
from bacpypes3.constructeddata import Any as AnyValue
from bacpypes3.constructeddata import Array, ListOf, SequenceOf
from bacpypes3.ipv4.bvll import Result as BVLLResult
from bacpypes3.ipv4.link import NormalLinkLayer
from bacpypes3.ipv4.service import BVLLServiceElement
from bacpypes3.comm import bind
from bacpypes3.pdu import Address, GlobalBroadcast, IPv4Address
from bacpypes3.primitivedata import (
    Atomic,
    BitString,
    Boolean,
    CharacterString,
    Date,
    Double,
    Enumerated,
    Integer,
    Null,
    ObjectIdentifier,
    OctetString,
    PropertyIdentifier,
    Real,
    TagClass,
    TagList,
    Time,
    Unsigned,
)
from bacpypes3.vendor import get_vendor_info

ADAPTER = "bacpypes3"
OUTCOMES = ("pass", "fail", "unsupported", "not-tested", "known-difference", "infra-error")
CLIENT_INSTANCE = 4001  # the client's own device instance; not in any scenario range
CLIENT_PORT = 47808
BVLC_PORT = 47809  # the unregistered link layer for the BVLC table services
FILE_CHUNK = 480  # AtomicReadFile requested-octet-count per request

BVLC_RESULTS = {
    0x0000: "successful-completion",
    0x0010: "write-bdt-nak",
    0x0020: "read-bdt-nak",
    0x0030: "register-fd-nak",
    0x0040: "read-fdt-nak",
    0x0050: "delete-fdt-nak",
    0x0060: "distribute-broadcast-nak",
}
TIME_STAMP_INDEX = {"offnormal": 1, "high-limit": 1, "low-limit": 1, "fault": 2, "normal": 3}
TRANSITIONS = ("to-offnormal", "to-fault", "to-normal")


class Infra(Exception):
    """The scenario could not be run (no binding, no answer, socket error)."""


class Unsupported(Exception):
    """BACpypes3 at the pin cannot issue the request (never a pass)."""


class KnownDifference(Exception):
    """A recorded upstream deviation (PEER_SUPPORT.md) hides the result."""


class Undecodable(Exception):
    """The DUT answered, but BACpypes3 could not decode the answer."""

    def __init__(self, pdu_type: int, service: int, octets: str, error: str) -> None:
        super().__init__(f"BACpypes3 could not decode the answer (PDU type {pdu_type}, service {service}, "
                         f"{error}): '{octets}'")
        self.pdu_type = pdu_type
        self.service = service
        self.octets = octets
        self.error = error


# Answers BACpypes3 0.0.110 cannot decode, by (PDU type, service choice);
# the ApplicationServiceAccessPoint drops them and the request times out
# (PEER_SUPPORT.md):
# - the Error of AddListElement (8) and RemoveListElement (9): its
#   ChangeListError has no service_choice, so ErrorSequence.__init__ raises
#   AttributeError;
# - the Error of SubscribeCOVProperty (28): 28 is not in BACpypes3's
#   error_types, so the decoder raises "unrecognized service choice";
# - an empty GetAlarmSummary-ACK (3) or GetEnrollmentSummary-ACK (4): the
#   list is a required element of the Sequence, and an empty SEQUENCE OF
#   has no octets to decode it from.
CHANGE_LIST = "BACpypes3 0.0.110 cannot decode the ChangeList-Error the device answered (ChangeListError has no service_choice)"
KNOWN_UNDECODABLE = {
    (5, 8): CHANGE_LIST,
    (5, 9): CHANGE_LIST,
    (5, 28): "BACpypes3 0.0.110 cannot decode an Error of SubscribeCOVProperty (service choice 28 is not in its error_types)",
    (3, 3): "BACpypes3 0.0.110 cannot decode an empty GetAlarmSummary-ACK (listOfAlarmSummaries is a required element)",
    (3, 4): "BACpypes3 0.0.110 cannot decode an empty GetEnrollmentSummary-ACK (listOfEnrollmentSummaries is a required element)",
}


# --- the Application -------------------------------------------------------


class ClientApplication(Application):
    """Stock Application; incoming notifications are recorded for scenarios.

    Upstream's COV handlers deliver notifications only to its subscription
    context manager, which cancels the subscription when it exits; a scenario
    leaves the subscription to the DUT (a later scenario cancels it), so the
    adapter records the decoded notifications itself and acknowledges the
    confirmed ones with a SimpleACK, as upstream does.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.cov_notifications: list[tuple[Any, int, Any]] = []
        self.i_ams: list[Any] = []
        # (source, invoke ID) -> Undecodable, for answers BACpypes3 dropped.
        self.undecodable: dict[tuple[str, int], Undecodable] = {}

    def observe_answers(self) -> None:
        """Record answers the ApplicationServiceAccessPoint cannot decode.

        BACpypes3 drops an Error or ComplexACK it cannot decode and the
        request then times out. The wrapper decodes a copy of each with the
        same upstream APCISequence.decode first, records a failure with the
        octets, and hands the original on unchanged, so a dropped answer is
        told apart from no answer.
        """
        asap = self.asap
        upstream = asap.sap_response

        async def sap_response(apdu: Any) -> None:
            if isinstance(apdu, (ErrorPDU, ComplexAckPDU)) and not isinstance(apdu, APCISequence):
                octets = bytes(apdu.pduData)
                probe = type(apdu)()
                probe.update(apdu)
                probe.put_data(octets)
                try:
                    APCISequence.decode(probe)
                except Exception as err:  # noqa: BLE001 - recorded, not handled
                    self.undecodable[(hostport(apdu.pduSource), int(apdu.apduInvokeID))] = Undecodable(
                        int(apdu.apduType), int(apdu.apduService), octets.hex(), f"{type(err).__name__}: {err}")
            await upstream(apdu)

        asap.sap_response = sap_response

    async def do_UnconfirmedCOVNotificationRequest(self, apdu: Any) -> None:
        self.cov_notifications.append((apdu.pduSource, int(apdu.subscriberProcessIdentifier),
                                       apdu.monitoredObjectIdentifier, list(apdu.listOfValues or [])))

    async def do_ConfirmedCOVNotificationRequest(self, apdu: Any) -> None:
        self.cov_notifications.append((apdu.pduSource, int(apdu.subscriberProcessIdentifier),
                                       apdu.monitoredObjectIdentifier, list(apdu.listOfValues or [])))
        await self.response(SimpleAckPDU(context=apdu))

    async def do_IAmRequest(self, apdu: Any) -> None:
        self.i_ams.append(apdu)
        await super().do_IAmRequest(apdu)


# --- network helpers -------------------------------------------------------


def split_hostport(s: str) -> tuple[str, int]:
    host, _, port = s.rpartition(":")
    return host, int(port)


def local_ipv4(towards: str) -> str:
    """This container's address on the route towards HOST:PORT."""
    host, port = split_hostport(towards)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((host, port))
        return s.getsockname()[0]


def interface_prefix(ip: str) -> int | None:
    """Prefix length of the local IPv4 subnet that holds ip, or None."""
    import fcntl
    import struct

    siocgifaddr, siocgifnetmask = 0x8915, 0x891B
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _, name in socket.if_nameindex():
            ifreq = struct.pack("256s", name.encode()[:15])
            try:
                addr = socket.inet_ntoa(fcntl.ioctl(probe.fileno(), siocgifaddr, ifreq)[20:24])
                if addr != ip:
                    continue
                mask = fcntl.ioctl(probe.fileno(), siocgifnetmask, ifreq)[20:24]
            except OSError:
                continue
            return bin(int.from_bytes(mask, "big")).count("1")
    finally:
        probe.close()
    return None


def hostport(addr: Any) -> str:
    """HOST:PORT of a BACpypes3 Address or IPv4Address."""
    t = getattr(addr, "addrTuple", None)
    if t:
        return f"{t[0]}:{t[1]}"
    return str(addr)


# --- values ----------------------------------------------------------------


def scenario_value(v: dict[str, Any]) -> Atomic:
    """A scenario value as the BACpypes3 primitive that encodes it."""
    t = v["type"]
    if t == "null":
        return Null(())
    if t == "boolean":
        return Boolean(bool(v["value"]))
    if t == "unsigned":
        return Unsigned(int(v["value"]))
    if t == "signed":
        return Integer(int(v["value"]))
    if t == "real":
        return Real(float(v["value"]))
    if t == "character-string":
        return CharacterString(str(v["value"]))
    if t == "enumerated":
        return Enumerated(int(v["value"]))
    if t == "object-identifier":
        return ObjectIdentifier(v["value"])
    raise Infra(f"value type {t} is not encoded by this driver")


def any_of(*values: Any) -> AnyValue:
    """An Any holding the application-tagged encoding of values, in order."""
    tags = TagList()
    for v in values:
        tags.extend(v.encode())
    return AnyValue(tags)


def observed_value(v: Any) -> dict[str, Any]:
    """A decoded BACpypes3 value as a scenario value."""
    if isinstance(v, Null):
        return {"type": "null"}
    if isinstance(v, Boolean):
        return {"type": "boolean", "value": bool(v)}
    if isinstance(v, Enumerated):
        name = str(v)
        return {"type": "enumerated", "value": int(v) if name.isdigit() else name}
    if isinstance(v, Unsigned):
        return {"type": "unsigned", "value": int(v)}
    if isinstance(v, Integer):
        return {"type": "signed", "value": int(v)}
    if isinstance(v, (Real, Double)):
        return {"type": "real", "value": float(v)}
    if isinstance(v, CharacterString):
        return {"type": "character-string", "value": str(v)}
    if isinstance(v, ObjectIdentifier):
        return {"type": "object-identifier", "value": f"{v[0]},{v[1]}"}
    if isinstance(v, OctetString):
        return {"type": "octet-string", "value": bytes(v).hex()}
    if isinstance(v, BitString):
        return {"type": "bit-string", "value": [int(b) for b in v]}
    if isinstance(v, (list, tuple)) and not isinstance(v, Atomic):
        return {"type": "list", "value": [observed_value(x) for x in v]}
    return {"type": "text", "value": str(v)}


def generic_values(any_value: AnyValue) -> list[Any]:
    """The application-tagged primitives of an Any, decoded by BACpypes3."""
    out = []
    for tag in any_value.tagList or []:
        if tag.tag_class == TagClass.application:
            out.append(tag.app_to_object())
        else:
            raise ValueError("context-tagged content")
    return out


def property_type(objid: ObjectIdentifier, prop: Any, array_index: int | None) -> type | None:
    """The datatype BACpypes3's object model gives the property, or None."""
    cls = get_vendor_info(0).get_object_class(objid[0])
    if cls is None:
        return None
    ptype = cls.get_property_type(prop)
    if ptype is None:
        return None
    if issubclass(ptype, Array) and array_index is not None:
        ptype = Unsigned if array_index == 0 else ptype._subtype
    return ptype


def decode_property(objid: ObjectIdentifier, prop: Any, array_index: int | None, value: AnyValue) -> Any:
    ptype = property_type(objid, prop, array_index)
    if ptype is not None:
        try:
            return value.cast_out(ptype, null=issubclass(ptype, Atomic))
        except Exception:  # noqa: BLE001 - fall back to the generic decoding
            pass
    vals = generic_values(value)
    return vals[0] if len(vals) == 1 else vals


def same_value(got: dict[str, Any], want: dict[str, Any]) -> bool:
    if got.get("type") != want.get("type"):
        return False
    gv, wv = got.get("value"), want.get("value")
    if want["type"] == "real" and isinstance(gv, float) and isinstance(wv, (int, float)):
        return math.isclose(gv, float(wv), rel_tol=1e-6, abs_tol=1e-6)
    return gv == wv


def time_text(t: Time) -> str:
    h, m, s, hh = tuple(t)
    return f"{h}:{m:02d}:{s:02d}.{hh:02d}"


def datetime_text(d: Date, t: Time) -> str:
    y, mo, day, _ = tuple(d)
    h, m, s, _ = tuple(t)
    return f"{y + 1900:04d}-{mo:02d}-{day:02d}T{h:02d}:{m:02d}:{s:02d}"


def bacnet_datetime(when: dt.datetime) -> DateTime:
    return DateTime(date=Date((when.year - 1900, when.month, when.day, when.isoweekday())),
                    time=Time((when.hour, when.minute, when.second, when.microsecond // 10000)))


def destination(d: dict[str, Any]) -> Destination:
    if "device" not in d["recipient"]:
        raise Infra("only device recipients are encoded by this driver")
    days = [0] * 7
    for x in d["valid_days"]:
        days[x - 1] = 1
    transitions = [1 if name in d["transitions"] else 0 for name in TRANSITIONS]
    return Destination(
        validDays=DaysOfWeek(days),
        fromTime=Time(d["from_time"]),
        toTime=Time(d["to_time"]),
        recipient=Recipient(device=ObjectIdentifier(("device", d["recipient"]["device"]))),
        processIdentifier=d["process_id"],
        issueConfirmedNotifications=d["confirmed"],
        transitions=EventTransitionBits(transitions),
    )


def observed_destination(d: Destination) -> dict[str, Any]:
    rec: dict[str, Any] = {}
    if d.recipient.device is not None:
        rec["device"] = int(d.recipient.device[1])
    else:
        rec["address"] = str(d.recipient.address)
    return {
        "valid_days": [i + 1 for i, b in enumerate(d.validDays) if b],
        "from_time": time_text(d.fromTime),
        "to_time": time_text(d.toTime),
        "recipient": rec,
        "process_id": int(d.processIdentifier),
        "confirmed": bool(d.issueConfirmedNotifications),
        "transitions": [TRANSITIONS[i] for i, b in enumerate(d.transitions) if b and i < len(TRANSITIONS)],
    }


# --- the environment -------------------------------------------------------


class Env:
    """What every scenario needs: the Application, the target and the timing."""

    def __init__(self, args: argparse.Namespace, timeout_ms: int, retries: int) -> None:
        self.args = args
        self.target = Address(args.target) if args.target else None
        self.device = args.device
        self.timeout_ms = timeout_ms
        self.retries = retries
        # How long a request may take with all its retries.
        self.request_s = timeout_ms / 1000 * (retries + 1) + 2
        # How long to collect unconfirmed answers (I-Am, I-Have).
        self.listen_s = max(2.0, timeout_ms / 1000)
        self.app: ClientApplication | None = None
        self.bound = False
        self.bind_detail = ""
        self.my_ip = ""
        self.bvlc: BVLLServiceElement | None = None
        self.bvlc_link: NormalLinkLayer | None = None

    async def start(self) -> None:
        towards = self.args.bbmd or self.args.target or self.args.broadcast or "192.0.2.1:47808"
        self.my_ip = local_ipv4(towards)
        if self.args.bbmd:
            address = f"{self.my_ip}:{CLIENT_PORT}"
        else:
            prefix = interface_prefix(self.my_ip) or 16
            address = f"{self.my_ip}/{prefix}:{CLIENT_PORT}"
        ns = argparse.Namespace(
            name=f"bacpypes3-client-{CLIENT_INSTANCE}",
            instance=CLIENT_INSTANCE,
            network=0,
            address=address,
            vendoridentifier=999,
            foreign=self.args.bbmd or None,
            ttl=self.args.fd_ttl,
            bbmd=None,
        )
        self.app = ClientApplication.from_args(ns)
        dev = self.app.device_object
        dev.apduTimeout = self.timeout_ms
        dev.numberOfApduRetries = self.retries
        self.app.observe_answers()
        if self.args.bbmd:
            await self.wait_registered()

    async def wait_registered(self) -> None:
        link = next(iter(self.app.link_layers.values()))
        deadline = time.monotonic() + self.request_s + 5
        while time.monotonic() < deadline:
            status = link.bbmdRegistrationStatus
            if status == 0:
                return
            if status > 0:
                raise Infra(f"Register-Foreign-Device answered with BVLC-Result 0x{status:04x}")
            await asyncio.sleep(0.1)
        raise Infra("no BVLC-Result for Register-Foreign-Device")

    async def bind_target(self) -> None:
        """Unicast Who-Is to the target: BACpypes3 caches its I-Am."""
        if self.bound:
            return
        if self.target is None:
            raise Infra("--target is required for confirmed services")
        if self.bind_detail:
            raise Infra(self.bind_detail)
        found = await self.app.who_is(self.device, self.device, self.target, timeout=self.request_s)
        if not found:
            self.bind_detail = f"device {self.device} did not answer a Who-Is to {self.args.target}"
            raise Infra(self.bind_detail)
        src = hostport(found[0].pduSource)
        if src != self.args.target:
            self.bind_detail = f"I-Am for device {self.device} from {src}, not the target {self.args.target}"
            raise Infra(self.bind_detail)
        self.bound = True

    async def confirmed(self, apdu: Any) -> Any:
        """Send a confirmed request to the target; the ACK, or the Error,
        Reject or Abort as an exception."""
        await self.bind_target()
        apdu.pduDestination = self.target
        future = self.app.request(apdu)
        key = (self.args.target, int(apdu.apduInvokeID))
        self.app.undecodable.pop(key, None)
        deadline = time.monotonic() + self.request_s + 5
        while not future.done():
            # A dropped answer never completes the future: stop waiting.
            u = self.app.undecodable.pop(key, None)
            if u is not None:
                future.cancel()
                raise u
            if time.monotonic() >= deadline:
                future.cancel()
                raise Infra("no answer within the APDU timeout and retries")
            await asyncio.wait({future}, timeout=0.05)
        return future.result()

    async def unconfirmed(self, apdu: Any) -> None:
        if apdu.pduDestination is None:
            await self.bind_target()
            apdu.pduDestination = self.target
        await self.app.request(apdu)
        # Let the send task run before the next scenario.
        await asyncio.sleep(0.2)

    def bvlc_ase(self) -> BVLLServiceElement:
        if self.bvlc is None:
            self.bvlc_link = NormalLinkLayer(IPv4Address(f"{self.my_ip}:{BVLC_PORT}"))
            self.bvlc = BVLLServiceElement()
            bind(self.bvlc, self.bvlc_link)
        return self.bvlc

    def bbmd_address(self) -> IPv4Address:
        return IPv4Address(self.args.bbmd or self.args.target)

    def close(self) -> None:
        if self.bvlc_link is not None:
            self.bvlc_link.close()
        if self.app is not None:
            self.app.close()


def answer(exc: BaseException) -> dict[str, Any]:
    """An Error, Reject or Abort decoded by BACpypes3, as an observation."""
    if isinstance(exc, RejectPDU):
        return {"reject": str(RejectReason(exc.apduAbortRejectReason))}
    if isinstance(exc, AbortPDU):
        reason = AbortReason(exc.apduAbortRejectReason)
        if int(reason) == int(AbortReason.noResponse):
            raise Infra("no answer within the APDU timeout and retries")
        return {"abort": str(reason)}
    if isinstance(exc, ErrorPDU):
        err_type = getattr(exc, "errorType", None)
        src = err_type if err_type is not None else exc
        err: dict[str, Any] = {"class": str(src.errorClass), "code": str(src.errorCode)}
        ff = getattr(exc, "firstFailedWriteAttempt", None)
        if ff is not None:
            err["first_failed"] = {"object": f"{ff.objectIdentifier[0]},{ff.objectIdentifier[1]}",
                                   "property": prop_name(ff.propertyIdentifier)}
        ffe = getattr(exc, "firstFailedElementNumber", None)
        if ffe is not None:
            err["first_failed_element"] = int(ffe)
        return {"error": err}
    raise Infra(f"unexpected answer {exc!r}")


def prop_name(p: Any) -> str | int:
    name = str(p)
    return int(name) if name.isdigit() else name


def prop_id(p: str | int) -> PropertyIdentifier:
    return PropertyIdentifier(p)


def objid(ref: str) -> ObjectIdentifier:
    return ObjectIdentifier(ref)


async def ack_or_answer(env: Env, apdu: Any) -> tuple[Any, dict[str, Any] | None]:
    try:
        return await env.confirmed(apdu), None
    except ErrorRejectAbortNack as exc:
        return None, answer(exc)


async def simple(env: Env, apdu: Any) -> dict[str, Any]:
    resp, a = await ack_or_answer(env, apdu)
    if a is not None:
        return a
    if isinstance(resp, SimpleAckPDU):
        return {"ack": True}
    raise Infra(f"unexpected answer {type(resp).__name__}")


# --- services ---------------------------------------------------------------


async def who_is(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    low, high = sc.get("low"), sc.get("high", sc.get("low"))
    env.app.i_ams.clear()
    if env.args.broadcast:
        req = WhoIsRequest(destination=Address(env.args.broadcast))
        if low is not None:
            req.deviceInstanceRangeLowLimit = low
            req.deviceInstanceRangeHighLimit = high
        await env.app.request(req)
        await asyncio.sleep(env.listen_s)
    else:
        await env.app.who_is(low, high, timeout=env.listen_s)
        # who_is resolves at the first matching I-Am of a single-device
        # range; give a second answer the chance to arrive.
        await asyncio.sleep(0.3)
    devices = []
    for apdu in env.app.i_ams:
        inst = int(apdu.iAmDeviceIdentifier[1])
        if inst == CLIENT_INSTANCE:
            continue
        if low is not None and not low <= inst <= high:
            continue
        src = hostport(apdu.pduSource)
        if env.args.target and src != env.args.target:
            raise Infra(f"I-Am for device {inst} from {src}, not the target {env.args.target}")
        if inst not in devices:
            devices.append(inst)
    return {"i-am": sorted(devices)}


async def who_has(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"timeout": env.listen_s}
    if "object" in sc:
        kwargs["object_identifier"] = objid(sc["object"])
    else:
        kwargs["object_name"] = CharacterString(sc["name"])
    found = await env.app.who_has(**kwargs)
    out = []
    for apdu in found or []:
        dev = int(apdu.deviceIdentifier[1])
        if dev == CLIENT_INSTANCE:
            continue
        entry = {"device": dev, "object": f"{apdu.objectIdentifier[0]},{apdu.objectIdentifier[1]}"}
        if entry not in out:
            out.append(entry)
    return {"i-have": out}


async def read_property(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    oid, pid = objid(sc["object"]), prop_id(sc["property"])
    req = ReadPropertyRequest(objectIdentifier=oid, propertyIdentifier=pid)
    if "array_index" in sc:
        req.propertyArrayIndex = sc["array_index"]
    resp, a = await ack_or_answer(env, req)
    if a is not None:
        return a
    if not isinstance(resp, ReadPropertyACK):
        raise Infra(f"unexpected answer {type(resp).__name__}")
    value = decode_property(oid, pid, sc.get("array_index"), resp.propertyValue)
    if "recipients" in sc["expect"]:
        if isinstance(value, list) and all(isinstance(d, Destination) for d in value):
            return {"recipients": [observed_destination(d) for d in value]}
        return {"value": observed_value(value)}
    return {"value": observed_value(value)}


async def read_property_multiple(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    await env.bind_target()
    params: list[Any] = []
    for r in sc["reads"]:
        params += [objid(r["object"]), [prop_id(p) for p in r["properties"]]]
    try:
        result = await asyncio.wait_for(
            env.app.read_property_multiple(env.target, params, vendor_info=get_vendor_info(0)),
            env.request_s + 5)
    except ErrorRejectAbortNack as exc:
        return answer(exc)
    except asyncio.TimeoutError as exc:
        raise Infra("no answer within the APDU timeout and retries") from exc
    if result is None:
        raise Infra("no ReadPropertyMultiple-ACK")
    values = []
    for oid, pid, _idx, value in result:
        entry: dict[str, Any] = {"object": f"{oid[0]},{oid[1]}", "property": prop_name(pid)}
        if value is not None and hasattr(value, "errorClass") and hasattr(value, "errorCode"):
            entry["error"] = {"class": str(value.errorClass), "code": str(value.errorCode)}
        elif value is None:
            entry["value"] = {"type": "text", "value": "-no property type-"}
        else:
            entry["value"] = observed_value(value)
        values.append(entry)
    return {"values": values}


def write_spec(w: dict[str, Any]) -> PropertyValue:
    pv = PropertyValue(propertyIdentifier=prop_id(w["property"]), value=any_of(scenario_value(w["value"])))
    if "priority" in w:
        pv.priority = w["priority"]
    return pv


async def write_property(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    req = WritePropertyRequest(objectIdentifier=objid(sc["object"]), propertyIdentifier=prop_id(sc["property"]),
                               propertyValue=any_of(scenario_value(sc["value"])))
    if "priority" in sc:
        req.priority = sc["priority"]
    if "array_index" in sc:
        req.propertyArrayIndex = sc["array_index"]
    return await simple(env, req)


async def write_property_multiple(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    specs: list[WriteAccessSpecification] = []
    for w in sc["writes"]:
        oid = objid(w["object"])
        if specs and specs[-1].objectIdentifier == oid:
            specs[-1].listOfProperties.append(write_spec(w))
        else:
            specs.append(WriteAccessSpecification(objectIdentifier=oid, listOfProperties=[write_spec(w)]))
    req = WritePropertyMultipleRequest(listOfWriteAccessSpecs=specs)
    return await simple(env, req)


async def wait_cov(env: Env, start: int, oid: ObjectIdentifier, pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        for src, proc, obj, _values in env.app.cov_notifications[start:]:
            if proc == pid and obj == oid and hostport(src) == env.args.target:
                return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.05)


async def subscribe_cov(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    oid = objid(sc["object"])
    req = SubscribeCOVRequest(subscriberProcessIdentifier=sc["process_id"], monitoredObjectIdentifier=oid)
    if not sc.get("cancel"):
        req.issueConfirmedNotifications = bool(sc.get("confirmed"))
        req.lifetime = sc.get("lifetime", 60)
    start = len(env.app.cov_notifications)
    resp, a = await ack_or_answer(env, req)
    if a is not None:
        return a
    if not isinstance(resp, SimpleAckPDU):
        raise Infra(f"unexpected answer {type(resp).__name__}")
    got = False
    if not sc.get("cancel"):
        got = await wait_cov(env, start, oid, sc["process_id"], env.listen_s)
    return {"subscribed": {"notification": got}}


async def subscribe_cov_property(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    oid = objid(sc["object"])
    # The request's PropertyReference element casts from a name, a number or
    # a (property, index) tuple only.
    prop = sc["property"]
    ref = (prop, sc["array_index"]) if "array_index" in sc else prop
    req = SubscribeCOVPropertyRequest(subscriberProcessIdentifier=sc["process_id"], monitoredObjectIdentifier=oid,
                                      monitoredPropertyIdentifier=ref)
    if not sc.get("cancel"):
        req.issueConfirmedNotifications = bool(sc.get("confirmed"))
        req.lifetime = sc.get("lifetime", 60)
        if "cov_increment" in sc:
            req.covIncrement = sc["cov_increment"]
    start = len(env.app.cov_notifications)
    resp, a = await ack_or_answer(env, req)
    if a is not None:
        return a
    if not isinstance(resp, SimpleAckPDU):
        raise Infra(f"unexpected answer {type(resp).__name__}")
    got = False
    if not sc.get("cancel"):
        got = await wait_cov(env, start, oid, sc["process_id"], env.listen_s)
    return {"subscribed": {"notification": got}}


async def subscribe_cov_property_multiple(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    raise Unsupported(
        "BACpypes3 0.0.110 has no SubscribeCOVPropertyMultiple request APDU and no "
        "ConfirmedCOVNotificationMultiple/UnconfirmedCOVNotificationMultiple type, so its "
        "Application cannot issue the request or decode the notification")


def observed_record(rec: Any) -> dict[str, Any]:
    datum = rec.logDatum
    for attr, typ in (("realValue", "real"), ("unsignedValue", "unsigned"), ("signedValue", "signed"),
                      ("booleanValue", "boolean"), ("enumValue", "enumerated"), ("nullValue", "null")):
        v = getattr(datum, attr, None)
        if v is not None:
            value = observed_value(v)
            value["type"] = typ
            break
    else:
        value = {"type": "text", "value": str(datum)}
    return {"timestamp": datetime_text(rec.timestamp.date, rec.timestamp.time), "value": value}


async def read_range(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    oid, pid = objid(sc["object"]), prop_id(sc["property"])
    req = ReadRangeRequest(objectIdentifier=oid, propertyIdentifier=pid)
    r = sc["range"]
    if r["by"] == "position":
        req.range = Range(byPosition=RangeByPosition(referenceIndex=r.get("index", 1), count=r.get("count", 1)))
    elif r["by"] == "sequence":
        req.range = Range(bySequenceNumber=RangeBySequenceNumber(referenceSequenceNumber=r.get("index", 1),
                                                                 count=r.get("count", 1)))
    resp, a = await ack_or_answer(env, req)
    if a is not None:
        return a
    if not isinstance(resp, ReadRangeACK):
        raise Infra(f"unexpected answer {type(resp).__name__}")
    ptype = property_type(oid, pid, None)
    if ptype is None:
        raise Infra(f"BACpypes3 has no datatype for {sc['object']} {sc['property']}")
    items = resp.itemData.cast_out(ptype)
    return {"records": [observed_record(rec) for rec in items]}


async def device_communication_control(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    req = DeviceCommunicationControlRequest(enableDisable=DeviceCommunicationControlRequestEnableDisable(sc["state"]))
    if "duration" in sc:
        req.timeDuration = sc["duration"]
    if "password" in sc:
        req.password = sc["password"]
    return await simple(env, req)


async def reinitialize_device(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    req = ReinitializeDeviceRequest(
        reinitializedStateOfDevice=ReinitializeDeviceRequestReinitializedStateOfDevice(sc["state"]))
    if "password" in sc:
        req.password = sc["password"]
    return await simple(env, req)


async def atomic_read_file(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    """Stream access from start; with count one request for count octets
    (its ACK may be segmented), without it requests of FILE_CHUNK octets
    until end-of-file."""
    data = b""
    pos = sc.get("start", 0)
    single = "count" in sc
    while True:
        req = AtomicReadFileRequest(
            fileIdentifier=objid(sc["object"]),
            accessMethod=AtomicReadFileRequestAccessMethodChoice(
                streamAccess=AtomicReadFileRequestAccessMethodChoiceStreamAccess(
                    fileStartPosition=pos, requestedOctetCount=sc["count"] if single else FILE_CHUNK)))
        resp, a = await ack_or_answer(env, req)
        if a is not None:
            return a
        if not isinstance(resp, AtomicReadFileACK) or resp.accessMethod.streamAccess is None:
            raise Infra(f"unexpected answer {type(resp).__name__}")
        chunk = bytes(resp.accessMethod.streamAccess.fileData)
        data += chunk
        pos += len(chunk)
        if single or resp.endOfFile or not chunk:
            break
    return {"octets_base64": base64.b64encode(data).decode()}


async def atomic_write_file(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    req = AtomicWriteFileRequest(
        fileIdentifier=objid(sc["object"]),
        accessMethod=AtomicWriteFileRequestAccessMethodChoice(
            streamAccess=AtomicWriteFileRequestAccessMethodChoiceStreamAccess(
                fileStartPosition=sc.get("start", 0), fileData=OctetString(base64.b64decode(sc["data_base64"])))))
    try:
        resp, a = await ack_or_answer(env, req)
    except Infra as exc:
        size = len(base64.b64decode(sc["data_base64"]))
        max_apdu = getattr(await env.app.device_info_cache.get_device_info(env.target), "max_apdu_length_accepted", None)
        if max_apdu and size > max_apdu:
            raise Infra(f"{exc}: the request ({size} octets of file data, more than the device's "
                        f"max APDU {max_apdu}) was sent segmented and no SegmentACK or answer arrived") from exc
        raise
    if a is not None:
        return a
    return {"ack": True}


async def list_element(sc: dict[str, Any], env: Env, cls: type) -> dict[str, Any]:
    elements = ListOf(Destination)([destination(d) for d in sc["elements"]])
    req = cls(objectIdentifier=objid(sc["object"]), propertyIdentifier=prop_id(sc["property"]),
              listOfElements=AnyValue(elements))
    return await simple(env, req)


async def create_object(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    if "instance" in sc:
        spec = CreateObjectRequestObjectSpecifier(objectIdentifier=ObjectIdentifier((sc["object_type"], sc["instance"])))
    else:
        spec = CreateObjectRequestObjectSpecifier(objectType=sc["object_type"])
    resp, a = await ack_or_answer(env, CreateObjectRequest(objectSpecifier=spec))
    if a is not None:
        return a
    if not isinstance(resp, CreateObjectACK):
        raise Infra(f"unexpected answer {type(resp).__name__}")
    oid = resp.objectIdentifier
    return {"created": f"{oid[0]},{oid[1]}"}


async def delete_object(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    return await simple(env, DeleteObjectRequest(objectIdentifier=objid(sc["object"])))


async def get_event_information(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    last = None
    while True:
        req = GetEventInformationRequest()
        if last is not None:
            req.lastReceivedObjectIdentifier = last
        resp, a = await ack_or_answer(env, req)
        if a is not None:
            return a
        if not isinstance(resp, GetEventInformationACK):
            raise Infra(f"unexpected answer {type(resp).__name__}")
        for s in resp.listOfEventSummaries:
            events.append({"object": f"{s.objectIdentifier[0]},{s.objectIdentifier[1]}",
                           "event_state": str(s.eventState)})
            last = s.objectIdentifier
        if not resp.moreEvents or last is None:
            break
    return {"events": events}


async def acknowledge_alarm(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    oid = objid(sc["object"])
    state = sc["event_state_acked"]
    if sc["time_stamp"] == "event":
        req = ReadPropertyRequest(objectIdentifier=oid, propertyIdentifier=PropertyIdentifier("event-time-stamps"),
                                  propertyArrayIndex=TIME_STAMP_INDEX[state])
        resp, a = await ack_or_answer(env, req)
        if a is not None or not isinstance(resp, ReadPropertyACK):
            raise Infra(f"Event_Time_Stamps of {sc['object']} not readable: {a}")
        stamp = resp.propertyValue.cast_out(TimeStamp)
    else:
        when = dt.datetime.strptime(sc["time_stamp"], "%Y-%m-%dT%H:%M:%S")
        stamp = TimeStamp(dateTime=bacnet_datetime(when))
    req = AcknowledgeAlarmRequest(
        acknowledgingProcessIdentifier=sc["process_id"], eventObjectIdentifier=oid,
        eventStateAcknowledged=EventState(state), timeStamp=stamp,
        acknowledgmentSource=CharacterString("interop"),
        timeOfAcknowledgment=TimeStamp(dateTime=bacnet_datetime(dt.datetime.now())))
    return await simple(env, req)


async def get_alarm_summary(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    resp, a = await ack_or_answer(env, GetAlarmSummaryRequest())
    if a is not None:
        return a
    if not isinstance(resp, GetAlarmSummaryACK):
        raise Infra(f"unexpected answer {type(resp).__name__}")
    return {"alarms": [{"object": f"{s.objectIdentifier[0]},{s.objectIdentifier[1]}",
                        "alarm_state": str(s.alarmState)} for s in resp.listOfAlarmSummaries]}


async def get_enrollment_summary(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    # acknowledgmentFilter is required (clause 13.11); the scenarios filter
    # on the event state only.
    req = GetEnrollmentSummaryRequest(acknowledgmentFilter=GetEnrollmentSummaryRequestAcknowledgmentFilterType("all"))
    if "event_state_filter" in sc:
        req.eventStateFilter = GetEnrollmentSummaryRequestEventStateFilterType(sc["event_state_filter"])
    resp, a = await ack_or_answer(env, req)
    if a is not None:
        return a
    if not isinstance(resp, GetEnrollmentSummaryACK):
        raise Infra(f"unexpected answer {type(resp).__name__}")
    out = []
    for s in resp.listOfEnrollmentSummaries:
        e: dict[str, Any] = {"object": f"{s.objectIdentifier[0]},{s.objectIdentifier[1]}",
                             "event_state": str(s.eventState), "event_type": str(s.eventType),
                             "priority": int(s.priority)}
        if s.notificationClass is not None:
            e["notification_class"] = int(s.notificationClass)
        out.append(e)
    return {"enrollments": out}


def sent(operation: str) -> dict[str, Any]:
    return {"sent": {"operation": operation}}


async def time_synchronization(sc: dict[str, Any], env: Env, utc: bool) -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc) if utc else dt.datetime.now()
    cls = UTCTimeSynchronizationRequest if utc else TimeSynchronizationRequest
    await env.unconfirmed(cls(time=bacnet_datetime(now)))
    return sent("utc-time-synchronization" if utc else "time-synchronization")


async def unconfirmed_private_transfer(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    req = UnconfirmedPrivateTransferRequest(vendorID=sc["vendor_id"], serviceNumber=sc["service_number"])
    if sc.get("parameters"):
        req.serviceParameters = any_of(*[scenario_value(v) for v in sc["parameters"]])
    await env.unconfirmed(req)
    return sent("unconfirmed-private-transfer")


async def confirmed_private_transfer(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    req = ConfirmedPrivateTransferRequest(vendorID=sc["vendor_id"], serviceNumber=sc["service_number"])
    if sc.get("parameters"):
        req.serviceParameters = any_of(*[scenario_value(v) for v in sc["parameters"]])
    resp, a = await ack_or_answer(env, req)
    if a is not None:
        return a
    if not isinstance(resp, ConfirmedPrivateTransferACK):
        raise Infra(f"unexpected answer {type(resp).__name__}")
    return {"ack": True}


def text_message_fields(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    return {
        "textMessageSourceDevice": ObjectIdentifier(("device", CLIENT_INSTANCE)),
        "messagePriority": sc.get("message_priority", "normal"),
        "message": CharacterString(sc["message"]),
    }


async def text_message(sc: dict[str, Any], env: Env, confirmed: bool) -> dict[str, Any]:
    cls = ConfirmedTextMessageRequest if confirmed else UnconfirmedTextMessageRequest
    req = cls(**text_message_fields(sc, env))
    if confirmed:
        return await simple(env, req)
    await env.unconfirmed(req)
    return sent("unconfirmed-text-message")


def channel_value(v: dict[str, Any]) -> ChannelValue:
    t = v["type"]
    if t == "null":
        return ChannelValue(null=Null(()))
    if t == "real":
        return ChannelValue(real=Real(float(v["value"])))
    if t == "unsigned":
        return ChannelValue(unsigned=Unsigned(int(v["value"])))
    if t == "signed":
        return ChannelValue(integer=Integer(int(v["value"])))
    if t == "boolean":
        return ChannelValue(boolean=Boolean(bool(v["value"])))
    if t == "enumerated":
        return ChannelValue(enumerated=Enumerated(int(v["value"])))
    if t == "character-string":
        return ChannelValue(characterString=CharacterString(v["value"]))
    raise Infra(f"channel value type {t} is not encoded by this driver")


async def write_group(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    changes = []
    for c in sc["changes"]:
        gcv = GroupChannelValue(channel=c["channel"], value=channel_value(c["value"]))
        # 0 is how the scenario writes "no overriding priority" (bacwg).
        if c.get("overriding_priority"):
            gcv.overridingPriority = c["overriding_priority"]
        changes.append(gcv)
    req = WriteGroupRequest(groupNumber=sc["group"], writePriority=sc["priority"],
                            changeList=SequenceOf(GroupChannelValue)(changes), inhibitDelay=bool(sc.get("inhibit")))
    await env.unconfirmed(req)
    return sent("write-group")


# BVLC table services, from the unregistered normal-mode link layer.


async def bvlc_call(env: Env, fn: Callable[[], Awaitable[Any]]) -> tuple[Any, str | None]:
    try:
        result = await asyncio.wait_for(fn(), env.request_s + 5)
    except BVLLResult as res:
        code = int(res.bvlciResultCode)
        return None, BVLC_RESULTS.get(code, f"0x{code:04x}")
    except asyncio.TimeoutError as exc:
        raise Infra("no BVLC answer") from exc
    return result, None


async def read_bdt(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    ase = env.bvlc_ase()
    bbmd = env.bbmd_address()
    result, nak = await bvlc_call(env, lambda: ase.read_broadcast_distribution_table(bbmd))
    if nak is not None:
        return {"bvlc_result": nak}
    if result is None:
        raise Infra("no Read-Broadcast-Distribution-Table-Ack")
    me = hostport(bbmd)
    out = []
    for entry in result:
        addr = hostport(entry)
        out.append({"address": "bbmd" if addr == me else addr, "mask": str(entry.netmask)})
    return {"bdt": out}


async def read_fdt(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    ase = env.bvlc_ase()
    bbmd = env.bbmd_address()
    result, nak = await bvlc_call(env, lambda: ase.read_foreign_device_table(bbmd))
    if nak is not None:
        return {"bvlc_result": nak}
    if result is None:
        raise Infra("no Read-Foreign-Device-Table-Ack")
    me = f"{env.my_ip}:{CLIENT_PORT}"
    mine = [e for e in result if hostport(e.fdAddress) == me]
    return {"fdt": {"contains_self": bool(mine), "ttl": int(mine[0].fdTTL) if mine else 0}}


async def write_bdt(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    ase = env.bvlc_ase()
    bbmd = env.bbmd_address()
    entries = [IPv4Address(hostport(bbmd) if e == "bbmd" else e) for e in sc["bdt"]]
    result, code = await bvlc_call(env, lambda: ase.write_broadcast_distribution_table(bbmd, entries))
    if code is None:
        raise Infra("no BVLC-Result for Write-Broadcast-Distribution-Table")
    return {"bvlc_result": code}


SERVICES: dict[str, Callable[[dict[str, Any], Env], Awaitable[dict[str, Any]]]] = {
    "who-is": who_is,
    "who-has": who_has,
    "read-property": read_property,
    "read-property-multiple": read_property_multiple,
    "write-property": write_property,
    "write-property-multiple": write_property_multiple,
    "subscribe-cov": subscribe_cov,
    "subscribe-cov-property": subscribe_cov_property,
    "subscribe-cov-property-multiple": subscribe_cov_property_multiple,
    "read-range": read_range,
    "device-communication-control": device_communication_control,
    "reinitialize-device": reinitialize_device,
    "atomic-read-file": atomic_read_file,
    "atomic-write-file": atomic_write_file,
    "add-list-element": lambda sc, env: list_element(sc, env, AddListElementRequest),
    "remove-list-element": lambda sc, env: list_element(sc, env, RemoveListElementRequest),
    "create-object": create_object,
    "delete-object": delete_object,
    "get-event-information": get_event_information,
    "acknowledge-alarm": acknowledge_alarm,
    "get-alarm-summary": get_alarm_summary,
    "get-enrollment-summary": get_enrollment_summary,
    "time-synchronization": lambda sc, env: time_synchronization(sc, env, False),
    "utc-time-synchronization": lambda sc, env: time_synchronization(sc, env, True),
    "unconfirmed-private-transfer": unconfirmed_private_transfer,
    "confirmed-private-transfer": confirmed_private_transfer,
    "confirmed-text-message": lambda sc, env: text_message(sc, env, True),
    "unconfirmed-text-message": lambda sc, env: text_message(sc, env, False),
    "write-group": write_group,
    "read-bdt": read_bdt,
    "read-fdt": read_fdt,
    "write-bdt": write_bdt,
}


# --- comparison (as in the bacnet-stack driver) -------------------------------


def norm_name(s: str) -> str:
    """Enumeration names compare without case, spaces or hyphens. BACpypes3
    derives its names from camel case: error code 22 is
    "property-is-not-alist" (propertyIsNotAList), and a scenario writes
    "property-is-not-a-list"; reject reasons are "Undefined Enumeration" in
    the scenarios (bacnet-stack's text) and "undefined-enumeration" in
    BACpypes3."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def norm_time(s: str) -> str:
    h, rest = s.split(":", 1)
    return f"{int(h)}:{rest}"


def norm_destinations(ds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for d in ds:
        d = dict(d)
        d["from_time"], d["to_time"] = norm_time(d["from_time"]), norm_time(d["to_time"])
        d["valid_days"], d["transitions"] = sorted(d["valid_days"]), sorted(d["transitions"])
        out.append(d)
    return out


def compare(expect: dict[str, Any], observed: dict[str, Any]) -> bool:
    key = next(iter(expect))
    if key not in observed:
        return False
    want, got = expect[key], observed[key]
    if key == "value":
        return same_value(got, want)
    if key == "values":
        if len(got) != len(want):
            return False
        for g, w in zip(got, want):
            if g["object"] != w["object"] or str(g["property"]) != str(w["property"]):
                return False
            if "error" in w:
                ge = g.get("error") or {}
                if any(norm_name(str(ge.get(k, ""))) != norm_name(w["error"][k]) for k in ("class", "code")):
                    return False
            elif "value" not in g or not same_value(g["value"], w["value"]):
                return False
        return True
    if key == "error":
        if any(norm_name(str(got.get(k, ""))) != norm_name(want[k]) for k in ("class", "code")):
            return False
        if "first_failed" in want:
            ff = got.get("first_failed") or {}
            if ff.get("object") != want["first_failed"]["object"] or str(ff.get("property")) != str(want["first_failed"]["property"]):
                return False
        if "first_failed_element" in want and got.get("first_failed_element") != want["first_failed_element"]:
            return False
        return True
    if key in ("reject", "abort"):
        return norm_name(got) == norm_name(want)
    if key == "records":
        return len(got) == len(want) and all(
            g["timestamp"] == w["timestamp"] and same_value(g["value"], w["value"]) for g, w in zip(got, want))
    if key == "subscribed":
        return not want["notification"] or got["notification"]
    if key == "i-have":
        return sorted(got, key=json.dumps) == sorted(want, key=json.dumps)
    if key == "i-am":
        return sorted(got) == sorted(want)
    if key == "recipients":
        return norm_destinations(got) == norm_destinations(want)
    if key == "enrollments":
        # event_type and notification_class are compared when given.
        return len(got) == len(want) and all(
            all(norm_name(str(g.get(k))) == norm_name(str(w[k])) for k in w) for g, w in zip(got, want))
    return got == want


# --- main ------------------------------------------------------------------


def emit(line: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(line, separators=(",", ":")) + "\n")
    sys.stdout.flush()


async def run(args: argparse.Namespace, doc: dict[str, Any], timeout_ms: int, retries: int) -> None:
    env = Env(args, timeout_ms, retries)
    start_error = ""
    try:
        await env.start()
    except Infra as exc:
        start_error = str(exc)
    except OSError as exc:
        start_error = f"cannot start the BACpypes3 application: {exc}"
    emit({
        "event": "ready",
        "mode": "client",
        "adapter": ADAPTER,
        "version": os.environ.get("ADAPTER_VERSION", "dev"),
        "peer_version": os.environ.get("BACPYPES3_VERSION", "unknown"),
        "scenarios": str(doc.get("id", "")),
    })
    only = {s for s in args.only.split(",") if s}
    summary = dict.fromkeys(OUTCOMES, 0)
    for sc in doc["scenarios"]:
        if only and sc["id"] not in only:
            continue
        begin = time.monotonic()
        line: dict[str, Any] = {"event": "result", "scenario": sc["id"], "service": sc["service"]}
        fn = SERVICES.get(sc["service"])
        try:
            if start_error:
                raise Infra(start_error)
            if fn is None:
                raise Unsupported(f"BACpypes3 0.0.110 has no request for {sc['service']} in this driver")
            observed = await fn(sc, env)
            line["outcome"] = "pass" if compare(sc["expect"], observed) else "fail"
            line["observed"] = observed
        except Undecodable as exc:
            known = KNOWN_UNDECODABLE.get((exc.pdu_type, exc.service))
            if known is not None:
                line["outcome"] = "known-difference"
                line["detail"] = f"{known}; {exc.error}; answer octets '{exc.octets}'"
            else:
                line["outcome"] = "fail"
                line["observed"] = {"undecodable": exc.octets}
                line["detail"] = str(exc)
        except Unsupported as exc:
            line["outcome"] = "unsupported"
            line["detail"] = str(exc)
        except KnownDifference as exc:
            line["outcome"] = "known-difference"
            line["detail"] = str(exc)
        except Infra as exc:
            line["outcome"] = "infra-error"
            line["detail"] = str(exc)
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
            line["outcome"] = "infra-error"
            line["detail"] = f"{type(exc).__name__}: {exc}"
        line["durationMs"] = int((time.monotonic() - begin) * 1000)
        summary[line["outcome"]] += 1
        emit(line)
    emit({"event": "done", "summary": summary})
    env.close()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="client", description=__doc__.split("\n\n")[0])
    ap.add_argument("--target", default="", help="DUT HOST:PORT")
    ap.add_argument("--device", type=int, required=True, help="DUT device instance")
    ap.add_argument("--scenarios", required=True, help="scenario file")
    ap.add_argument("--only", default="", help="comma-separated scenario ids")
    ap.add_argument("--broadcast", default="", help="HOST:PORT discovery requests are sent to")
    ap.add_argument("--bbmd", default="", help="BBMD HOST:PORT to register with as a foreign device")
    ap.add_argument("--fd-ttl", type=int, default=60, help="foreign-device TTL in seconds (default 60)")
    args = ap.parse_args(argv)
    if not 1 <= args.fd_ttl <= 65535:
        print("client: --fd-ttl must be 1..65535", file=sys.stderr)
        return 2
    for name in ("target", "broadcast", "bbmd"):
        v = getattr(args, name)
        if v and not re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}:[0-9]+", v):
            print(f"client: --{name} must be IPv4:PORT", file=sys.stderr)
            return 2
    try:
        doc = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))
        if not isinstance(doc.get("scenarios"), list):
            raise KeyError("scenarios")
    except (OSError, ValueError, KeyError, AttributeError) as exc:
        print(f"client: cannot read scenarios: {exc}", file=sys.stderr)
        return 2
    if doc.get("requires_bbmd") and not args.bbmd:
        print(f"client: {doc.get('id')} requires --bbmd", file=sys.stderr)
        return 2
    try:
        timeout_ms = int(os.environ.get("BACNET_CLIENT_TIMEOUT_MS", "3000"))
        retries = int(os.environ.get("BACNET_CLIENT_RETRIES", "1"))
    except ValueError:
        print("client: BACNET_CLIENT_TIMEOUT_MS and BACNET_CLIENT_RETRIES must be integers", file=sys.stderr)
        return 2
    asyncio.run(run(args, doc, timeout_ms, retries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
