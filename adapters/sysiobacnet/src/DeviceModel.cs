// SPDX-License-Identifier: MIT

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO.BACnet;
using System.IO.BACnet.Storage;
using System.Linq;
using System.Text.Json;
using BacnetObject = System.IO.BACnet.Storage.Object;

namespace Otfabric.BacnetInterop.SysIoBacnet;

// Fixture loading: turns a device-baseline JSON into the upstream
// System.IO.BACnet.Storage.DeviceStorage object model (the storage class the
// NuGet package ships and its BasicServer / Room.Simulator examples serve from).
//
// DeviceStorage holds plain property values only. What it has no notion of is
// kept beside it here: the Trend Log record buffer, File contents and the
// alarm state of objects with intrinsic reporting.
internal sealed class DeviceModel
{
    public DeviceStorage Storage { get; }

    // Trend Log buffers by object, oldest record first (adapter-supplied data).
    public Dictionary<BacnetObjectId, List<BacnetLogRecord>> TrendLogs { get; } = new();

    // Stream-access File contents by object (adapter-supplied data).
    public Dictionary<BacnetObjectId, byte[]> Files { get; } = new();

    // Record-access File contents by object (adapter-supplied data).
    public Dictionary<BacnetObjectId, List<byte[]>> RecordFiles { get; } = new();

    // Intrinsic out-of-range reporting state by object (adapter-supplied
    // semantics: the package has the alarm codecs but no alarm behaviour).
    public Dictionary<BacnetObjectId, AlarmState> Alarms { get; } = new();

    public const float AlarmHighLimit = 80f;

    internal sealed class AlarmState
    {
        public uint NotificationClass;
        public BacnetEventStates State = BacnetEventStates.EVENT_STATE_NORMAL;
        // to-offnormal, to-fault, to-normal. A transition that never happened
        // carries sequence number 0.
        public BacnetGenericTime[] TimeStamps =
        {
            new(default, BacnetTimestampTags.TIME_STAMP_SEQUENCE, 0),
            new(default, BacnetTimestampTags.TIME_STAMP_SEQUENCE, 0),
            new(default, BacnetTimestampTags.TIME_STAMP_SEQUENCE, 0),
        };
        public bool[] Acked = { true, true, true };
    }

    // DeviceStorage accepts a write to any stored property. Like the upstream
    // examples, the adapter decides which properties a client may write.
    private readonly HashSet<(BacnetObjectTypes, BacnetPropertyIds)> _writable = new()
    {
        (BacnetObjectTypes.OBJECT_DEVICE, BacnetPropertyIds.PROP_DESCRIPTION),
        (BacnetObjectTypes.OBJECT_DEVICE, BacnetPropertyIds.PROP_LOCATION),
        (BacnetObjectTypes.OBJECT_ANALOG_VALUE, BacnetPropertyIds.PROP_PRESENT_VALUE),
        (BacnetObjectTypes.OBJECT_ANALOG_VALUE, BacnetPropertyIds.PROP_OUT_OF_SERVICE),
        (BacnetObjectTypes.OBJECT_ANALOG_VALUE, BacnetPropertyIds.PROP_DESCRIPTION),
        (BacnetObjectTypes.OBJECT_BINARY_VALUE, BacnetPropertyIds.PROP_PRESENT_VALUE),
        (BacnetObjectTypes.OBJECT_BINARY_VALUE, BacnetPropertyIds.PROP_OUT_OF_SERVICE),
        (BacnetObjectTypes.OBJECT_BINARY_VALUE, BacnetPropertyIds.PROP_DESCRIPTION),
        (BacnetObjectTypes.OBJECT_ANALOG_INPUT, BacnetPropertyIds.PROP_OUT_OF_SERVICE),
        (BacnetObjectTypes.OBJECT_ANALOG_INPUT, BacnetPropertyIds.PROP_DESCRIPTION),
        (BacnetObjectTypes.OBJECT_ANALOG_VALUE, BacnetPropertyIds.PROP_HIGH_LIMIT),
        (BacnetObjectTypes.OBJECT_FILE, BacnetPropertyIds.PROP_ARCHIVE),
        (BacnetObjectTypes.OBJECT_FILE, BacnetPropertyIds.PROP_DESCRIPTION),
        (BacnetObjectTypes.OBJECT_TRENDLOG, BacnetPropertyIds.PROP_DESCRIPTION),
    };

