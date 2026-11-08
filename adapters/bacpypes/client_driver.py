#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Legacy BACpypes client mode (docs/CLIENT_DRIVER_CONTRACT.md).

Runs one upstream ``bacpypes`` application (PyPI bacpypes 0.19.0, not
BACpypes3), unmodified, as a client against a device under test (DUT) and
turns what BACpypes decoded into result lines. Every request is an upstream
APDU class from ``bacpypes.apdu`` sent through the application's IOCB
interface (``ApplicationIOController.request_io``); every answer is decoded
by BACpypes. The adapter builds the requests from the scenario file and
compares the decoded answers with the expectation.

The upstream core (``bacpypes.core.run``, asyncore) runs in the main thread;
the scenarios run in a worker thread that hands each request to the core
with ``deferred`` and waits on its IOCB, the pattern of upstream's
samples/ThreadedReadProperty.py.

With --bbmd the link layer is upstream ``BIPForeign`` (the stack of
``bacpypes.app.BIPForeignApplication``). The BVLC table services
(Read-BDT, Read-FDT, Write-BDT) are sent from a second, unregistered
``AnnexJCodec`` on its own ``UDPMultiplexer`` (port 47809), as upstream's
samples/ReadWriteBBMD.py does: BIPForeign takes every BVLC-Result from the
BBMD as its registration status.
"""

import argparse
import base64
import copy
import datetime as dt
import json
import math
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import ADAPTER, emit, interface_prefix, local_ipv4, log  # noqa: E402

from bacpypes.apdu import (  # noqa: E402
    AbortPDU,
    AbortReason,
    AcknowledgeAlarmRequest,
    AddListElementRequest,
    AtomicReadFileACK,
    AtomicReadFileRequest,
    AtomicReadFileRequestAccessMethodChoice,
    AtomicReadFileRequestAccessMethodChoiceStreamAccess,
    AtomicWriteFileRequest,
    AtomicWriteFileRequestAccessMethodChoice,
    AtomicWriteFileRequestAccessMethodChoiceStreamAccess,
    ComplexAckPDU,
    ConfirmedPrivateTransferACK,
    ConfirmedPrivateTransferRequest,
    ConfirmedTextMessageRequest,
    CreateObjectACK,
    CreateObjectRequest,
    CreateObjectRequestObjectSpecifier,
    DeleteObjectRequest,
    DeviceCommunicationControlRequest,
    Error,
    ErrorPDU,
    GetAlarmSummaryACK,
    GetAlarmSummaryRequest,
    GetEnrollmentSummaryACK,
    GetEnrollmentSummaryRequest,
    GetEventInformationACK,
    GetEventInformationRequest,
    GroupChannelValue,
    IAmRequest,
    Range,
    RangeByPosition,
    RangeBySequenceNumber,
    ReadAccessSpecification,
    ReadPropertyACK,
    ReadPropertyMultipleACK,
    ReadPropertyMultipleRequest,
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
    WhoHasObject,
    WhoHasRequest,
    WhoIsRequest,
    WriteAccessSpecification,
    WriteGroupRequest,
    WritePropertyMultipleRequest,
    WritePropertyRequest,
    complex_ack_types,
    error_types,
)
from bacpypes.app import ApplicationIOController  # noqa: E402
from bacpypes.appservice import ApplicationServiceAccessPoint, StateMachineAccessPoint  # noqa: E402
from bacpypes.basetypes import (  # noqa: E402
    ChannelValue,
    DateTime,
    DaysOfWeek,
    Destination,
    EventTransitionBits,
    PropertyReference,
    PropertyValue,
    Recipient,
    TimeStamp,
)
from bacpypes.bvll import (  # noqa: E402
    ReadBroadcastDistributionTable,
    ReadBroadcastDistributionTableAck,
    ReadForeignDeviceTable,
    ReadForeignDeviceTableAck,
    Result,
    WriteBroadcastDistributionTable,
)
from bacpypes.bvllservice import AnnexJCodec, BIPForeign, BIPSimple, UDPMultiplexer  # noqa: E402
from bacpypes.comm import Client, bind  # noqa: E402
from bacpypes.constructeddata import Any, Array, List, ListOf, SequenceOf  # noqa: E402
from bacpypes.core import deferred, enable_sleeping, run, stop  # noqa: E402
from bacpypes.iocb import IOCB  # noqa: E402
from bacpypes.local.device import LocalDeviceObject  # noqa: E402
from bacpypes.netservice import NetworkServiceAccessPoint, NetworkServiceElement  # noqa: E402
from bacpypes.object import get_datatype  # noqa: E402
from bacpypes.pdu import Address, GlobalBroadcast  # noqa: E402
from bacpypes.primitivedata import (  # noqa: E402
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
    Real,
    Tag,
    TagList,
    Time,
    Unsigned,
)
from bacpypes.service.device import WhoIsIAmServices  # noqa: E402

OUTCOMES = ("pass", "fail", "unsupported", "not-tested", "known-difference", "infra-error")
CLIENT_INSTANCE = 4002  # the client's own device instance (BACpypes3's driver uses 4001)
CLIENT_PORT = 47808
BVLC_PORT = 47809
FILE_CHUNK = 480
PEER = "BACpypes 0.19.0"

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

# Answers upstream decodes as something they are not, by (PDU type, service
# choice). ApplicationServiceAccessPoint.confirmation (bacpypes/appservice.py)
# replaces an Error it cannot decode with Error(0, 0) and a ComplexACK with
# Error(7, 57), so the driver decodes a copy first (observe_answers) and
# reports the octets instead of the substitute.
KNOWN_UNDECODABLE = {}


class Infra(Exception):
    """The scenario could not be run (no binding, no answer, socket error)."""


class Unsupported(Exception):
    """Upstream at the pin cannot issue the request (never a pass)."""


class Undecodable(Exception):
    def __init__(self, pdu_type, service, octets, error):
        Exception.__init__(self, "%s could not decode the answer (PDU type %d, service %d, %s): '%s'" % (
            PEER, pdu_type, service, error, octets))
        self.pdu_type, self.service, self.octets, self.error = pdu_type, service, octets, error


# --- names ----------------------------------------------------------------------


def camel(name):
    """A scenario name (hyphens) as an upstream name (camel case)."""
    if isinstance(name, int):
        return name
    head, *rest = str(name).split("-")
    return head + "".join(p[:1].upper() + p[1:] for p in rest)


def hyphen(name):
    """An upstream camel-case name as a scenario name; numbers stay numbers."""
    if isinstance(name, int):
        return name
    s = str(name)
    if s.isdigit():
        return int(s)
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", s).lower()


def objid(ref):
    t, i = ref.split(",")
    t = int(t) if t.isdigit() else camel(t)
    return (t, int(i))


def objref(oid):
    return "%s,%d" % (hyphen(oid[0]), int(oid[1]))


def norm_name(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


# --- the application ------------------------------------------------------------


class ClientApplication(ApplicationIOController, WhoIsIAmServices):
    """The stack of upstream BIPSimpleApplication (or BIPForeignApplication)
    with the WhoIsIAmServices capability; I-Am, I-Have and COV notifications
    are recorded for the scenarios."""

    def __init__(self, device, address, bbmd=None, ttl=60):
        ApplicationIOController.__init__(self, device)
        self.localAddress = address
        self.asap = ApplicationServiceAccessPoint()
        self.smap = StateMachineAccessPoint(device)
        self.smap.deviceInfoCache = self.deviceInfoCache
        self.nsap = NetworkServiceAccessPoint()
        self.nse = NetworkServiceElement()
        bind(self.nse, self.nsap)
        bind(self, self.asap, self.smap, self.nsap)
        if bbmd:
            self.bip = BIPForeign(Address(bbmd), ttl)
            self.mux = UDPMultiplexer(address, noBroadcast=True)
        else:
            self.bip = BIPSimple()
            self.mux = UDPMultiplexer(address)
        self.annexj = AnnexJCodec()
        bind(self.bip, self.annexj, self.mux.annexJ)
        self.nsap.bind(self.bip, address=address)
        self.lock = threading.Lock()
        self.i_ams = []
        self.i_haves = []
        self.cov = []
        self.undecodable = {}

    def observe_answers(self):
        asap = self.asap
        upstream = asap.confirmation

        def confirmation(apdu):
            klass = None
            if isinstance(apdu, ComplexAckPDU):
                klass = complex_ack_types.get(apdu.apduService)
            elif isinstance(apdu, ErrorPDU):
                klass = error_types.get(apdu.apduService, Error)
            if klass is not None:
                probe = copy.deepcopy(apdu)
                try:
                    klass().decode(probe)
                except Exception as err:  # noqa: BLE001 - recorded, then upstream runs
                    with self.lock:
                        self.undecodable[(str(apdu.pduSource), int(apdu.apduInvokeID))] = Undecodable(
                            int(apdu.apduType), int(apdu.apduService), bytes(apdu.pduData).hex(),
                            "%s: %s" % (type(err).__name__, err))
            upstream(apdu)

        asap.confirmation = confirmation

    def do_IAmRequest(self, apdu):
        # Upstream's handler checks the parameters and stops there; the cache
        # entry is what the segmentation state machines read (app.py
        # DeviceInfoCache.iam_device_info).
        WhoIsIAmServices.do_IAmRequest(self, apdu)
        self.deviceInfoCache.iam_device_info(apdu)
        with self.lock:
            self.i_ams.append(apdu)

    def do_IHaveRequest(self, apdu):
        with self.lock:
            self.i_haves.append(apdu)

    def do_UnconfirmedCOVNotificationRequest(self, apdu):
        with self.lock:
            self.cov.append(apdu)

    def do_ConfirmedCOVNotificationRequest(self, apdu):
        with self.lock:
            self.cov.append(apdu)
        self.response(SimpleAckPDU(context=apdu))


class BVLCClient(Client):
    """Receives the BVLC answers of the unregistered link layer."""

    def __init__(self):
        Client.__init__(self)
        self.answers = []
        self.event = threading.Event()

    def confirmation(self, pdu):
        if isinstance(pdu, (ReadBroadcastDistributionTableAck, ReadForeignDeviceTableAck, Result)):
            self.answers.append(pdu)
            self.event.set()


# --- values ---------------------------------------------------------------------


def scenario_value(v):
    """A scenario value as the upstream primitive that encodes it."""
    t = v["type"]
    if t == "null":
        return Null()
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
        return ObjectIdentifier(objid(v["value"]))
    raise Infra("value type %s is not encoded by this driver" % t)


def any_of(*values):
    a = Any()
    for v in values:
        a.cast_in(v)
    return a


def observed_value(datatype, value):
    """A value decoded by upstream (cast_out of datatype) as a scenario value."""
    if datatype is None:
        return {"type": "text", "value": str(value)}
    if issubclass(datatype, Null):
        return {"type": "null"}
    if issubclass(datatype, Boolean):
        return {"type": "boolean", "value": bool(value)}
    if issubclass(datatype, Enumerated):
        return {"type": "enumerated", "value": hyphen(value)}
    if issubclass(datatype, Unsigned):
        return {"type": "unsigned", "value": int(value)}
    if issubclass(datatype, Integer):
        return {"type": "signed", "value": int(value)}
    if issubclass(datatype, (Real, Double)):
        return {"type": "real", "value": float(value)}
    if issubclass(datatype, CharacterString):
        return {"type": "character-string", "value": str(value)}
    if issubclass(datatype, ObjectIdentifier):
        return {"type": "object-identifier", "value": objref(value)}
    if issubclass(datatype, OctetString):
        return {"type": "octet-string", "value": bytes(value).hex()}
    if issubclass(datatype, BitString):
        return {"type": "bit-string", "value": [int(b) for b in value]}
    if isinstance(value, (list, tuple)):
        sub = getattr(datatype, "subtype", None)
        return {"type": "list", "value": [observed_value(sub, x) for x in value]}
    return {"type": "text", "value": str(value)}


def generic_value(any_value):
    """The first application-tagged primitive of an Any, decoded by upstream."""
    tags = any_value.tagList
    if not tags or tags[0].tagClass != Tag.applicationTagClass:
        raise ValueError("context-tagged content")
    obj = tags[0].app_to_object()
    return type(obj), obj.value


def property_datatype(oid, prop, index):
    dtype = get_datatype(oid[0], prop)
    if dtype is not None and issubclass(dtype, Array) and index is not None:
        dtype = Unsigned if index == 0 else dtype.subtype
    return dtype


def decode_property(oid, prop, index, value):
    """(datatype, decoded value): upstream's object model first, else the
    application tag."""
    dtype = property_datatype(oid, prop, index)
    if dtype is not None:
        try:
            if value.is_application_class_null():
                return Null, None
            return dtype, value.cast_out(dtype)
        except Exception:  # noqa: BLE001 - fall back to the tag
            pass
    return generic_value(value)


def same_value(got, want):
    if got.get("type") != want.get("type"):
        return False
    gv, wv = got.get("value"), want.get("value")
    if want["type"] == "real" and isinstance(gv, float) and isinstance(wv, (int, float)):
        return math.isclose(gv, float(wv), rel_tol=1e-6, abs_tol=1e-6)
    if want["type"] == "enumerated" and isinstance(gv, str) and isinstance(wv, str):
        return norm_name(gv) == norm_name(wv)
    return gv == wv


def bacnet_datetime(when):
    return DateTime(date=(when.year - 1900, when.month, when.day, when.isoweekday()),
                    time=(when.hour, when.minute, when.second, when.microsecond // 10000))


def time_text(t):
    h, m, s, hh = tuple(t)
    return "%d:%02d:%02d.%02d" % (h, m, s, hh)


def datetime_text(d, t):
    y, mo, day, _ = tuple(d)
    h, m, s, _ = tuple(t)
    return "%04d-%02d-%02dT%02d:%02d:%02d" % (y + 1900, mo, day, h, m, s)


def parse_time(text):
    h, m, rest = text.split(":")
    s, _, hh = rest.partition(".")
    return (int(h), int(m), int(s), int(hh or 0))


def destination(d):
    if "device" not in d["recipient"]:
        raise Infra("only device recipients are encoded by this driver")
    days = [0] * 7
    for x in d["valid_days"]:
        days[x - 1] = 1
    return Destination(
        validDays=DaysOfWeek(days),
        fromTime=parse_time(d["from_time"]),
        toTime=parse_time(d["to_time"]),
        recipient=Recipient(device=("device", d["recipient"]["device"])),
        processIdentifier=d["process_id"],
        issueConfirmedNotifications=d["confirmed"],
        transitions=EventTransitionBits([1 if n in d["transitions"] else 0 for n in TRANSITIONS]),
    )


def observed_destination(d):
    rec = {}
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


# --- the environment ------------------------------------------------------------


class Env:
    def __init__(self, args, timeout_ms, retries):
        self.args = args
        self.target = Address(args.target) if args.target else None
        self.device = args.device
        self.timeout_ms, self.retries = timeout_ms, retries
        self.request_s = timeout_ms / 1000.0 * (retries + 1) + 2
        self.listen_s = max(2.0, timeout_ms / 1000.0)
        self.app = None
        self.bound = False
        self.bind_detail = ""
        self.my_ip = ""
        self.bvlc = None
        self.bvlc_mux = None

    def start(self):
        towards = self.args.bbmd or self.args.target or self.args.broadcast or "192.0.2.1:47808"
        self.my_ip = local_ipv4(towards)
        if self.args.bbmd:
            address = Address("%s:%d" % (self.my_ip, CLIENT_PORT))
        else:
            address = Address("%s/%d:%d" % (self.my_ip, interface_prefix(self.my_ip) or 16, CLIENT_PORT))
        device = LocalDeviceObject(
            objectName="bacpypes-client-%d" % CLIENT_INSTANCE,
            objectIdentifier=("device", CLIENT_INSTANCE),
            vendorIdentifier=999,
            maxApduLengthAccepted=1476,
            segmentationSupported="segmentedBoth",
            apduTimeout=self.timeout_ms,
            numberOfApduRetries=self.retries,
        )
        self.app = ClientApplication(device, address, bbmd=self.args.bbmd or None, ttl=self.args.fd_ttl)
        self.app.observe_answers()

    def wait_registered(self):
        deadline = time.monotonic() + self.request_s + 5
        while time.monotonic() < deadline:
            status = self.app.bip.registrationStatus
            if status == 0:
                return
            if status > 0:
                raise Infra("Register-Foreign-Device answered with BVLC-Result 0x%04x" % status)
            time.sleep(0.1)
        raise Infra("no BVLC-Result for Register-Foreign-Device")

    def call(self, fn, *args):
        """Run fn in the core thread and wait for it."""
        done = threading.Event()
        box = {}

        def wrapper():
            try:
                box["value"] = fn(*args)
            except Exception as exc:  # noqa: BLE001 - re-raised in the caller
                box["error"] = exc
            done.set()

        deferred(wrapper)
        if not done.wait(10):
            raise Infra("the BACpypes core did not run the request")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def bind_target(self):
        """A unicast Who-Is to the target fills upstream's device info cache."""
        if self.bound:
            return
        if self.target is None:
            raise Infra("--target is required for confirmed services")
        if self.bind_detail:
            raise Infra(self.bind_detail)
        start = len(self.app.i_ams)
        self.call(self.app.who_is, self.device, self.device, self.target)
        deadline = time.monotonic() + self.request_s
        while time.monotonic() < deadline:
            with self.app.lock:
                found = [a for a in self.app.i_ams[start:] if int(a.iAmDeviceIdentifier[1]) == self.device]
            if found:
                src = hostport(found[0].pduSource)
                if src != self.args.target:
                    self.bind_detail = "I-Am for device %d from %s, not the target %s" % (self.device, src, self.args.target)
                    raise Infra(self.bind_detail)
                self.bound = True
                return
            time.sleep(0.05)
        self.bind_detail = "device %d did not answer a Who-Is to %s" % (self.device, self.args.target)
        raise Infra(self.bind_detail)

    def confirmed(self, apdu):
        """The ACK, or the Error, Reject or Abort as an exception."""
        self.bind_target()
        apdu.pduDestination = self.target
        iocb = IOCB(apdu)
        self.call(self.app.request_io, iocb)
        done = iocb.ioComplete.wait(self.request_s + 5)
        key = (str(self.target), int(apdu.apduInvokeID)) if apdu.apduInvokeID is not None else None
        with self.app.lock:
            u = self.app.undecodable.pop(key, None) if key else None
        if not done:
            self.call(iocb.abort, Infra("no answer"))
            # Upstream's substitute for an Error it cannot decode,
            # Error(0, 0), carries no source or invoke ID, so the IOCB never
            # completes (appservice.py ApplicationServiceAccessPoint.confirmation).
            if u is not None:
                raise u
            raise Infra("no answer within the APDU timeout and retries")
        if u is not None:
            raise u
        if iocb.ioError is not None:
            raise Answer(iocb.ioError)
        return iocb.ioResponse

    def unconfirmed(self, apdu, broadcast=False):
        if apdu.pduDestination is None:
            if not broadcast:
                self.bind_target()
                apdu.pduDestination = self.target
        self.call(self.app.request, apdu)
        time.sleep(0.2)

    def bvlc_client(self):
        if self.bvlc is None:
            self.bvlc = BVLCClient()
            annexj = AnnexJCodec()
            self.bvlc_mux = UDPMultiplexer(Address("%s:%d" % (self.my_ip, BVLC_PORT)), noBroadcast=True)
            bind(self.bvlc, annexj, self.bvlc_mux.annexJ)
        return self.bvlc

    def bvlc_request(self, pdu, want):
        def build():
            c = self.bvlc_client()
            c.answers.clear()
            c.event.clear()
            c.request(pdu)
            return c

        c = self.call(build)
        deadline = time.monotonic() + self.request_s
        while time.monotonic() < deadline:
            c.event.wait(0.1)
            for a in list(c.answers):
                if isinstance(a, (want, Result)):
                    return a
        raise Infra("no BVLC answer")

    def bbmd_address(self):
        return Address(self.args.bbmd or self.args.target)

    def close(self):
        if self.app is not None:
            self.app.mux.close_socket()
        if self.bvlc_mux is not None:
            self.bvlc_mux.close_socket()


