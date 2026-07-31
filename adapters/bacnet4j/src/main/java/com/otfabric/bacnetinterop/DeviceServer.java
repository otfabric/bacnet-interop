// SPDX-License-Identifier: MIT
package com.otfabric.bacnetinterop;

import java.io.BufferedWriter;
import java.io.OutputStreamWriter;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.serotonin.bacnet4j.LocalDevice;
import com.serotonin.bacnet4j.npdu.ip.IpNetwork;
import com.serotonin.bacnet4j.npdu.ip.IpNetworkBuilder;
import com.serotonin.bacnet4j.obj.AnalogValueObject;
import com.serotonin.bacnet4j.obj.BinaryValueObject;
import com.serotonin.bacnet4j.obj.DeviceObject;
import com.serotonin.bacnet4j.transport.DefaultTransport;
import com.serotonin.bacnet4j.type.enumerated.BinaryPV;
import com.serotonin.bacnet4j.type.enumerated.EngineeringUnits;
import com.serotonin.bacnet4j.type.enumerated.PropertyIdentifier;
import com.serotonin.bacnet4j.type.enumerated.Segmentation;
import com.serotonin.bacnet4j.type.primitive.CharacterString;
import com.serotonin.bacnet4j.type.primitive.UnsignedInteger;

/**
 * Fixture-driven BACnet/IP device server for bacnet-interop.
 *
 * Loads device-baseline-v1 JSON, binds UDP, emits a single JSON Lines ready
 * event on stdout, then serves until SIGTERM/SIGINT. Diagnostics go to stderr.
 */
public final class DeviceServer {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final String FIXTURE_DEFAULT = "device-baseline-v1";
    private static final String FIXTURE_PATH_DEFAULT = "/fixtures/device/device-baseline-v1.json";
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

        IpNetworkBuilder builder = new IpNetworkBuilder()
                .withLocalBindAddress(bind)
                .withSubnet("255.255.0.0", 16)
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
                default -> System.err.println("skipping unsupported object type '" + type + "'");
            }
        }

        localDevice.initialize();

        ObjectNode ready = JSON.createObjectNode();
        ready.put("event", "ready");
        ready.put("adapter", "bacnet4j");
        ready.put("version", adapterVersion);
        ready.put("fixture", fixtureId);
        ready.put("address", "0.0.0.0:" + port);
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

    private static String primaryIPv4() {
        try (DatagramSocket socket = new DatagramSocket()) {
            socket.connect(InetAddress.getByName("8.8.8.8"), 80);
            return socket.getLocalAddress().getHostAddress();
        } catch (Exception e) {
            try {
                return InetAddress.getLocalHost().getHostAddress();
            } catch (Exception e2) {
                return "127.0.0.1";
            }
        }
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
