// SPDX-License-Identifier: MIT
package com.otfabric.bacnetinterop;

import java.io.PrintStream;
import java.net.Inet4Address;
import java.net.InetSocketAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collections;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.serotonin.bacnet4j.LocalDevice;
import com.serotonin.bacnet4j.RemoteDevice;
import com.serotonin.bacnet4j.RemoteObject;
import com.serotonin.bacnet4j.enums.DayOfWeek;
import com.serotonin.bacnet4j.enums.Month;
import com.serotonin.bacnet4j.event.DeviceEventAdapter;
import com.serotonin.bacnet4j.exception.AbortAPDUException;
import com.serotonin.bacnet4j.exception.BACnetException;
import com.serotonin.bacnet4j.exception.BACnetTimeoutException;
import com.serotonin.bacnet4j.exception.ErrorAPDUException;
import com.serotonin.bacnet4j.exception.RejectAPDUException;
import com.serotonin.bacnet4j.npdu.ip.IpNetwork;
import com.serotonin.bacnet4j.npdu.ip.IpNetworkBuilder;
import com.serotonin.bacnet4j.npdu.ip.IpNetworkUtils;
import com.serotonin.bacnet4j.service.Service;
import com.serotonin.bacnet4j.service.acknowledgement.AcknowledgementService;
import com.serotonin.bacnet4j.service.acknowledgement.AtomicReadFileAck;
import com.serotonin.bacnet4j.service.acknowledgement.CreateObjectAck;
import com.serotonin.bacnet4j.service.acknowledgement.GetAlarmSummaryAck;
import com.serotonin.bacnet4j.service.acknowledgement.GetEnrollmentSummaryAck;
import com.serotonin.bacnet4j.service.acknowledgement.GetEventInformationAck;
import com.serotonin.bacnet4j.service.acknowledgement.ReadPropertyAck;
import com.serotonin.bacnet4j.service.acknowledgement.ReadPropertyMultipleAck;
import com.serotonin.bacnet4j.service.acknowledgement.ReadRangeAck;
import com.serotonin.bacnet4j.service.confirmed.AcknowledgeAlarmRequest;
import com.serotonin.bacnet4j.service.confirmed.AddListElementRequest;
import com.serotonin.bacnet4j.service.confirmed.AtomicReadFileRequest;
import com.serotonin.bacnet4j.service.confirmed.AtomicWriteFileRequest;
import com.serotonin.bacnet4j.service.confirmed.ConfirmedCovNotificationMultipleRequest;
import com.serotonin.bacnet4j.service.confirmed.ConfirmedPrivateTransferRequest;
import com.serotonin.bacnet4j.service.confirmed.ConfirmedRequestService;
import com.serotonin.bacnet4j.service.confirmed.ConfirmedTextMessageRequest;
import com.serotonin.bacnet4j.service.confirmed.CreateObjectRequest;
import com.serotonin.bacnet4j.service.confirmed.DeleteObjectRequest;
import com.serotonin.bacnet4j.service.confirmed.DeviceCommunicationControlRequest;
import com.serotonin.bacnet4j.service.confirmed.GetAlarmSummaryRequest;
import com.serotonin.bacnet4j.service.confirmed.GetEnrollmentSummaryRequest;
import com.serotonin.bacnet4j.service.confirmed.GetEventInformationRequest;
import com.serotonin.bacnet4j.service.confirmed.ReadPropertyMultipleRequest;
import com.serotonin.bacnet4j.service.confirmed.ReadPropertyRequest;
import com.serotonin.bacnet4j.service.confirmed.ReadRangeRequest;
import com.serotonin.bacnet4j.service.confirmed.ReinitializeDeviceRequest;
import com.serotonin.bacnet4j.service.confirmed.RemoveListElementRequest;
import com.serotonin.bacnet4j.service.confirmed.SubscribeCOVPropertyMultipleRequest;
import com.serotonin.bacnet4j.service.confirmed.SubscribeCOVPropertyMultipleRequest.CovSubscriptionSpecification;
import com.serotonin.bacnet4j.service.confirmed.SubscribeCOVPropertyMultipleRequest.CovSubscriptionSpecification.CovReference;
import com.serotonin.bacnet4j.service.confirmed.SubscribeCOVPropertyRequest;
import com.serotonin.bacnet4j.service.confirmed.SubscribeCOVRequest;
import com.serotonin.bacnet4j.service.confirmed.WritePropertyMultipleRequest;
import com.serotonin.bacnet4j.service.confirmed.WritePropertyRequest;
import com.serotonin.bacnet4j.service.unconfirmed.TimeSynchronizationRequest;
import com.serotonin.bacnet4j.service.unconfirmed.UTCTimeSynchronizationRequest;
import com.serotonin.bacnet4j.service.unconfirmed.UnconfirmedCovNotificationMultipleRequest;
import com.serotonin.bacnet4j.service.unconfirmed.UnconfirmedPrivateTransferRequest;
import com.serotonin.bacnet4j.service.unconfirmed.UnconfirmedRequestService;
import com.serotonin.bacnet4j.service.unconfirmed.UnconfirmedTextMessageRequest;
import com.serotonin.bacnet4j.service.unconfirmed.WhoHasRequest;
import com.serotonin.bacnet4j.service.unconfirmed.WhoIsRequest;
import com.serotonin.bacnet4j.service.unconfirmed.WriteGroupRequest;
import com.serotonin.bacnet4j.transport.DefaultTransport;
import com.serotonin.bacnet4j.type.Encodable;
import com.serotonin.bacnet4j.type.constructed.Address;
import com.serotonin.bacnet4j.type.constructed.ChannelValue;
import com.serotonin.bacnet4j.type.constructed.DateTime;
import com.serotonin.bacnet4j.type.constructed.DaysOfWeek;
import com.serotonin.bacnet4j.type.constructed.Destination;
import com.serotonin.bacnet4j.type.constructed.EventTransitionBits;
import com.serotonin.bacnet4j.type.constructed.GroupChannelValue;
import com.serotonin.bacnet4j.type.constructed.LogRecord;
import com.serotonin.bacnet4j.type.constructed.PropertyReference;
import com.serotonin.bacnet4j.type.constructed.PropertyValue;
import com.serotonin.bacnet4j.type.constructed.ReadAccessResult;
import com.serotonin.bacnet4j.type.constructed.ReadAccessSpecification;
import com.serotonin.bacnet4j.type.constructed.Recipient;
import com.serotonin.bacnet4j.type.constructed.SequenceOf;
import com.serotonin.bacnet4j.type.constructed.TimeStamp;
import com.serotonin.bacnet4j.type.constructed.WriteAccessSpecification;
import com.serotonin.bacnet4j.type.enumerated.EventState;
import com.serotonin.bacnet4j.type.enumerated.MessagePriority;
import com.serotonin.bacnet4j.type.enumerated.ObjectType;
import com.serotonin.bacnet4j.type.enumerated.PropertyIdentifier;
import com.serotonin.bacnet4j.type.error.BaseError;
import com.serotonin.bacnet4j.type.error.ChangeListError;
import com.serotonin.bacnet4j.type.error.CreateObjectError;
import com.serotonin.bacnet4j.type.error.ErrorClassAndCode;
import com.serotonin.bacnet4j.type.error.SubscribeCovPropertyMultipleError;
import com.serotonin.bacnet4j.type.error.WritePropertyMultipleError;
import com.serotonin.bacnet4j.type.primitive.Boolean;
import com.serotonin.bacnet4j.type.primitive.CharacterString;
import com.serotonin.bacnet4j.type.primitive.Date;
import com.serotonin.bacnet4j.type.primitive.Enumerated;
import com.serotonin.bacnet4j.type.primitive.Null;
import com.serotonin.bacnet4j.type.primitive.ObjectIdentifier;
import com.serotonin.bacnet4j.type.primitive.OctetString;
import com.serotonin.bacnet4j.type.primitive.Real;
import com.serotonin.bacnet4j.type.primitive.SignedInteger;
import com.serotonin.bacnet4j.type.primitive.Time;
import com.serotonin.bacnet4j.type.primitive.Unsigned16;
import com.serotonin.bacnet4j.type.primitive.Unsigned32;
import com.serotonin.bacnet4j.type.primitive.UnsignedInteger;

