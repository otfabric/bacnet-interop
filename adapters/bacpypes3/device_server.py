#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""BACpypes3 device server for bacnet-interop.

Loads device-baseline-v2 JSON, binds BACnet/IP, emits a single JSON Lines ready
event on stdout once the application is live, then serves until SIGTERM/SIGINT.
Diagnostics go to stderr.

Horizon 2 additions:
- ReinitializeDevice → SimpleACK (no process restart)
- Optional UnconfirmedEventNotification emit after the first ReadProperty when
  BACNET_EMIT_EVENT=1 (destination = request source; no fixed IPs in fixture)
- Trend Log objects in the fixture are skipped (BACpypes3 ReadRange server is
  NotImplementedError)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
from pathlib import Path
from typing import Any, Optional

from bacpypes3.apdu import (
    ComplexAckSequence,
    ConfirmedPrivateTransferRequest,
    ConfirmedRequestSequence,
    ConfirmedTextMessageRequest,
    GetEnrollmentSummaryACK,
    GetEnrollmentSummaryRequest,
    ReadPropertyRequest,
    ReinitializeDeviceRequest,
    SimpleAckPDU,
    TimeSynchronizationRequest,
    UnconfirmedEventNotificationRequest,
    UnconfirmedPrivateTransferRequest,
    UnconfirmedRequestSequence,
    UnconfirmedTextMessageRequest,
    UTCTimeSynchronizationRequest,
    VTCloseRequest,
    VTDataACK,
    VTDataRequest,
    VTOpenACK,
    VTOpenRequest,
    WriteGroupRequest,
    WritePropertyMultipleRequest,
    register_complex_ack_type,
    register_confirmed_request_type,
    register_unconfirmed_request_type,
)
from bacpypes3.app import Application
from bacpypes3.argparse import SimpleArgumentParser
from bacpypes3.basetypes import (
    AuditLogQueryParameters,
    AuditLogQueryParametersBySource,
    AuditLogQueryParametersByTarget,
    AuditLogRecord,
    AuditLogRecordLogDatum,
    AuditLogRecordResult,
    AuditNotification,
    AuditOperation,
    COVMultipleSubscriptionList,
    DateTime,
    DeviceAddress,
    ErrorType,
    EventState,
    EventType,
    GetEnrollmentSummaryEnrollmentSummary,
    LogStatus,
    NotifyType,
    Recipient,
    Segmentation,
    TimeStamp,
)
from bacpypes3.constructeddata import Any as AnyValue
from bacpypes3.constructeddata import Array, SequenceOf
from bacpypes3.errors import ExecutionError
from bacpypes3.local.analog import AnalogValueObjectCmd
from bacpypes3.local.binary import BinaryValueObjectCmd
from bacpypes3.primitivedata import Boolean, ObjectIdentifier, Real, Unsigned
from bacpypes3.service.device import DeviceCommunicationControlServices


FIXTURE_DEFAULT = "device-baseline-v2"
FIXTURE_PATH_DEFAULT = "/fixtures/device/device-baseline-v2.json"
PORT_DEFAULT = 47808


class InteropApplication(Application, DeviceCommunicationControlServices):
    """Stock Application plus the upstream DeviceCommunicationControl mixin.

    BACpypes3 0.0.110 ships DeviceCommunicationControlServices but does not mix
    it into Application. The mixin stores the state in ``self.smap``; the
    Application calls that same ApplicationServiceAccessPoint ``asap`` (it is
    the object that filters on ``dccEnableDisable``), so the name is aliased
    here. Service behaviour is entirely upstream.
    """

    @property
    def smap(self):  # type: ignore[no-untyped-def]
        return self.asap


