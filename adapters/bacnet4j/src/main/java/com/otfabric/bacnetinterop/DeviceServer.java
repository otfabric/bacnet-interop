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
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicBoolean;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.serotonin.bacnet4j.LocalDevice;
import com.serotonin.bacnet4j.event.DeviceEventAdapter;
import com.serotonin.bacnet4j.event.ReinitializeDeviceHandler;
import com.serotonin.bacnet4j.npdu.ip.IpNetwork;
import com.serotonin.bacnet4j.npdu.ip.IpNetworkBuilder;
import com.serotonin.bacnet4j.obj.AnalogValueObject;
import com.serotonin.bacnet4j.obj.BinaryValueObject;
import com.serotonin.bacnet4j.obj.DeviceObject;
import com.serotonin.bacnet4j.obj.TrendLogObject;
import com.serotonin.bacnet4j.obj.logBuffer.LinkedListLogBuffer;
import com.serotonin.bacnet4j.service.Service;
import com.serotonin.bacnet4j.service.confirmed.ReadPropertyRequest;
import com.serotonin.bacnet4j.service.confirmed.ReinitializeDeviceRequest.ReinitializedStateOfDevice;
import com.serotonin.bacnet4j.service.unconfirmed.UnconfirmedEventNotificationRequest;
import com.serotonin.bacnet4j.transport.DefaultTransport;
import com.serotonin.bacnet4j.type.constructed.Address;
import com.serotonin.bacnet4j.type.constructed.DateTime;
import com.serotonin.bacnet4j.type.constructed.DeviceObjectPropertyReference;
import com.serotonin.bacnet4j.type.constructed.LogRecord;
import com.serotonin.bacnet4j.type.constructed.PropertyStates;
import com.serotonin.bacnet4j.type.constructed.StatusFlags;
import com.serotonin.bacnet4j.type.constructed.TimeStamp;
import com.serotonin.bacnet4j.type.notificationParameters.ChangeOfStateNotif;
import com.serotonin.bacnet4j.type.notificationParameters.NotificationParameters;
import com.serotonin.bacnet4j.type.enumerated.BinaryPV;
import com.serotonin.bacnet4j.type.enumerated.EngineeringUnits;
import com.serotonin.bacnet4j.type.enumerated.EventState;
import com.serotonin.bacnet4j.type.enumerated.EventType;
import com.serotonin.bacnet4j.type.enumerated.NotifyType;
import com.serotonin.bacnet4j.type.enumerated.ObjectType;
import com.serotonin.bacnet4j.type.enumerated.PropertyIdentifier;
import com.serotonin.bacnet4j.type.enumerated.Segmentation;
import com.serotonin.bacnet4j.type.primitive.Boolean;
import com.serotonin.bacnet4j.type.primitive.CharacterString;
import com.serotonin.bacnet4j.type.primitive.ObjectIdentifier;
import com.serotonin.bacnet4j.type.primitive.Real;
import com.serotonin.bacnet4j.type.primitive.UnsignedInteger;

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
                    LinkedListLogBuffer<LogRecord> buffer = new LinkedListLogBuffer<>();
                    DateTime now = new DateTime(System.currentTimeMillis());
                    StatusFlags flags = new StatusFlags(false, false, false, false);
                    // Seed a few records so ReadRange byPosition has content without waiting on polls.
                    for (int i = 0; i < 4; i++) {
                        buffer.add(new LogRecord(now, true, new Real(20.0f + i), flags));
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
                    if (!description.isEmpty()) {
                        tl.writePropertyInternal(PropertyIdentifier.description, new CharacterString(description));
                    }
                    System.err.println("bacnet4j trend-log:" + oinst + " seededRecords=" + buffer.size());
                }
                default -> System.err.println("skipping unsupported object type '" + type + "'");
            }
        }

        localDevice.initialize();

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

    private static void emitReady(ObjectNode ready) throws Exception {
        BufferedWriter out = new BufferedWriter(new OutputStreamWriter(System.out, StandardCharsets.UTF_8));
        out.write(JSON.writeValueAsString(ready));
        out.write('\n');
        out.flush();
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