class Answer(Exception):
    """An Error, Reject or Abort the device (or the client's TSM) answered."""

    def __init__(self, pdu):
        Exception.__init__(self, repr(pdu))
        self.pdu = pdu


def hostport(addr):
    t = getattr(addr, "addrTuple", None)
    if t:
        return "%s:%d" % (t[0], t[1])
    return str(addr)


REJECT_NAMES = {v: k for k, v in RejectReason.enumerations.items()}
ABORT_NAMES = {v: k for k, v in AbortReason.enumerations.items()}


def reason_name(r, names):
    """An abort or reject reason (a number in the decoded PDU) by its upstream name."""
    if isinstance(r, int):
        return hyphen(names.get(r, str(r)))
    return hyphen(r)


def answer(exc):
    pdu = exc.pdu
    if isinstance(pdu, RejectPDU):
        return {"reject": str(reason_name(pdu.apduAbortRejectReason, REJECT_NAMES))}
    if isinstance(pdu, AbortPDU):
        reason = reason_name(pdu.apduAbortRejectReason, ABORT_NAMES)
        if str(reason) == "no-response":
            raise Infra("no answer within the APDU timeout and retries")
        return {"abort": str(reason)}
    if isinstance(pdu, ErrorPDU):
        src = getattr(pdu, "errorType", None) or pdu
        err = {"class": str(hyphen(src.errorClass)), "code": str(hyphen(src.errorCode))}
        ff = getattr(pdu, "firstFailedWriteAttempt", None)
        if ff is not None:
            err["first_failed"] = {"object": objref(ff.objectIdentifier), "property": hyphen(ff.propertyIdentifier)}
        ffe = getattr(pdu, "firstFailedElementNumber", None)
        if ffe is not None:
            err["first_failed_element"] = int(ffe)
        return {"error": err}
    if isinstance(pdu, Exception):
        raise Infra("%s: %s" % (type(pdu).__name__, pdu))
    raise Infra("unexpected answer %r" % (pdu,))