def load_device_fixture(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("device fixture must be a JSON object")
    if "device_instance" not in data or "device_name" not in data:
        raise ValueError("device fixture requires device_instance and device_name")
    return data


def primary_ipv4() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        host = s.getsockname()[0]
        s.close()
        return host
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def interface_prefix(ip: str) -> int | None:
    """Prefix length of the local IPv4 subnet that holds ip, or None."""
    import fcntl
    import struct

    SIOCGIFADDR, SIOCGIFNETMASK = 0x8915, 0x891B
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _, name in socket.if_nameindex():
            ifreq = struct.pack("256s", name.encode()[:15])
            try:
                addr = socket.inet_ntoa(fcntl.ioctl(probe.fileno(), SIOCGIFADDR, ifreq)[20:24])
                if addr != ip:
                    continue
                mask = fcntl.ioctl(probe.fileno(), SIOCGIFNETMASK, ifreq)[20:24]
            except OSError:
                continue
            return bin(int.from_bytes(mask, "big")).count("1")
    finally:
        probe.close()
    return None


def resolve_numeric_address(address: str, *, with_prefix: bool = False) -> str:
    """Resolve host:<port> to a numeric IP[:/prefix]:port for BBMD.

    BACpypes3 HostNPort.address raises NotImplementedError for name-based hosts.
    BBMD local distribution also needs a broadcast-capable address (CIDR form).
    """
    host, sep, port = address.rpartition(":")
    if not sep:
        host, port = address, str(PORT_DEFAULT)
    # Strip an existing prefix length from the host part.
    prefix = ""
    if "/" in host:
        host, prefix = host.split("/", 1)
        prefix = "/" + prefix
    if host in ("", "host", "0.0.0.0", "::"):
        host = primary_ipv4()
    elif any(c.isalpha() for c in host):
        host = socket.gethostbyname(host)
    if with_prefix and not prefix:
        # The prefix of the interface gives BACpypes3 the subnet broadcast
        # address it listens on and sends to. Docker user-defined bridges are
        # /16 by default, which is the fallback when it cannot be read.
        detected = interface_prefix(host)
        prefix = f"/{detected}" if detected else "/16"
    return f"{host}{prefix}:{port}"


def emit_ready(
    adapter: str,
    version: str,
    fixture: str,
    port: int,
    peer_version: str,
) -> None:
    line = {
        "event": "ready",
        "adapter": adapter,
        "version": version,
        "fixture": fixture,
        "address": f"0.0.0.0:{port}",
        "peer_version": peer_version,
    }
    sys.stdout.write(json.dumps(line, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def emit_operation(operation: str, result: str = "accepted") -> None:
    """Adapter diagnostic JSON Lines event (not cross-stack semantics)."""
    line = {
        "event": "operation",
        "adapter": "bacpypes3",
        "operation": operation,
        "result": result,
    }
    sys.stdout.write(json.dumps(line, separators=(",", ":")) + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Evidence frames for services BACpypes3 has data types for but no APDU class.
#
# BACpypes3 0.0.110 ships the Clause 21 data types
# COVMultipleSubscriptionList, AuditNotification, AuditLogQueryParameters and
# AuditLogRecordResult, but no service class for SubscribeCOVPropertyMultiple,
# the audit notifications or AuditLogQuery. The classes below are the ADAPTER's
# declaration of the service frame (the few context-tagged fields around the
# upstream type); every structured parameter inside is decoded and encoded by
# the upstream type. Evidence drawn from them is therefore partial: upstream
# for the nested parameters, adapter-declared for the frame.
# ---------------------------------------------------------------------------


@register_confirmed_request_type
class SubscribeCOVPropertyMultipleRequest(ConfirmedRequestSequence):
    service_choice = 30
    _order = (
        "subscriberProcessIdentifier",
        "issueConfirmedNotifications",
        "lifetime",
        "maxNotificationDelay",
        "listOfCOVSubscriptionSpecifications",
    )
    subscriberProcessIdentifier = Unsigned(_context=0)
    issueConfirmedNotifications = Boolean(_context=1, _optional=True)
    lifetime = Unsigned(_context=2, _optional=True)
    maxNotificationDelay = Unsigned(_context=3, _optional=True)
    listOfCOVSubscriptionSpecifications = SequenceOf(COVMultipleSubscriptionList, _context=4)


@register_confirmed_request_type
class ConfirmedAuditNotificationRequest(ConfirmedRequestSequence):
    service_choice = 32
    _order = ("notifications",)
    notifications = SequenceOf(AuditNotification, _context=0)


@register_unconfirmed_request_type
class UnconfirmedAuditNotificationRequest(UnconfirmedRequestSequence):
    service_choice = 12
    _order = ("notifications",)
    notifications = SequenceOf(AuditNotification, _context=0)


@register_confirmed_request_type
class AuditLogQueryRequest(ConfirmedRequestSequence):
    service_choice = 33
    _order = ("auditLog", "queryParameters", "startAtSequenceNumber", "requestedCount")
    auditLog = ObjectIdentifier(_context=0)
    queryParameters = AuditLogQueryParameters(_context=1)
    startAtSequenceNumber = Unsigned(_context=2, _optional=True)
    requestedCount = Unsigned(_context=3)


@register_complex_ack_type
class AuditLogQueryACK(ComplexAckSequence):
    service_choice = 33
    _order = ("auditLog", "records", "noMoreItems")
    auditLog = ObjectIdentifier(_context=0)
    records = SequenceOf(AuditLogRecordResult, _context=1)
    noMoreItems = Boolean(_context=2)


def _oid(value: Any) -> Optional[dict[str, int]]:
    if value is None:
        return None
    return {"type": int(value[0]), "instance": int(value[1])}


def _opt_int(value: Any) -> Optional[int]:
    return None if value is None else int(value)


def _set_bits(value: Any) -> Optional[list[int]]:
    """Numbers of the bits set in a decoded bit string (None when absent)."""
    if value is None:
        return None
    return [i for i, bit in enumerate(value) if bit]


def emit_decoded(operation: str, decoder: str, fields: dict[str, Any]) -> None:
    """Operation line carrying the fields a BACpypes3 decoder extracted."""
    line = {
        "event": "operation",
        "adapter": "bacpypes3",
        "operation": operation,
        "result": "accepted",
        "decoder": decoder,
        "fields": fields,
    }
    sys.stdout.write(json.dumps(line, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def interop_audit_notifications(instance: int) -> list[AuditNotification]:
    """The two notifications the adapter reports with BACNET_EMIT_AUDIT=1.

    The first sets every field of BACnetAuditNotification; the second only the
    three required ones, with the target given as a BACnetAddress.
    """
    full = AuditNotification(
        sourceTimestamp=TimeStamp(sequenceNumber=7),
        targetTimestamp=TimeStamp(dateTime=DateTime(date=(126, 10, 10, 6), time=(12, 30, 0, 0))),
        sourceDevice=Recipient(device=("device", instance)),
        sourceObject=("device", instance),
        operation=AuditOperation("write"),
        sourceComment="interop-source",
        targetComment="interop-target",
        invokeID=5,
        sourceUserID=1001,
        sourceUserRole=3,
        targetDevice=Recipient(device=("device", instance)),
        targetObject=("analog-value", 1),
        targetProperty="presentValue",
        targetPriority=8,
        targetValue=AnyValue(Real(42.5)),
        currentValue=AnyValue(Real(21.5)),
        result=ErrorType(errorClass="property", errorCode="writeAccessDenied"),
    )
    minimal = AuditNotification(
        sourceDevice=Recipient(device=("device", instance)),
        operation=AuditOperation("general"),
        targetDevice=Recipient(address=DeviceAddress(networkNumber=7, macAddress=b"\x0a\x00\x00\x01\xba\xc0")),
    )
    return [full, minimal]


def truthy(v: Optional[str]) -> bool:
    if v is None:
        return False
    return v.strip().lower() in ("1", "true", "yes")


def install_horizon2_handlers(app: Application, fixture: dict[str, Any]) -> None:
    """Install ReinitializeDevice, WPM, messaging sinks, and optional EventNotification emit hooks."""
    instance = int(fixture["device_instance"])
    emit_event = truthy(os.environ.get("BACNET_EMIT_EVENT"))
    emitted = {"done": False}

    async def do_ReinitializeDeviceRequest(apdu: ReinitializeDeviceRequest) -> None:
        state = getattr(apdu, "reinitializedStateOfDevice", None)
        print(f"bacpypes3 ReinitializeDevice state={state!r}", file=sys.stderr, flush=True)
        await app.response(SimpleAckPDU(context=apdu))

    app.do_ReinitializeDeviceRequest = do_ReinitializeDeviceRequest  # type: ignore[method-assign]

    # Messaging / time / group sinks for device-baseline-v6 (B7d). Stock BACpypes3
    # has APDU codecs but no application do_* handlers — without these, confirmed
    # services Reject and unconfirmed services are silently dropped.
    async def do_TimeSynchronizationRequest(apdu: TimeSynchronizationRequest) -> None:
        emit_operation("time-synchronization")

    async def do_UTCTimeSynchronizationRequest(apdu: UTCTimeSynchronizationRequest) -> None:
        emit_operation("utc-time-synchronization")

    async def do_UnconfirmedTextMessageRequest(apdu: UnconfirmedTextMessageRequest) -> None:
        emit_operation("unconfirmed-text-message")

    async def do_ConfirmedTextMessageRequest(apdu: ConfirmedTextMessageRequest) -> None:
        emit_operation("confirmed-text-message")
        await app.response(SimpleAckPDU(context=apdu))

    async def do_UnconfirmedPrivateTransferRequest(apdu: UnconfirmedPrivateTransferRequest) -> None:
        emit_operation("unconfirmed-private-transfer")

    async def do_ConfirmedPrivateTransferRequest(apdu: ConfirmedPrivateTransferRequest) -> None:
        emit_operation("confirmed-private-transfer")
        await app.response(SimpleAckPDU(context=apdu))

    # GetEnrollmentSummary (adapter-shim). BACpypes3 has the request and ACK
    # types but no handler and no event-enrollment objects. The adapter lists
    # one fixed enrollment per Analog Value (out-of-range, priority 100,
    # notification class 1) and per Binary Value (change-of-state, priority
    # 200, notification class 2) of the fixture, all in event state normal and
    # acknowledged, and applies the request's filters to that list. The
    # request decoding and the ACK encoding are the stack's.
    async def do_GetEnrollmentSummaryRequest(apdu: GetEnrollmentSummaryRequest) -> None:
        table = {"analog-value": ("outOfRange", 100, 1), "binary-value": ("changeOfState", 200, 2)}
        ack_filter = int(apdu.acknowledgmentFilter)
        state_filter = None if apdu.eventStateFilter is None else int(apdu.eventStateFilter)
        type_filter = None if apdu.eventTypeFilter is None else int(apdu.eventTypeFilter)
        class_filter = None if apdu.notificationClassFilter is None else int(apdu.notificationClassFilter)
        prio = apdu.priorityFilter
        summaries = []
        for obj in fixture.get("objects", []):
            entry = table.get(obj.get("type"))
            if entry is None:
                continue
            event_type, priority, notification_class = entry
            if ack_filter == 2:  # notAcked: every enrollment is acknowledged
                continue
            if state_filter is not None and state_filter not in (2, 3):  # normal, all
                continue
            if type_filter is not None and type_filter != int(EventType(event_type)):
                continue
            if prio is not None and not (int(prio.minPriority) <= priority <= int(prio.maxPriority)):
                continue
            if class_filter is not None and class_filter != notification_class:
                continue
            summaries.append(
                GetEnrollmentSummaryEnrollmentSummary(
                    objectIdentifier=(obj["type"], int(obj["instance"])),
                    eventType=event_type,
                    eventState="normal",
                    priority=priority,
                    notificationClass=notification_class,
                )
            )
        emit_operation("get-enrollment-summary")
        await app.response(GetEnrollmentSummaryACK(listOfEnrollmentSummaries=summaries, context=apdu))

    app.do_GetEnrollmentSummaryRequest = do_GetEnrollmentSummaryRequest  # type: ignore[method-assign]

    async def do_WriteGroupRequest(apdu: WriteGroupRequest) -> None:
        emit_operation("write-group")

    app.do_TimeSynchronizationRequest = do_TimeSynchronizationRequest  # type: ignore[method-assign]
    app.do_UTCTimeSynchronizationRequest = do_UTCTimeSynchronizationRequest  # type: ignore[method-assign]
    app.do_UnconfirmedTextMessageRequest = do_UnconfirmedTextMessageRequest  # type: ignore[method-assign]
    app.do_ConfirmedTextMessageRequest = do_ConfirmedTextMessageRequest  # type: ignore[method-assign]
    app.do_UnconfirmedPrivateTransferRequest = do_UnconfirmedPrivateTransferRequest  # type: ignore[method-assign]
    app.do_ConfirmedPrivateTransferRequest = do_ConfirmedPrivateTransferRequest  # type: ignore[method-assign]
    app.do_WriteGroupRequest = do_WriteGroupRequest  # type: ignore[method-assign]

    # Stock BACpypes3 raises NotImplementedError for WPM; implement via write_property.
    async def do_WritePropertyMultipleRequest(apdu: WritePropertyMultipleRequest) -> None:
        for spec in apdu.listOfWriteAccessSpecs or []:
            obj = app.get_object_id(spec.objectIdentifier)
            if not obj:
                raise ExecutionError(errorClass="object", errorCode="unknownObject")
            for pw in spec.listOfProperties or []:
                property_type = obj.get_property_type(pw.propertyIdentifier)
                array_index = pw.propertyArrayIndex
                priority = pw.priority
                cast_type = property_type
                if issubclass(property_type, Array):
                    if array_index is None:
                        pass
                    elif array_index == 0:
                        cast_type = Unsigned
                    else:
                        cast_type = property_type._subtype
                property_value = pw.value.cast_out(
                    cast_type, null=(priority is not None)
                )
                await obj.write_property(
                    pw.propertyIdentifier, property_value, array_index, priority
                )
        await app.response(SimpleAckPDU(context=apdu))

    app.do_WritePropertyMultipleRequest = do_WritePropertyMultipleRequest  # type: ignore[method-assign]

    install_evidence_handlers(app, instance)

    if not emit_event:
        return

    orig_rp = app.do_ReadPropertyRequest

    async def do_ReadPropertyRequest(apdu: ReadPropertyRequest) -> None:
        await orig_rp(apdu)
        if emitted["done"]:
            return
        dest = getattr(apdu, "pduSource", None)
        if dest is None:
            return
        emitted["done"] = True
        # TimeStamp.as_sequenceNumber(n) is still buggy in 0.0.110 when n is not
        # None (UnboundLocalError: `now` only assigned in the None branch).
        note = UnconfirmedEventNotificationRequest(
            processIdentifier=1,
            initiatingDeviceIdentifier=("device", instance),
            eventObjectIdentifier=("analog-value", 1),
            timeStamp=TimeStamp(sequenceNumber=1),
            notificationClass=1,
            priority=100,
            eventType=EventType("changeOfState"),
            messageText="interop-event",
            notifyType=NotifyType("alarm"),
            ackRequired=False,
            fromState=EventState("normal"),
            toState=EventState("offnormal"),
        )
        note.pduDestination = dest
        try:
            await app.request(note)
            print(f"bacpypes3 emitted UnconfirmedEventNotification to {dest!r}", file=sys.stderr, flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"bacpypes3 event emit failed: {exc}", file=sys.stderr, flush=True)

    app.do_ReadPropertyRequest = do_ReadPropertyRequest  # type: ignore[method-assign]
    print("bacpypes3 BACNET_EMIT_EVENT=1 (emit once after first ReadProperty)", file=sys.stderr, flush=True)


def install_evidence_handlers(app: Application, instance: int) -> None:
    """Decode-evidence sinks: VT, SubscribeCOVPropertyMultiple, audit.

    Each handler reports the fields the BACpypes3 decoder extracted from the
    request in the operation line. None of them executes the service: there is
    no VT session, no COV-multiple subscription and no Audit Log object.
    """

    # --- Virtual terminal: upstream request and ACK classes -----------------
    async def do_VTOpenRequest(apdu: VTOpenRequest) -> None:
        local = int(apdu.localVTSessionIdentifier)
        emit_decoded(
            "vt-open",
            "bacpypes3.apdu.VTOpenRequest",
            {"vt_class": int(apdu.vtClass), "local_vt_session_identifier": local},
        )
        # The remote session identifier is derived from the local one so that
        # a test can tell the ACK belongs to its request.
        await app.response(VTOpenACK(remoteVTSessionIdentifier=(local + 100) % 256, context=apdu))

    async def do_VTDataRequest(apdu: VTDataRequest) -> None:
        emit_decoded(
            "vt-data",
            "bacpypes3.apdu.VTDataRequest",
            {
                "vt_session_identifier": int(apdu.vtSessionIdentifier),
                "vt_new_data_hex": bytes(apdu.vtNewData).hex(),
                "vt_data_flag": int(apdu.vtDataFlag),
            },
        )
        # accepted-octet-count is optional in the standard (present when not
        # all data was accepted) but a required element of BACpypes3's VTDataACK.
        await app.response(
            VTDataACK(allNewDataAccepted=True, acceptedOctetCount=len(bytes(apdu.vtNewData)), context=apdu)
        )

    async def do_VTCloseRequest(apdu: VTCloseRequest) -> None:
        emit_decoded(
            "vt-close",
            "bacpypes3.apdu.VTCloseRequest",
            {"remote_vt_session_identifiers": [int(v) for v in apdu.listOfRemoteVTSessionIdentifiers or []]},
        )
        await app.response(SimpleAckPDU(context=apdu))

    app.do_VTOpenRequest = do_VTOpenRequest  # type: ignore[attr-defined]
    app.do_VTDataRequest = do_VTDataRequest  # type: ignore[attr-defined]
    app.do_VTCloseRequest = do_VTCloseRequest  # type: ignore[attr-defined]

    # --- SubscribeCOVPropertyMultiple: adapter frame, upstream spec list ----
    async def do_SubscribeCOVPropertyMultipleRequest(apdu: SubscribeCOVPropertyMultipleRequest) -> None:
        specs = []
        for spec in apdu.listOfCOVSubscriptionSpecifications or []:
            refs = []
            for ref in spec.listOfCOVReferences or []:
                prop = ref.monitoredProperty
                refs.append(
                    {
                        "property_identifier": int(prop.propertyIdentifier),
                        "property_array_index": _opt_int(prop.propertyArrayIndex),
                        "cov_increment": None if ref.covIncrement is None else float(ref.covIncrement),
                        "timestamped": bool(ref.timestamped),
                    }
                )
            specs.append({"monitored_object_identifier": _oid(spec.monitoredObjectIdentifier), "cov_references": refs})
        issue = apdu.issueConfirmedNotifications
        emit_decoded(
            "subscribe-cov-property-multiple",
            "adapter frame + bacpypes3.basetypes.COVMultipleSubscriptionList",
            {
                "subscriber_process_identifier": int(apdu.subscriberProcessIdentifier),
                "issue_confirmed_notifications": None if issue is None else bool(issue),
                "lifetime": _opt_int(apdu.lifetime),
                "max_notification_delay": _opt_int(apdu.maxNotificationDelay),
                "cov_subscription_specifications": specs,
            },
        )
        await app.response(SimpleAckPDU(context=apdu))

    app.do_SubscribeCOVPropertyMultipleRequest = do_SubscribeCOVPropertyMultipleRequest  # type: ignore[attr-defined]

    # --- AuditLogQuery: adapter frame, upstream parameters and records ------
    async def do_AuditLogQueryRequest(apdu: AuditLogQueryRequest) -> None:
        params = apdu.queryParameters
        fields: dict[str, Any] = {
            "audit_log": _oid(apdu.auditLog),
            "start_at_sequence_number": _opt_int(apdu.startAtSequenceNumber),
            "requested_count": int(apdu.requestedCount),
        }
        target = params.byTarget
        source = params.bySource
        if target is not None:
            fields["by_target"] = {
                "target_device_identifier": _oid(target.targetDeviceIdentifier),
                "target_object_identifier": _oid(target.targetObjectIdentifier),
                "target_property_identifier": _opt_int(target.targetPropertyIdentifier),
                "target_array_index": _opt_int(target.targetArrayIndex),
                "target_priority": _opt_int(target.targetPriority),
                "operations": _set_bits(target.operations),
                "successful_actions_only": bool(target.successfulActionsOnly),
            }
        if source is not None:
            fields["by_source"] = {
                "source_device_identifier": _oid(source.sourceDeviceIdentifier),
                "source_object_identifier": _oid(source.sourceObjectIdentifier),
                "operations": _set_bits(source.operations),
                "successful_actions_only": bool(source.successfulActionsOnly),
            }
        emit_decoded(
            "audit-log-query",
            "adapter frame + bacpypes3.basetypes.AuditLogQueryParameters",
            fields,
        )
        # Two records, encoded by the upstream AuditLogRecordResult type. The
        # time-change alternative is left out: BACpypes3 declares it without
        # its context tag [2].
        first = int(apdu.startAtSequenceNumber) if apdu.startAtSequenceNumber is not None else 100
        stamp = DateTime(date=(126, 10, 10, 6), time=(12, 30, 0, 0))
        records = [
            AuditLogRecordResult(
                sequenceNumber=first,
                logRecord=AuditLogRecord(
                    timestamp=stamp,
                    logDatum=AuditLogRecordLogDatum(logStatus=LogStatus([0, 1, 0])),
                ),
            ),
            AuditLogRecordResult(
                sequenceNumber=first + 1,
                logRecord=AuditLogRecord(
                    timestamp=stamp,
                    logDatum=AuditLogRecordLogDatum(auditNotification=interop_audit_notifications(instance)[0]),
                ),
            ),
        ]
        await app.response(AuditLogQueryACK(auditLog=apdu.auditLog, records=records, noMoreItems=True, context=apdu))

    app.do_AuditLogQueryRequest = do_AuditLogQueryRequest  # type: ignore[attr-defined]

    # --- Audit notifications toward the client (BACNET_EMIT_AUDIT=1) --------
    if not truthy(os.environ.get("BACNET_EMIT_AUDIT")):
        return

    audit_emitted = {"done": False}
    orig_rp = app.do_ReadPropertyRequest

    async def emit_audit(dest: Any) -> None:
        notes = interop_audit_notifications(instance)
        try:
            unconfirmed = UnconfirmedAuditNotificationRequest(notifications=notes, destination=dest)
            await app.request(unconfirmed)
            emit_operation("emit-unconfirmed-audit-notification", "sent")
            confirmed = ConfirmedAuditNotificationRequest(notifications=notes, destination=dest)
            ack = await app.request(confirmed)
            if isinstance(ack, SimpleAckPDU):
                emit_operation("confirmed-audit-notification-ack", "simple-ack")
            else:
                emit_operation("confirmed-audit-notification-ack", f"unexpected:{type(ack).__name__}")
        except Exception as exc:  # noqa: BLE001
            print(f"bacpypes3 audit emit failed: {exc!r}", file=sys.stderr, flush=True)

    async def do_ReadPropertyRequest(apdu: ReadPropertyRequest) -> None:
        await orig_rp(apdu)
        dest = getattr(apdu, "pduSource", None)
        if audit_emitted["done"] or dest is None:
            return
        audit_emitted["done"] = True
        # Not awaited here: the confirmed notification waits for its SimpleACK.
        asyncio.get_running_loop().create_task(emit_audit(dest))

    app.do_ReadPropertyRequest = do_ReadPropertyRequest  # type: ignore[method-assign]
    print("bacpypes3 BACNET_EMIT_AUDIT=1 (audit notifications once after first ReadProperty)", file=sys.stderr, flush=True)


def build_app(
    fixture: dict[str, Any],
    address: str,
    max_apdu: Optional[int] = None,
    bbmd: bool = False,
    network: Optional[int] = None,
) -> Application:
    name = str(fixture["device_name"])
    instance = int(fixture["device_instance"])
    parser = SimpleArgumentParser()
    argv = [
        "--name",
        name,
        "--instance",
        str(instance),
        "--address",
        address,
        "--vendoridentifier",
        "999",
    ]
    if network is not None and network > 0:
        argv += ["--network", str(network)]
    if bbmd:
        # Enable BBMD and accept FD registrations. Include this device in the
        # BDT so Distribute-Broadcast-To-Network has a local distribution entry.
        # Bind + BDT must be numeric CIDR so BACpypes3 can compute a broadcast.
        address = resolve_numeric_address(address, with_prefix=True)
        argv[argv.index("--address") + 1] = address
        argv += ["--bbmd", address]
        print(f"bacpypes3 BBMD address/BDT={address}", file=sys.stderr, flush=True)
    args = parser.parse_args(argv)
    logging.getLogger().handlers.clear()
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

    app = InteropApplication.from_args(args)

    # Upstream reads the DeviceCommunicationControl password from the private
    # device-object attribute _dcc_password; unset or empty means "no check".
    dcc_password = os.environ.get("BACNET_DCC_PASSWORD", "")
    if dcc_password:
        app.device_object._dcc_password = dcc_password
        print("bacpypes3 DeviceCommunicationControl password configured", file=sys.stderr, flush=True)

    # Optional small MaxAPDU for segmented-response interop (default keeps BACpypes3's 1024).
    if max_apdu is not None and max_apdu > 0:
        device = getattr(app, "device_object", None) or getattr(app, "deviceObject", None)
        if device is None:
            # Application exposes the device object via objectIdentifier lookup.
            try:
                device = app.get_object_id(("device", instance))
            except Exception:  # noqa: BLE001
                device = None
        if device is None:
            raise RuntimeError("unable to locate device object to set maxApduLengthAccepted")
        device.maxApduLengthAccepted = int(max_apdu)
        # Keep segmentation enabled so oversized ComplexACKs can be segmented.
        if getattr(device, "segmentationSupported", None) is not None:
            device.segmentationSupported = Segmentation.segmentedBoth
        print(f"bacpypes3 maxApduLengthAccepted={max_apdu}", file=sys.stderr, flush=True)

    for obj in fixture.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        otype = obj.get("type")
        oinst = int(obj.get("instance", 0))
        oname = str(obj.get("object_name", otype))
        if otype == "device":
            continue
        if otype == "analog-value":
            # Commandable AV supports WriteProperty present-value (+ priority).
            app.add_object(
                AnalogValueObjectCmd(
                    objectIdentifier=("analog-value", oinst),
                    objectName=oname,
                    presentValue=float(obj.get("present_value", 0.0)),
                    covIncrement=0.1,
                    description=str(obj.get("description", f"{fixture.get('fixture', 'device')} analog value")),
                )
            )
        elif otype == "binary-value":
            app.add_object(
                BinaryValueObjectCmd(
                    objectIdentifier=("binary-value", oinst),
                    objectName=oname,
                    presentValue=str(obj.get("present_value", "inactive")),
                    description=str(obj.get("description", f"{fixture.get('fixture', 'device')} binary value")),
                )
            )
        elif otype == "analog-input":
            try:
                from bacpypes3.local.analog import AnalogInputObject
            except Exception:
                print("skipping analog-input (AnalogInputObject unavailable)", file=sys.stderr)
            else:
                app.add_object(
                    AnalogInputObject(
                        objectIdentifier=("analog-input", oinst),
                        objectName=oname,
                        presentValue=float(obj.get("present_value", 0.0)),
                        description=str(obj.get("description", f"{fixture.get('fixture', 'device')} analog input")),
                    )
                )
        elif otype in ("trend-log", "notification-class", "event-enrollment", "file", "audit-log", "life-safety-point", "life-safety-zone"):
            # Partial v3+: skip types without a stable local object implementation.
            print(f"skipping unsupported object type {otype!r}", file=sys.stderr)
        else:
            print(f"skipping unsupported object type {otype!r}", file=sys.stderr)

    install_horizon2_handlers(app, fixture)
    return app


async def _serve(
    fixture: dict[str, Any],
    address: str,
    ready_args: dict[str, Any],
    max_apdu: Optional[int],
    bbmd: bool,
    network: Optional[int],
) -> None:
    app = build_app(fixture, address, max_apdu=max_apdu, bbmd=bbmd, network=network)
    # Application is bound; announce readiness only after that completes.
    emit_ready(**ready_args)
    mode = "bbmd" if bbmd else "normal"
    print(f"bacpypes3 listening address={address} mode={mode}", file=sys.stderr, flush=True)

    stop = asyncio.get_running_loop().create_future()

    def _stop() -> None:
        if not stop.done():
            stop.set_result(None)

    loop = asyncio.get_running_loop()
    for sig in ("SIGINT", "SIGTERM"):
        try:
            import signal

            loop.add_signal_handler(getattr(signal, sig), _stop)
        except (NotImplementedError, RuntimeError, AttributeError):
            pass

    await stop
    if hasattr(app, "close"):
        close = getattr(app, "close")
        result = close()
        if asyncio.iscoroutine(result):
            await result


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="bacnet-interop BACpypes3 device server")
    p.add_argument("--port", type=int, default=int(os.environ.get("BACNET_IP_PORT", PORT_DEFAULT)))
    p.add_argument(
        "--fixture-file",
        default=os.environ.get("DEVICE_FIXTURE_FILE", FIXTURE_PATH_DEFAULT),
    )
    p.add_argument(
        "--fixture",
        default=os.environ.get("FIXTURE", FIXTURE_DEFAULT),
    )
    p.add_argument(
        "--address",
        default=os.environ.get("BACNET_DEVICE_ADDRESS", ""),
        help="BACpypes3 address (default: host:<port>)",
    )
    p.add_argument(
        "--max-apdu",
        type=int,
        default=int(os.environ.get("BACNET_MAX_APDU", "0")),
        help="Override device maxApduLengthAccepted (0 = BACpypes3 default). Use small values for segmented-response tests.",
    )
    p.add_argument(
        "--bbmd",
        action="store_true",
        default=os.environ.get("BACNET_BBMD", "").lower() in ("1", "true", "yes"),
        help="Run as BBMD accepting foreign-device registrations (BDT includes this device).",
    )
    p.add_argument(
        "--network",
        type=int,
        default=int(os.environ.get("BACNET_NETWORK", "0")),
        help="Optional BACnet network number for the local port (0 = unset).",
    )
    args = p.parse_args(argv)

    version = os.environ.get("ADAPTER_VERSION", "dev")
    peer_version = os.environ.get("BACPYPES3_VERSION", "unknown")
    address = args.address.strip() or f"host:{args.port}"
    if "/" not in address:
        # Without a prefix BACpypes3 binds the unicast address only and never
        # hears a broadcast Who-Is. A device on a subnet has a broadcast
        # address: give it the one of its interface.
        address = resolve_numeric_address(address, with_prefix=True)

    try:
        fixture = load_device_fixture(args.fixture_file)
    except Exception as exc:  # noqa: BLE001
        print(f"bacpypes3 adapter failed to load fixture: {exc}", file=sys.stderr)
        return 1

    fixture_id = str(fixture.get("fixture", args.fixture))
    ready_args = {
        "adapter": "bacpypes3",
        "version": version,
        "fixture": fixture_id,
        "port": args.port,
        "peer_version": peer_version,
    }

    max_apdu = args.max_apdu if args.max_apdu > 0 else None
    network = args.network if args.network > 0 else None
    try:
        asyncio.run(_serve(fixture, address, ready_args, max_apdu, args.bbmd, network))
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"bacpypes3 adapter failed to start: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