/**
 * BACnet4J client mode (docs/CLIENT_DRIVER_CONTRACT.md).
 *
 * Runs the scenarios of a scenario file against a device under test with
 * the upstream BACnet4J LocalDevice at the image's pin, unmodified, and
 * writes one result line per scenario. Requests are built from BACnet4J's
 * service classes and sent through its transport (segmentation included);
 * what is reported as observed is what BACnet4J decoded.
 *
 * The device is bound by a Who-Is sent to --target: the I-Am gives its
 * address, Max_APDU_Length_Accepted and segmentation, which BACnet4J uses to
 * decide on segmenting requests. An I-Am from another address than --target
 * is infra-error. With --bbmd the local device registers as a foreign device
 * first, so its broadcasts become Distribute-Broadcast-To-Network.
 */
public final class ClientDriver {
    private static final String ADAPTER = "bacnet4j";
    private static final String[] OUTCOMES = {"pass", "fail", "unsupported", "not-tested", "known-difference", "infra-error"};
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final JsonNodeFactory NF = JsonNodeFactory.instance;
    private static final Pattern HOSTPORT = Pattern.compile("^([0-9]{1,3}(?:\\.[0-9]{1,3}){3}):([0-9]+)$");
    private static final Pattern TIME = Pattern.compile("^([0-9]{1,2}):([0-9]{2}):([0-9]{2})\\.([0-9]{2})$");
    private static final Pattern DATETIME = Pattern.compile("^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})$");
    /** Local device instance; not one a scenario file names. */
    private static final int CLIENT_INSTANCE_DEFAULT = 4001;
    /** AtomicReadFile chunk when a scenario gives no count. */
    private static final int READ_CHUNK = 1024;
    /** Event_Time_Stamps index per acknowledged state (to-offnormal, to-fault, to-normal). */
    private static final Map<String, Integer> TIME_STAMP_INDEX = Map.of(
            "offnormal", 1, "high-limit", 1, "low-limit", 1, "fault", 2, "normal", 3);

    /** The scenario could not be run (no binding, no reply, socket error). */
    static final class Infra extends Exception {
        private static final long serialVersionUID = 1L;

        Infra(String msg) {
            super(msg);
        }
    }

    /** The peer's client has no API for the service. */
    static final class Unsupported extends Exception {
        private static final long serialVersionUID = 1L;

        Unsupported(String msg) {
            super(msg);
        }
    }

    /** A recorded BACnet4J deviation (PEER_SUPPORT.md) hides the result. */
    static final class KnownDifference extends Exception {
        private static final long serialVersionUID = 1L;

        KnownDifference(String msg) {
            super(msg);
        }
    }

    private final LocalDevice local;
    private final Address target;
    private final String targetHostPort;
    private final int device;
    private final String broadcast;
    private final int timeoutMs;
    private final List<RemoteDevice> iAms = new CopyOnWriteArrayList<>();
    private final List<ObjectNode> iHaves = new CopyOnWriteArrayList<>();
    /** COV notifications as {pid, object}. */
    private final List<long[]> covs = new CopyOnWriteArrayList<>();
    private RemoteDevice bound;

    private ClientDriver(LocalDevice local, String targetHostPort, int device, String broadcast, int timeoutMs) {
        this.local = local;
        this.targetHostPort = targetHostPort;
        this.target = targetHostPort.isEmpty() ? null : toAddress(targetHostPort);
        this.device = device;
        this.broadcast = broadcast;
        this.timeoutMs = timeoutMs;
        local.getEventHandler().addListener(new DeviceEventAdapter() {
            @Override
            public void iAmReceived(RemoteDevice d) {
                iAms.add(d);
            }

            @Override
            public void iHaveReceived(RemoteDevice d, RemoteObject o) {
                ObjectNode n = NF.objectNode();
                n.put("device", d.getInstanceNumber());
                n.put("object", objectRef(o.getObjectIdentifier()));
                iHaves.add(n);
            }

            @Override
            public void covNotificationReceived(UnsignedInteger pid, ObjectIdentifier initiating,
                    ObjectIdentifier monitored, UnsignedInteger remaining, SequenceOf<PropertyValue> values) {
                covs.add(new long[] {pid.longValue(), objectKey(monitored)});
            }

            // BACnet4J decodes COVNotificationMultiple but its handle()
            // throws NotImplementedException; the decoded request is seen
            // here first (DefaultTransport fires requestReceived before
            // handle).
            @Override
            public void requestReceived(Address from, Service service) {
                if (service instanceof UnconfirmedCovNotificationMultipleRequest u) {
                    for (UnconfirmedCovNotificationMultipleRequest.CovNotification n : u.getListOfCovNotifications()) {
                        covs.add(new long[] {u.getSubscriberProcessIdentifier().longValue(),
                                objectKey(n.getMonitoredObjectIdentifier())});
                    }
                } else if (service instanceof ConfirmedCovNotificationMultipleRequest c) {
                    for (ConfirmedCovNotificationMultipleRequest.CovNotification n : c.getListOfCovNotifications()) {
                        covs.add(new long[] {c.getSubscriberProcessIdentifier().longValue(),
                                objectKey(n.getMonitoredObjectIdentifier())});
                    }
                }
            }
        });
    }

    // --- binding -------------------------------------------------------------

    private RemoteDevice bind() throws Infra {
        if (bound != null) {
            return bound;
        }
        iAms.clear();
        WhoIsRequest whoIs = new WhoIsRequest(device, device);
        if (target != null) {
            local.send(target, whoIs);
        } else {
            local.sendGlobalBroadcast(whoIs);
        }
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (System.currentTimeMillis() < deadline) {
            for (RemoteDevice d : iAms) {
                if (d.getInstanceNumber() != device) {
                    continue;
                }
                if (target != null && !sameAddress(d.getAddress(), target)) {
                    throw new Infra("I-Am for device " + device + " from " + addressText(d.getAddress())
                            + ", not the target " + targetHostPort);
                }
                bound = d;
                return d;
            }
            sleep(20);
        }
        throw new Infra("device not bound: no I-Am for device " + device);
    }

    private <T extends AcknowledgementService> T confirmed(ConfirmedRequestService req) throws BACnetException, Infra {
        RemoteDevice d = bind();
        return local.send(d, req).get();
    }

    private void unconfirmed(UnconfirmedRequestService req) throws Infra {
        if (target != null) {
            local.send(target, req);
        } else {
            local.send(bind(), req);
        }
    }

    // --- services ------------------------------------------------------------

    private ObjectNode run(JsonNode sc) throws Exception {
        String service = sc.path("service").asText();
        switch (service) {
            case "who-is":
                return whoIs(sc);
            case "who-has":
                return whoHas(sc);
            case "read-bdt":
            case "read-fdt":
            case "write-bdt":
                throw new Unsupported("BACnet4J has no client for the BVLC table functions (IpNetwork serves them as a BBMD only)");
            default:
                break;
        }
        try {
            return confirmedService(service, sc);
        } catch (ErrorAPDUException e) {
            return errorObserved(e.getApdu().getError());
        } catch (RejectAPDUException e) {
            return single("reject", NF.textNode(e.getApdu().getRejectReason().toString()));
        } catch (AbortAPDUException e) {
            return single("abort", NF.textNode(e.getApdu().getAbortReason().toString()));
        } catch (BACnetTimeoutException e) {
            throw new Infra("no reply: " + e.getMessage());
        }
    }