def ack_or_answer(env, apdu):
    try:
        return env.confirmed(apdu), None
    except Answer as exc:
        return None, answer(exc)


def simple(env, apdu):
    resp, a = ack_or_answer(env, apdu)
    if a is not None:
        return a
    if isinstance(resp, SimpleAckPDU):
        return {"ack": True}
    raise Infra("unexpected answer %s" % type(resp).__name__)


# --- services ---------------------------------------------------------------------


def who_is(sc, env):
    low, high = sc.get("low"), sc.get("high", sc.get("low"))
    with env.app.lock:
        env.app.i_ams.clear()
    dest = Address(env.args.broadcast) if env.args.broadcast else GlobalBroadcast()
    env.call(env.app.who_is, low, high, dest)
    time.sleep(env.listen_s)
    devices = []
    with env.app.lock:
        got = list(env.app.i_ams)
    for apdu in got:
        inst = int(apdu.iAmDeviceIdentifier[1])
        if inst == CLIENT_INSTANCE:
            continue
        if low is not None and not low <= inst <= high:
            continue
        src = hostport(apdu.pduSource)
        if env.args.target and src != env.args.target:
            raise Infra("I-Am for device %d from %s, not the target %s" % (inst, src, env.args.target))
        if inst not in devices:
            devices.append(inst)
    return {"i-am": sorted(devices)}