    public const int TrendLogSeedRecords = 4;

    private DeviceModel(DeviceStorage storage)
    {
        Storage = storage;
    }

    public bool IsWritable(BacnetObjectTypes type, BacnetPropertyIds property) => _writable.Contains((type, property));

    public bool IsCovObject(BacnetObjectTypes type) =>
        type is BacnetObjectTypes.OBJECT_ANALOG_VALUE or BacnetObjectTypes.OBJECT_BINARY_VALUE or BacnetObjectTypes.OBJECT_ANALOG_INPUT;

    public static DeviceModel FromFixture(JsonElement fixture, BacnetClient client, string adapterVersion, string peerVersion)
    {
        var deviceInstance = fixture.GetProperty("device_instance").GetUInt32();
        var deviceName = fixture.GetProperty("device_name").GetString() ?? "InteropDevice";
        var fixtureId = fixture.TryGetProperty("fixture", out var fid) ? fid.GetString() ?? "device" : "device";

        var storage = new DeviceStorage { DeviceId = deviceInstance };
        var model = new DeviceModel(storage);
        var objects = new List<BacnetObject>();
        var servedTypes = new SortedSet<BacnetObjectTypes> { BacnetObjectTypes.OBJECT_DEVICE };

        // The device object comes first, as in the upstream device descriptors.
        var deviceDescription = $"{fixtureId} System.IO.BACnet device";
        var later = new List<BacnetObject>();
        // A fixture with a Notification Class (device-baseline-v3) asks for
        // alarms: its Analog Values then report intrinsic out-of-range events.
        uint? notificationClass = null;
        if (fixture.TryGetProperty("objects", out var scan) && scan.ValueKind == JsonValueKind.Array)
        {
            foreach (var o in scan.EnumerateArray())
            {
                if (o.ValueKind == JsonValueKind.Object && Str(o, "type", "") == "notification-class")
                {
                    notificationClass = o.TryGetProperty("instance", out var nci) ? nci.GetUInt32() : 0u;
                    break;
                }
            }
        }
        if (fixture.TryGetProperty("objects", out var list) && list.ValueKind == JsonValueKind.Array)
        {
            foreach (var o in list.EnumerateArray())
            {
                if (o.ValueKind != JsonValueKind.Object) continue;
                var type = Str(o, "type", "");
                var instance = o.TryGetProperty("instance", out var i) ? i.GetUInt32() : 0u;
                var name = Str(o, "object_name", type);
                var description = Str(o, "description", $"{fixtureId} {type}");
                switch (type)
                {
                    case "device":
                        if (o.TryGetProperty("description", out _)) deviceDescription = description;
                        break;
                    case "analog-value":
                        later.Add(Analog(BacnetObjectTypes.OBJECT_ANALOG_VALUE, instance, name, description, Real(o), commandable: true,
                            notificationClass));
                        if (notificationClass.HasValue)
                            model.Alarms[new BacnetObjectId(BacnetObjectTypes.OBJECT_ANALOG_VALUE, instance)] =
                                new AlarmState { NotificationClass = notificationClass.Value };
                        servedTypes.Add(BacnetObjectTypes.OBJECT_ANALOG_VALUE);
                        break;
                    case "notification-class":
                        later.Add(NotificationClass(instance, name, description));
                        servedTypes.Add(BacnetObjectTypes.OBJECT_NOTIFICATION_CLASS);
                        break;
                    case "analog-input":
                        later.Add(Analog(BacnetObjectTypes.OBJECT_ANALOG_INPUT, instance, name, description, Real(o), commandable: false, null));
                        servedTypes.Add(BacnetObjectTypes.OBJECT_ANALOG_INPUT);
                        break;
                    case "binary-value":
                        later.Add(BinaryValue(instance, name, description, Str(o, "present_value", "inactive") == "active"));
                        servedTypes.Add(BacnetObjectTypes.OBJECT_BINARY_VALUE);
                        break;
                    case "trend-log":
                        later.Add(TrendLog(instance, name, description));
                        model.TrendLogs[new BacnetObjectId(BacnetObjectTypes.OBJECT_TRENDLOG, instance)] = SeedLog();
                        servedTypes.Add(BacnetObjectTypes.OBJECT_TRENDLOG);
                        break;
                    case "file" when Str(o, "access_method", "stream") == "stream":
                        later.Add(StreamFile(instance, name, description));
                        model.Files[new BacnetObjectId(BacnetObjectTypes.OBJECT_FILE, instance)] =
                            Convert.FromBase64String(Str(o, "stream_data_base64", ""));
                        servedTypes.Add(BacnetObjectTypes.OBJECT_FILE);
                        break;
                    case "file":
                        later.Add(RecordFile(instance, name, description));
                        var records = new List<byte[]>();
                        if (o.TryGetProperty("records", out var recs) && recs.ValueKind == JsonValueKind.Array)
                            foreach (var r in recs.EnumerateArray())
                                records.Add(System.Text.Encoding.UTF8.GetBytes(r.GetString() ?? ""));
                        model.RecordFiles[new BacnetObjectId(BacnetObjectTypes.OBJECT_FILE, instance)] = records;
                        servedTypes.Add(BacnetObjectTypes.OBJECT_FILE);
                        break;
                    default:
                        // event-enrollment, audit-log, life-safety-*: the package
                        // ships no object behaviour for them.
                        Console.Error.WriteLine($"sysiobacnet skipping unsupported object type \"{type}\" ({name})");
                        break;
                }
            }
        }

        objects.Add(Device(deviceInstance, deviceName, deviceDescription, client, adapterVersion, peerVersion, servedTypes, notificationClass.HasValue));
        objects.AddRange(later);
        storage.Objects = objects.ToArray();
        return model;
    }