    private ObjectNode confirmedService(String service, JsonNode sc) throws Exception {
        switch (service) {
            case "read-property":
                return readProperty(sc);
            case "read-property-multiple":
                return readPropertyMultiple(sc);
            case "write-property": {
                confirmed(new WritePropertyRequest(oid(sc.path("object")), pid(sc.path("property")),
                        arrayIndex(sc), encode(sc.path("value")), priority(sc)));
                return ack();
            }
            case "write-property-multiple":
                return writePropertyMultiple(sc);
            case "subscribe-cov":
                return subscribeCov(sc);
            case "subscribe-cov-property":
                return subscribeCovProperty(sc);
            case "subscribe-cov-property-multiple":
                return subscribeCovPropertyMultiple(sc);
            case "read-range":
                return readRange(sc);
            case "device-communication-control": {
                UnsignedInteger duration = sc.has("duration") ? new UnsignedInteger(sc.get("duration").asInt()) : null;
                confirmed(new DeviceCommunicationControlRequest(duration,
                        DeviceCommunicationControlRequest.EnableDisable.forName(sc.path("state").asText()), password(sc)));
                return ack();
            }
            case "reinitialize-device": {
                JsonNode st = sc.path("state");
                ReinitializeDeviceRequest.ReinitializedStateOfDevice state = st.isInt()
                        ? ReinitializeDeviceRequest.ReinitializedStateOfDevice.forId(st.asInt())
                        : ReinitializeDeviceRequest.ReinitializedStateOfDevice.forName(st.asText());
                confirmed(new ReinitializeDeviceRequest(state, password(sc)));
                return ack();
            }
            case "atomic-read-file":
                return atomicReadFile(sc);
            case "atomic-write-file": {
                byte[] data = Base64.getDecoder().decode(sc.path("data_base64").asText());
                confirmed(new AtomicWriteFileRequest(oid(sc.path("object")), new AtomicWriteFileRequest.StreamAccess(
                        new SignedInteger(sc.path("start").asInt(0)), new OctetString(data))));
                return ack();
            }
            case "add-list-element":
                confirmed(new AddListElementRequest(oid(sc.path("object")), pid(sc.path("property")), arrayIndex(sc),
                        destinations(sc.path("elements"))));
                return ack();
            case "remove-list-element":
                confirmed(new RemoveListElementRequest(oid(sc.path("object")), pid(sc.path("property")), arrayIndex(sc),
                        destinations(sc.path("elements"))));
                return ack();
            case "create-object": {
                ObjectType type = ObjectType.forName(sc.path("object_type").asText());
                CreateObjectRequest req = sc.has("instance")
                        ? new CreateObjectRequest(new ObjectIdentifier(type, sc.get("instance").asInt()), null)
                        : new CreateObjectRequest(type, null);
                CreateObjectAck a = confirmed(req);
                return single("created", NF.textNode(objectRef(a.getObjectIdentifier())));
            }
            case "delete-object":
                confirmed(new DeleteObjectRequest(oid(sc.path("object"))));
                return ack();
            case "get-event-information":
                return getEventInformation();
            case "acknowledge-alarm":
                return acknowledgeAlarm(sc);
            case "get-alarm-summary":
                return getAlarmSummary();
            case "get-enrollment-summary":
                return getEnrollmentSummary(sc);
            case "confirmed-text-message":
                confirmed(new ConfirmedTextMessageRequest(local.getDeviceObject().getId(), messagePriority(sc),
                        new CharacterString(sc.path("message").asText())));
                return ack();
            case "confirmed-private-transfer":
                confirmed(new ConfirmedPrivateTransferRequest(sc.path("vendor_id").asInt(),
                        sc.path("service_number").asInt(), parameters(sc)));
                return ack();
            case "time-synchronization":
                unconfirmed(new TimeSynchronizationRequest(new DateTime(local)));
                return sent(service);
            case "utc-time-synchronization":
                unconfirmed(new UTCTimeSynchronizationRequest(new DateTime(local)));
                return sent(service);
            case "unconfirmed-private-transfer":
                unconfirmed(new UnconfirmedPrivateTransferRequest(sc.path("vendor_id").asInt(),
                        sc.path("service_number").asInt(), parameters(sc)));
                return sent(service);
            case "unconfirmed-text-message":
                unconfirmed(new UnconfirmedTextMessageRequest(local.getDeviceObject().getId(), messagePriority(sc),
                        new CharacterString(sc.path("message").asText())));
                return sent(service);
            case "write-group":
                return writeGroup(sc);
            default:
                throw new Unsupported("no BACnet4J request for " + service + " in this driver");
        }
    }

    private ObjectNode whoIs(JsonNode sc) throws Infra {
        iAms.clear();
        WhoIsRequest req = sc.has("low")
                ? new WhoIsRequest(sc.get("low").asInt(), sc.path("high").asInt(sc.get("low").asInt()))
                : new WhoIsRequest();
        if (!broadcast.isEmpty()) {
            local.send(toAddress(broadcast), req);
        } else {
            local.sendGlobalBroadcast(req);
        }
        sleep(timeoutMs);
        Set<Integer> seen = new HashSet<>();
        List<Integer> devices = new ArrayList<>();
        int self = local.getInstanceNumber();
        for (RemoteDevice d : iAms) {
            if (d.getInstanceNumber() == self) {
                continue;
            }
            if (target != null && !sameAddress(d.getAddress(), target)) {
                throw new Infra("I-Am for device " + d.getInstanceNumber() + " from " + addressText(d.getAddress())
                        + ", not the target " + targetHostPort);
            }
            if (seen.add(d.getInstanceNumber())) {
                devices.add(d.getInstanceNumber());
            }
        }
        Collections.sort(devices);
        ArrayNode arr = NF.arrayNode();
        devices.forEach(arr::add);
        return single("i-am", arr);
    }

    private ObjectNode whoHas(JsonNode sc) throws Exception {
        iHaves.clear();
        WhoHasRequest req = sc.has("object")
                ? new WhoHasRequest(null, oid(sc.get("object")))
                : new WhoHasRequest(null, new CharacterString(sc.path("name").asText()));
        if (!broadcast.isEmpty()) {
            local.send(toAddress(broadcast), req);
        } else {
            local.sendGlobalBroadcast(req);
        }
        sleep(timeoutMs);
        ArrayNode arr = NF.arrayNode();
        Set<String> seen = new HashSet<>();
        int self = local.getInstanceNumber();
        for (ObjectNode n : iHaves) {
            if (n.path("device").asInt() != self && seen.add(n.toString())) {
                arr.add(n);
            }
        }
        return single("i-have", arr);
    }

    private ObjectNode readProperty(JsonNode sc) throws Exception {
        ReadPropertyRequest req = new ReadPropertyRequest(oid(sc.path("object")), pid(sc.path("property")), arrayIndex(sc));
        ReadPropertyAck a = confirmed(req);
        Encodable v = a.getValue();
        if (sc.path("expect").has("recipients")) {
            if (v instanceof SequenceOf<?> seq) {
                ArrayNode arr = NF.arrayNode();
                for (Object o : seq) {
                    if (!(o instanceof Destination d)) {
                        return single("value", valueJson(v));
                    }
                    arr.add(destinationJson(d));
                }
                return single("recipients", arr);
            }
        }
        return single("value", valueJson(v));
    }