def who_has(sc, env):
    # Upstream's WhoHasIHaveServices.who_has raises NotImplementedError; the
    # request is the upstream WhoHasRequest APDU class.
    if "object" in sc:
        thing = WhoHasObject(objectIdentifier=objid(sc["object"]))
    else:
        thing = WhoHasObject(objectName=sc["name"])
    req = WhoHasRequest(object=thing)
    req.pduDestination = Address(env.args.broadcast) if env.args.broadcast else GlobalBroadcast()
    with env.app.lock:
        env.app.i_haves.clear()
    env.unconfirmed(req, broadcast=True)
    time.sleep(env.listen_s)
    out = []
    with env.app.lock:
        got = list(env.app.i_haves)
    for apdu in got:
        dev = int(apdu.deviceIdentifier[1])
        if dev == CLIENT_INSTANCE:
            continue
        entry = {"device": dev, "object": objref(apdu.objectIdentifier)}
        if entry not in out:
            out.append(entry)
    return {"i-have": out}


def read_property(sc, env):
    oid, pid = objid(sc["object"]), camel(sc["property"])
    req = ReadPropertyRequest(objectIdentifier=oid, propertyIdentifier=pid)
    if "array_index" in sc:
        req.propertyArrayIndex = sc["array_index"]
    resp, a = ack_or_answer(env, req)
    if a is not None:
        return a
    if not isinstance(resp, ReadPropertyACK):
        raise Infra("unexpected answer %s" % type(resp).__name__)
    dtype, value = decode_property(oid, pid, sc.get("array_index"), resp.propertyValue)
    if "recipients" in sc["expect"] and isinstance(value, list) and all(isinstance(d, Destination) for d in value):
        return {"recipients": [observed_destination(d) for d in value]}
    return {"value": observed_value(dtype, value)}


