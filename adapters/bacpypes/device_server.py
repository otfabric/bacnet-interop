#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Legacy BACpypes device server for bacnet-interop.

Runs one BACnet/IP device on the upstream ``bacpypes`` package (PyPI
bacpypes 0.19.0, the asyncore code base; not BACpypes3). The application is
the upstream stack wired like ``bacpypes.app.BIPSimpleApplication`` (or with
``bacpypes.bvllservice.BIPBBMD`` as its link layer when BACNET_BBMD=1), with
the upstream service capabilities mixed in:

    WhoIsIAmServices, WhoHasIHaveServices, ReadWritePropertyServices,
    ReadWritePropertyMultipleServices, ChangeOfValueServices, FileServices,
    DeviceCommunicationControlServices

Services upstream has an APDU class for but no server handler are supplied
by adapter code below, each marked ``adapter-shim`` (and so in
adapters/inventory.yaml): WritePropertyMultiple, ReadRange,
ReinitializeDevice, and the sinks for TimeSynchronization,
UTCTimeSynchronization, text messages, private transfer and WriteGroup, which
write an ``operation`` line. Everything else is answered by upstream:
Reject unrecognized-service for a confirmed service without a handler.

Writes the ready line on stdout once the socket is bound; diagnostics go to
stderr.
"""

import argparse
import base64
import json
import os
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import ADAPTER, emit, interface_prefix, local_ipv4, log, truthy  # noqa: E402

from bacpypes.apdu import (  # noqa: E402
    ConfirmedPrivateTransferACK,
    ReadRangeACK,
    SimpleAckPDU,
    WritePropertyMultipleError,
)
from bacpypes.app import ApplicationIOController  # noqa: E402
from bacpypes.appservice import ApplicationServiceAccessPoint, StateMachineAccessPoint  # noqa: E402
from bacpypes.basetypes import (  # noqa: E402
    DateTime,
    Destination,
    EngineeringUnits,
    LogRecord,
    LogRecordLogDatum,
    ObjectPropertyReference,
    ObjectTypesSupported,
    ResultFlags,
    StatusFlags,
)
from bacpypes.bvllservice import AnnexJCodec, BIPBBMD, BIPSimple, UDPMultiplexer  # noqa: E402
from bacpypes.comm import bind  # noqa: E402
from bacpypes.constructeddata import Array, List, SequenceOfAny  # noqa: E402
from bacpypes.core import run, stop  # noqa: E402
from bacpypes.errors import ExecutionError, UndefinedEnumeration  # noqa: E402
from bacpypes.local.device import LocalDeviceObject  # noqa: E402
from bacpypes.local.file import LocalRecordAccessFileObject, LocalStreamAccessFileObject  # noqa: E402
from bacpypes.local.object import AnalogValueCmdObject, BinaryValueCmdObject  # noqa: E402
from bacpypes.netservice import NetworkServiceAccessPoint, NetworkServiceElement  # noqa: E402
from bacpypes.object import (  # noqa: E402
    register_object_type,
    AnalogInputObject,
    LifeSafetyPointObject,
    LifeSafetyZoneObject,
    NotificationClassObject,
    PropertyError,
    TrendLogObject,
)
from bacpypes.pdu import Address  # noqa: E402
from bacpypes.primitivedata import Date, Null, Time, Unsigned  # noqa: E402
from bacpypes.service.cov import ChangeOfValueServices  # noqa: E402
from bacpypes.service.device import (  # noqa: E402
    DeviceCommunicationControlServices,
    WhoHasIHaveServices,
    WhoIsIAmServices,
)
from bacpypes.service.file import FileServices  # noqa: E402
from bacpypes.service.object import ReadWritePropertyMultipleServices, ReadWritePropertyServices  # noqa: E402

PORT_DEFAULT = 47808
FIXTURE_PATH_DEFAULT = "/fixtures/device/device-baseline-v2.json"
VENDOR_ID = 999


def operation(name, result="accepted", **fields):
    line = {"event": "operation", "adapter": ADAPTER, "operation": name, "result": result}
    line.update(fields)
    emit(line)


# --- the application ---------------------------------------------------------


# --- adapter shims ------------------------------------------------------------


class ShimServices:
    """Handlers for services upstream decodes and encodes but does not serve.

    Each is adapter-shim (adapters/inventory.yaml): the request is decoded by
    the upstream APDU class and the answer encoded by the upstream ACK or
    Error class; only the service procedure is the adapter's.
    """

    # adapter-shim: upstream's do_WritePropertyMultipleRequest is commented
    # out in bacpypes/service/object.py. The procedure follows clause 15.10:
    # the writes run in order, a failure stops the remaining ones and is
    # answered with WritePropertyMultiple-Error naming the first failed write.
    # The conversion of each value is upstream's do_WritePropertyRequest.
    def do_WritePropertyMultipleRequest(self, apdu):
        for spec in apdu.listOfWriteAccessSpecs:
            objid = spec.objectIdentifier
            obj = self.get_object_id(objid)
            for pv in spec.listOfProperties:
                try:
                    if obj is None:
                        raise ExecutionError(errorClass="object", errorCode="unknownObject")
                    self._write_one(obj, pv.propertyIdentifier, pv.propertyArrayIndex, pv.value, pv.priority)
                except ExecutionError as err:
                    resp = WritePropertyMultipleError(context=apdu)
                    resp.errorType = _error_type(err.errorClass, err.errorCode)
                    resp.firstFailedWriteAttempt = ObjectPropertyReference(
                        objectIdentifier=objid,
                        propertyIdentifier=pv.propertyIdentifier,
                        propertyArrayIndex=pv.propertyArrayIndex,
                    )
                    self.response(resp)
                    return
            if obj is None:
                # An empty list of properties for an unknown object.
                raise ExecutionError(errorClass="object", errorCode="unknownObject")
        operation("write-property-multiple")
        self.response(SimpleAckPDU(context=apdu))

    def _write_one(self, obj, prop, index, value, priority):
        # Mirrors bacpypes.service.object.ReadWritePropertyServices
        # .do_WritePropertyRequest; a value that does not cast is
        # invalid-data-type (upstream lets that exception through as
        # device/operational-problem).
        try:
            if obj.ReadProperty(prop, index) is None:
                raise PropertyError(prop)
        except PropertyError:
            raise ExecutionError(errorClass="property", errorCode="unknownProperty")
        if value.is_application_class_null():
            datatype = Null
        else:
            datatype = obj.get_datatype(prop)
        try:
            if issubclass(datatype, Array) and index is not None:
                cast = Unsigned if index == 0 else datatype.subtype
                v = value.cast_out(cast)
            else:
                v = value.cast_out(datatype)
        except ExecutionError:
            raise
        except Exception:  # noqa: BLE001 - upstream raises plain exceptions
            raise ExecutionError(errorClass="property", errorCode="invalidDataType")
        obj.WriteProperty(prop, v, index, priority)

    # adapter-shim: ReadRange (clause 15.8) of a List property, by position
    # or by sequence number; upstream has ReadRangeRequest/ReadRangeACK but
    # no handler (samples/ReadRangeServer.py returns the whole list whatever
    # the range).
    def do_ReadRangeRequest(self, apdu):
        obj = self.get_object_id(apdu.objectIdentifier)
        if obj is None:
            raise ExecutionError(errorClass="object", errorCode="unknownObject")
        datatype = obj.get_datatype(apdu.propertyIdentifier)
        if datatype is None:
            raise ExecutionError(errorClass="property", errorCode="unknownProperty")
        if not issubclass(datatype, List):
            raise ExecutionError(errorClass="services", errorCode="propertyIsNotAList")
        if apdu.propertyArrayIndex is not None:
            raise ExecutionError(errorClass="property", errorCode="propertyIsNotAnArray")
        items = list(obj.ReadProperty(apdu.propertyIdentifier) or [])
        n = len(items)
        first_seq = None
        if apdu.range is None:
            lo, hi = 1, n
        elif apdu.range.byPosition is not None:
            ref, count = int(apdu.range.byPosition.referenceIndex), int(apdu.range.byPosition.count)
            lo, hi = _window(ref, count)
        elif apdu.range.bySequenceNumber is not None:
            # Records are numbered 1..n: the position is the sequence number.
            ref, count = int(apdu.range.bySequenceNumber.referenceSequenceNumber), int(apdu.range.bySequenceNumber.count)
            lo, hi = _window(ref, count)
        else:
            raise ExecutionError(errorClass="services", errorCode="optionalFunctionalityNotSupported")
        lo, hi = max(lo, 1), min(hi, n)
        chosen = items[lo - 1:hi] if lo <= hi else []
        if chosen and apdu.range is not None and apdu.range.bySequenceNumber is not None:
            first_seq = lo
        resp = ReadRangeACK(context=apdu)
        resp.objectIdentifier = apdu.objectIdentifier
        resp.propertyIdentifier = apdu.propertyIdentifier
        resp.resultFlags = ResultFlags([int(bool(chosen) and lo == 1), int(bool(chosen) and hi == n), 0])
        resp.itemCount = len(chosen)
        resp.itemData = SequenceOfAny()
        resp.itemData.cast_in(datatype(chosen))
        if first_seq is not None:
            resp.firstSequenceNumber = first_seq
        self.response(resp)

    # adapter-shim: ReinitializeDevice (clause 16.4) is acknowledged without
    # restarting; the password is checked against BACNET_DCC_PASSWORD like
    # upstream's DeviceCommunicationControl handler does.
    def do_ReinitializeDeviceRequest(self, apdu):
        # Upstream decodes a state outside its enumeration as a number; the
        # shim rejects it (clause 18.8, undefined-enumeration).
        if isinstance(apdu.reinitializedStateOfDevice, int):
            raise UndefinedEnumeration("reinitialized-state-of-device")
        password = getattr(self.localDevice, "_dcc_password", None)
        if password and apdu.password != password:
            raise ExecutionError(errorClass="security", errorCode="passwordFailure")
        operation("reinitialize-device", state=str(apdu.reinitializedStateOfDevice))
        self.response(SimpleAckPDU(context=apdu))

    # adapter diagnostics: sinks that report what upstream decoded.
    def do_TimeSynchronizationRequest(self, apdu):
        operation("time-synchronization")

    def do_UTCTimeSynchronizationRequest(self, apdu):
        operation("utc-time-synchronization")

    def do_UnconfirmedTextMessageRequest(self, apdu):
        operation("unconfirmed-text-message", message=str(apdu.message))

    def do_ConfirmedTextMessageRequest(self, apdu):
        operation("confirmed-text-message", message=str(apdu.message))
        self.response(SimpleAckPDU(context=apdu))

    def do_UnconfirmedPrivateTransferRequest(self, apdu):
        operation("unconfirmed-private-transfer", vendor_id=int(apdu.vendorID), service_number=int(apdu.serviceNumber))

    def do_ConfirmedPrivateTransferRequest(self, apdu):
        operation("confirmed-private-transfer", vendor_id=int(apdu.vendorID), service_number=int(apdu.serviceNumber))
        self.response(ConfirmedPrivateTransferACK(
            context=apdu, vendorID=apdu.vendorID, serviceNumber=apdu.serviceNumber))

    def do_WriteGroupRequest(self, apdu):
        operation("write-group", group=int(apdu.groupNumber))


def _window(ref, count):
    """Positions lo..hi of a by-position range (clause 15.8.1.1.4.1)."""
    if count >= 0:
        return ref, ref + count - 1
    return ref + count + 1, ref


def _error_type(cls, code):
    from bacpypes.basetypes import ErrorType

    return ErrorType(errorClass=cls, errorCode=code)


class DeviceApplication(
    ShimServices,
    ApplicationIOController,
    WhoIsIAmServices,
    WhoHasIHaveServices,
    ReadWritePropertyServices,
    ReadWritePropertyMultipleServices,
    ChangeOfValueServices,
    FileServices,
    DeviceCommunicationControlServices,
):
    """The upstream stack of BIPSimpleApplication with every upstream server
    capability mixed in. With bbmd the link layer is BIPBBMD instead of
    BIPSimple; the rest of the stack is the same.

    The capabilities are direct bases on purpose: upstream's
    Collector._search_capability (bacpypes/capability.py) collects the
    capabilities of a base class's bases with ``map(rslt.append, ...)``,
    which Python 3 never evaluates, so a capability one level down is never
    initialised (DeviceCommunicationControlServices then fails with
    AttributeError _dcc_enable_task, ChangeOfValueServices with
    cov_detections).
    """

    def __init__(self, device, address, bbmd=False):
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
            self.bip = BIPBBMD(address)
            # The BBMD's own entry: with it, BIPBBMD re-broadcasts a
            # Distribute-Broadcast-To-Network or a Forwarded-NPDU on the
            # local subnet (bvllservice.py BIPBBMD.confirmation). Given
            # without a prefix, the entry's broadcast distribution mask is
            # 255.255.255.255 (clause J.4.3.2, two-hop distribution).
            host = address.addrTuple[0]
            self.bip.add_peer(Address("%s:%d" % (host, address.addrPort)))
        else:
            self.bip = BIPSimple()
        self.annexj = AnnexJCodec()
        self.mux = UDPMultiplexer(address)
        bind(self.bip, self.annexj, self.mux.annexJ)
        self.nsap.bind(self.bip, address=address)

    def close_socket(self):
        self.mux.close_socket()


# The commandable classes of bacpypes.local.object are not registered: until
# they are, an instance reads its properties from the registered base class,
# where Present_Value is read-only (WriteProperty answers write-access-denied).
# Registering them for the vendor is how upstream's samples/CommandableMixin.py
# uses them.
register_object_type(AnalogValueCmdObject, vendor_id=VENDOR_ID)
register_object_type(BinaryValueCmdObject, vendor_id=VENDOR_ID)


# --- fixture objects ------------------------------------------------------------


class StreamFile(LocalStreamAccessFileObject):
    """Stream-access File object backed by bytes (upstream leaves the storage
    abstract, as samples/ReadWriteFileServer.py does)."""

    def __init__(self, data, **kwargs):
        self._data = bytearray(data)
        LocalStreamAccessFileObject.__init__(self, fileSize=len(data), **kwargs)

    def __len__(self):
        return len(self._data)

    def read_stream(self, start, count):
        chunk = bytes(self._data[start:start + count])
        return start + count >= len(self._data), chunk

    def write_stream(self, start, data):
        # Clause 14.2.1.2: a start of -1 appends.
        if start < 0:
            start = len(self._data)
        if start > len(self._data):
            raise ExecutionError(errorClass="services", errorCode="invalidFileStartPosition")
        self._data[start:start + len(data)] = data
        self.fileSize = len(self._data)
        return start


class RecordFile(LocalRecordAccessFileObject):
    """Record-access File object backed by a list of octet strings."""

    def __init__(self, records, **kwargs):
        self._records = [bytes(r) for r in records]
        LocalRecordAccessFileObject.__init__(
            self, fileSize=sum(len(r) for r in records), recordCount=len(records), **kwargs)

    def __len__(self):
        return len(self._records)

    def read_record(self, start, count):
        chosen = self._records[start:start + count]
        return start + count >= len(self._records), chosen

    def write_record(self, start, count, data):
        if start < 0:
            start = len(self._records)
        if start > len(self._records):
            raise ExecutionError(errorClass="services", errorCode="invalidFileStartPosition")
        self._records[start:start + len(data)] = [bytes(r) for r in data]
        self.recordCount = len(self._records)
        self.fileSize = sum(len(r) for r in self._records)
        return start


def _status_flags():
    return StatusFlags([0, 0, 0, 0])


def _datetime(text):
    """A fixture timestamp YYYY-MM-DDTHH:MM:SS as a BACnet DateTime."""
    import datetime as dt

    when = dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
    return DateTime(
        date=Date((when.year - 1900, when.month, when.day, when.isoweekday())).value,
        time=Time((when.hour, when.minute, when.second, 0)).value,
    )


def build_objects(fixture):
    """Upstream object classes for the fixture's objects; types the adapter
    cannot represent are skipped with a note on stderr."""
    out = []
    for o in fixture.get("objects") or []:
        otype = o.get("type")
        inst = int(o.get("instance", 0))
        name = str(o.get("object_name", "%s-%d" % (otype, inst)))
        desc = str(o.get("description", ""))[:255]
        common = {"objectName": name, "description": desc}
        if otype == "device":
            continue
        # The fixture's present_value is the value with nothing commanded:
        # Relinquish_Default, which upstream's Commandable otherwise sets to
        # the datatype's default (0.0, inactive).
        if otype == "analog-value":
            obj = AnalogValueCmdObject(
                objectIdentifier=("analogValue", inst),
                presentValue=float(o.get("present_value", 0.0)),
                relinquishDefault=float(o.get("present_value", 0.0)),
                statusFlags=_status_flags(),
                eventState="normal",
                outOfService=False,
                units=EngineeringUnits("noUnits"),
                covIncrement=0.1,
                **common)
        elif otype == "binary-value":
            obj = BinaryValueCmdObject(
                objectIdentifier=("binaryValue", inst),
                presentValue=str(o.get("present_value", "inactive")),
                relinquishDefault=str(o.get("present_value", "inactive")),
                statusFlags=_status_flags(),
                eventState="normal",
                outOfService=False,
                **common)
        elif otype == "analog-input":
            obj = AnalogInputObject(
                objectIdentifier=("analogInput", inst),
                presentValue=float(o.get("present_value", 0.0)),
                statusFlags=_status_flags(),
                eventState="normal",
                outOfService=False,
                units=EngineeringUnits("noUnits"),
                covIncrement=0.1,
                **common)
        elif otype == "notification-class":
            obj = NotificationClassObject(
                objectIdentifier=("notificationClass", inst),
                notificationClass=inst,
                priority=[255, 255, 255],
                ackRequired=[0, 0, 0],
                recipientList=[],
                **common)
        elif otype == "trend-log":
            records = []
            for rec in o.get("log_buffer") or []:
                records.append(LogRecord(
                    timestamp=_datetime(rec["timestamp"]),
                    logDatum=LogRecordLogDatum(realValue=float(rec["real"])),
                    statusFlags=_status_flags(),
                ))
            obj = TrendLogObject(
                objectIdentifier=("trendLog", inst),
                enable=True,
                stopWhenFull=False,
                bufferSize=max(len(records), 1),
                logBuffer=records,
                recordCount=len(records),
                totalRecordCount=len(records),
                eventState="normal",
                statusFlags=_status_flags(),
                loggingType="polled",
                **common)
        elif otype == "file" and o.get("access_method") == "record":
            obj = RecordFile(
                [r.encode() for r in o.get("records") or []],
                objectIdentifier=("file", inst), fileType="interop", readOnly=False, archive=False,
                modificationDate=_datetime("2009-01-01T00:00:00"), **common)
        elif otype == "file":
            obj = StreamFile(
                base64.b64decode(o.get("stream_data_base64", "")),
                objectIdentifier=("file", inst), fileType="interop", readOnly=False, archive=False,
                modificationDate=_datetime("2009-01-01T00:00:00"), **common)
        elif otype == "life-safety-point":
            obj = LifeSafetyPointObject(
                objectIdentifier=("lifeSafetyPoint", inst), presentValue="quiet", trackingValue="quiet",
                statusFlags=_status_flags(), eventState="normal", outOfService=False, reliability="noFaultDetected",
                mode="on", acceptedModes=["on", "off"], silenced="unsilenced", operationExpected="none", **common)
        elif otype == "life-safety-zone":
            obj = LifeSafetyZoneObject(
                objectIdentifier=("lifeSafetyZone", inst), presentValue="quiet", trackingValue="quiet",
                statusFlags=_status_flags(), eventState="normal", outOfService=False, reliability="noFaultDetected",
                mode="on", acceptedModes=["on", "off"], silenced="unsilenced", operationExpected="none",
                zoneMembers=[], **common)
        else:
            log("skipping object type %r (no adapter mapping)" % (otype,))
            continue
        out.append(obj)
    return out


# --- main -----------------------------------------------------------------------


def main(argv=None):
    p = argparse.ArgumentParser(description="bacnet-interop legacy BACpypes device server")
    p.add_argument("--port", type=int, default=int(os.environ.get("BACNET_IP_PORT", PORT_DEFAULT)))
    p.add_argument("--fixture-file", default=os.environ.get("DEVICE_FIXTURE_FILE", FIXTURE_PATH_DEFAULT))
    args = p.parse_args(argv)

    try:
        with open(args.fixture_file, encoding="utf-8") as f:
            fixture = json.load(f)
        instance = int(fixture["device_instance"])
        device_name = str(fixture["device_name"])
    except (OSError, ValueError, KeyError) as exc:
        log("cannot load fixture %s: %s" % (args.fixture_file, exc))
        return 1

    ip = os.environ.get("BACNET_DEVICE_ADDRESS", "").strip() or local_ipv4()
    if "/" not in ip:
        # The prefix gives upstream's UDPMultiplexer the subnet broadcast
        # address, on which it opens a second socket (bvllservice.py).
        ip = "%s/%d" % (ip, interface_prefix(ip) or 16)
    address = Address("%s:%d" % (ip, args.port))

    max_apdu = int(os.environ.get("BACNET_MAX_APDU", "0") or 0)
    device = LocalDeviceObject(
        objectName=device_name,
        objectIdentifier=("device", instance),
        vendorIdentifier=VENDOR_ID,
        vendorName="otfabric bacnet-interop",
        modelName="bacpypes adapter",
        firmwareRevision=os.environ.get("BACPYPES_VERSION", "unknown"),
        applicationSoftwareVersion=os.environ.get("ADAPTER_VERSION", "dev"),
        protocolVersion=1,
        protocolRevision=22,
        systemStatus="operational",
        databaseRevision=1,
        maxApduLengthAccepted=max_apdu if max_apdu > 0 else 1024,
        segmentationSupported="segmentedBoth",
        maxSegmentsAccepted=int(os.environ.get("BACNET_MAX_SEGMENTS", "16")),
        deviceAddressBinding=[],
        description=str(fixture.get("description", ""))[:255],
    )
    password = os.environ.get("BACNET_DCC_PASSWORD", "")
    if password:
        # Where upstream's DeviceCommunicationControlServices reads it.
        device._dcc_password = password

    bbmd = truthy(os.environ.get("BACNET_BBMD"))
    app = DeviceApplication(device, address, bbmd=bbmd)
    window = int(os.environ.get("BACNET_SEGMENT_WINDOW", "0") or 0)
    if window > 0:
        app.smap.proposedWindowSize = window
    for obj in build_objects(fixture):
        app.add_object(obj)

    supported = ObjectTypesSupported()
    for obj in app.iter_objects():
        supported[obj.objectType] = 1
    device.protocolObjectTypesSupported = supported

    def _stop(*_):
        stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    emit({
        "event": "ready",
        "adapter": ADAPTER,
        "version": os.environ.get("ADAPTER_VERSION", "dev"),
        "fixture": str(fixture.get("fixture", "")),
        "address": "0.0.0.0:%d" % args.port,
        "peer_version": os.environ.get("BACPYPES_VERSION", "unknown"),
    })
    log("listening on %s (%s), %d objects, max APDU %d, window %d" % (
        address, "bbmd" if bbmd else "simple", len(app.objectIdentifier),
        device.maxApduLengthAccepted, app.smap.proposedWindowSize))
    run()
    app.close_socket()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