    private ObjectNode readPropertyMultiple(JsonNode sc) throws Exception {
        List<ReadAccessSpecification> specs = new ArrayList<>();
        for (JsonNode r : sc.path("reads")) {
            List<PropertyReference> refs = new ArrayList<>();
            for (JsonNode p : r.path("properties")) {
                refs.add(new PropertyReference(pid(p)));
            }
            specs.add(new ReadAccessSpecification(oid(r.path("object")), new SequenceOf<>(refs)));
        }
        ReadPropertyMultipleAck a = confirmed(new ReadPropertyMultipleRequest(new SequenceOf<>(specs)));
        ArrayNode values = NF.arrayNode();
        for (ReadAccessResult rar : a.getListOfReadAccessResults()) {
            String obj = objectRef(rar.getObjectIdentifier());
            for (ReadAccessResult.Result res : rar.getListOfResults()) {
                ObjectNode e = NF.objectNode();
                e.put("object", obj);
                putProperty(e, "property", res.getPropertyIdentifier());
                Encodable datum = res.getReadResult().getDatum();
                if (res.isError()) {
                    e.set("error", classCode((ErrorClassAndCode) datum));
                } else {
                    e.set("value", valueJson(datum));
                }
                values.add(e);
            }
        }
        return single("values", values);
    }

    private ObjectNode writePropertyMultiple(JsonNode sc) throws Exception {
        List<WriteAccessSpecification> specs = new ArrayList<>();
        for (JsonNode w : sc.path("writes")) {
            UnsignedInteger prio = w.has("priority") ? new UnsignedInteger(w.get("priority").asInt()) : null;
            PropertyValue pv = new PropertyValue(pid(w.path("property")), null, encode(w.path("value")), prio);
            specs.add(new WriteAccessSpecification(oid(w.path("object")), new SequenceOf<>(pv)));
        }
        confirmed(new WritePropertyMultipleRequest(new SequenceOf<>(specs)));
        return ack();
    }

    private ObjectNode subscribeCov(JsonNode sc) throws Exception {
        ObjectIdentifier obj = oid(sc.path("object"));
        long pid = sc.path("process_id").asLong();
        covs.clear();
        boolean cancel = sc.path("cancel").asBoolean(false);
        confirmed(new SubscribeCOVRequest(new UnsignedInteger(pid), obj,
                cancel ? null : Boolean.valueOf(sc.path("confirmed").asBoolean(false)),
                cancel ? null : new UnsignedInteger(sc.path("lifetime").asInt(60))));
        return subscribed(pid, Set.of(objectKey(obj)), cancel, sc);
    }

    private ObjectNode subscribeCovProperty(JsonNode sc) throws Exception {
        ObjectIdentifier obj = oid(sc.path("object"));
        long pid = sc.path("process_id").asLong();
        covs.clear();
        boolean cancel = sc.path("cancel").asBoolean(false);
        Real increment = sc.has("cov_increment") ? new Real((float) sc.get("cov_increment").asDouble()) : null;
        confirmed(new SubscribeCOVPropertyRequest(new UnsignedInteger(pid), obj,
                cancel ? null : Boolean.valueOf(sc.path("confirmed").asBoolean(false)),
                cancel ? null : new UnsignedInteger(sc.path("lifetime").asInt(60)),
                new PropertyReference(pid(sc.path("property"))), cancel ? null : increment));
        return subscribed(pid, Set.of(objectKey(obj)), cancel, sc);
    }

    private ObjectNode subscribeCovPropertyMultiple(JsonNode sc) throws Exception {
        long pid = sc.path("process_id").asLong();
        covs.clear();
        boolean cancel = sc.path("cancel").asBoolean(false);
        List<CovSubscriptionSpecification> specs = new ArrayList<>();
        Set<Long> objects = new HashSet<>();
        for (JsonNode s : sc.path("subscriptions")) {
            ObjectIdentifier obj = oid(s.path("object"));
            objects.add(objectKey(obj));
            List<CovReference> refs = new ArrayList<>();
            for (JsonNode p : s.path("properties")) {
                Real increment = p.has("cov_increment") ? new Real((float) p.get("cov_increment").asDouble()) : null;
                refs.add(new CovReference(new PropertyReference(pid(p.path("property"))), increment,
                        Boolean.valueOf(p.path("timestamped").asBoolean(false))));
            }
            specs.add(new CovSubscriptionSpecification(obj, new SequenceOf<>(refs)));
        }
        // Without issueConfirmedNotifications and lifetime the request is a
        // cancellation (clause 13.16).
        confirmed(new SubscribeCOVPropertyMultipleRequest(new Unsigned32((int) pid),
                cancel ? null : Boolean.valueOf(sc.path("confirmed").asBoolean(false)),
                cancel ? null : new UnsignedInteger(sc.path("lifetime").asInt(60)), null, new SequenceOf<>(specs)));
        return subscribed(pid, objects, cancel, sc);
    }

    /** Waits for a COV notification of the subscription when one is expected. */
    private ObjectNode subscribed(long pid, Set<Long> objects, boolean cancel, JsonNode sc) {
        boolean want = sc.path("expect").path("subscribed").path("notification").asBoolean(false);
        long wait = cancel ? 0 : (want ? Math.max(timeoutMs, 3000) : 1000);
        long deadline = System.currentTimeMillis() + wait;
        boolean got = false;
        do {
            for (long[] n : covs) {
                if (n[0] == pid && objects.contains(n[1])) {
                    got = true;
                }
            }
            if (got) {
                break;
            }
            sleep(20);
        } while (System.currentTimeMillis() < deadline);
        ObjectNode s = NF.objectNode();
        s.put("notification", got);
        return single("subscribed", s);
    }

    private ObjectNode readRange(JsonNode sc) throws Exception {
        JsonNode r = sc.path("range");
        ObjectIdentifier obj = oid(sc.path("object"));
        PropertyIdentifier prop = pid(sc.path("property"));
        ReadRangeRequest req = switch (r.path("by").asText()) {
            case "position" -> new ReadRangeRequest(obj, prop, null,
                    new ReadRangeRequest.ByPosition(r.path("index").asInt(), r.path("count").asInt()));
            case "sequence" -> new ReadRangeRequest(obj, prop, null,
                    new ReadRangeRequest.BySequenceNumber(r.path("index").asLong(), r.path("count").asInt()));
            default -> new ReadRangeRequest(obj, prop, null);
        };
        ReadRangeAck a = confirmed(req);
        ArrayNode records = NF.arrayNode();
        for (Encodable e : a.getItemData()) {
            if (!(e instanceof LogRecord lr)) {
                ObjectNode n = NF.objectNode();
                n.set("item", valueJson(e));
                records.add(n);
                continue;
            }
            ObjectNode n = NF.objectNode();
            n.put("timestamp", dateTimeText(lr.getTimestamp()));
            n.set("value", valueJson(lr.getChoice()));
            records.add(n);
        }
        return single("records", records);
    }

    private ObjectNode atomicReadFile(JsonNode sc) throws Exception {
        ObjectIdentifier file = oid(sc.path("object"));
        int start = sc.path("start").asInt(0);
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        if (sc.has("count")) {
            AtomicReadFileAck a = confirmed(new AtomicReadFileRequest(file, new AtomicReadFileRequest.StreamAccess(
                    new SignedInteger(start), new UnsignedInteger(sc.get("count").asInt()))));
            if (!a.isStreamAccess()) {
                throw new Infra("AtomicReadFile-ACK with record access for a stream request");
            }
            out.write(a.getStreamAccess().getFileData().getBytes());
        } else {
            for (int i = 0; i < 4096; i++) {
                AtomicReadFileAck a = confirmed(new AtomicReadFileRequest(file, new AtomicReadFileRequest.StreamAccess(
                        new SignedInteger(start), new UnsignedInteger(READ_CHUNK))));
                if (!a.isStreamAccess()) {
                    throw new Infra("AtomicReadFile-ACK with record access for a stream request");
                }
                byte[] chunk = a.getStreamAccess().getFileData().getBytes();
                out.write(chunk);
                start += chunk.length;
                if (a.getEndOfFile().booleanValue() || chunk.length == 0) {
                    break;
                }
            }
        }
        return single("octets_base64", NF.textNode(Base64.getEncoder().encodeToString(out.toByteArray())));
    }