def read_property_multiple(sc, env):
    specs = []
    for r in sc["reads"]:
        specs.append(ReadAccessSpecification(
            objectIdentifier=objid(r["object"]),
            listOfPropertyReferences=[PropertyReference(propertyIdentifier=camel(p)) for p in r["properties"]]))
    resp, a = ack_or_answer(env, ReadPropertyMultipleRequest(listOfReadAccessSpecs=specs))
    if a is not None:
        return a
    if not isinstance(resp, ReadPropertyMultipleACK):
        raise Infra("unexpected answer %s" % type(resp).__name__)
    values = []
    for result in resp.listOfReadAccessResults:
        oid = result.objectIdentifier
        for elem in result.listOfResults:
            entry = {"object": objref(oid), "property": hyphen(elem.propertyIdentifier)}
            rr = elem.readResult
            if rr.propertyAccessError is not None:
                entry["error"] = {"class": hyphen(rr.propertyAccessError.errorClass),
                                  "code": hyphen(rr.propertyAccessError.errorCode)}
            else:
                dtype, value = decode_property(oid, elem.propertyIdentifier, elem.propertyArrayIndex, rr.propertyValue)
                entry["value"] = observed_value(dtype, value)
            values.append(entry)
    return {"values": values}


def write_spec(w):
    pv = PropertyValue(propertyIdentifier=camel(w["property"]), value=any_of(scenario_value(w["value"])))
    if "priority" in w:
        pv.priority = w["priority"]
    return pv


def write_property(sc, env):
    req = WritePropertyRequest(objectIdentifier=objid(sc["object"]), propertyIdentifier=camel(sc["property"]),
                               propertyValue=any_of(scenario_value(sc["value"])))
    if "priority" in sc:
        req.priority = sc["priority"]
    if "array_index" in sc:
        req.propertyArrayIndex = sc["array_index"]
    return simple(env, req)


def write_property_multiple(sc, env):
    specs = []
    for w in sc["writes"]:
        oid = objid(w["object"])
        if specs and tuple(specs[-1].objectIdentifier) == oid:
            specs[-1].listOfProperties.append(write_spec(w))
        else:
            specs.append(WriteAccessSpecification(objectIdentifier=oid, listOfProperties=[write_spec(w)]))
    return simple(env, WritePropertyMultipleRequest(listOfWriteAccessSpecs=specs))


def wait_cov(env, start, oid, pid, seconds):
    deadline = time.monotonic() + seconds
    while True:
        with env.app.lock:
            got = list(env.app.cov[start:])
        for n in got:
            if (int(n.subscriberProcessIdentifier) == pid and tuple(n.monitoredObjectIdentifier) == tuple(oid)
                    and hostport(n.pduSource) == env.args.target):
                return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def subscribe(env, sc, req):
    oid = req.monitoredObjectIdentifier
    if not sc.get("cancel"):
        req.issueConfirmedNotifications = bool(sc.get("confirmed"))
        req.lifetime = sc.get("lifetime", 60)
    with env.app.lock:
        start = len(env.app.cov)
    resp, a = ack_or_answer(env, req)
    if a is not None:
        return a
    if not isinstance(resp, SimpleAckPDU):
        raise Infra("unexpected answer %s" % type(resp).__name__)
    got = False
    if not sc.get("cancel"):
        got = wait_cov(env, start, oid, sc["process_id"], env.listen_s)
    return {"subscribed": {"notification": got}}


def subscribe_cov(sc, env):
    return subscribe(env, sc, SubscribeCOVRequest(
        subscriberProcessIdentifier=sc["process_id"], monitoredObjectIdentifier=objid(sc["object"])))


def subscribe_cov_property(sc, env):
    ref = PropertyReference(propertyIdentifier=camel(sc["property"]))
    if "array_index" in sc:
        ref.propertyArrayIndex = sc["array_index"]
    req = SubscribeCOVPropertyRequest(subscriberProcessIdentifier=sc["process_id"],
                                      monitoredObjectIdentifier=objid(sc["object"]),
                                      monitoredPropertyIdentifier=ref)
    if not sc.get("cancel") and "cov_increment" in sc:
        req.covIncrement = sc["cov_increment"]
    return subscribe(env, sc, req)