    private static string Str(JsonElement o, string key, string fallback) =>
        o.TryGetProperty(key, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() ?? fallback : fallback;

    private static float Real(JsonElement o) =>
        o.TryGetProperty("present_value", out var v) && v.ValueKind == JsonValueKind.Number ? v.GetSingle() : 0f;

    private static string R(float f) => f.ToString("R", CultureInfo.InvariantCulture);

    private static Property P(BacnetPropertyIds id, BacnetApplicationTags tag, params string[] values) =>
        new() { Id = id, Tag = tag, Value = values };

    private static Property Text(BacnetPropertyIds id, string value) =>
        P(id, BacnetApplicationTags.BACNET_APPLICATION_TAG_CHARACTER_STRING, value);

    private static Property Unsigned(BacnetPropertyIds id, uint value) =>
        P(id, BacnetApplicationTags.BACNET_APPLICATION_TAG_UNSIGNED_INT, value.ToString(CultureInfo.InvariantCulture));

    private static Property Enumerated(BacnetPropertyIds id, uint value) =>
        P(id, BacnetApplicationTags.BACNET_APPLICATION_TAG_ENUMERATED, value.ToString(CultureInfo.InvariantCulture));

    private static Property Bool(BacnetPropertyIds id, bool value) =>
        P(id, BacnetApplicationTags.BACNET_APPLICATION_TAG_BOOLEAN, value ? "True" : "False");

    private static Property Bits(BacnetPropertyIds id, string bits) =>
        P(id, BacnetApplicationTags.BACNET_APPLICATION_TAG_BIT_STRING, bits);

    private static List<Property> Identity(BacnetObjectTypes type, uint instance, string name, string description) => new()
    {
        P(BacnetPropertyIds.PROP_OBJECT_IDENTIFIER, BacnetApplicationTags.BACNET_APPLICATION_TAG_OBJECT_ID, $"{type}:{instance}"),
        Text(BacnetPropertyIds.PROP_OBJECT_NAME, name),
        Enumerated(BacnetPropertyIds.PROP_OBJECT_TYPE, (uint)type),
        Text(BacnetPropertyIds.PROP_DESCRIPTION, description),
    };

    private static BacnetObject Make(BacnetObjectTypes type, uint instance, List<Property> properties) =>
        new() { Type = type, Instance = instance, Properties = properties.ToArray() };

    // Sixteen empty slots under the NULL tag: the layout DeviceStorage's
    // WriteCommandableProperty expects (see upstream DeviceStorage.xml).
    private static Property PriorityArray() =>
        P(BacnetPropertyIds.PROP_PRIORITY_ARRAY, BacnetApplicationTags.BACNET_APPLICATION_TAG_NULL,
            Enumerable.Repeat("", 16).ToArray());

    private static BacnetObject Analog(BacnetObjectTypes type, uint instance, string name, string description, float pv, bool commandable,
        uint? notificationClass)
    {
        var p = Identity(type, instance, name, description);
        p.Add(P(BacnetPropertyIds.PROP_PRESENT_VALUE, BacnetApplicationTags.BACNET_APPLICATION_TAG_REAL, R(pv)));
        p.Add(Bits(BacnetPropertyIds.PROP_STATUS_FLAGS, "0000"));
        p.Add(Enumerated(BacnetPropertyIds.PROP_EVENT_STATE, 0));
        p.Add(Bool(BacnetPropertyIds.PROP_OUT_OF_SERVICE, false));
        p.Add(Enumerated(BacnetPropertyIds.PROP_UNITS, (uint)BacnetUnitsId.UNITS_NO_UNITS));
        if (commandable)
        {
            p.Add(PriorityArray());
            p.Add(P(BacnetPropertyIds.PROP_RELINQUISH_DEFAULT, BacnetApplicationTags.BACNET_APPLICATION_TAG_REAL, R(pv)));
        }
        if (notificationClass.HasValue)
        {
            // Intrinsic reporting, high limit only. Event_State, Status_Flags
            // and Acked_Transitions are kept current by DeviceServer.
            p.Add(P(BacnetPropertyIds.PROP_HIGH_LIMIT, BacnetApplicationTags.BACNET_APPLICATION_TAG_REAL, R(AlarmHighLimit)));
            p.Add(P(BacnetPropertyIds.PROP_LOW_LIMIT, BacnetApplicationTags.BACNET_APPLICATION_TAG_REAL, R(0f)));
            p.Add(P(BacnetPropertyIds.PROP_DEADBAND, BacnetApplicationTags.BACNET_APPLICATION_TAG_REAL, R(0f)));
            p.Add(Unsigned(BacnetPropertyIds.PROP_TIME_DELAY, 0));
            p.Add(Unsigned(BacnetPropertyIds.PROP_NOTIFICATION_CLASS, notificationClass.Value));
            p.Add(Bits(BacnetPropertyIds.PROP_LIMIT_ENABLE, "01")); // low-limit off, high-limit on
            p.Add(Bits(BacnetPropertyIds.PROP_EVENT_ENABLE, "101")); // to-offnormal, to-normal
            p.Add(Bits(BacnetPropertyIds.PROP_ACKED_TRANSITIONS, "111"));
            p.Add(Enumerated(BacnetPropertyIds.PROP_NOTIFY_TYPE, (uint)BacnetNotifyTypes.NOTIFY_ALARM));
        }
        return Make(type, instance, p);
    }

    private static BacnetObject NotificationClass(uint instance, string name, string description)
    {
        var p = Identity(BacnetObjectTypes.OBJECT_NOTIFICATION_CLASS, instance, name, description);
        p.Add(Unsigned(BacnetPropertyIds.PROP_NOTIFICATION_CLASS, instance));
        p.Add(P(BacnetPropertyIds.PROP_PRIORITY, BacnetApplicationTags.BACNET_APPLICATION_TAG_UNSIGNED_INT, "100", "100", "100"));
        p.Add(Bits(BacnetPropertyIds.PROP_ACK_REQUIRED, "100")); // to-offnormal
        return Make(BacnetObjectTypes.OBJECT_NOTIFICATION_CLASS, instance, p);
    }

    private static BacnetObject BinaryValue(uint instance, string name, string description, bool active)
    {
        var p = Identity(BacnetObjectTypes.OBJECT_BINARY_VALUE, instance, name, description);
        p.Add(Enumerated(BacnetPropertyIds.PROP_PRESENT_VALUE, active ? 1u : 0u));
        p.Add(Bits(BacnetPropertyIds.PROP_STATUS_FLAGS, "0000"));
        p.Add(Enumerated(BacnetPropertyIds.PROP_EVENT_STATE, 0));
        p.Add(Bool(BacnetPropertyIds.PROP_OUT_OF_SERVICE, false));
        p.Add(PriorityArray());
        p.Add(Enumerated(BacnetPropertyIds.PROP_RELINQUISH_DEFAULT, active ? 1u : 0u));
        return Make(BacnetObjectTypes.OBJECT_BINARY_VALUE, instance, p);
    }

    private static BacnetObject TrendLog(uint instance, string name, string description)
    {
        var p = Identity(BacnetObjectTypes.OBJECT_TRENDLOG, instance, name, description);
        p.Add(Bool(BacnetPropertyIds.PROP_ENABLE, false));
        p.Add(Bool(BacnetPropertyIds.PROP_STOP_WHEN_FULL, false));
        p.Add(Unsigned(BacnetPropertyIds.PROP_BUFFER_SIZE, TrendLogSeedRecords));
        p.Add(Unsigned(BacnetPropertyIds.PROP_RECORD_COUNT, TrendLogSeedRecords));
        p.Add(Unsigned(BacnetPropertyIds.PROP_TOTAL_RECORD_COUNT, TrendLogSeedRecords));
        p.Add(Enumerated(BacnetPropertyIds.PROP_LOGGING_TYPE, 2)); // triggered: the buffer never grows
        p.Add(Bits(BacnetPropertyIds.PROP_STATUS_FLAGS, "0000"));
        p.Add(Enumerated(BacnetPropertyIds.PROP_EVENT_STATE, 0));
        return Make(BacnetObjectTypes.OBJECT_TRENDLOG, instance, p);
    }

    // Deterministic buffer: four REAL records one minute apart.
    private static List<BacnetLogRecord> SeedLog()
    {
        var start = new DateTime(2024, 1, 1, 0, 0, 0, DateTimeKind.Unspecified);
        var records = new List<BacnetLogRecord>();
        for (var i = 0; i < TrendLogSeedRecords; i++)
            records.Add(new BacnetLogRecord(BacnetTrendLogValueType.TL_TYPE_REAL, 20f + i, start.AddMinutes(i), 0));
        return records;
    }

    private static BacnetObject StreamFile(uint instance, string name, string description)
    {
        var p = Identity(BacnetObjectTypes.OBJECT_FILE, instance, name, description);
        p.Add(Text(BacnetPropertyIds.PROP_FILE_TYPE, "application/octet-stream"));
        // PROP_FILE_SIZE is answered from the live content (DeviceServer.ReadOverride).
        p.Add(Unsigned(BacnetPropertyIds.PROP_FILE_SIZE, 0));
        p.Add(P(BacnetPropertyIds.PROP_MODIFICATION_DATE, BacnetApplicationTags.BACNET_APPLICATION_TAG_DATETIME, "2024/01/01-00:00:00.00"));
        p.Add(Bool(BacnetPropertyIds.PROP_ARCHIVE, false));
        p.Add(Bool(BacnetPropertyIds.PROP_READ_ONLY, false));
        p.Add(Enumerated(BacnetPropertyIds.PROP_FILE_ACCESS_METHOD, (uint)BacnetFileAccessMethod.STREAM_ACCESS));
        return Make(BacnetObjectTypes.OBJECT_FILE, instance, p);
    }

    private static BacnetObject RecordFile(uint instance, string name, string description)
    {
        var p = Identity(BacnetObjectTypes.OBJECT_FILE, instance, name, description);
        p.Add(Text(BacnetPropertyIds.PROP_FILE_TYPE, "text/plain"));
        // PROP_FILE_SIZE and PROP_RECORD_COUNT are answered from the live content.
        p.Add(Unsigned(BacnetPropertyIds.PROP_FILE_SIZE, 0));
        p.Add(Unsigned(BacnetPropertyIds.PROP_RECORD_COUNT, 0));
        p.Add(P(BacnetPropertyIds.PROP_MODIFICATION_DATE, BacnetApplicationTags.BACNET_APPLICATION_TAG_DATETIME, "2024/01/01-00:00:00.00"));
        p.Add(Bool(BacnetPropertyIds.PROP_ARCHIVE, false));
        p.Add(Bool(BacnetPropertyIds.PROP_READ_ONLY, false));
        p.Add(Enumerated(BacnetPropertyIds.PROP_FILE_ACCESS_METHOD, (uint)BacnetFileAccessMethod.RECORD_ACCESS));
        return Make(BacnetObjectTypes.OBJECT_FILE, instance, p);
    }

    private static BacnetObject Device(uint instance, string name, string description, BacnetClient client,
        string adapterVersion, string peerVersion, IEnumerable<BacnetObjectTypes> servedTypes, bool alarms)
    {
        var services = new BacnetBitString();
        services.SetBit((byte)BacnetServicesSupported.MAX_BACNET_SERVICES_SUPPORTED, false);
        foreach (var s in DeviceServer.ServicesSupported)
            services.SetBit((byte)s, true);
        if (alarms)
        {
            services.SetBit((byte)BacnetServicesSupported.SERVICE_SUPPORTED_GET_EVENT_INFORMATION, true);
            services.SetBit((byte)BacnetServicesSupported.SERVICE_SUPPORTED_ACKNOWLEDGE_ALARM, true);
            services.SetBit((byte)BacnetServicesSupported.SERVICE_SUPPORTED_UNCONFIRMED_EVENT_NOTIFICATION, true);
        }

        var types = new BacnetBitString();
        types.SetBit((byte)BacnetObjectTypes.OBJECT_TREND_LOG_MULTIPLE, false);
        foreach (var t in servedTypes)
            types.SetBit((byte)t, true);

        var p = Identity(BacnetObjectTypes.OBJECT_DEVICE, instance, name, description);
        p.Add(Enumerated(BacnetPropertyIds.PROP_SYSTEM_STATUS, (uint)BacnetDeviceStatus.OPERATIONAL));
        p.Add(Text(BacnetPropertyIds.PROP_VENDOR_NAME, "otfabric bacnet-interop"));
        p.Add(Unsigned(BacnetPropertyIds.PROP_VENDOR_IDENTIFIER, client.VendorId));
        p.Add(Text(BacnetPropertyIds.PROP_MODEL_NAME, "System.IO.BACnet interop adapter"));
        p.Add(Text(BacnetPropertyIds.PROP_FIRMWARE_REVISION, peerVersion));
        p.Add(Text(BacnetPropertyIds.PROP_APPLICATION_SOFTWARE_VERSION, adapterVersion));
        p.Add(Text(BacnetPropertyIds.PROP_LOCATION, "bacnet-interop"));
        p.Add(Unsigned(BacnetPropertyIds.PROP_PROTOCOL_VERSION, 1));
        p.Add(Unsigned(BacnetPropertyIds.PROP_PROTOCOL_REVISION, 14));
        p.Add(Bits(BacnetPropertyIds.PROP_PROTOCOL_SERVICES_SUPPORTED, services.ToString()));
        p.Add(Bits(BacnetPropertyIds.PROP_PROTOCOL_OBJECT_TYPES_SUPPORTED, types.ToString()));
        // PROP_OBJECT_LIST is answered from the storage's objects (DeviceServer.ReadOverride).
        p.Add(P(BacnetPropertyIds.PROP_OBJECT_LIST, BacnetApplicationTags.BACNET_APPLICATION_TAG_OBJECT_ID));
        // What the stack puts in its I-Am: the transport's APDU limit.
        p.Add(Unsigned(BacnetPropertyIds.PROP_MAX_APDU_LENGTH_ACCEPTED, (uint)client.GetMaxApdu()));
        p.Add(Enumerated(BacnetPropertyIds.PROP_SEGMENTATION_SUPPORTED, (uint)BacnetSegmentations.SEGMENTATION_BOTH));
        p.Add(Unsigned(BacnetPropertyIds.PROP_MAX_SEGMENTS_ACCEPTED, 64));
        p.Add(Unsigned(BacnetPropertyIds.PROP_APDU_SEGMENT_TIMEOUT, (uint)client.Timeout));
        p.Add(Unsigned(BacnetPropertyIds.PROP_APDU_TIMEOUT, (uint)client.Timeout));
        p.Add(Unsigned(BacnetPropertyIds.PROP_NUMBER_OF_APDU_RETRIES, (uint)client.Retries));
        p.Add(P(BacnetPropertyIds.PROP_DEVICE_ADDRESS_BINDING, BacnetApplicationTags.BACNET_APPLICATION_TAG_NULL));
        p.Add(Unsigned(BacnetPropertyIds.PROP_DATABASE_REVISION, 1));
        return Make(BacnetObjectTypes.OBJECT_DEVICE, instance, p);
    }
}