    private ObjectNode getEventInformation() throws Exception {
        GetEventInformationAck a = confirmed(new GetEventInformationRequest(null));
        ArrayNode events = NF.arrayNode();
        for (GetEventInformationAck.EventSummary s : a.getListOfEventSummaries()) {
            ObjectNode n = NF.objectNode();
            n.put("object", objectRef(s.getObjectIdentifier()));
            n.put("event_state", s.getEventState().toString());
            events.add(n);
        }
        return single("events", events);
    }

    private ObjectNode getAlarmSummary() throws Exception {
        GetAlarmSummaryAck a = confirmed(new GetAlarmSummaryRequest());
        ArrayNode alarms = NF.arrayNode();
        for (GetAlarmSummaryAck.AlarmSummary s : a.getValues()) {
            ObjectNode n = NF.objectNode();
            n.put("object", objectRef(s.getObjectIdentifier()));
            n.put("alarm_state", s.getAlarmState().toString());
            alarms.add(n);
        }
        return single("alarms", alarms);
    }

    private ObjectNode getEnrollmentSummary(JsonNode sc) throws Exception {
        GetEnrollmentSummaryRequest.EventStateFilter filter = sc.has("event_state_filter")
                ? GetEnrollmentSummaryRequest.EventStateFilter.forName(sc.get("event_state_filter").asText())
                : null;
        GetEnrollmentSummaryAck a = confirmed(new GetEnrollmentSummaryRequest(
                GetEnrollmentSummaryRequest.AcknowledgmentFilter.all, null, filter, null, null, null));
        ArrayNode out = NF.arrayNode();
        for (GetEnrollmentSummaryAck.EnrollmentSummary s : a.getValues()) {
            ObjectNode n = NF.objectNode();
            n.put("object", objectRef(s.getObjectIdentifier()));
            n.put("event_state", s.getEventState().toString());
            n.put("event_type", s.getEventType().toString());
            if (s.getNotificationClass() != null) {
                n.put("notification_class", s.getNotificationClass().longValue());
            }
            if (s.getPriority() != null) {
                n.put("priority", s.getPriority().longValue());
            }
            out.add(n);
        }
        return single("enrollments", out);
    }

    private ObjectNode acknowledgeAlarm(JsonNode sc) throws Exception {
        ObjectIdentifier obj = oid(sc.path("object"));
        String state = sc.path("event_state_acked").asText();
        TimeStamp stamp;
        String ts = sc.path("time_stamp").asText();
        if ("event".equals(ts)) {
            Integer index = TIME_STAMP_INDEX.get(state);
            ReadPropertyAck a;
            try {
                a = confirmed(new ReadPropertyRequest(obj, PropertyIdentifier.eventTimeStamps, new UnsignedInteger(index)));
            } catch (BACnetException e) {
                throw new Infra("Event_Time_Stamps of " + objectRef(obj) + " not readable: " + e);
            }
            if (!(a.getValue() instanceof TimeStamp t)) {
                throw new Infra("Event_Time_Stamps[" + index + "] of " + objectRef(obj) + " is " + a.getValue());
            }
            stamp = t;
        } else {
            stamp = new TimeStamp(parseDateTime(ts));
        }
        confirmed(new AcknowledgeAlarmRequest(new UnsignedInteger(sc.path("process_id").asLong()), obj,
                EventState.forName(state), stamp, new CharacterString("interop"), new TimeStamp(new DateTime(local))));
        return ack();
    }

    private ObjectNode writeGroup(JsonNode sc) throws Exception {
        List<GroupChannelValue> changes = new ArrayList<>();
        for (JsonNode c : sc.path("changes")) {
            int op = c.path("overriding_priority").asInt(0);
            changes.add(new GroupChannelValue(new Unsigned16(c.path("channel").asInt()),
                    op == 0 ? null : new UnsignedInteger(op), channelValue(c.path("value"))));
        }
        unconfirmed(new WriteGroupRequest(new Unsigned32(sc.path("group").asInt()),
                new UnsignedInteger(sc.path("priority").asInt()), new SequenceOf<>(changes),
                Boolean.valueOf(sc.path("inhibit").asBoolean(false))));
        return sent("write-group");
    }

    // --- encoding --------------------------------------------------------------

    private static ObjectIdentifier oid(JsonNode ref) throws Infra {
        String[] parts = ref.asText().split(",");
        if (parts.length != 2) {
            throw new Infra("object reference " + ref);
        }
        return new ObjectIdentifier(ObjectType.forName(parts[0]), Integer.parseInt(parts[1]));
    }

    private static PropertyIdentifier pid(JsonNode p) {
        return p.isInt() ? PropertyIdentifier.forId(p.asInt()) : PropertyIdentifier.forName(p.asText());
    }

    private static UnsignedInteger arrayIndex(JsonNode sc) {
        return sc.has("array_index") ? new UnsignedInteger(sc.get("array_index").asInt()) : null;
    }

    private static UnsignedInteger priority(JsonNode sc) {
        return sc.has("priority") ? new UnsignedInteger(sc.get("priority").asInt()) : null;
    }

    private static CharacterString password(JsonNode sc) {
        return sc.has("password") ? new CharacterString(sc.get("password").asText()) : null;
    }

    private static MessagePriority messagePriority(JsonNode sc) {
        return "urgent".equals(sc.path("message_priority").asText("normal")) ? MessagePriority.urgent : MessagePriority.normal;
    }

    private static Encodable encode(JsonNode v) throws Infra {
        String type = v.path("type").asText();
        JsonNode val = v.path("value");
        return switch (type) {
            case "null" -> Null.instance;
            case "boolean" -> Boolean.valueOf(val.asBoolean());
            case "unsigned" -> new UnsignedInteger(val.asLong());
            case "signed" -> new SignedInteger(val.asLong());
            case "real" -> new Real((float) val.asDouble());
            case "character-string" -> new CharacterString(val.asText());
            case "enumerated" -> {
                if (!val.isInt()) {
                    throw new Infra("an enumerated value to send must be a number in this driver");
                }
                yield new Enumerated(val.asInt());
            }
            case "object-identifier" -> oid(val);
            default -> throw new Infra("no encoding for value type " + type + " in this driver");
        };
    }

    private static ChannelValue channelValue(JsonNode v) throws Infra {
        Encodable e = encode(v);
        if (e instanceof Real r) {
            return new ChannelValue(r);
        } else if (e instanceof Null n) {
            return new ChannelValue(n);
        } else if (e instanceof Boolean b) {
            return new ChannelValue(b);
        } else if (e instanceof UnsignedInteger u) {
            return new ChannelValue(u);
        } else if (e instanceof SignedInteger s) {
            return new ChannelValue(s);
        } else if (e instanceof CharacterString c) {
            return new ChannelValue(c);
        } else if (e instanceof Enumerated en) {
            return new ChannelValue(en);
        } else if (e instanceof ObjectIdentifier o) {
            return new ChannelValue(o);
        }
        throw new Infra("no channel value for " + v);
    }

    private static Encodable parameters(JsonNode sc) throws Infra {
        if (!sc.has("parameters") || sc.get("parameters").isEmpty()) {
            return null;
        }
        List<Encodable> values = new ArrayList<>();
        for (JsonNode v : sc.get("parameters")) {
            values.add(encode(v));
        }
        return new SequenceOf<>(values);
    }