def subscribe_cov_property_multiple(sc, env):
    raise Unsupported(
        "%s has no SubscribeCOVPropertyMultiple request APDU and no COVNotificationMultiple type "
        "(bacpypes/apdu.py registers no confirmed service 30)" % PEER)


def observed_record(rec):
    datum = rec.logDatum
    for attr, typ, dtype in (("realValue", "real", Real), ("unsignedValue", "unsigned", Unsigned),
                             ("signedValue", "signed", Integer), ("booleanValue", "boolean", Boolean),
                             ("enumValue", "enumerated", Enumerated)):
        v = getattr(datum, attr, None)
        if v is not None:
            value = observed_value(dtype, v)
            value["type"] = typ
            break
    else:
        value = {"type": "text", "value": str(datum)}
    return {"timestamp": datetime_text(rec.timestamp.date, rec.timestamp.time), "value": value}


def read_range(sc, env):
    oid, pid = objid(sc["object"]), camel(sc["property"])
    req = ReadRangeRequest(objectIdentifier=oid, propertyIdentifier=pid)
    r = sc["range"]
    if r["by"] == "position":
        req.range = Range(byPosition=RangeByPosition(referenceIndex=r.get("index", 1), count=r.get("count", 1)))
    elif r["by"] == "sequence":
        req.range = Range(bySequenceNumber=RangeBySequenceNumber(
            referenceSequenceNumber=r.get("index", 1), count=r.get("count", 1)))
    resp, a = ack_or_answer(env, req)
    if a is not None:
        return a
    if not isinstance(resp, ReadRangeACK):
        raise Infra("unexpected answer %s" % type(resp).__name__)
    dtype = get_datatype(oid[0], pid)
    if dtype is None:
        raise Infra("%s has no datatype for %s %s" % (PEER, sc["object"], sc["property"]))
    items = resp.itemData.cast_out(dtype)
    return {"records": [observed_record(rec) for rec in items]}


def device_communication_control(sc, env):
    req = DeviceCommunicationControlRequest(enableDisable=camel(sc["state"]))
    if "duration" in sc:
        req.timeDuration = sc["duration"]
    if "password" in sc:
        req.password = sc["password"]
    return simple(env, req)


def reinitialize_device(sc, env):
    req = ReinitializeDeviceRequest(reinitializedStateOfDevice=sc["state"])
    if "password" in sc:
        req.password = sc["password"]
    return simple(env, req)


def atomic_read_file(sc, env):
    data = b""
    pos = sc.get("start", 0)
    single = "count" in sc
    while True:
        req = AtomicReadFileRequest(
            fileIdentifier=objid(sc["object"]),
            accessMethod=AtomicReadFileRequestAccessMethodChoice(
                streamAccess=AtomicReadFileRequestAccessMethodChoiceStreamAccess(
                    fileStartPosition=pos, requestedOctetCount=sc["count"] if single else FILE_CHUNK)))
        resp, a = ack_or_answer(env, req)
        if a is not None:
            return a
        if not isinstance(resp, AtomicReadFileACK) or resp.accessMethod.streamAccess is None:
            raise Infra("unexpected answer %s" % type(resp).__name__)
        chunk = bytes(resp.accessMethod.streamAccess.fileData)
        data += chunk
        pos += len(chunk)
        if single or resp.endOfFile or not chunk:
            break
    return {"octets_base64": base64.b64encode(data).decode()}


def atomic_write_file(sc, env):
    req = AtomicWriteFileRequest(
        fileIdentifier=objid(sc["object"]),
        accessMethod=AtomicWriteFileRequestAccessMethodChoice(
            streamAccess=AtomicWriteFileRequestAccessMethodChoiceStreamAccess(
                fileStartPosition=sc.get("start", 0), fileData=base64.b64decode(sc["data_base64"]))))
    resp, a = ack_or_answer(env, req)
    if a is not None:
        return a
    return {"ack": True}


def list_element(sc, env, cls):
    elements = Any()
    elements.cast_in(ListOf(Destination)([destination(d) for d in sc["elements"]]))
    req = cls(objectIdentifier=objid(sc["object"]), propertyIdentifier=camel(sc["property"]),
              listOfElements=elements)
    return simple(env, req)


def create_object(sc, env):
    if "instance" in sc:
        spec = CreateObjectRequestObjectSpecifier(objectIdentifier=(camel(sc["object_type"]), sc["instance"]))
    else:
        spec = CreateObjectRequestObjectSpecifier(objectType=camel(sc["object_type"]))
    resp, a = ack_or_answer(env, CreateObjectRequest(objectSpecifier=spec))
    if a is not None:
        return a
    if not isinstance(resp, CreateObjectACK):
        raise Infra("unexpected answer %s" % type(resp).__name__)
    return {"created": objref(resp.objectIdentifier)}


def delete_object(sc, env):
    return simple(env, DeleteObjectRequest(objectIdentifier=objid(sc["object"])))


def get_event_information(sc, env):
    events, last = [], None
    while True:
        req = GetEventInformationRequest()
        if last is not None:
            req.lastReceivedObjectIdentifier = last
        resp, a = ack_or_answer(env, req)
        if a is not None:
            return a
        if not isinstance(resp, GetEventInformationACK):
            raise Infra("unexpected answer %s" % type(resp).__name__)
        for s in resp.listOfEventSummaries:
            events.append({"object": objref(s.objectIdentifier), "event_state": hyphen(s.eventState)})
            last = s.objectIdentifier
        if not resp.moreEvents or last is None:
            break
    return {"events": events}


