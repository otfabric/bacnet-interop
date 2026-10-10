// SPDX-License-Identifier: MIT
package com.otfabric.bacnetinterop;

import java.io.BufferedWriter;
import java.io.OutputStreamWriter;
import java.net.DatagramSocket;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.lang.reflect.Field;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicBoolean;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.serotonin.bacnet4j.LocalDevice;
import com.serotonin.bacnet4j.ResponseConsumer;
import com.serotonin.bacnet4j.apdu.AckAPDU;
import com.serotonin.bacnet4j.enums.MaxApduLength;
import com.serotonin.bacnet4j.exception.BACnetException;
import com.serotonin.bacnet4j.service.acknowledgement.AcknowledgementService;
import com.serotonin.bacnet4j.service.confirmed.ConfirmedCovNotificationMultipleRequest;
import com.serotonin.bacnet4j.service.confirmed.ConfirmedCovNotificationMultipleRequest.CovNotification;
import com.serotonin.bacnet4j.service.confirmed.ConfirmedCovNotificationMultipleRequest.CovNotification.CovNotificationValue;
import com.serotonin.bacnet4j.service.confirmed.SubscribeCOVPropertyMultipleRequest;
import com.serotonin.bacnet4j.service.confirmed.SubscribeCOVPropertyMultipleRequest.CovSubscriptionSpecification;
import com.serotonin.bacnet4j.service.confirmed.SubscribeCOVPropertyMultipleRequest.CovSubscriptionSpecification.CovReference;
import com.serotonin.bacnet4j.service.unconfirmed.UnconfirmedCovNotificationMultipleRequest;
import com.serotonin.bacnet4j.type.primitive.Unsigned32;
import com.serotonin.bacnet4j.enums.DayOfWeek;
import com.serotonin.bacnet4j.enums.Month;
import com.serotonin.bacnet4j.event.DeviceEventAdapter;
import com.serotonin.bacnet4j.event.PrivateTransferHandler;
import com.serotonin.bacnet4j.event.ReinitializeDeviceHandler;
import com.serotonin.bacnet4j.npdu.ip.IpNetwork;
import com.serotonin.bacnet4j.npdu.ip.IpNetworkBuilder;
import com.serotonin.bacnet4j.obj.AnalogInputObject;
import com.serotonin.bacnet4j.obj.AnalogValueObject;
import com.serotonin.bacnet4j.obj.BACnetObject;
import com.serotonin.bacnet4j.obj.BinaryValueObject;
import com.serotonin.bacnet4j.obj.DeviceObject;
import com.serotonin.bacnet4j.obj.EventEnrollmentObject;
import com.serotonin.bacnet4j.obj.FileObject;
import com.serotonin.bacnet4j.obj.LifeSafetyPointObject;
import com.serotonin.bacnet4j.obj.LifeSafetyZoneObject;
import com.serotonin.bacnet4j.obj.NotificationClassObject;
import com.serotonin.bacnet4j.obj.TrendLogObject;
import com.serotonin.bacnet4j.service.confirmed.CreateObjectRequest;
import com.serotonin.bacnet4j.obj.fileAccess.CrlfDelimitedFileAccess;
import com.serotonin.bacnet4j.obj.fileAccess.FileAccess;
import com.serotonin.bacnet4j.obj.logBuffer.LinkedListLogBuffer;
import com.serotonin.bacnet4j.service.Service;
import com.serotonin.bacnet4j.service.confirmed.ReadPropertyRequest;
import com.serotonin.bacnet4j.service.confirmed.ReinitializeDeviceRequest.ReinitializedStateOfDevice;
import com.serotonin.bacnet4j.service.unconfirmed.UnconfirmedEventNotificationRequest;
import com.serotonin.bacnet4j.transport.DefaultTransport;
import com.serotonin.bacnet4j.type.constructed.Address;
import com.serotonin.bacnet4j.type.constructed.DateTime;
import com.serotonin.bacnet4j.type.constructed.DeviceObjectPropertyReference;
import com.serotonin.bacnet4j.type.constructed.DeviceObjectReference;
import com.serotonin.bacnet4j.type.constructed.EventTransitionBits;
import com.serotonin.bacnet4j.type.constructed.LimitEnable;
import com.serotonin.bacnet4j.type.constructed.LogRecord;
import com.serotonin.bacnet4j.type.constructed.PropertyStates;
import com.serotonin.bacnet4j.type.constructed.SequenceOf;
import com.serotonin.bacnet4j.type.constructed.StatusFlags;
import com.serotonin.bacnet4j.type.constructed.TimeStamp;
import com.serotonin.bacnet4j.type.eventParameter.EventParameter;
import com.serotonin.bacnet4j.type.eventParameter.OutOfRange;
import com.serotonin.bacnet4j.type.notificationParameters.ChangeOfStateNotif;
import com.serotonin.bacnet4j.type.notificationParameters.NotificationParameters;
import com.serotonin.bacnet4j.type.enumerated.BinaryPV;
import com.serotonin.bacnet4j.type.enumerated.EngineeringUnits;
import com.serotonin.bacnet4j.type.enumerated.EventState;
import com.serotonin.bacnet4j.type.enumerated.EventType;
import com.serotonin.bacnet4j.type.enumerated.LifeSafetyMode;
import com.serotonin.bacnet4j.type.enumerated.LifeSafetyOperation;
import com.serotonin.bacnet4j.type.enumerated.LifeSafetyState;
import com.serotonin.bacnet4j.type.enumerated.NotifyType;
import com.serotonin.bacnet4j.type.enumerated.ObjectType;
import com.serotonin.bacnet4j.type.enumerated.PropertyIdentifier;
import com.serotonin.bacnet4j.type.enumerated.Segmentation;
import com.serotonin.bacnet4j.type.enumerated.SilencedState;
import com.serotonin.bacnet4j.type.Encodable;
import com.serotonin.bacnet4j.type.EncodedValue;
import com.serotonin.bacnet4j.type.primitive.Boolean;
import com.serotonin.bacnet4j.type.primitive.CharacterString;
import com.serotonin.bacnet4j.type.primitive.Date;
import com.serotonin.bacnet4j.type.primitive.ObjectIdentifier;
import com.serotonin.bacnet4j.type.primitive.Real;
import com.serotonin.bacnet4j.type.primitive.Time;
import com.serotonin.bacnet4j.type.primitive.UnsignedInteger;