    private static SequenceOf<Destination> destinations(JsonNode elements) throws Infra {
        List<Destination> out = new ArrayList<>();
        for (JsonNode d : elements) {
            if (!d.path("recipient").has("device")) {
                throw new Infra("only device recipients are supported by this driver");
            }
            DaysOfWeek days = new DaysOfWeek(false);
            for (JsonNode day : d.path("valid_days")) {
                switch (day.asInt()) {
                    case 1 -> days.setMonday(true);
                    case 2 -> days.setTuesday(true);
                    case 3 -> days.setWednesday(true);
                    case 4 -> days.setThursday(true);
                    case 5 -> days.setFriday(true);
                    case 6 -> days.setSaturday(true);
                    case 7 -> days.setSunday(true);
                    default -> throw new Infra("valid day " + day);
                }
            }
            Set<String> tr = new HashSet<>();
            d.path("transitions").forEach(t -> tr.add(t.asText()));
            out.add(new Destination(days, parseTime(d.path("from_time").asText()), parseTime(d.path("to_time").asText()),
                    new Recipient(new ObjectIdentifier(ObjectType.device, d.path("recipient").path("device").asInt())),
                    new UnsignedInteger(d.path("process_id").asLong()), Boolean.valueOf(d.path("confirmed").asBoolean()),
                    new EventTransitionBits(tr.contains("to-offnormal"), tr.contains("to-fault"), tr.contains("to-normal"))));
        }
        return new SequenceOf<>(out);
    }

    private static Time parseTime(String s) throws Infra {
        Matcher m = TIME.matcher(s);
        if (!m.matches()) {
            throw new Infra("time " + s);
        }
        return new Time(Integer.parseInt(m.group(1)), Integer.parseInt(m.group(2)), Integer.parseInt(m.group(3)),
                Integer.parseInt(m.group(4)));
    }

    private static DateTime parseDateTime(String s) throws Infra {
        Matcher m = DATETIME.matcher(s);
        if (!m.matches()) {
            throw new Infra("date-time " + s);
        }
        int year = Integer.parseInt(m.group(1));
        int month = Integer.parseInt(m.group(2));
        int day = Integer.parseInt(m.group(3));
        java.time.DayOfWeek dow = java.time.LocalDate.of(year, month, day).getDayOfWeek();
        Date date = new Date(year, Month.valueOf(month), day, DayOfWeek.valueOf(dow.getValue()));
        return new DateTime(date, new Time(Integer.parseInt(m.group(4)), Integer.parseInt(m.group(5)),
                Integer.parseInt(m.group(6)), 0));
    }

    // --- decoding ------------------------------------------------------------

    private static JsonNode valueJson(Encodable e) {
        ObjectNode n = NF.objectNode();
        if (e == null || e instanceof Null) {
            n.put("type", "null");
        } else if (e instanceof Boolean b) {
            n.put("type", "boolean");
            n.put("value", b.booleanValue());
        } else if (e instanceof UnsignedInteger u) {
            n.put("type", "unsigned");
            n.put("value", u.longValue());
        } else if (e instanceof SignedInteger s) {
            n.put("type", "signed");
            n.put("value", s.longValue());
        } else if (e instanceof Real r) {
            n.put("type", "real");
            // The float's shortest decimal form, so 21.5f is 21.5.
            n.put("value", Double.parseDouble(Float.toString(r.floatValue())));
        } else if (e instanceof CharacterString c) {
            n.put("type", "character-string");
            n.put("value", c.getValue());
        } else if (e instanceof Enumerated en) {
            n.put("type", "enumerated");
            String name = en.toString();
            if (name.matches("[0-9]+")) {
                n.put("value", Integer.parseInt(name));
            } else {
                n.put("value", name);
            }
        } else if (e instanceof ObjectIdentifier o) {
            n.put("type", "object-identifier");
            n.put("value", objectRef(o));
        } else if (e instanceof DateTime dt) {
            n.put("type", "date-time");
            n.put("value", dateTimeText(dt));
        } else if (e instanceof SequenceOf<?> seq) {
            n.put("type", "list");
            ArrayNode arr = n.putArray("value");
            for (Object o : seq) {
                arr.add(valueJson((Encodable) o));
            }
        } else {
            n.put("type", "text");
            n.put("value", e.getClass().getSimpleName() + ": " + e);
        }
        return n;
    }

    private static ObjectNode destinationJson(Destination d) {
        ObjectNode n = NF.objectNode();
        ArrayNode days = n.putArray("valid_days");
        DaysOfWeek w = d.getValidDays();
        boolean[] set = {w.isMonday(), w.isTuesday(), w.isWednesday(), w.isThursday(), w.isFriday(), w.isSaturday(),
            w.isSunday()};
        for (int i = 0; i < set.length; i++) {
            if (set[i]) {
                days.add(i + 1);
            }
        }
        n.put("from_time", timeText(d.getFromTime()));
        n.put("to_time", timeText(d.getToTime()));
        ObjectNode rec = n.putObject("recipient");
        if (d.getRecipient().isDevice()) {
            rec.put("device", d.getRecipient().getDevice().getInstanceNumber());
        } else {
            rec.put("address", d.getRecipient().getAddress().toString());
        }
        n.put("process_id", d.getProcessIdentifier().longValue());
        n.put("confirmed", d.getIssueConfirmedNotifications().booleanValue());
        ArrayNode tr = n.putArray("transitions");
        EventTransitionBits t = d.getTransitions();
        if (t.isToOffnormal()) {
            tr.add("to-offnormal");
        }
        if (t.isToFault()) {
            tr.add("to-fault");
        }
        if (t.isToNormal()) {
            tr.add("to-normal");
        }
        return n;
    }

    private static ObjectNode errorObserved(BaseError be) {
        ObjectNode err;
        if (be instanceof WritePropertyMultipleError w) {
            err = classCode(w.getErrorType());
            ObjectNode ff = err.putObject("first_failed");
            ff.put("object", objectRef(w.getFirstFailedWriteAttempt().getObjectIdentifier()));
            putProperty(ff, "property", w.getFirstFailedWriteAttempt().getPropertyIdentifier());
        } else if (be instanceof ChangeListError c) {
            err = classCode(c.getErrorType());
            err.put("first_failed_element", c.getFirstFailedElementNumber().longValue());
        } else if (be instanceof CreateObjectError c) {
            err = classCode(c.getErrorType());
            err.put("first_failed_element", c.getFirstFailedElementNumber().longValue());
        } else if (be instanceof SubscribeCovPropertyMultipleError s && s.isFirstFailedSubscription()) {
            SubscribeCovPropertyMultipleError.FirstFailedSubscription f = s.getFirstFailedSubscription();
            err = classCode(f.getErrorType());
            ObjectNode ff = err.putObject("first_failed");
            ff.put("object", objectRef(f.getMonitoredObjectIdentifier()));
            putProperty(ff, "property", f.getMonitoredPropertyReference().getPropertyIdentifier());
        } else {
            err = classCode(be.getErrorClassAndCode());
        }
        return single("error", err);
    }

    private static ObjectNode classCode(ErrorClassAndCode e) {
        ObjectNode n = NF.objectNode();
        n.put("class", e.getErrorClass().toString());
        n.put("code", e.getErrorCode().toString());
        return n;
    }

    private static void putProperty(ObjectNode n, String key, PropertyIdentifier p) {
        String name = p.toString();
        if (name.matches("[0-9]+")) {
            n.put(key, Integer.parseInt(name));
        } else {
            n.put(key, name);
        }
    }

    private static String objectRef(ObjectIdentifier o) {
        return o.getObjectType().toString() + "," + o.getInstanceNumber();
    }