def acknowledge_alarm(sc, env):
    oid = objid(sc["object"])
    state = sc["event_state_acked"]
    if sc["time_stamp"] == "event":
        req = ReadPropertyRequest(objectIdentifier=oid, propertyIdentifier="eventTimeStamps",
                                  propertyArrayIndex=TIME_STAMP_INDEX[state])
        resp, a = ack_or_answer(env, req)
        if a is not None or not isinstance(resp, ReadPropertyACK):
            raise Infra("Event_Time_Stamps of %s not readable: %s" % (sc["object"], a))
        stamp = resp.propertyValue.cast_out(TimeStamp)
    else:
        when = dt.datetime.strptime(sc["time_stamp"], "%Y-%m-%dT%H:%M:%S")
        stamp = TimeStamp(dateTime=bacnet_datetime(when))
    req = AcknowledgeAlarmRequest(
        acknowledgingProcessIdentifier=sc["process_id"], eventObjectIdentifier=oid,
        eventStateAcknowledged=camel(state), timeStamp=stamp, acknowledgmentSource="interop",
        timeOfAcknowledgment=TimeStamp(dateTime=bacnet_datetime(dt.datetime.now())))
    return simple(env, req)


def get_alarm_summary(sc, env):
    resp, a = ack_or_answer(env, GetAlarmSummaryRequest())
    if a is not None:
        return a
    if not isinstance(resp, GetAlarmSummaryACK):
        raise Infra("unexpected answer %s" % type(resp).__name__)
    return {"alarms": [{"object": objref(s.objectIdentifier), "alarm_state": hyphen(s.alarmState)}
                       for s in resp.listOfAlarmSummaries]}


def get_enrollment_summary(sc, env):
    req = GetEnrollmentSummaryRequest(acknowledgmentFilter="all")
    if "event_state_filter" in sc:
        req.eventStateFilter = camel(sc["event_state_filter"])
    resp, a = ack_or_answer(env, req)
    if a is not None:
        return a
    if not isinstance(resp, GetEnrollmentSummaryACK):
        raise Infra("unexpected answer %s" % type(resp).__name__)
    out = []
    for s in resp.listOfEnrollmentSummaries:
        e = {"object": objref(s.objectIdentifier), "event_state": hyphen(s.eventState),
             "event_type": hyphen(s.eventType), "priority": int(s.priority)}
        if s.notificationClass is not None:
            e["notification_class"] = int(s.notificationClass)
        out.append(e)
    return {"enrollments": out}


def sent(operation):
    return {"sent": {"operation": operation}}


def time_synchronization(sc, env, utc):
    now = dt.datetime.now(dt.timezone.utc) if utc else dt.datetime.now()
    cls = UTCTimeSynchronizationRequest if utc else TimeSynchronizationRequest
    env.unconfirmed(cls(time=bacnet_datetime(now)))
    return sent("utc-time-synchronization" if utc else "time-synchronization")


def private_parameters(sc):
    return any_of(*[scenario_value(v) for v in sc["parameters"]])


def unconfirmed_private_transfer(sc, env):
    req = UnconfirmedPrivateTransferRequest(vendorID=sc["vendor_id"], serviceNumber=sc["service_number"])
    if sc.get("parameters"):
        req.serviceParameters = private_parameters(sc)
    env.unconfirmed(req)
    return sent("unconfirmed-private-transfer")


def confirmed_private_transfer(sc, env):
    req = ConfirmedPrivateTransferRequest(vendorID=sc["vendor_id"], serviceNumber=sc["service_number"])
    if sc.get("parameters"):
        req.serviceParameters = private_parameters(sc)
    resp, a = ack_or_answer(env, req)
    if a is not None:
        return a
    if not isinstance(resp, ConfirmedPrivateTransferACK):
        raise Infra("unexpected answer %s" % type(resp).__name__)
    return {"ack": True}


def text_message(sc, env, confirmed):
    cls = ConfirmedTextMessageRequest if confirmed else UnconfirmedTextMessageRequest
    req = cls(textMessageSourceDevice=("device", CLIENT_INSTANCE),
              messagePriority=sc.get("message_priority", "normal"), message=sc["message"])
    if confirmed:
        return simple(env, req)
    env.unconfirmed(req)
    return sent("unconfirmed-text-message")


def channel_value(v):
    t = v["type"]
    table = {"null": ("null", lambda x: ()), "real": ("real", float), "unsigned": ("unsigned", int),
             "signed": ("integer", int), "boolean": ("boolean", bool), "enumerated": ("enumerated", int),
             "character-string": ("characterString", str)}
    if t not in table:
        raise Infra("channel value type %s is not encoded by this driver" % t)
    name, conv = table[t]
    return ChannelValue(**{name: conv(v.get("value"))})


def write_group(sc, env):
    changes = []
    for c in sc["changes"]:
        gcv = GroupChannelValue(channel=c["channel"], value=channel_value(c["value"]))
        if c.get("overriding_priority"):
            gcv.overridingPriority = c["overriding_priority"]
        changes.append(gcv)
    req = WriteGroupRequest(groupNumber=sc["group"], writePriority=sc["priority"], changeList=changes,
                            inhibitDelay=bool(sc.get("inhibit")))
    env.unconfirmed(req)
    return sent("write-group")


def bvlc_nak(res):
    code = int(res.bvlciResultCode)
    return BVLC_RESULTS.get(code, "0x%04x" % code)


def read_bdt(sc, env):
    bbmd = env.bbmd_address()
    ans = env.bvlc_request(ReadBroadcastDistributionTable(destination=bbmd), ReadBroadcastDistributionTableAck)
    if isinstance(ans, Result):
        return {"bvlc_result": bvlc_nak(ans)}
    me = hostport(bbmd)
    out = []
    for entry in ans.bvlciBDT:
        addr = hostport(entry)
        mask = ".".join(str(b) for b in entry.addrMask.to_bytes(4, "big")) if isinstance(entry.addrMask, int) \
            else str(entry.addrMask)
        out.append({"address": "bbmd" if addr == me else addr, "mask": mask})
    return {"bdt": out}