import java.io.File;
import java.io.FileOutputStream;
import java.util.Base64;

/**
 * Fixture-driven BACnet/IP device server for bacnet-interop.
 *
 * Loads device-baseline-v2 JSON, binds UDP, emits a single JSON Lines ready
 * event on stdout, then serves until SIGTERM/SIGINT. Diagnostics go to stderr.
 */
public final class DeviceServer {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final String FIXTURE_DEFAULT = "device-baseline-v2";
    private static final String FIXTURE_PATH_DEFAULT = "/fixtures/device/device-baseline-v2.json";
    private static final int PORT_DEFAULT = 47808;
    // Trend Log seed: see the trend-log case below and the adapter README.
    private static final int TREND_LOG_SEED_RECORDS = 36;
    private static final int TREND_LOG_SEED_INTERVAL_MINUTES = 15;

    private DeviceServer() {}

    public static void main(String[] args) throws Exception {
        Map<String, String> env = System.getenv();
        Path fixturePath = Path.of(env.getOrDefault("DEVICE_FIXTURE_FILE", FIXTURE_PATH_DEFAULT));
        int port = parseInt(env.get("BACNET_IP_PORT"), PORT_DEFAULT);
        String adapterVersion = env.getOrDefault("ADAPTER_VERSION", "dev");
        String peerVersion = env.getOrDefault("BACNET4J_VERSION", "unknown");
        boolean bbmd = truthy(env.get("BACNET_BBMD"));
        int maxApdu = parseInt(env.get("BACNET_MAX_APDU"), 0);
        int networkNumber = parseInt(env.get("BACNET_NETWORK"), 0);

        JsonNode fixture = JSON.readTree(Files.readString(fixturePath));
        int instance = fixture.path("device_instance").asInt(1234);
        String deviceName = fixture.path("device_name").asText("InteropDevice");
        String fixtureId = fixture.path("fixture").asText(env.getOrDefault("FIXTURE", FIXTURE_DEFAULT));
        if (fixture.path("port").isIntegralNumber()) {
            port = fixture.path("port").asInt(port);
        }

        String bind = env.getOrDefault("BACNET_DEVICE_ADDRESS", "").trim();
        if (bind.isEmpty() || "host".equalsIgnoreCase(bind) || bind.startsWith("0.0.0.0")) {
            bind = primaryIPv4();
        } else if (bind.contains(":")) {
            // host:port form — strip port; UDP port comes from BACNET_IP_PORT / fixture.
            bind = bind.substring(0, bind.lastIndexOf(':'));
            if ("host".equalsIgnoreCase(bind)) {
                bind = primaryIPv4();
            }
        }

        String subnetMask = subnetMaskFor(bind);
        IpNetworkBuilder builder = new IpNetworkBuilder()
                .withLocalBindAddress(bind)
                .withSubnet(subnetMask, prefixLength(subnetMask))
                .withPort(port)
                .withReuseAddress(true);
        if (networkNumber > 0) {
            builder.withLocalNetworkNumber(networkNumber);
        }
        IpNetwork network = builder.build();
        if (bbmd) {
            network.enableBBMD();
            List<IpNetwork.BDTEntry> bdt = new ArrayList<>();
            bdt.add(new IpNetwork.BDTEntry(bind, port));
            network.writeBDT(bdt);
            System.err.println("bacnet4j BBMD enabled BDT self-entry=" + bind + ":" + port);
        }

        DefaultTransport transport = new DefaultTransport(network);
        LocalDevice localDevice = new LocalDevice(instance, transport);
        // LocalDevice has one password; upstream checks it for both
        // DeviceCommunicationControl and ReinitializeDevice. Unset = null: a
        // request is then accepted only when it carries no password.
        String devicePassword = env.getOrDefault("BACNET_DCC_PASSWORD", "");
        if (!devicePassword.isEmpty()) {
            localDevice.withPassword(devicePassword);
            System.err.println("bacnet4j device password configured (DeviceCommunicationControl, ReinitializeDevice)");
        }
        // Default handler rejects warmstart with notConfigured; install a no-op.
        localDevice.setReinitializeDeviceHandler(new ReinitializeDeviceHandler() {
            @Override
            public void handle(LocalDevice ld, Address from, ReinitializedStateOfDevice state) {
                System.err.println("bacnet4j ReinitializeDevice state=" + state + " from=" + from);
            }
        });

        DeviceObject deviceObject = localDevice.getDeviceObject();
        deviceObject.writePropertyInternal(PropertyIdentifier.objectName, new CharacterString(deviceName));
        deviceObject.writePropertyInternal(PropertyIdentifier.vendorIdentifier, new UnsignedInteger(999));
        deviceObject.writePropertyInternal(PropertyIdentifier.vendorName, new CharacterString("OT Fabric Interop"));
        deviceObject.writePropertyInternal(PropertyIdentifier.modelName, new CharacterString("bacnet4j-adapter"));
        deviceObject.writePropertyInternal(PropertyIdentifier.description,
                new CharacterString("bacnet-interop BACnet4J peer"));
        if (maxApdu > 0) {
            deviceObject.writePropertyInternal(PropertyIdentifier.maxApduLengthAccepted, new UnsignedInteger(maxApdu));
            deviceObject.writePropertyInternal(PropertyIdentifier.segmentationSupported, Segmentation.segmentedBoth);
            System.err.println("bacnet4j maxApduLengthAccepted=" + maxApdu);
        } else {
            deviceObject.writePropertyInternal(PropertyIdentifier.segmentationSupported, Segmentation.segmentedBoth);
        }

        // EventEnrollment requires LocalDevice.timer from initialize(); create after.
        List<JsonNode> deferredEventEnrollments = new ArrayList<>();

        for (JsonNode obj : fixture.withArray("objects")) {
            if (!obj.isObject()) {
                continue;
            }
            String type = obj.path("type").asText("");
            int oinst = obj.path("instance").asInt(0);
            String oname = obj.path("object_name").asText(type);
            String description = obj.path("description").asText("");
            switch (type) {
                case "device" -> {
                    // Device object already created by LocalDevice.
                }
                case "analog-value" -> {
                    float pv = (float) obj.path("present_value").asDouble(0.0);
                    AnalogValueObject av = new AnalogValueObject(
                            localDevice, oinst, oname, pv, EngineeringUnits.noUnits, false);
                    av.supportCommandable(pv);
                    av.supportCovReporting(0.1f);
                    if (!description.isEmpty()) {
                        av.writePropertyInternal(PropertyIdentifier.description, new CharacterString(description));
                    }
                    // v3: highLimit=80 so Present_Value=90 triggers Out_Of_Range (timeDelay=0).
                    if (fixtureId.contains("v3") || description.toLowerCase().contains("out_of_range")
                            || description.toLowerCase().contains("out-of-range")) {
                        try {
                            // timeDelay, notificationClass, high/low/deadband,
                            // faultHigh/faultLow, limitEnable, eventEnable, notifyType, timeDelayNormal
                            av.supportIntrinsicReporting(
                                    0, 1,
                                    80.0f, 0.0f, 0.0f,
                                    1000.0f, -1000.0f,
                                    new LimitEnable(true, true),
                                    new EventTransitionBits(true, true, true),
                                    NotifyType.alarm,
                                    0);
                            System.err.println("bacnet4j analog-value:" + oinst + " intrinsicReporting highLimit=80");
                        } catch (Exception ex) {
                            System.err.println("bacnet4j analog-value intrinsicReporting failed: " + ex);
                        }
                    }
                }
                case "binary-value" -> {
                    BinaryPV pv = parseBinaryPV(obj.get("present_value"));
                    BinaryValueObject bv = new BinaryValueObject(localDevice, oinst, oname, pv, false);
                    bv.supportCommandable(pv);
                    bv.supportCovReporting();
                    if (!description.isEmpty()) {
                        bv.writePropertyInternal(PropertyIdentifier.description, new CharacterString(description));
                    }
                }
                case "trend-log" -> {
                    // Deterministic seed (documented in the adapter README), built
                    // the way TrendLogObject.addLogRecordImpl would have built it:
                    // record k (1-based position) has
                    //   time stamp       2024-01-01 00:00:00 + (k-1) x 15 minutes (a Monday)
                    //   logDatum         real-value 20.0 + (k-1)
                    //   statusFlags      present, all clear
                    //   sequence number  k
                    // with Record_Count = Total_Record_Count = TREND_LOG_SEED_RECORDS.
                    LinkedListLogBuffer<LogRecord> buffer = new LinkedListLogBuffer<>();
                    StatusFlags flags = new StatusFlags(false, false, false, false);
                    for (int i = 0; i < TREND_LOG_SEED_RECORDS; i++) {
                        int minutes = i * TREND_LOG_SEED_INTERVAL_MINUTES;
                        DateTime stamp = new DateTime(
                                new Date(2024, Month.JANUARY, 1, DayOfWeek.MONDAY),
                                new Time(minutes / 60, minutes % 60, 0, 0));
                        LogRecord record = new LogRecord(stamp, false, new Real(20.0f + i), flags);
                        record.setSequenceNumber(i + 1L);
                        buffer.add(record);
                    }
                    DeviceObjectPropertyReference monitored = new DeviceObjectPropertyReference(
                            instance,
                            new ObjectIdentifier(ObjectType.analogValue, 1),
                            PropertyIdentifier.presentValue);
                    // enable=false: buffer is static seed data for interop ReadRange.
                    TrendLogObject tl = new TrendLogObject(
                            localDevice, oinst, oname, buffer,
                            false, DateTime.UNSPECIFIED, DateTime.UNSPECIFIED,
                            monitored, 0, false, 100);
                    // The constructor resets both counts to zero; the records were
                    // added to the buffer directly, so set them to match.
                    tl.writePropertyInternal(PropertyIdentifier.recordCount, new UnsignedInteger(buffer.size()));
                    tl.writePropertyInternal(PropertyIdentifier.totalRecordCount, new UnsignedInteger(buffer.size()));
                    if (!description.isEmpty()) {
                        tl.writePropertyInternal(PropertyIdentifier.description, new CharacterString(description));
                    }
                    System.err.println("bacnet4j trend-log:" + oinst + " seededRecords=" + buffer.size());
                }
                case "analog-input" -> {
                    float pv = (float) obj.path("present_value").asDouble(0.0);
                    try {
                        AnalogInputObject ai = new AnalogInputObject(
                                localDevice, oinst, oname, pv, EngineeringUnits.noUnits, false);
                        ai.supportCovReporting(0.1f);
                        if (!description.isEmpty()) {
                            ai.writePropertyInternal(PropertyIdentifier.description, new CharacterString(description));
                        }
                        System.err.println("bacnet4j analog-input:" + oinst);
                    } catch (Exception ex) {
                        System.err.println("skipping analog-input: " + ex);
                    }
                }
                case "notification-class" -> {
                    try {
                        NotificationClassObject nc = new NotificationClassObject(
                                localDevice, oinst, oname, 100, 100, 100,
                                new EventTransitionBits(true, true, true));
                        if (!description.isEmpty()) {
                            nc.writePropertyInternal(PropertyIdentifier.description, new CharacterString(description));
                        }
                        System.err.println("bacnet4j notification-class:" + oinst);
                    } catch (Exception ex) {
                        System.err.println("skipping notification-class: " + ex);
                    }
                }
                case "event-enrollment" -> deferredEventEnrollments.add(obj);
                case "file" -> {
                    try {
                        createFileObject(localDevice, obj, oinst, oname, description);
                    } catch (Exception ex) {
                        System.err.println("skipping file:" + oinst + " " + ex);
                    }
                }
                case "life-safety-point" -> {
                    try {
                        LifeSafetyPointObject lsp = new LifeSafetyPointObject(
                                localDevice, oinst, oname,
                                LifeSafetyState.quiet, LifeSafetyMode.on, false,
                                new SequenceOf<>(LifeSafetyMode.on, LifeSafetyMode.off, LifeSafetyMode.enabled),
                                LifeSafetyOperation.none, SilencedState.unsilenced);
                        if (!description.isEmpty()) {
                            lsp.writePropertyInternal(PropertyIdentifier.description, new CharacterString(description));
                        }
                        System.err.println("bacnet4j life-safety-point:" + oinst);
                    } catch (Exception ex) {
                        System.err.println("skipping life-safety-point: " + ex);
                    }
                }
                case "life-safety-zone" -> {
                    try {
                        SequenceOf<DeviceObjectReference> members = new SequenceOf<>();
                        // Prefer LSP-1 as zone member when present in the same fixture.
                        members.add(new DeviceObjectReference(null,
                                new ObjectIdentifier(ObjectType.lifeSafetyPoint, 1)));
                        LifeSafetyZoneObject lsz = new LifeSafetyZoneObject(
                                localDevice, oinst, oname,
                                LifeSafetyState.quiet, LifeSafetyMode.on, false,
                                new SequenceOf<>(LifeSafetyMode.on, LifeSafetyMode.off, LifeSafetyMode.enabled),
                                LifeSafetyOperation.none, SilencedState.unsilenced, members);
                        if (!description.isEmpty()) {
                            lsz.writePropertyInternal(PropertyIdentifier.description, new CharacterString(description));
                        }
                        System.err.println("bacnet4j life-safety-zone:" + oinst);
                    } catch (Exception ex) {
                        System.err.println("skipping life-safety-zone: " + ex);
                    }
                }
                case "audit-log" ->
                        System.err.println("skipping unsupported object type 'audit-log' (unsupported-upstream)");
                default -> System.err.println("skipping unsupported object type '" + type + "'");
            }
        }

        localDevice.initialize();

        for (JsonNode obj : deferredEventEnrollments) {
            int oinst = obj.path("instance").asInt(0);
            String oname = obj.path("object_name").asText("event-enrollment");
            String description = obj.path("description").asText("");
            try {
                DeviceObjectPropertyReference monitored = new DeviceObjectPropertyReference(
                        instance,
                        new ObjectIdentifier(ObjectType.analogValue, 1),
                        PropertyIdentifier.presentValue);
                EventParameter ep = new EventParameter(new OutOfRange(
                        new UnsignedInteger(0),
                        new Real(0.0f),
                        new Real(80.0f),
                        new Real(0.0f)));
                EventEnrollmentObject ee = new EventEnrollmentObject(
                        localDevice, oinst, oname, monitored, NotifyType.alarm, ep,
                        new EventTransitionBits(true, true, true),
                        1, // notificationClass
                        1000, // pollDelayMillis
                        new UnsignedInteger(0),
                        null);
                if (!description.isEmpty()) {
                    ee.writePropertyInternal(PropertyIdentifier.description, new CharacterString(description));
                }
                System.err.println("bacnet4j event-enrollment:" + oinst + " monitors AV-1 OutOfRange");
            } catch (Exception ex) {
                System.err.println("skipping event-enrollment: " + ex);
            }
        }

        configureObjectLifecycle(localDevice, fixture);

        // Accept ConfirmedPrivateTransfer for interop VendorID=1 / serviceNumber=1.
        localDevice.addPrivateTransferHandler(1, 1, new PrivateTransferHandler() {
            @Override
            public Encodable handle(LocalDevice ld, Address from, UnsignedInteger vendorId,
                    UnsignedInteger serviceNumber, EncodedValue serviceParameters, boolean confirmed) {
                return null; // empty resultBlock → ConfirmedPrivateTransferACK
            }
        });

        final boolean emitCovMultiple = truthy(env.get("BACNET_EMIT_COV_MULTIPLE"));
        // Diagnostic sinks for messaging / time / group services (device-baseline-v6+).
        localDevice.getEventHandler().addListener(new DeviceEventAdapter() {
            @Override
            public void requestReceived(Address from, Service service) {
                String op = messagingOperationName(service.getClass().getSimpleName());
                if (op != null) {
                    emitOperation("bacnet4j", op, "accepted");
                }
                if (service instanceof SubscribeCOVPropertyMultipleRequest req) {
                    covMultipleReceived(localDevice, transport, instance, from, req, emitCovMultiple);
                }
            }
        });
        if (emitCovMultiple) {
            System.err.println("bacnet4j BACNET_EMIT_COV_MULTIPLE=1 "
                    + "(COVNotificationMultiple after each SubscribeCOVPropertyMultiple)");
        }

        // Register after initialize so internal TrendLog/COV setup does not trigger emit.
        if (truthy(env.get("BACNET_EMIT_EVENT"))) {
            AtomicBoolean emitted = new AtomicBoolean(false);
            localDevice.getEventHandler().addListener(new DeviceEventAdapter() {
                @Override
                public void requestReceived(Address from, Service service) {
                    if (!(service instanceof ReadPropertyRequest)) {
                        return;
                    }
                    if (!emitted.compareAndSet(false, true)) {
                        return;
                    }
                    emitUnconfirmedEvent(localDevice, instance, from);
                }
            });
            System.err.println("bacnet4j BACNET_EMIT_EVENT=1 (emit once after first ReadProperty)");
        }

        ObjectNode ready = JSON.createObjectNode();
        ready.put("event", "ready");
        ready.put("adapter", "bacnet4j");
        ready.put("version", adapterVersion);
        ready.put("fixture", fixtureId);
        ready.put("address", bind + ":" + port);
        ready.put("peer_version", peerVersion);
        emitReady(ready);
        System.err.println("bacnet4j listening bind=" + bind + ":" + port
                + " instance=" + instance + " mode=" + (bbmd ? "bbmd" : "normal"));

        CountDownLatch stop = new CountDownLatch(1);
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            try {
                localDevice.terminate();
            } catch (Exception ignored) {
                // best-effort
            }
            stop.countDown();
        }, "bacnet4j-shutdown"));
        stop.await();
    }

    /**
     * Fixture-driven CreateObject/DeleteObject support (device-baseline-v5).
     *
     * BACnet4J only ships CreateObject creators for a few object types. Register
     * AnalogValue/BinaryValue via the private creators map, and mark precreated
     * deletable objects from {@code object_lifecycle}.
     */
    @SuppressWarnings("unchecked")
    private static void configureObjectLifecycle(LocalDevice localDevice, JsonNode fixture) {
        JsonNode life = fixture.path("object_lifecycle");
        List<String> creatable = new ArrayList<>();
        if (life.path("creatable_types").isArray()) {
            for (JsonNode t : life.withArray("creatable_types")) {
                creatable.add(t.asText("").trim().toLowerCase());
            }
        }
        if (creatable.isEmpty() && fixture.path("fixture").asText("").contains("v5")) {
            creatable.add("analog-value");
            creatable.add("binary-value");
        }
        try {
            Field creatorsField = CreateObjectRequest.class.getDeclaredField("creators");
            creatorsField.setAccessible(true);
            Map<ObjectType, CreateObjectRequest.ObjectCreator> creators =
                    (Map<ObjectType, CreateObjectRequest.ObjectCreator>) creatorsField.get(null);
            if (creatable.contains("analog-value")) {
                creators.put(ObjectType.analogValue, (d, inst) -> {
                    AnalogValueObject av = new AnalogValueObject(
                            d, inst, "AV-" + inst, 0.0f, EngineeringUnits.noUnits, false);
                    av.supportCommandable(0.0f);
                    av.supportCovReporting(0.1f);
                    return av;
                });
                System.err.println("bacnet4j CreateObject creator registered: analog-value");
            }
            if (creatable.contains("binary-value")) {
                creators.put(ObjectType.binaryValue, (d, inst) -> {
                    BinaryValueObject bv = new BinaryValueObject(
                            d, inst, "BV-" + inst, BinaryPV.inactive, false);
                    bv.supportCommandable(BinaryPV.inactive);
                    bv.supportCovReporting();
                    return bv;
                });
                System.err.println("bacnet4j CreateObject creator registered: binary-value");
            }
        } catch (Exception ex) {
            System.err.println("bacnet4j CreateObject creator registration failed: " + ex);
        }

        if (life.path("precreated_deletable").isArray()) {
            for (JsonNode ref : life.withArray("precreated_deletable")) {
                ObjectType ot = objectTypeFromFixture(ref.path("type").asText(""));
                int inst = ref.path("instance").asInt(-1);
                if (ot == null || inst < 0) {
                    continue;
                }
                BACnetObject obj = localDevice.getObject(new ObjectIdentifier(ot, inst));
                if (obj != null) {
                    obj.setDeletable(true);
                    System.err.println("bacnet4j marked deletable: " + ot + ":" + inst);
                } else {
                    System.err.println("bacnet4j precreated_deletable missing: " + ot + ":" + inst);
                }
            }
        } else {
            // Fallback for older v5 fixtures: AV instance >= 100.
            for (BACnetObject obj : localDevice.getLocalObjects()) {
                if (obj.getId().getObjectType().equals(ObjectType.analogValue)
                        && obj.getId().getInstanceNumber() >= 100) {
                    obj.setDeletable(true);
                    System.err.println("bacnet4j marked deletable (fallback): " + obj.getId());
                }
            }
        }
    }

    private static ObjectType objectTypeFromFixture(String type) {
        return switch (type.trim().toLowerCase()) {
            case "analog-value" -> ObjectType.analogValue;
            case "binary-value" -> ObjectType.binaryValue;
            case "device" -> ObjectType.device;
            case "analog-input" -> ObjectType.analogInput;
            case "file" -> ObjectType.file;
            default -> null;
        };
    }

    private static void createFileObject(LocalDevice localDevice, JsonNode obj, int oinst, String oname,
            String description) throws Exception {
        String access = obj.path("access_method").asText("stream").trim().toLowerCase();
        Path dir = Path.of(System.getProperty("java.io.tmpdir"), "bacnet-interop-files");
        Files.createDirectories(dir);
        File disk = dir.resolve("file-" + oinst + ".dat").toFile();
        if ("record".equals(access)) {
            StringBuilder sb = new StringBuilder();
            if (obj.path("records").isArray()) {
                for (JsonNode rec : obj.withArray("records")) {
                    sb.append(rec.asText("")).append('\n');
                }
            }
            try (FileOutputStream out = new FileOutputStream(disk)) {
                out.write(sb.toString().getBytes(StandardCharsets.UTF_8));
            }
            FileObject fo = new FileObject(localDevice, oinst, oname, new CrlfDelimitedFileAccess(disk));
            if (!description.isEmpty()) {
                fo.writePropertyInternal(PropertyIdentifier.description, new CharacterString(description));
            }
            System.err.println("bacnet4j file:" + oinst + " record records=" + obj.path("records").size());
            return;
        }
        byte[] data = new byte[0];
        String b64 = obj.path("stream_data_base64").asText("");
        if (!b64.isEmpty()) {
            data = Base64.getDecoder().decode(b64);
        }
        try (FileOutputStream out = new FileOutputStream(disk)) {
            out.write(data);
        }
        FileObject fo = new FileObject(localDevice, oinst, oname, newStreamFileAccess(disk));
        if (!description.isEmpty()) {
            fo.writePropertyInternal(PropertyIdentifier.description, new CharacterString(description));
        }
        System.err.println("bacnet4j file:" + oinst + " stream bytes=" + data.length);
    }

    /**
     * BACnet4J 6.x: concrete {@code StreamAccess(File)}.
     * BACnet4J 7+: {@code StreamAccess} is abstract; use {@code FileStreamAccess(File)}.
     * Resolve at runtime so the adapter compiles against either pin.
     */
    private static FileAccess newStreamFileAccess(File disk) throws Exception {
        for (String className : new String[] {
            "com.serotonin.bacnet4j.obj.fileAccess.FileStreamAccess",
            "com.serotonin.bacnet4j.obj.fileAccess.StreamAccess",
        }) {
            try {
                Class<?> cls = Class.forName(className);
                if (java.lang.reflect.Modifier.isAbstract(cls.getModifiers())) {
                    continue;
                }
                Object access = cls.getConstructor(File.class).newInstance(disk);
                return (FileAccess) access;
            } catch (ClassNotFoundException ignored) {
                // try next candidate
            }
        }
        throw new IllegalStateException(
                "no concrete stream FileAccess implementation for " + disk);
    }

    private static void emitReady(ObjectNode ready) throws Exception {
        BufferedWriter out = new BufferedWriter(new OutputStreamWriter(System.out, StandardCharsets.UTF_8));
        out.write(JSON.writeValueAsString(ready));
        out.write('\n');
        out.flush();
    }

    /**
     * Map BACnet4J service simple names to kebab-case operation ids used in
     * device-baseline-v6 notes and go-bacnet awaitOperation assertions.
     */
    private static String messagingOperationName(String simpleName) {
        return switch (simpleName) {
            case "TimeSynchronizationRequest" -> "time-synchronization";
            case "UTCTimeSynchronizationRequest" -> "utc-time-synchronization";
            case "UnconfirmedTextMessageRequest" -> "unconfirmed-text-message";
            case "ConfirmedTextMessageRequest" -> "confirmed-text-message";
            case "UnconfirmedPrivateTransferRequest" -> "unconfirmed-private-transfer";
            case "ConfirmedPrivateTransferRequest" -> "confirmed-private-transfer";
            case "WriteGroupRequest" -> "write-group";
            case "WhoAmIRequest" -> "who-am-i";
            case "YouAreRequest" -> "you-are";
            default -> null;
        };
    }

    /** Adapter diagnostic JSON Lines event (not cross-stack semantics). */
    private static void emitOperation(String adapter, String operation, String result) {
        try {
            ObjectNode ev = JSON.createObjectNode();
            ev.put("event", "operation");
            ev.put("adapter", adapter);
            ev.put("operation", operation);
            ev.put("result", result);
            BufferedWriter out = new BufferedWriter(new OutputStreamWriter(System.out, StandardCharsets.UTF_8));
            out.write(JSON.writeValueAsString(ev));
            out.write('\n');
            out.flush();
        } catch (Exception e) {
            System.err.println("bacnet4j operation event failed: " + e);
        }
    }

    /** Operation line with the fields a stack decoder extracted or an emitter sent. */
    private static void emitOperation(String adapter, String operation, String result, ObjectNode fields) {
        try {
            ObjectNode ev = JSON.createObjectNode();
            ev.put("event", "operation");
            ev.put("adapter", adapter);
            ev.put("operation", operation);
            ev.put("result", result);
            ev.set("fields", fields);
            BufferedWriter out = new BufferedWriter(new OutputStreamWriter(System.out, StandardCharsets.UTF_8));
            out.write(JSON.writeValueAsString(ev));
            out.write('\n');
            out.flush();
        } catch (Exception e) {
            System.err.println("bacnet4j operation event failed: " + e);
        }
    }

    private static Object privateField(Object target, String name) throws Exception {
        Field f = target.getClass().getDeclaredField(name);
        f.setAccessible(true);
        return f.get(target);
    }

    private static ObjectNode objectIdJson(ObjectIdentifier oid) {
        ObjectNode n = JSON.createObjectNode();
        n.put("type", oid.getObjectType().intValue());
        n.put("instance", oid.getInstanceNumber());
        return n;
    }

    private static ObjectNode timeJson(Time t) {
        ObjectNode n = JSON.createObjectNode();
        n.put("hour", t.getHour());
        n.put("minute", t.getMinute());
        n.put("second", t.getSecond());
        n.put("hundredths", t.getHundredth());
        return n;
    }

    /**
     * SubscribeCOVPropertyMultiple, seen in requestReceived: BACnet4J has
     * parsed the request with its own class; its handle() then throws
     * NotImplementedException, which the stack answers with Reject
     * unrecognized-service. Nothing is subscribed.
     *
     * The operation line reports what the stack's parser extracted. The
     * top-level class has no getters, so its private fields are read by
     * reflection; the nested specification classes have getters.
     *
     * With BACNET_EMIT_COV_MULTIPLE=1 the adapter then sends the requester one
     * UnconfirmedCOVNotificationMultiple and one ConfirmedCOVNotificationMultiple
     * for the objects and properties of the request, built with BACnet4J's
     * request classes from the current property values. That is an adapter
     * trigger for the stack's encoder, not a subscription.
     */
    private static void covMultipleReceived(LocalDevice localDevice, DefaultTransport transport, int deviceInstance,
            Address from, SubscribeCOVPropertyMultipleRequest req, boolean emit) {
        final Unsigned32 processId;
        final UnsignedInteger lifetime;
        final SequenceOf<CovSubscriptionSpecification> specs;
        try {
            processId = (Unsigned32) privateField(req, "subscriberProcessIdentifier");
            Boolean issueConfirmed = (Boolean) privateField(req, "issueConfirmedNotifications");
            lifetime = (UnsignedInteger) privateField(req, "lifetime");
            UnsignedInteger maxDelay = (UnsignedInteger) privateField(req, "maxNotificationDelay");
            @SuppressWarnings("unchecked")
            SequenceOf<CovSubscriptionSpecification> list = (SequenceOf<CovSubscriptionSpecification>)
                    privateField(req, "listOfCovSubscriptionSpecifications");
            specs = list;

            ObjectNode fields = JSON.createObjectNode();
            fields.put("subscriber_process_identifier", processId.longValue());
            if (issueConfirmed == null) {
                fields.putNull("issue_confirmed_notifications");
            } else {
                fields.put("issue_confirmed_notifications", issueConfirmed.booleanValue());
            }
            if (lifetime == null) {
                fields.putNull("lifetime");
            } else {
                fields.put("lifetime", lifetime.longValue());
            }
            if (maxDelay == null) {
                fields.putNull("max_notification_delay");
            } else {
                fields.put("max_notification_delay", maxDelay.longValue());
            }
            ArrayNode specNodes = fields.putArray("cov_subscription_specifications");
            for (CovSubscriptionSpecification spec : specs) {
                ObjectNode sn = specNodes.addObject();
                sn.set("monitored_object_identifier", objectIdJson(spec.getMonitoredObjectIdentifier()));
                ArrayNode refs = sn.putArray("cov_references");
                for (CovReference ref : spec.getListOfCovReferences()) {
                    ObjectNode rn = refs.addObject();
                    rn.put("property_identifier", ref.getMonitoredProperty().getPropertyIdentifier().intValue());
                    UnsignedInteger index = ref.getMonitoredProperty().getPropertyArrayIndex();
                    if (index == null) {
                        rn.putNull("property_array_index");
                    } else {
                        rn.put("property_array_index", index.longValue());
                    }
                    if (ref.getCovIncrement() == null) {
                        rn.putNull("cov_increment");
                    } else {
                        rn.put("cov_increment", ref.getCovIncrement().floatValue());
                    }
                    rn.put("timestamped", ref.getTimestamped().booleanValue());
                }
            }
            emitOperation("bacnet4j", "subscribe-cov-property-multiple", "parsed", fields);
        } catch (Exception e) {
            System.err.println("bacnet4j SubscribeCOVPropertyMultiple evidence failed: " + e);
            return;
        }
        if (!emit) {
            return;
        }

        // Build the notification from the current values. A reference the
        // device cannot read (unknown object or property) is left out.
        DateTime timestamp = new DateTime(localDevice);
        Time timeOfChange = timestamp.getTime();
        UnsignedInteger timeRemaining = lifetime == null ? UnsignedInteger.ZERO : lifetime;
        ObjectIdentifier device = new ObjectIdentifier(ObjectType.device, deviceInstance);
        // The two request classes each have their own nested notification types.
        SequenceOf<CovNotification> notifications = new SequenceOf<>();
        SequenceOf<UnconfirmedCovNotificationMultipleRequest.CovNotification> unconfirmedNotifications =
                new SequenceOf<>();
        ObjectNode sent = JSON.createObjectNode();
        sent.put("subscriber_process_identifier", processId.longValue());
        sent.set("initiating_device_identifier", objectIdJson(device));
        sent.put("time_remaining", timeRemaining.longValue());
        ObjectNode ts = sent.putObject("timestamp");
        ts.put("year", timestamp.getDate().getCenturyYear());
        ts.put("month", timestamp.getDate().getMonth().getId());
        ts.put("day", timestamp.getDate().getDay());
        ts.put("weekday", timestamp.getDate().getDayOfWeek().getId());
        ts.setAll(timeJson(timestamp.getTime()));
        ArrayNode noteNodes = sent.putArray("cov_notifications");
        for (CovSubscriptionSpecification spec : specs) {
            ObjectIdentifier oid = spec.getMonitoredObjectIdentifier();
            BACnetObject obj = localDevice.getObject(oid);
            if (obj == null) {
                continue;
            }
            SequenceOf<CovNotificationValue> values = new SequenceOf<>();
            SequenceOf<UnconfirmedCovNotificationMultipleRequest.CovNotification.CovNotificationValue>
                    unconfirmedValues = new SequenceOf<>();
            ObjectNode nn = JSON.createObjectNode();
            nn.set("monitored_object_identifier", objectIdJson(oid));
            ArrayNode valueNodes = nn.putArray("values");
            for (CovReference ref : spec.getListOfCovReferences()) {
                PropertyIdentifier pid = ref.getMonitoredProperty().getPropertyIdentifier();
                UnsignedInteger index = ref.getMonitoredProperty().getPropertyArrayIndex();
                Encodable value;
                try {
                    value = obj.readProperty(pid, index);
                } catch (Exception e) {
                    value = null;
                }
                if (value == null) {
                    continue;
                }
                Time changed = ref.getTimestamped().booleanValue() ? timeOfChange : null;
                values.add(new CovNotificationValue(pid, index, value, changed));
                unconfirmedValues.add(
                        new UnconfirmedCovNotificationMultipleRequest.CovNotification.CovNotificationValue(
                                pid, index, value, changed));
                ObjectNode vn = valueNodes.addObject();
                vn.put("property_identifier", pid.intValue());
                if (index == null) {
                    vn.putNull("property_array_index");
                } else {
                    vn.put("property_array_index", index.longValue());
                }
                vn.put("value", value.toString());
                if (changed == null) {
                    vn.putNull("time_of_change");
                } else {
                    vn.set("time_of_change", timeJson(changed));
                }
            }
            if (values.size() > 0) {
                notifications.add(new CovNotification(oid, values));
                unconfirmedNotifications.add(
                        new UnconfirmedCovNotificationMultipleRequest.CovNotification(oid, unconfirmedValues));
                noteNodes.add(nn);
            }
        }
        final UnconfirmedCovNotificationMultipleRequest unconfirmed = new UnconfirmedCovNotificationMultipleRequest(
                processId, device, timeRemaining, timestamp, unconfirmedNotifications);
        final ConfirmedCovNotificationMultipleRequest confirmed = new ConfirmedCovNotificationMultipleRequest(
                processId, device, timeRemaining, timestamp, notifications);
        // Off the transport thread, and after the stack has answered the
        // request itself.
        Thread sender = new Thread(() -> {
            try {
                Thread.sleep(200);
                localDevice.send(from, unconfirmed);
                emitOperation("bacnet4j", "emit-unconfirmed-cov-notification-multiple", "sent", sent);
                // The requester is not in the remote-device cache, for which
                // LocalDevice.send assumes Max_APDU 50. Use the transport with
                // 480 and no segmentation.
                transport.send(from, MaxApduLength.UP_TO_480.getMaxLengthInt(), Segmentation.noSegmentation,
                        confirmed, new ResponseConsumer() {
                            @Override
                            public void success(AcknowledgementService ack) {
                                emitOperation("bacnet4j", "confirmed-cov-notification-multiple-ack",
                                        ack == null ? "simple-ack" : "complex-ack");
                            }

                            @Override
                            public void fail(AckAPDU ack) {
                                emitOperation("bacnet4j", "confirmed-cov-notification-multiple-ack",
                                        "refused: " + ack);
                            }

                            @Override
                            public void ex(BACnetException e) {
                                emitOperation("bacnet4j", "confirmed-cov-notification-multiple-ack",
                                        "failed: " + e);
                            }
                        });
                emitOperation("bacnet4j", "emit-confirmed-cov-notification-multiple", "sent", sent);
            } catch (Exception e) {
                System.err.println("bacnet4j COVNotificationMultiple emit failed: " + e);
            }
        }, "bacnet4j-cov-multiple");
        sender.setDaemon(true);
        sender.start();
    }

    /** Emit one UnconfirmedEventNotification to the given BACnet address. */
    private static void emitUnconfirmedEvent(LocalDevice localDevice, int deviceInstance, Address to) {
        try {
            NotificationParameters params = new NotificationParameters(
                    new ChangeOfStateNotif(
                            new PropertyStates(EventState.offnormal),
                            new StatusFlags(false, false, false, false)));
            UnconfirmedEventNotificationRequest note = new UnconfirmedEventNotificationRequest(
                    new UnsignedInteger(1),
                    new ObjectIdentifier(ObjectType.device, deviceInstance),
                    new ObjectIdentifier(ObjectType.analogValue, 1),
                    new TimeStamp(new UnsignedInteger(1)),
                    new UnsignedInteger(1),
                    new UnsignedInteger(100),
                    EventType.changeOfState,
                    new CharacterString("interop-event"),
                    NotifyType.alarm,
                    Boolean.FALSE,
                    EventState.normal,
                    EventState.offnormal,
                    params);
            localDevice.send(to, note);
            System.err.println("bacnet4j emitted UnconfirmedEventNotification to " + to);
        } catch (Exception e) {
            System.err.println("bacnet4j event emit failed: " + e);
        }
    }

    private static BinaryPV parseBinaryPV(JsonNode node) {
        if (node == null || node.isNull()) {
            return BinaryPV.inactive;
        }
        if (node.isBoolean()) {
            return node.asBoolean() ? BinaryPV.active : BinaryPV.inactive;
        }
        if (node.isNumber()) {
            return node.asInt() != 0 ? BinaryPV.active : BinaryPV.inactive;
        }
        String s = node.asText("inactive").trim().toLowerCase();
        if ("active".equals(s) || "1".equals(s) || "true".equals(s)) {
            return BinaryPV.active;
        }
        return BinaryPV.inactive;
    }

    /**
     * Prefer a non-loopback site-local IPv4 (typical docker bridge). Avoid
     * InetAddress.getLocalHost(), which often returns 127.0.0.1 in containers
     * and leaves the peer unreachable for routed topology tests.
     */
    private static String primaryIPv4() {
        String enumerated = firstNonLoopbackIPv4(true);
        if (enumerated != null) {
            return enumerated;
        }
        enumerated = firstNonLoopbackIPv4(false);
        if (enumerated != null) {
            return enumerated;
        }
        try (DatagramSocket socket = new DatagramSocket()) {
            socket.connect(InetAddress.getByName("8.8.8.8"), 80);
            InetAddress local = socket.getLocalAddress();
            if (local instanceof Inet4Address && !local.isLoopbackAddress()) {
                return local.getHostAddress();
            }
        } catch (Exception ignored) {
            // fall through
        }
        throw new IllegalStateException("no non-loopback IPv4 address for BACnet bind");
    }

    private static String firstNonLoopbackIPv4(boolean siteLocalOnly) {
        try {
            for (NetworkInterface nif : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!nif.isUp() || nif.isLoopback()) {
                    continue;
                }
                for (InterfaceAddress ia : nif.getInterfaceAddresses()) {
                    InetAddress addr = ia.getAddress();
                    if (!(addr instanceof Inet4Address) || addr.isLoopbackAddress()) {
                        continue;
                    }
                    if (siteLocalOnly && !addr.isSiteLocalAddress()) {
                        continue;
                    }
                    return addr.getHostAddress();
                }
            }
        } catch (Exception ignored) {
            // fall through
        }
        return null;
    }

    private static String subnetMaskFor(String bindIP) {
        try {
            InetAddress bind = InetAddress.getByName(bindIP);
            for (NetworkInterface nif : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                for (InterfaceAddress ia : nif.getInterfaceAddresses()) {
                    if (bind.equals(ia.getAddress()) && ia.getNetworkPrefixLength() > 0) {
                        return prefixToMask(ia.getNetworkPrefixLength());
                    }
                }
            }
        } catch (Exception ignored) {
            // fall through
        }
        // Docker bridge default.
        return "255.255.0.0";
    }

    private static String prefixToMask(int prefix) {
        int mask = prefix == 0 ? 0 : 0xffffffff << (32 - prefix);
        return String.format("%d.%d.%d.%d",
                (mask >>> 24) & 0xff, (mask >>> 16) & 0xff, (mask >>> 8) & 0xff, mask & 0xff);
    }

    private static int prefixLength(String dottedMask) {
        String[] parts = dottedMask.split("\\.");
        int mask = 0;
        for (String p : parts) {
            mask = (mask << 8) | Integer.parseInt(p);
        }
        return Integer.bitCount(mask);
    }

    private static int parseInt(String v, int def) {
        if (v == null || v.isBlank()) {
            return def;
        }
        try {
            return Integer.parseInt(v.trim());
        } catch (NumberFormatException e) {
            return def;
        }
    }

    private static boolean truthy(String v) {
        if (v == null) {
            return false;
        }
        String s = v.trim().toLowerCase();
        return s.equals("1") || s.equals("true") || s.equals("yes");
    }
}