    private static long objectKey(ObjectIdentifier o) {
        return ((long) o.getObjectType().intValue() << 22) | o.getInstanceNumber();
    }

    private static String timeText(Time t) {
        return String.format("%d:%02d:%02d.%02d", t.getHour(), t.getMinute(), t.getSecond(), t.getHundredth());
    }

    private static String dateTimeText(DateTime dt) {
        Date d = dt.getDate();
        Time t = dt.getTime();
        return String.format("%04d-%02d-%02dT%02d:%02d:%02d", d.getCenturyYear(), d.getMonth().getId(), d.getDay(),
                t.getHour(), t.getMinute(), t.getSecond());
    }

    private static ObjectNode single(String key, JsonNode value) {
        ObjectNode n = NF.objectNode();
        n.set(key, value);
        return n;
    }

    private static ObjectNode ack() {
        return single("ack", NF.booleanNode(true));
    }

    private static ObjectNode sent(String operation) {
        ObjectNode s = NF.objectNode();
        s.put("operation", operation);
        return single("sent", s);
    }

    // --- comparison ----------------------------------------------------------

    /**
     * BACnet4J 6.1.1 decodes SubscribeCOVPropertyMultiple-Error as a CHOICE
     * of errorType [0] or firstFailedSubscription [1]
     * (SubscribeCovPropertyMultipleError.choiceOptions), while clause 21
     * defines a SEQUENCE of both: it reads errorType and drops the first
     * failed subscription. When class and code agree and only first_failed
     * is missing, the result is a known difference, not a pass or a fail.
     */
    static void knownDifference(JsonNode sc, JsonNode observed) throws KnownDifference {
        JsonNode want = sc.path("expect").path("error");
        JsonNode got = observed.path("error");
        if ("subscribe-cov-property-multiple".equals(sc.path("service").asText()) && want.has("first_failed")
                && got.isObject() && !got.has("first_failed")
                && got.path("class").asText().equals(want.path("class").asText())
                && got.path("code").asText().equals(want.path("code").asText())) {
            throw new KnownDifference("BACnet4J decodes SubscribeCOVPropertyMultiple-Error as a CHOICE and drops "
                    + "firstFailedSubscription; error class and code agree (PEER_SUPPORT.md)");
        }
    }

    static boolean compare(JsonNode expect, JsonNode observed) {
        String key = expect.fieldNames().next();
        if (!observed.has(key)) {
            return false;
        }
        JsonNode want = expect.get(key);
        JsonNode got = observed.get(key);
        switch (key) {
            case "value":
                return sameValue(got, want);
            case "values": {
                if (got.size() != want.size()) {
                    return false;
                }
                for (int i = 0; i < want.size(); i++) {
                    JsonNode g = got.get(i);
                    JsonNode w = want.get(i);
                    if (!g.path("object").asText().equals(w.path("object").asText())
                            || !g.path("property").asText().equals(w.path("property").asText())) {
                        return false;
                    }
                    if (w.has("error")) {
                        if (!sameError(g.path("error"), w.get("error"))) {
                            return false;
                        }
                    } else if (!g.has("value") || !sameValue(g.get("value"), w.get("value"))) {
                        return false;
                    }
                }
                return true;
            }
            case "error":
                return sameError(got, want);
            case "reject":
            case "abort":
                return normalise(got.asText()).equals(normalise(want.asText()));
            case "records": {
                if (got.size() != want.size()) {
                    return false;
                }
                for (int i = 0; i < want.size(); i++) {
                    if (!got.get(i).path("timestamp").asText().equals(want.get(i).path("timestamp").asText())
                            || !sameValue(got.get(i).path("value"), want.get(i).path("value"))) {
                        return false;
                    }
                }
                return true;
            }
            case "subscribed":
                return !want.path("notification").asBoolean() || got.path("notification").asBoolean();
            case "i-am":
            case "i-have":
                return sortedEqual(got, want);
            case "enrollments": {
                if (got.size() != want.size()) {
                    return false;
                }
                for (int i = 0; i < want.size(); i++) {
                    JsonNode g = got.get(i);
                    JsonNode w = want.get(i);
                    for (String f : List.of("object", "event_state", "event_type", "notification_class")) {
                        if (w.has(f) && !w.get(f).asText().equals(g.path(f).asText())) {
                            return false;
                        }
                    }
                }
                return true;
            }
            default:
                return got.equals(want);
        }
    }

    private static boolean sameError(JsonNode got, JsonNode want) {
        if (!got.path("class").asText().equals(want.path("class").asText())
                || !got.path("code").asText().equals(want.path("code").asText())) {
            return false;
        }
        if (want.has("first_failed")) {
            JsonNode ff = got.path("first_failed");
            if (!ff.path("object").asText().equals(want.get("first_failed").path("object").asText())
                    || !ff.path("property").asText().equals(want.get("first_failed").path("property").asText())) {
                return false;
            }
        }
        if (want.has("first_failed_element")
                && got.path("first_failed_element").asLong(-1) != want.get("first_failed_element").asLong()) {
            return false;
        }
        return true;
    }

    private static boolean sameValue(JsonNode got, JsonNode want) {
        if (!got.path("type").asText().equals(want.path("type").asText())) {
            return false;
        }
        JsonNode g = got.path("value");
        JsonNode w = want.path("value");
        if ("real".equals(want.path("type").asText()) && g.isNumber() && w.isNumber()) {
            double a = g.asDouble();
            double b = w.asDouble();
            return Math.abs(a - b) <= Math.max(1e-6, 1e-6 * Math.abs(b));
        }
        if (g.isMissingNode() && w.isMissingNode()) {
            return true;
        }
        if (g.isNumber() && w.isNumber()) {
            return g.asLong() == w.asLong();
        }
        return g.equals(w);
    }

    private static boolean sortedEqual(JsonNode got, JsonNode want) {
        List<String> a = new ArrayList<>();
        List<String> b = new ArrayList<>();
        got.forEach(n -> a.add(n.toString()));
        want.forEach(n -> b.add(n.toString()));
        Collections.sort(a);
        Collections.sort(b);
        return a.equals(b);
    }

    private static String normalise(String s) {
        return s.toLowerCase().replaceAll("[^a-z0-9]", "");
    }

    // --- network ---------------------------------------------------------------

    private static Address toAddress(String hostPort) {
        Matcher m = HOSTPORT.matcher(hostPort);
        if (!m.matches()) {
            throw new IllegalArgumentException(hostPort);
        }
        return IpNetworkUtils.toAddress(m.group(1), Integer.parseInt(m.group(2)));
    }

    private static boolean sameAddress(Address a, Address b) {
        return a != null && b != null && a.getMacAddress().equals(b.getMacAddress());
    }

    private static String addressText(Address a) {
        return a == null ? "?" : IpNetworkUtils.toIpPortString(a.getMacAddress());
    }

    private static InterfaceAddress primaryInterface() {
        try {
            for (NetworkInterface nif : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!nif.isUp() || nif.isLoopback()) {
                    continue;
                }
                for (InterfaceAddress ia : nif.getInterfaceAddresses()) {
                    if (ia.getAddress() instanceof Inet4Address && !ia.getAddress().isLoopbackAddress()) {
                        return ia;
                    }
                }
            }
        } catch (Exception ignored) {
            // fall through
        }
        return null;
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    // --- main ------------------------------------------------------------------

    private static int usage(String msg) {
        System.err.println("client: " + msg);
        System.err.println("usage: client --device N --scenarios FILE [--target HOST:PORT] [--only ID[,ID]] "
                + "[--broadcast HOST:PORT] [--bbmd HOST:PORT] [--fd-ttl S]");
        return 2;
    }

    public static void main(String[] args) {
        System.exit(run(args));
    }