def read_fdt(sc, env):
    bbmd = env.bbmd_address()
    ans = env.bvlc_request(ReadForeignDeviceTable(destination=bbmd), ReadForeignDeviceTableAck)
    if isinstance(ans, Result):
        return {"bvlc_result": bvlc_nak(ans)}
    me = "%s:%d" % (env.my_ip, CLIENT_PORT)
    mine = [e for e in ans.bvlciFDT if hostport(e.fdAddress) == me]
    return {"fdt": {"contains_self": bool(mine), "ttl": int(mine[0].fdTTL) if mine else 0}}


def write_bdt(sc, env):
    bbmd = env.bbmd_address()
    entries = [Address(hostport(bbmd) if e == "bbmd" else e) for e in sc["bdt"]]
    ans = env.bvlc_request(WriteBroadcastDistributionTable(bdt=entries, destination=bbmd), Result)
    if not isinstance(ans, Result):
        raise Infra("no BVLC-Result for Write-Broadcast-Distribution-Table")
    return {"bvlc_result": bvlc_nak(ans)}


SERVICES = {
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


# --- comparison (as in the bacnet-stack and BACpypes3 drivers) ---------------------


def norm_time(s):
    h, rest = s.split(":", 1)
    return "%d:%s" % (int(h), rest)


def norm_destinations(ds):
    out = []
    for d in ds:
        d = dict(d)
        d["from_time"], d["to_time"] = norm_time(d["from_time"]), norm_time(d["to_time"])
        d["valid_days"], d["transitions"] = sorted(d["valid_days"]), sorted(d["transitions"])
        out.append(d)
    return out


def compare(expect, observed):
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
                if any(norm_name(ge.get(k, "")) != norm_name(w["error"][k]) for k in ("class", "code")):
                    return False
            elif "value" not in g or not same_value(g["value"], w["value"]):
                return False
        return True
    if key == "error":
        if any(norm_name(got.get(k, "")) != norm_name(want[k]) for k in ("class", "code")):
            return False
        if "first_failed" in want:
            ff = got.get("first_failed") or {}
            if ff.get("object") != want["first_failed"]["object"] or \
                    str(ff.get("property")) != str(want["first_failed"]["property"]):
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
        return len(got) == len(want) and all(
            all(norm_name(g.get(k)) == norm_name(w[k]) for k in w) for g, w in zip(got, want))
    if key in ("alarms", "events"):
        return len(got) == len(want) and all(
            all(norm_name(g.get(k)) == norm_name(w[k]) for k in w) for g, w in zip(got, want))
    return got == want


# --- main --------------------------------------------------------------------------


def scenarios(args, doc, env, start_error):
    try:
        emit({
            "event": "ready",
            "mode": "client",
            "adapter": ADAPTER,
            "version": os.environ.get("ADAPTER_VERSION", "dev"),
            "peer_version": os.environ.get("BACPYPES_VERSION", "unknown"),
            "scenarios": str(doc.get("id", "")),
        })
        if not start_error and args.bbmd:
            try:
                env.wait_registered()
            except Infra as exc:
                start_error = str(exc)
        only = {s for s in args.only.split(",") if s}
        summary = dict.fromkeys(OUTCOMES, 0)
        for sc in doc["scenarios"]:
            if only and sc["id"] not in only:
                continue
            begin = time.monotonic()
            line = {"event": "result", "scenario": sc["id"], "service": sc["service"]}
            fn = SERVICES.get(sc["service"])
            try:
                if start_error:
                    raise Infra(start_error)
                if fn is None:
                    raise Unsupported("%s has no request for %s in this driver" % (PEER, sc["service"]))
                observed = fn(sc, env)
                line["outcome"] = "pass" if compare(sc["expect"], observed) else "fail"
                line["observed"] = observed
            except Undecodable as exc:
                known = KNOWN_UNDECODABLE.get((exc.pdu_type, exc.service))
                if known is not None:
                    line["outcome"] = "known-difference"
                    line["detail"] = "%s; %s; answer octets '%s'" % (known, exc.error, exc.octets)
                else:
                    line["outcome"] = "fail"
                    line["observed"] = {"undecodable": exc.octets}
                    line["detail"] = str(exc)
            except Unsupported as exc:
                line["outcome"] = "unsupported"
                line["detail"] = str(exc)
            except Infra as exc:
                line["outcome"] = "infra-error"
                line["detail"] = str(exc)
            except Exception as exc:  # noqa: BLE001 - one scenario never stops the run
                line["outcome"] = "infra-error"
                line["detail"] = "%s: %s" % (type(exc).__name__, exc)
            line["durationMs"] = int((time.monotonic() - begin) * 1000)
            summary[line["outcome"]] += 1
            emit(line)
        emit({"event": "done", "summary": summary})
    finally:
        deferred(stop)


def main(argv):
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
            print("client: --%s must be IPv4:PORT" % name, file=sys.stderr)
            return 2
    try:
        with open(args.scenarios, encoding="utf-8") as f:
            doc = json.load(f)
        if not isinstance(doc.get("scenarios"), list):
            raise KeyError("scenarios")
    except (OSError, ValueError, KeyError, AttributeError) as exc:
        print("client: cannot read scenarios: %s" % exc, file=sys.stderr)
        return 2
    if doc.get("requires_bbmd") and not args.bbmd:
        print("client: %s requires --bbmd" % doc.get("id"), file=sys.stderr)
        return 2
    try:
        timeout_ms = int(os.environ.get("BACNET_CLIENT_TIMEOUT_MS", "3000"))
        retries = int(os.environ.get("BACNET_CLIENT_RETRIES", "1"))
    except ValueError:
        print("client: BACNET_CLIENT_TIMEOUT_MS and BACNET_CLIENT_RETRIES must be integers", file=sys.stderr)
        return 2
    env = Env(args, timeout_ms, retries)
    start_error = ""
    try:
        env.start()
    except OSError as exc:
        start_error = "cannot start the BACpypes application: %s" % exc
    enable_sleeping()
    worker = threading.Thread(target=scenarios, args=(args, doc, env, start_error), daemon=True)
    worker.start()
    run()
    worker.join(5)
    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