    static int run(String[] args) {
        Map<String, String> opt = new LinkedHashMap<>();
        Set<String> known = Set.of("--target", "--device", "--scenarios", "--only", "--broadcast", "--bbmd", "--fd-ttl");
        for (int i = 0; i < args.length; i++) {
            String a = args[i];
            String v;
            int eq = a.indexOf('=');
            if (eq > 0) {
                v = a.substring(eq + 1);
                a = a.substring(0, eq);
            } else {
                if (i + 1 >= args.length) {
                    return usage(a + " needs a value");
                }
                v = args[++i];
            }
            if (!known.contains(a)) {
                return usage("unknown argument " + a);
            }
            opt.put(a, v);
        }
        if (!opt.containsKey("--device") || !opt.containsKey("--scenarios")) {
            return usage("--device and --scenarios are required");
        }
        int device;
        int fdTtl;
        try {
            device = Integer.parseInt(opt.get("--device"));
            fdTtl = Integer.parseInt(opt.getOrDefault("--fd-ttl", "60"));
        } catch (NumberFormatException e) {
            return usage("--device and --fd-ttl must be numbers");
        }
        if (fdTtl < 1 || fdTtl > 65535) {
            return usage("--fd-ttl must be 1..65535");
        }
        String target = opt.getOrDefault("--target", "");
        String broadcast = opt.getOrDefault("--broadcast", "");
        String bbmd = opt.getOrDefault("--bbmd", "");
        for (String[] hp : new String[][] {{"target", target}, {"broadcast", broadcast}, {"bbmd", bbmd}}) {
            if (!hp[1].isEmpty() && !HOSTPORT.matcher(hp[1]).matches()) {
                return usage("--" + hp[0] + " must be IPv4:PORT");
            }
        }
        JsonNode doc;
        try {
            doc = JSON.readTree(Files.readString(Path.of(opt.get("--scenarios")), StandardCharsets.UTF_8));
        } catch (Exception e) {
            System.err.println("client: cannot read scenarios: " + e);
            return 2;
        }
        if (!doc.path("scenarios").isArray()) {
            System.err.println("client: cannot read scenarios: no scenarios array");
            return 2;
        }
        if (doc.path("requires_bbmd").asBoolean(false) && bbmd.isEmpty()) {
            System.err.println("client: " + doc.path("id").asText() + " requires --bbmd");
            return 2;
        }
        Set<String> only = new HashSet<>();
        for (String s : opt.getOrDefault("--only", "").split(",")) {
            if (!s.isEmpty()) {
                only.add(s);
            }
        }
        Map<String, String> env = System.getenv();
        int timeoutMs = Integer.parseInt(env.getOrDefault("BACNET_CLIENT_TIMEOUT_MS", "3000"));
        int retries = Integer.parseInt(env.getOrDefault("BACNET_CLIENT_RETRIES", "1"));
        int clientInstance = Integer.parseInt(env.getOrDefault("BACNET_CLIENT_DEVICE", String.valueOf(CLIENT_INSTANCE_DEFAULT)));

        PrintStream out = System.out;
        LocalDevice local;
        IpNetwork network;
        try {
            InterfaceAddress ia = primaryInterface();
            if (ia == null) {
                System.err.println("client: no IPv4 interface");
                return 1;
            }
            int prefix = ia.getNetworkPrefixLength();
            String bcast = ia.getBroadcast() != null ? ia.getBroadcast().getHostAddress()
                    : IpNetworkUtils.toIpAddrString(IpNetworkUtils.toBroadcast(
                            IpNetworkUtils.bytesToLong(ia.getAddress().getAddress()), IpNetworkUtils.createMask(prefix)));
            // Bound to the wildcard address: a socket bound to the unicast
            // address does not receive the broadcast I-Am.
            network = new IpNetworkBuilder()
                    .withLocalBindAddress(IpNetwork.DEFAULT_BIND_IP)
                    .withBroadcast(bcast, prefix)
                    .withPort(IpNetwork.DEFAULT_PORT)
                    .withReuseAddress(true)
                    .build();
            DefaultTransport transport = new DefaultTransport(network);
            transport.setTimeout(timeoutMs);
            transport.setRetries(retries);
            transport.setSegTimeout(Math.max(1000, timeoutMs / 2));
            local = new LocalDevice(clientInstance, transport);
            local.getDeviceObject().writePropertyInternal(PropertyIdentifier.objectName,
                    new CharacterString("bacnet-interop BACnet4J client"));
            local.initialize();
        } catch (Exception e) {
            System.err.println("client: cannot start BACnet4J: " + e);
            return 1;
        }

        String registration = null;
        if (!bbmd.isEmpty()) {
            Matcher m = HOSTPORT.matcher(bbmd);
            m.matches();
            try {
                network.registerAsForeignDevice(new InetSocketAddress(m.group(1), Integer.parseInt(m.group(2))), fdTtl);
            } catch (Exception e) {
                registration = "foreign-device registration with " + bbmd + " failed: " + e.getMessage();
            }
        }

        ClientDriver driver = new ClientDriver(local, target, device, broadcast, timeoutMs);
        ObjectNode ready = NF.objectNode();
        ready.put("event", "ready");
        ready.put("mode", "client");
        ready.put("adapter", ADAPTER);
        ready.put("version", env.getOrDefault("ADAPTER_VERSION", "dev"));
        ready.put("peer_version", "bacnet4j-" + env.getOrDefault("BACNET4J_VERSION", "unknown"));
        ready.put("scenarios", doc.path("id").asText(""));
        out.println(ready.toString());
        out.flush();

        Map<String, Integer> summary = new LinkedHashMap<>();
        for (String o : OUTCOMES) {
            summary.put(o, 0);
        }
        for (JsonNode sc : doc.get("scenarios")) {
            String id = sc.path("id").asText();
            if (!only.isEmpty() && !only.contains(id)) {
                continue;
            }
            long start = System.nanoTime();
            ObjectNode line = NF.objectNode();
            line.put("event", "result");
            line.put("scenario", id);
            line.put("service", sc.path("service").asText());
            try {
                if (registration != null) {
                    throw new Infra(registration);
                }
                // Re-read so that numbers compare by value (Jackson's
                // LongNode(7) is not equal to IntNode(7)).
                JsonNode observed = JSON.readTree(driver.run(sc).toString());
                knownDifference(sc, observed);
                line.put("outcome", compare(sc.path("expect"), observed) ? "pass" : "fail");
                line.set("observed", observed);
            } catch (KnownDifference e) {
                line.put("outcome", "known-difference");
                line.put("detail", e.getMessage());
            } catch (Unsupported e) {
                line.put("outcome", "unsupported");
                line.put("detail", e.getMessage());
            } catch (Infra e) {
                line.put("outcome", "infra-error");
                line.put("detail", e.getMessage());
            } catch (Exception e) {
                // A reply BACnet4J could not decode, or a request it refused
                // to build: what the peer's client did, so a fail.
                line.put("outcome", "fail");
                ObjectNode observed = NF.objectNode();
                observed.put("exception", e.getClass().getSimpleName() + ": " + e.getMessage());
                line.set("observed", observed);
            }
            line.put("durationMs", (System.nanoTime() - start) / 1_000_000);
            summary.merge(line.get("outcome").asText(), 1, Integer::sum);
            out.println(line.toString());
            out.flush();
        }
        ObjectNode done = NF.objectNode();
        done.put("event", "done");
        ObjectNode s = done.putObject("summary");
        summary.forEach(s::put);
        out.println(done.toString());
        out.flush();
        try {
            if (!bbmd.isEmpty() && registration == null) {
                network.unregisterAsForeignDevice();
            }
            local.terminate();
        } catch (Exception ignored) {
            // exiting
        }
        return 0;
    }
}
