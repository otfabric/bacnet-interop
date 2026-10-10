// SPDX-License-Identifier: MIT

using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO.BACnet;
using System.IO.BACnet.Serialize;
using System.IO.BACnet.Storage;
using System.Linq;
using System.Threading;

namespace Otfabric.BacnetInterop.SysIoBacnet;

// Glue between System.IO.BACnet's BacnetClient events and its DeviceStorage.
//
// What the NuGet package does itself ("native"): BVLC/NPDU/APDU, request
// decoding and dispatch, Reject for a service nobody handles, Abort for a
// request it cannot decode, segmented request reassembly, segmented ComplexACK
// transmission, every response encoder, and the DeviceStorage read/write model
// (array index 0/N, Device wildcard instance, per-property ReadPropertyMultiple
// errors, the priority array of a commandable present-value, change events).
//
// What this file adds ("adapter-shim"), following the handlers in the upstream
// BasicServer and Bacnet.Room.Simulator examples: mapping DeviceStorage status
// codes to BACnet Error class/code, the list of writable properties, the COV
// subscription table, the Trend Log buffer and the File contents.
internal sealed class DeviceServer : IDisposable
{
    // Protocol_Services_Supported: exactly the services wired below.
    internal static readonly BacnetServicesSupported[] ServicesSupported =
    {
        BacnetServicesSupported.SERVICE_SUPPORTED_WHO_IS,
        BacnetServicesSupported.SERVICE_SUPPORTED_I_AM,
        BacnetServicesSupported.SERVICE_SUPPORTED_WHO_HAS,
        BacnetServicesSupported.SERVICE_SUPPORTED_I_HAVE,
        BacnetServicesSupported.SERVICE_SUPPORTED_READ_PROPERTY,
        BacnetServicesSupported.SERVICE_SUPPORTED_READ_PROP_MULTIPLE,
        BacnetServicesSupported.SERVICE_SUPPORTED_WRITE_PROPERTY,
        BacnetServicesSupported.SERVICE_SUPPORTED_WRITE_PROP_MULTIPLE,
        BacnetServicesSupported.SERVICE_SUPPORTED_SUBSCRIBE_COV,
        BacnetServicesSupported.SERVICE_SUPPORTED_SUBSCRIBE_COV_PROPERTY,
        BacnetServicesSupported.SERVICE_SUPPORTED_CONFIRMED_COV_NOTIFICATION,
        BacnetServicesSupported.SERVICE_SUPPORTED_UNCONFIRMED_COV_NOTIFICATION,
        BacnetServicesSupported.SERVICE_SUPPORTED_READ_RANGE,
        BacnetServicesSupported.SERVICE_SUPPORTED_ATOMIC_READ_FILE,
        BacnetServicesSupported.SERVICE_SUPPORTED_ATOMIC_WRITE_FILE,
        BacnetServicesSupported.SERVICE_SUPPORTED_REINITIALIZE_DEVICE,
        BacnetServicesSupported.SERVICE_SUPPORTED_TIME_SYNCHRONIZATION,
        BacnetServicesSupported.SERVICE_SUPPORTED_UTC_TIME_SYNCHRONIZATION,
    };

    private const BacnetSegmentations Segmentation = BacnetSegmentations.SEGMENTATION_BOTH;

    private readonly BacnetClient _client;
    private readonly DeviceModel _model;
    private readonly DeviceStorage _storage;

    // Request handlers run on thread-pool threads; everything that touches the
    // storage or the tables below takes this lock (as the upstream examples do).
    private readonly object _gate = new();

    private readonly List<Subscription> _subscriptions = new();
    private readonly BlockingCollection<Action> _notifications = new();
    private readonly Thread _notifier;

    // BACNET_EMIT_EVENT=1: one UnconfirmedEventNotification to whoever sends
    // the first ReadProperty (the trigger the other adapters use).
    private readonly bool _emitEvent;
    private bool _emitted;

    // The peer whose request is being executed; the recipient of the event
    // notification when that request moves an object in or out of alarm.
    private BacnetAddress? _requester;

    public DeviceServer(BacnetClient client, DeviceModel model, bool emitEvent)
    {
        _emitEvent = emitEvent;
        _client = client;
        _model = model;
        _storage = model.Storage;
        _notifier = new Thread(NotifyLoop) { IsBackground = true, Name = "cov-notify" };
    }

    public void Start()
    {
        _storage.ReadOverride += ReadOverride;
        _storage.ChangeOfValue += OnChangeOfValue;

        _client.OnWhoIs += OnWhoIs;
        _client.OnWhoHas += OnWhoHas;
        _client.OnReadPropertyRequest += OnReadProperty;
        _client.OnReadPropertyMultipleRequest += OnReadPropertyMultiple;
        _client.OnWritePropertyRequest += OnWriteProperty;
        _client.OnWritePropertyMultipleRequest += OnWritePropertyMultiple;
        _client.OnSubscribeCOV += OnSubscribeCov;
        _client.OnSubscribeCOVProperty += OnSubscribeCovProperty;
        _client.OnReadRange += OnReadRange;
        _client.OnAtomicReadFileRequest += OnAtomicReadFile;
        _client.OnAtomicWriteFileRequest += OnAtomicWriteFile;
        if (_model.Alarms.Count > 0)
        {
            _client.OnGetAlarmSummaryOrEventInformation += OnGetEventInformation;
            _client.OnAlarmAcknowledge += OnAcknowledgeAlarm;
        }
        _client.OnReinitializedDevice += OnReinitializeDevice;
        _client.OnTimeSynchronize += OnTimeSynchronize;
        // Not wired on purpose (BacnetClient then answers Reject
        // unrecognized-service itself): DeviceCommunicationControl,
        // CreateObject / DeleteObject, PrivateTransfer, and the alarm services
        // when the fixture has no Notification Class. GetAlarmSummary is
        // rejected by BacnetClient 4.0.0 even with a handler registered.

        _notifier.Start();
        _client.Start();

        // Startup announcement, as every upstream server example sends it.
        try
        {
            _client.Iam(_storage.DeviceId, Segmentation);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"sysiobacnet startup I-Am not sent: {ex.Message}");
        }
    }

    public void Dispose()
    {
        _notifications.CompleteAdding();
    }

    // ---------------------------------------------------------------------
    // DeviceStorage hooks
    // ---------------------------------------------------------------------

    // Values DeviceStorage cannot hold as static property text. Object_List is
    // answered the way the upstream Room.Simulator example does it.
    private void ReadOverride(BacnetObjectId objectId, BacnetPropertyIds propertyId, uint arrayIndex,
        out IList<BacnetValue> value, out DeviceStorage.ErrorCodes status, out bool handled)
    {
        handled = true;
        value = Array.Empty<BacnetValue>();
        status = DeviceStorage.ErrorCodes.Good;

        if (objectId.type == BacnetObjectTypes.OBJECT_DEVICE && objectId.instance == _storage.DeviceId
            && propertyId == BacnetPropertyIds.PROP_OBJECT_LIST)
        {
            var objects = _storage.Objects;
            if (arrayIndex == 0)
                value = new[] { new BacnetValue(BacnetApplicationTags.BACNET_APPLICATION_TAG_UNSIGNED_INT, (uint)objects.Length) };
            else if (arrayIndex != ASN1.BACNET_ARRAY_ALL)
                value = new[] { ObjectIdValue(objects[arrayIndex - 1]) }; // out of range throws, see OnReadProperty
            else
                value = objects.Select(ObjectIdValue).ToArray();
        }
        else if (objectId.type == BacnetObjectTypes.OBJECT_FILE && propertyId == BacnetPropertyIds.PROP_FILE_SIZE
                 && _model.Files.TryGetValue(objectId, out var content))
        {
            value = new[] { new BacnetValue(BacnetApplicationTags.BACNET_APPLICATION_TAG_UNSIGNED_INT, (uint)content.Length) };
        }
        else if (objectId.type == BacnetObjectTypes.OBJECT_FILE && _model.RecordFiles.TryGetValue(objectId, out var records)
                 && propertyId is BacnetPropertyIds.PROP_FILE_SIZE or BacnetPropertyIds.PROP_RECORD_COUNT)
        {
            var n = propertyId == BacnetPropertyIds.PROP_RECORD_COUNT ? records.Count : records.Sum(r => r.Length);
            value = new[] { new BacnetValue(BacnetApplicationTags.BACNET_APPLICATION_TAG_UNSIGNED_INT, (uint)n) };
        }
        else
        {
            handled = false;
        }
    }

    private static BacnetValue ObjectIdValue(System.IO.BACnet.Storage.Object o) =>
        new(BacnetApplicationTags.BACNET_APPLICATION_TAG_OBJECT_ID, new BacnetObjectId(o.Type, o.Instance));

    // ---------------------------------------------------------------------
    // Who-Is / Who-Has
    // ---------------------------------------------------------------------

    private void OnWhoIs(BacnetClient sender, BacnetAddress adr, int lowLimit, int highLimit)
    {
        if (!InRange(lowLimit, highLimit)) return;
        // Answer the requester directly (BacnetClient.Iam's "receiver"). A
        // unicast I-Am reaches a client on any port and across a router; the
        // upstream examples broadcast it instead.
        sender.Iam(_storage.DeviceId, Segmentation, receiver: adr);
    }

    private void OnWhoHas(BacnetClient sender, BacnetAddress adr, int lowLimit, int highLimit, BacnetObjectId? objId, string objName)
    {
        if (!InRange(lowLimit, highLimit)) return;
        BacnetObjectId found;
        string name;
        lock (_gate)
        {
            System.IO.BACnet.Storage.Object? match = null;
            if (objId.HasValue)
                match = _storage.FindObject(objId.Value);
            else if (objName != null)
                match = _storage.Objects.FirstOrDefault(o => ObjectName(o) == objName);
            if (match == null) return;
            found = new BacnetObjectId(match.Type, match.Instance);
            name = ObjectName(match) ?? "";
        }
        sender.IHave(new BacnetObjectId(BacnetObjectTypes.OBJECT_DEVICE, _storage.DeviceId), found, name, receiver: adr);
    }

    private bool InRange(int lowLimit, int highLimit)
    {
        if (lowLimit != -1 && _storage.DeviceId < lowLimit) return false;
        if (highLimit != -1 && _storage.DeviceId > highLimit) return false;
        return true;
    }

    private static string? ObjectName(System.IO.BACnet.Storage.Object o) =>
        o.Properties.FirstOrDefault(p => p.Id == BacnetPropertyIds.PROP_OBJECT_NAME)?.Value?.FirstOrDefault();

    // ---------------------------------------------------------------------
    // ReadProperty / ReadPropertyMultiple
    // ---------------------------------------------------------------------

    private void OnReadProperty(BacnetClient sender, BacnetAddress adr, byte invokeId, BacnetObjectId objectId,
        BacnetPropertyReference property, BacnetMaxSegments maxSegments)
    {
        const BacnetConfirmedServices service = BacnetConfirmedServices.SERVICE_CONFIRMED_READ_PROPERTY;
        lock (_gate)
        {
            IList<BacnetValue> value;
            try
            {
                var code = _storage.ReadProperty(objectId, (BacnetPropertyIds)property.propertyIdentifier,
                    property.propertyArrayIndex, out value);
                if (code != DeviceStorage.ErrorCodes.Good)
                {
                    SendStorageError(sender, adr, service, invokeId, code);
                    return;
                }
            }
            catch (Exception ex) when (ex is IndexOutOfRangeException or ArgumentOutOfRangeException)
            {
                // DeviceStorage indexes the value list without a bounds check.
                sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_PROPERTY, BacnetErrorCodes.ERROR_CODE_INVALID_ARRAY_INDEX);
                return;
            }
            catch (Exception ex)
            {
                Unexpected(service, ex);
                sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_DEVICE, BacnetErrorCodes.ERROR_CODE_OTHER);
                return;
            }
            // Outside the try on purpose: what the stack does when it cannot
            // encode or send a reply (Abort) is its own behaviour.
            sender.ReadPropertyResponse(adr, invokeId, sender.GetSegmentBuffer(maxSegments), objectId, property, value);

            if (_emitEvent && !_emitted)
            {
                _emitted = true;
                var av = _storage.Objects.FirstOrDefault(o => o.Type == BacnetObjectTypes.OBJECT_ANALOG_VALUE);
                var target = new BacnetObjectId(BacnetObjectTypes.OBJECT_ANALOG_VALUE, av?.Instance ?? 1);
                QueueEventNotification(adr, OutOfRangeEvent(target, 1, BacnetNotifyTypes.NOTIFY_ALARM,
                    BacnetEventStates.EVENT_STATE_NORMAL, BacnetEventStates.EVENT_STATE_HIGH_LIMIT,
                    new BacnetGenericTime(default, BacnetTimestampTags.TIME_STAMP_SEQUENCE, 1), 0f, false));
            }
        }
    }

    // The upstream example handler in substance: DeviceStorage produces the
    // per-property results, errors included.
    private void OnReadPropertyMultiple(BacnetClient sender, BacnetAddress adr, byte invokeId,
        IList<BacnetReadAccessSpecification> properties, BacnetMaxSegments maxSegments)
    {
        const BacnetConfirmedServices service = BacnetConfirmedServices.SERVICE_CONFIRMED_READ_PROP_MULTIPLE;
        lock (_gate)
        {
            var values = new List<BacnetReadAccessResult>();
            try
            {
                foreach (var p in properties)
                {
                    IList<BacnetPropertyValue> value;
                    if (p.propertyReferences.Count == 1 && p.propertyReferences[0].propertyIdentifier == (uint)BacnetPropertyIds.PROP_ALL)
                    {
                        if (!_storage.ReadPropertyAll(Normalize(p.objectIdentifier), out value))
                        {
                            sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_OBJECT, BacnetErrorCodes.ERROR_CODE_UNKNOWN_OBJECT);
                            return;
                        }
                    }
                    else
                    {
                        _storage.ReadPropertyMultiple(p.objectIdentifier, p.propertyReferences, out value);
                    }
                    values.Add(new BacnetReadAccessResult(p.objectIdentifier, value));
                }
            }
            catch (Exception ex) when (ex is IndexOutOfRangeException or ArgumentOutOfRangeException)
            {
                // DeviceStorage.ReadPropertyMultiple has no per-property result
                // for an array index out of range: the whole request fails.
                sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_PROPERTY, BacnetErrorCodes.ERROR_CODE_INVALID_ARRAY_INDEX);
                return;
            }
            catch (Exception ex)
            {
                Unexpected(service, ex);
                sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_DEVICE, BacnetErrorCodes.ERROR_CODE_OTHER);
                return;
            }
            // Outside the try on purpose, as in OnReadProperty. BACnet 4.0.0
            // throws here when a result holds an empty list (ASN1.
            // encode_read_access_result reads value[0] unchecked) and
            // BacnetClient then answers Abort (other).
            sender.ReadPropertyMultipleResponse(adr, invokeId, sender.GetSegmentBuffer(maxSegments), values);
        }
    }

    // DeviceStorage resolves the Device wildcard instance in ReadProperty and
    // WriteProperty but not in its Find* lookups.
    private BacnetObjectId Normalize(BacnetObjectId id)
    {
        if (id.type == BacnetObjectTypes.OBJECT_DEVICE && id.instance >= ASN1.BACNET_MAX_INSTANCE)
            id.instance = _storage.DeviceId;
        return id;
    }

    private static (BacnetErrorClasses, BacnetErrorCodes) MapStorageError(DeviceStorage.ErrorCodes code) => code switch
    {
        // The same mapping DeviceStorage.ReadPropertyMultiple applies itself.
        DeviceStorage.ErrorCodes.UnknownObject => (BacnetErrorClasses.ERROR_CLASS_OBJECT, BacnetErrorCodes.ERROR_CODE_UNKNOWN_OBJECT),
        DeviceStorage.ErrorCodes.NotExist => (BacnetErrorClasses.ERROR_CLASS_PROPERTY, BacnetErrorCodes.ERROR_CODE_UNKNOWN_PROPERTY),
        DeviceStorage.ErrorCodes.UnknownProperty => (BacnetErrorClasses.ERROR_CLASS_PROPERTY, BacnetErrorCodes.ERROR_CODE_UNKNOWN_PROPERTY),
        DeviceStorage.ErrorCodes.WriteAccessDenied => (BacnetErrorClasses.ERROR_CLASS_PROPERTY, BacnetErrorCodes.ERROR_CODE_WRITE_ACCESS_DENIED),
        _ => (BacnetErrorClasses.ERROR_CLASS_DEVICE, BacnetErrorCodes.ERROR_CODE_OTHER),
    };

    // A handler failure the adapter did not anticipate: answered with Error
    // device/other and always reported on stderr.
    private static void Unexpected(BacnetConfirmedServices service, Exception ex)
    {
        Console.Error.WriteLine($"sysiobacnet {service} failed: {ex}");
    }

    private static void SendStorageError(BacnetClient sender, BacnetAddress adr, BacnetConfirmedServices service, byte invokeId,
        DeviceStorage.ErrorCodes code)
    {
        var (errorClass, errorCode) = MapStorageError(code);
        sender.ErrorResponse(adr, service, invokeId, errorClass, errorCode);
    }

    // ---------------------------------------------------------------------
    // WriteProperty / WritePropertyMultiple
    // ---------------------------------------------------------------------

    private void OnWriteProperty(BacnetClient sender, BacnetAddress adr, byte invokeId, BacnetObjectId objectId,
        BacnetPropertyValue value, BacnetMaxSegments maxSegments)
    {
        const BacnetConfirmedServices service = BacnetConfirmedServices.SERVICE_CONFIRMED_WRITE_PROPERTY;
        lock (_gate)
        {
            _requester = adr;
            var error = Write(objectId, value);
            _requester = null;
            if (error == null)
                sender.SimpleAckResponse(adr, service, invokeId);
            else
                sender.ErrorResponse(adr, service, invokeId, error.Value.Item1, error.Value.Item2);
        }
    }

    // DeviceStorage.WritePropertyMultiple exists but bypasses the priority
    // array, so each property takes the WriteProperty path instead. The first
    // failure ends the request. BacnetClient has no WritePropertyMultiple-Error
    // encoder: the Error PDU carries the class and code only, without
    // firstFailedWriteAttempt.
    private void OnWritePropertyMultiple(BacnetClient sender, BacnetAddress adr, byte invokeId,
        ICollection<BacnetWriteAccessSpecification> properties, BacnetMaxSegments maxSegments)
    {
        const BacnetConfirmedServices service = BacnetConfirmedServices.SERVICE_CONFIRMED_WRITE_PROP_MULTIPLE;
        lock (_gate)
        {
            foreach (var spec in properties)
            {
                foreach (var v in spec.propertyValues)
                {
                    var value = v;
                    // The WritePropertyMultiple decoder reports an absent priority as 0;
                    // the WriteProperty decoder reports it as 16.
                    if (value.priority == ASN1.BACNET_NO_PRIORITY)
                        value.priority = (byte)ASN1.BACNET_MAX_PRIORITY;
                    _requester = adr;
                    var error = Write(spec.objectIdentifier, value);
                    _requester = null;
                    if (error == null) continue;
                    sender.ErrorResponse(adr, service, invokeId, error.Value.Item1, error.Value.Item2);
                    return;
                }
            }
            sender.SimpleAckResponse(adr, service, invokeId);
        }
    }

    // One property write. Returns null on success. Caller holds _gate.
    private (BacnetErrorClasses, BacnetErrorCodes)? Write(BacnetObjectId objectId, BacnetPropertyValue value)
    {
        try
        {
            objectId = Normalize(objectId);
            var propertyId = (BacnetPropertyIds)value.property.propertyIdentifier;
            if (_storage.FindObject(objectId) == null)
                return (BacnetErrorClasses.ERROR_CLASS_OBJECT, BacnetErrorCodes.ERROR_CODE_UNKNOWN_OBJECT);
            var stored = _storage.FindProperty(objectId, propertyId);
            if (stored == null)
                return (BacnetErrorClasses.ERROR_CLASS_PROPERTY, BacnetErrorCodes.ERROR_CODE_UNKNOWN_PROPERTY);
            if (!_model.IsWritable(objectId.type, propertyId))
                return (BacnetErrorClasses.ERROR_CLASS_PROPERTY, BacnetErrorCodes.ERROR_CODE_WRITE_ACCESS_DENIED);
            // Every writable property is a scalar; DeviceStorage.WriteProperty
            // would replace the whole value list whatever the index says.
            if (value.property.propertyArrayIndex != ASN1.BACNET_ARRAY_ALL)
                return (BacnetErrorClasses.ERROR_CLASS_PROPERTY, BacnetErrorCodes.ERROR_CODE_PROPERTY_IS_NOT_AN_ARRAY);
            if (value.value == null || value.value.Count != 1)
                return (BacnetErrorClasses.ERROR_CLASS_PROPERTY, BacnetErrorCodes.ERROR_CODE_INVALID_DATA_TYPE);

            var commandable = propertyId == BacnetPropertyIds.PROP_PRESENT_VALUE
                              && _storage.FindProperty(objectId, BacnetPropertyIds.PROP_PRIORITY_ARRAY) != null;
            var written = value.value[0];
            var isNull = written.Tag == BacnetApplicationTags.BACNET_APPLICATION_TAG_NULL;
            // DeviceStorage stores values as text under the property's tag and
            // does not check what it is given.
            if (!(written.Tag == stored.Tag || (isNull && commandable)))
                return (BacnetErrorClasses.ERROR_CLASS_PROPERTY, BacnetErrorCodes.ERROR_CODE_INVALID_DATA_TYPE);

            // The upstream example sequence: commandable path first, plain
            // WriteProperty when DeviceStorage says the property is not commandable.
            var code = _storage.WriteCommandableProperty(objectId, propertyId, written, value.priority);
            if (code == DeviceStorage.ErrorCodes.NotForMe)
                code = _storage.WriteProperty(objectId, propertyId, value.property.propertyArrayIndex, value.value);
            return code == DeviceStorage.ErrorCodes.Good ? null : MapStorageError(code);
        }
        catch (Exception ex)
        {
            Unexpected(BacnetConfirmedServices.SERVICE_CONFIRMED_WRITE_PROPERTY, ex);
            return (BacnetErrorClasses.ERROR_CLASS_DEVICE, BacnetErrorCodes.ERROR_CODE_OTHER);
        }
    }

    // ---------------------------------------------------------------------
    // COV
    // ---------------------------------------------------------------------

    private sealed class Subscription
    {
        public required BacnetAddress Address;
        public required uint ProcessId;
        public required BacnetObjectId Object;
        public BacnetPropertyReference? Property; // null: SubscribeCOV (object subscription)
        public bool Confirmed;
        public uint Lifetime; // seconds, 0 = indefinite
        public DateTime Start;

        public bool Expired(DateTime now) => Lifetime != 0 && (now - Start).TotalSeconds >= Lifetime;

        public uint TimeRemaining(DateTime now) =>
            Lifetime == 0 ? 0 : (uint)Math.Max(0, Lifetime - (now - Start).TotalSeconds);
    }

    private void OnSubscribeCov(BacnetClient sender, BacnetAddress adr, byte invokeId, uint subscriberProcessIdentifier,
        BacnetObjectId monitoredObjectIdentifier, bool cancellationRequest, bool issueConfirmedNotifications, uint lifetime,
        BacnetMaxSegments maxSegments)
    {
        Subscribe(sender, adr, invokeId, BacnetConfirmedServices.SERVICE_CONFIRMED_SUBSCRIBE_COV, subscriberProcessIdentifier,
            monitoredObjectIdentifier, null, cancellationRequest, issueConfirmedNotifications, lifetime);
    }

    private void OnSubscribeCovProperty(BacnetClient sender, BacnetAddress adr, byte invokeId, uint subscriberProcessIdentifier,
        BacnetObjectId monitoredObjectIdentifier, BacnetPropertyReference monitoredProperty, bool cancellationRequest,
        bool issueConfirmedNotifications, uint lifetime, float covIncrement, BacnetMaxSegments maxSegments)
    {
        // covIncrement is decoded by the stack and, as in the upstream examples,
        // not applied: every write to the monitored property is notified.
        Subscribe(sender, adr, invokeId, BacnetConfirmedServices.SERVICE_CONFIRMED_SUBSCRIBE_COV_PROPERTY, subscriberProcessIdentifier,
            monitoredObjectIdentifier, monitoredProperty, cancellationRequest, issueConfirmedNotifications, lifetime);
    }

    private void Subscribe(BacnetClient sender, BacnetAddress adr, byte invokeId, BacnetConfirmedServices service, uint processId,
        BacnetObjectId objectId, BacnetPropertyReference? property, bool cancel, bool confirmed, uint lifetime)
    {
        lock (_gate)
        {
            var now = DateTime.UtcNow;
            _subscriptions.RemoveAll(s => s.Expired(now));

            var existing = _subscriptions.FirstOrDefault(s =>
                s.ProcessId == processId && s.Object.Equals(objectId) && s.Address.Equals(adr)
                && s.Property?.propertyIdentifier == property?.propertyIdentifier);

            if (cancel)
            {
                // Cancelling a subscription that does not exist succeeds (135 13.14.1.2).
                if (existing != null) _subscriptions.Remove(existing);
                sender.SimpleAckResponse(adr, service, invokeId);
                return;
            }

            if (_storage.FindObject(objectId) == null)
            {
                sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_OBJECT, BacnetErrorCodes.ERROR_CODE_UNKNOWN_OBJECT);
                return;
            }
            if (property == null && !_model.IsCovObject(objectId.type))
            {
                sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_OBJECT, BacnetErrorCodes.ERROR_CODE_OPTIONAL_FUNCTIONALITY_NOT_SUPPORTED);
                return;
            }
            if (property != null && _storage.FindProperty(objectId, (BacnetPropertyIds)property.Value.propertyIdentifier) == null)
            {
                sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_PROPERTY, BacnetErrorCodes.ERROR_CODE_UNKNOWN_PROPERTY);
                return;
            }

            if (existing == null)
            {
                existing = new Subscription { Address = adr, ProcessId = processId, Object = objectId, Property = property };
                _subscriptions.Add(existing);
            }
            existing.Confirmed = confirmed;
            existing.Lifetime = lifetime;
            existing.Start = now;

            sender.SimpleAckResponse(adr, service, invokeId);

            // Initial notification with the current values (135 13.14.1.1.4).
            QueueNotification(existing, now);
        }
    }

    // DeviceStorage raises this for every WriteProperty it performs, including
    // the present-value update that follows a priority-array change.
    private void OnChangeOfValue(DeviceStorage sender, BacnetObjectId objectId, BacnetPropertyIds propertyId, uint arrayIndex,
        IList<BacnetValue> value)
    {
        // Raised inside a request handler, so _gate is already held.
        if (propertyId == BacnetPropertyIds.PROP_PRESENT_VALUE && _model.Alarms.TryGetValue(objectId, out var alarm))
            EvaluateAlarm(objectId, alarm);
        var now = DateTime.UtcNow;
        _subscriptions.RemoveAll(s => s.Expired(now));
        foreach (var sub in _subscriptions)
        {
            if (!sub.Object.Equals(objectId)) continue;
            var monitored = sub.Property == null
                ? propertyId is BacnetPropertyIds.PROP_PRESENT_VALUE or BacnetPropertyIds.PROP_STATUS_FLAGS
                : sub.Property.Value.propertyIdentifier == (uint)propertyId;
            if (monitored) QueueNotification(sub, now);
        }
    }

    // Snapshot the values now (under _gate), send from the notifier thread:
    // a confirmed notification blocks until it is acknowledged or times out.
    private void QueueNotification(Subscription sub, DateTime now)
    {
        var values = new List<BacnetPropertyValue>();
        var monitoredId = sub.Property?.propertyIdentifier ?? (uint)BacnetPropertyIds.PROP_PRESENT_VALUE;
        foreach (var id in new[] { monitoredId, (uint)BacnetPropertyIds.PROP_STATUS_FLAGS }.Distinct())
        {
            if (_storage.ReadProperty(sub.Object, (BacnetPropertyIds)id, ASN1.BACNET_ARRAY_ALL, out var v) != DeviceStorage.ErrorCodes.Good)
                continue;
            values.Add(new BacnetPropertyValue { property = new BacnetPropertyReference(id), value = v });
        }
        var remaining = sub.TimeRemaining(now);
        var (address, processId, objectId, confirmed) = (sub.Address, sub.ProcessId, sub.Object, sub.Confirmed);
        _notifications.Add(() =>
        {
            try
            {
                if (!_client.Notify(address, processId, _storage.DeviceId, objectId, remaining, confirmed, values))
                    Console.Error.WriteLine($"sysiobacnet COV notification to {address} for {objectId} was not delivered");
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"sysiobacnet COV notification to {address} for {objectId} failed: {ex.Message}");
            }
        });
    }

    private void NotifyLoop()
    {
        foreach (var send in _notifications.GetConsumingEnumerable())
            send();
    }

    // ---------------------------------------------------------------------
    // ReadRange (Trend Log Log_Buffer)
    // ---------------------------------------------------------------------

    private void OnReadRange(BacnetClient sender, BacnetAddress adr, byte invokeId, BacnetObjectId objectId,
        BacnetPropertyReference property, BacnetReadRangeRequestTypes requestType, uint position, DateTime time, int count,
        BacnetMaxSegments maxSegments)
    {
        const BacnetConfirmedServices service = BacnetConfirmedServices.SERVICE_CONFIRMED_READ_RANGE;
        lock (_gate)
        {
            try
            {
                if (_storage.FindObject(objectId) == null)
                {
                    sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_OBJECT, BacnetErrorCodes.ERROR_CODE_UNKNOWN_OBJECT);
                    return;
                }
                if (!_model.TrendLogs.TryGetValue(objectId, out var log)
                    || property.propertyIdentifier != (uint)BacnetPropertyIds.PROP_LOG_BUFFER)
                {
                    sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_SERVICES, BacnetErrorCodes.ERROR_CODE_PROPERTY_IS_NOT_A_LIST);
                    return;
                }

                // Records are numbered 1..N; nothing was ever purged, so a
                // record's sequence number equals its position.
                int first, last; // inclusive, 1-based; first > last means no items
                switch (requestType)
                {
                    case BacnetReadRangeRequestTypes.RR_READ_ALL:
                        (first, last) = (1, log.Count);
                        break;
                    case BacnetReadRangeRequestTypes.RR_BY_POSITION:
                    case BacnetReadRangeRequestTypes.RR_BY_SEQUENCE:
                        if (count == 0)
                        {
                            sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_SERVICES, BacnetErrorCodes.ERROR_CODE_INCONSISTENT_PARAMETERS);
                            return;
                        }
                        if (position < 1 || position > log.Count)
                            (first, last) = (1, 0);
                        else if (count > 0)
                            (first, last) = ((int)position, (int)Math.Min(log.Count, position + (long)count - 1));
                        else
                            (first, last) = ((int)Math.Max(1, position + (long)count + 1), (int)position);
                        break;
                    case BacnetReadRangeRequestTypes.RR_BY_TIME:
                        if (count == 0)
                        {
                            sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_SERVICES, BacnetErrorCodes.ERROR_CODE_INCONSISTENT_PARAMETERS);
                            return;
                        }
                        if (count > 0)
                        {
                            // The |count| records newer than the reference time.
                            first = log.FindIndex(r => r.timestamp > time) + 1;
                            (first, last) = first == 0 ? (1, 0) : (first, Math.Min(log.Count, first + count - 1));
                        }
                        else
                        {
                            // The |count| records older than the reference time.
                            last = log.FindLastIndex(r => r.timestamp < time) + 1;
                            (first, last) = last == 0 ? (1, 0) : ((int)Math.Max(1, last + (long)count + 1), last);
                        }
                        break;
                    default:
                        sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_SERVICES, BacnetErrorCodes.ERROR_CODE_INCONSISTENT_PARAMETERS);
                        return;
                }

                var itemCount = Math.Max(0, last - first + 1);
                var data = new EncodeBuffer();
                for (var i = first; i <= last; i++)
                    Services.EncodeLogRecord(data, log[i - 1]);

                // Every item the request selects is returned (a reply too large
                // for one APDU is segmented by the stack), so MORE_ITEMS stays clear.
                var flags = BacnetResultFlags.NONE;
                if (itemCount > 0 && first == 1) flags |= BacnetResultFlags.FIRST_ITEM;
                if (itemCount > 0 && last == log.Count) flags |= BacnetResultFlags.LAST_ITEM;

                sender.ReadRangeResponse(adr, invokeId, sender.GetSegmentBuffer(maxSegments), objectId, property, flags,
                    (uint)itemCount, data.ToArray(), requestType, (uint)first);
            }
            catch (Exception ex)
            {
                Unexpected(service, ex);
                sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_DEVICE, BacnetErrorCodes.ERROR_CODE_OTHER);
            }
        }
    }

    // ---------------------------------------------------------------------
    // AtomicReadFile / AtomicWriteFile (stream access)
    // ---------------------------------------------------------------------

    private void OnAtomicReadFile(BacnetClient sender, BacnetAddress adr, byte invokeId, bool isStream, BacnetObjectId objectId,
        int position, uint count, BacnetMaxSegments maxSegments)
    {
        const BacnetConfirmedServices service = BacnetConfirmedServices.SERVICE_CONFIRMED_ATOMIC_READ_FILE;
        lock (_gate)
        {
            try
            {
                if (_model.RecordFiles.TryGetValue(objectId, out var records))
                {
                    ReadRecords(sender, adr, invokeId, isStream, records, position, count);
                    return;
                }
                if (!_model.Files.TryGetValue(objectId, out var content))
                {
                    sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_OBJECT, BacnetErrorCodes.ERROR_CODE_UNKNOWN_OBJECT);
                    return;
                }
                if (!isStream)
                {
                    sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_SERVICES, BacnetErrorCodes.ERROR_CODE_INVALID_FILE_ACCESS_METHOD);
                    return;
                }
                if (position < 0 || position > content.Length)
                {
                    sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_SERVICES, BacnetErrorCodes.ERROR_CODE_INVALID_FILE_START_POSITION);
                    return;
                }
                var n = (int)Math.Min(count, (uint)(content.Length - position));
                var chunk = new byte[n];
                Array.Copy(content, position, chunk, 0, n);
                var endOfFile = position + n >= content.Length;
                sender.ReadFileResponse(adr, invokeId, sender.GetSegmentBuffer(maxSegments), position, (uint)n, endOfFile, chunk);
            }
            catch (Exception ex)
            {
                Unexpected(service, ex);
                sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_DEVICE, BacnetErrorCodes.ERROR_CODE_OTHER);
            }
        }
    }

    private void OnAtomicWriteFile(BacnetClient sender, BacnetAddress adr, byte invokeId, bool isStream, BacnetObjectId objectId,
        int position, uint blockCount, byte[][] blocks, int[] counts, BacnetMaxSegments maxSegments)
    {
        const BacnetConfirmedServices service = BacnetConfirmedServices.SERVICE_CONFIRMED_ATOMIC_WRITE_FILE;
        lock (_gate)
        {
            try
            {
                if (_model.RecordFiles.TryGetValue(objectId, out var records))
                {
                    WriteRecords(sender, adr, invokeId, isStream, records, position, blockCount, blocks, counts);
                    return;
                }
                if (!_model.Files.TryGetValue(objectId, out var content))
                {
                    sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_OBJECT, BacnetErrorCodes.ERROR_CODE_UNKNOWN_OBJECT);
                    return;
                }
                if (!isStream || blockCount != 1)
                {
                    sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_SERVICES, BacnetErrorCodes.ERROR_CODE_INVALID_FILE_ACCESS_METHOD);
                    return;
                }
                // -1 appends (135 14.2.1.1.3).
                var start = position == -1 ? content.Length : position;
                if (start < 0 || start > content.Length)
                {
                    sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_SERVICES, BacnetErrorCodes.ERROR_CODE_INVALID_FILE_START_POSITION);
                    return;
                }
                var n = counts[0];
                var updated = new byte[Math.Max(content.Length, start + n)];
                Array.Copy(content, updated, content.Length);
                Array.Copy(blocks[0], 0, updated, start, n);
                _model.Files[objectId] = updated;
                sender.WriteFileResponse(adr, invokeId, sender.GetSegmentBuffer(maxSegments), start);
            }
            catch (Exception ex)
            {
                Unexpected(service, ex);
                sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_DEVICE, BacnetErrorCodes.ERROR_CODE_OTHER);
            }
        }
    }

    // Record access. The package decodes record requests and has the record
    // forms of both ACK encoders (Services.EncodeAtomicReadFileAcknowledge /
    // EncodeAtomicWriteFileAcknowledge), but BacnetClient.ReadFileResponse and
    // WriteFileResponse pass isStream = true unconditionally. The adapter
    // therefore sends the record ACKs itself, from the package's own public
    // NPDU, APDU and service encoders: an unsegmented ComplexACK.
    private void ReadRecords(BacnetClient sender, BacnetAddress adr, byte invokeId, bool isStream, List<byte[]> records,
        int position, uint count)
    {
        const BacnetConfirmedServices service = BacnetConfirmedServices.SERVICE_CONFIRMED_ATOMIC_READ_FILE;
        if (isStream)
        {
            sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_SERVICES, BacnetErrorCodes.ERROR_CODE_INVALID_FILE_ACCESS_METHOD);
            return;
        }
        if (position < 0 || position > records.Count)
        {
            sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_SERVICES, BacnetErrorCodes.ERROR_CODE_INVALID_FILE_START_POSITION);
            return;
        }
        var n = (int)Math.Min(count, (uint)(records.Count - position));
        var blocks = records.Skip(position).Take(n).ToArray();
        var endOfFile = position + n >= records.Count;
        SendUnsegmentedComplexAck(sender, adr, invokeId, service, b =>
            Services.EncodeAtomicReadFileAcknowledge(b, false, endOfFile, position, (uint)n, blocks, blocks.Select(r => r.Length).ToArray()));
    }

    private void WriteRecords(BacnetClient sender, BacnetAddress adr, byte invokeId, bool isStream, List<byte[]> records,
        int position, uint blockCount, byte[][] blocks, int[] counts)
    {
        const BacnetConfirmedServices service = BacnetConfirmedServices.SERVICE_CONFIRMED_ATOMIC_WRITE_FILE;
        if (isStream)
        {
            sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_SERVICES, BacnetErrorCodes.ERROR_CODE_INVALID_FILE_ACCESS_METHOD);
            return;
        }
        // -1 appends (135 14.2.1.1.3).
        var start = position == -1 ? records.Count : position;
        if (start < 0 || start > records.Count)
        {
            sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_SERVICES, BacnetErrorCodes.ERROR_CODE_INVALID_FILE_START_POSITION);
            return;
        }
        for (var i = 0; i < blockCount; i++)
        {
            var record = new byte[counts[i]];
            Array.Copy(blocks[i], record, counts[i]);
            if (start + i < records.Count) records[start + i] = record;
            else records.Add(record);
        }
        SendUnsegmentedComplexAck(sender, adr, invokeId, service, b => Services.EncodeAtomicWriteFileAcknowledge(b, false, start));
    }

    // What BacnetClient's private SendComplexAck does for a reply that fits
    // one APDU, with the same public encoders.
    private static void SendUnsegmentedComplexAck(BacnetClient sender, BacnetAddress adr, byte invokeId, BacnetConfirmedServices service,
        Action<EncodeBuffer> encode)
    {
        var header = sender.Transport.HeaderLength;
        var b = sender.GetEncodeBuffer(header);
        NPDU.Encode(b, BacnetNpduControls.PriorityNormalMessage, adr.RoutedSource, adr.RoutedDestination);
        var apduStart = b.offset;
        APDU.EncodeComplexAck(b, BacnetPduTypes.PDU_TYPE_COMPLEX_ACK, service, invokeId);
        encode(b);
        if ((b.result & EncodeResult.NotEnoughBuffer) != 0 || b.offset - apduStart > sender.GetMaxApdu())
        {
            sender.SendAbort(adr, invokeId, BacnetAbortReason.SEGMENTATION_NOT_SUPPORTED);
            return;
        }
        sender.Transport.Send(b.buffer, header, b.offset - header, adr, false, 0);
    }

    // ---------------------------------------------------------------------
    // Alarms: intrinsic out-of-range reporting (adapter-supplied semantics)
    // ---------------------------------------------------------------------
    //
    // The package decodes GetEventInformation and AcknowledgeAlarm, encodes the
    // GetEventInformation-ACK and event notifications, and has no alarm
    // behaviour of its own. The state machine here is the adapter's: Analog
    // Value Present_Value above High_Limit (80) is HIGH_LIMIT, otherwise NORMAL.

    private static int TransitionIndex(BacnetEventStates state) => state switch
    {
        BacnetEventStates.EVENT_STATE_NORMAL => 2,
        BacnetEventStates.EVENT_STATE_FAULT => 1,
        _ => 0,
    };

    // Caller holds _gate (raised from DeviceStorage.ChangeOfValue).
    private void EvaluateAlarm(BacnetObjectId objectId, DeviceModel.AlarmState alarm)
    {
        if (_storage.ReadProperty(objectId, BacnetPropertyIds.PROP_PRESENT_VALUE, ASN1.BACNET_ARRAY_ALL, out var pv) != DeviceStorage.ErrorCodes.Good
            || pv.Count != 1)
            return;
        var value = Convert.ToSingle(pv[0].Value, System.Globalization.CultureInfo.InvariantCulture);
        var limit = DeviceModel.AlarmHighLimit;
        if (_storage.ReadProperty(objectId, BacnetPropertyIds.PROP_HIGH_LIMIT, ASN1.BACNET_ARRAY_ALL, out var hl) == DeviceStorage.ErrorCodes.Good
            && hl.Count == 1)
            limit = Convert.ToSingle(hl[0].Value, System.Globalization.CultureInfo.InvariantCulture);

        var next = value > limit ? BacnetEventStates.EVENT_STATE_HIGH_LIMIT : BacnetEventStates.EVENT_STATE_NORMAL;
        if (next == alarm.State) return;
        var from = alarm.State;
        alarm.State = next;

        // Hundredths of a second: what a BACnet time can carry, so the time
        // stamp a client echoes in AcknowledgeAlarm compares equal.
        var now = DateTime.Now;
        now = new DateTime(now.Year, now.Month, now.Day, now.Hour, now.Minute, now.Second, now.Millisecond / 10 * 10, DateTimeKind.Local);
        var stamp = new BacnetGenericTime(now, BacnetTimestampTags.TIME_STAMP_DATETIME);
        var index = TransitionIndex(next);
        alarm.TimeStamps[index] = stamp;
        // Only to-offnormal needs an acknowledgement (Notification Class Ack_Required).
        var ackRequired = index == 0;
        alarm.Acked[index] = !ackRequired;

        var inAlarm = next != BacnetEventStates.EVENT_STATE_NORMAL;
        _storage.WriteProperty(objectId, BacnetPropertyIds.PROP_EVENT_STATE,
            new BacnetValue(BacnetApplicationTags.BACNET_APPLICATION_TAG_ENUMERATED, (uint)next));
        _storage.WriteProperty(objectId, BacnetPropertyIds.PROP_STATUS_FLAGS,
            new BacnetValue(BacnetApplicationTags.BACNET_APPLICATION_TAG_BIT_STRING, BacnetBitString.Parse(inAlarm ? "1000" : "0000")));
        StoreAckedTransitions(objectId, alarm);

        if (_requester != null)
            QueueEventNotification(_requester, OutOfRangeEvent(objectId, alarm.NotificationClass, BacnetNotifyTypes.NOTIFY_ALARM,
                from, next, stamp, value, ackRequired));
    }

    private void StoreAckedTransitions(BacnetObjectId objectId, DeviceModel.AlarmState alarm)
    {
        _storage.WriteProperty(objectId, BacnetPropertyIds.PROP_ACKED_TRANSITIONS,
            new BacnetValue(BacnetApplicationTags.BACNET_APPLICATION_TAG_BIT_STRING, AckedBits(alarm)));
    }

    private static BacnetBitString AckedBits(DeviceModel.AlarmState alarm) =>
        BacnetBitString.Parse(string.Concat(alarm.Acked.Select(a => a ? "1" : "0")));

    private BacnetEventNotificationData OutOfRangeEvent(BacnetObjectId objectId, uint notificationClass, BacnetNotifyTypes notifyType,
        BacnetEventStates from, BacnetEventStates to, BacnetGenericTime stamp, float value, bool ackRequired)
    {
        return new BacnetEventNotificationData
        {
            processIdentifier = 1,
            initiatingObjectIdentifier = new BacnetObjectId(BacnetObjectTypes.OBJECT_DEVICE, _storage.DeviceId),
            eventObjectIdentifier = objectId,
            timeStamp = stamp,
            notificationClass = notificationClass,
            priority = 100,
            eventType = BacnetEventTypes.EVENT_OUT_OF_RANGE,
            messageText = "interop-event",
            notifyType = notifyType,
            ackRequired = ackRequired,
            fromState = from,
            toState = to,
            outOfRange_exceedingValue = value,
            outOfRange_statusFlags = BacnetBitString.Parse(to == BacnetEventStates.EVENT_STATE_NORMAL ? "0000" : "1000"),
            outOfRange_deadband = 0f,
            outOfRange_exceededLimit = DeviceModel.AlarmHighLimit,
        };
    }

    // Unconfirmed, from the notifier thread, after the reply to the request
    // that caused it.
    private void QueueEventNotification(BacnetAddress recipient, BacnetEventNotificationData data)
    {
        _notifications.Add(() =>
        {
            try
            {
                _client.SendUnconfirmedEventNotification(recipient, data);
                Console.Error.WriteLine($"sysiobacnet UnconfirmedEventNotification {data.fromState} -> {data.toState} for {data.eventObjectIdentifier} to {recipient}");
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine($"sysiobacnet event notification to {recipient} failed: {ex.Message}");
            }
        });
    }

    private void OnGetEventInformation(BacnetClient sender, BacnetAddress adr, byte invokeId, bool getEvent, BacnetObjectId objectId,
        BacnetMaxAdpu maxApdu, BacnetMaxSegments maxSegments)
    {
        lock (_gate)
        {
            var summaries = new List<BacnetGetEventInformationData>();
            foreach (var (id, alarm) in _model.Alarms.OrderBy(a => a.Key))
            {
                // 135 13.12: objects not NORMAL, or with an unacknowledged transition.
                if (alarm.State == BacnetEventStates.EVENT_STATE_NORMAL && alarm.Acked.All(a => a)) continue;
                summaries.Add(new BacnetGetEventInformationData
                {
                    objectIdentifier = id,
                    eventState = alarm.State,
                    acknowledgedTransitions = AckedBits(alarm),
                    eventTimeStamps = (BacnetGenericTime[])alarm.TimeStamps.Clone(),
                    notifyType = BacnetNotifyTypes.NOTIFY_ALARM,
                    eventEnable = BacnetBitString.Parse("101"),
                    eventPriorities = new uint[] { 100, 100, 100 },
                });
            }
            sender.GetAlarmSummaryOrEventInformationResponse(adr, true, invokeId, sender.GetSegmentBuffer(maxSegments), summaries.ToArray(), false);
        }
    }

    private void OnAcknowledgeAlarm(BacnetClient sender, BacnetAddress adr, byte invokeId, uint ackProcessIdentifier,
        BacnetObjectId eventObjectIdentifier, uint eventStateAcked, string ackSource, BacnetGenericTime eventTimeStamp,
        BacnetGenericTime ackTimeStamp)
    {
        const BacnetConfirmedServices service = BacnetConfirmedServices.SERVICE_CONFIRMED_ACKNOWLEDGE_ALARM;
        lock (_gate)
        {
            if (_storage.FindObject(eventObjectIdentifier) == null)
            {
                sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_OBJECT, BacnetErrorCodes.ERROR_CODE_UNKNOWN_OBJECT);
                return;
            }
            if (!_model.Alarms.TryGetValue(eventObjectIdentifier, out var alarm))
            {
                sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_OBJECT, BacnetErrorCodes.ERROR_CODE_NO_ALARM_CONFIGURED);
                return;
            }
            var index = TransitionIndex((BacnetEventStates)eventStateAcked);
            // The acknowledged state must be the one the transition led to.
            var reached = index == 0 ? alarm.State != BacnetEventStates.EVENT_STATE_NORMAL && (uint)alarm.State == eventStateAcked
                : index == 2 && alarm.State == BacnetEventStates.EVENT_STATE_NORMAL;
            if (!reached)
            {
                sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_SERVICES, BacnetErrorCodes.ERROR_CODE_INVALID_EVENT_STATE);
                return;
            }
            if (!SameTimeStamp(alarm.TimeStamps[index], eventTimeStamp))
            {
                sender.ErrorResponse(adr, service, invokeId, BacnetErrorClasses.ERROR_CLASS_SERVICES, BacnetErrorCodes.ERROR_CODE_INVALID_TIME_STAMP);
                return;
            }
            alarm.Acked[index] = true;
            StoreAckedTransitions(eventObjectIdentifier, alarm);
            sender.SimpleAckResponse(adr, service, invokeId);
            Program.EmitOperation("acknowledge-alarm");
        }
    }

    private static bool SameTimeStamp(BacnetGenericTime stored, BacnetGenericTime given)
    {
        if (stored.Tag != given.Tag) return false;
        return stored.Tag switch
        {
            BacnetTimestampTags.TIME_STAMP_SEQUENCE => stored.Sequence == given.Sequence,
            _ => Math.Abs((stored.Time - given.Time).TotalMilliseconds) < 10,
        };
    }

    // ---------------------------------------------------------------------
    // Device management / time
    // ---------------------------------------------------------------------

    // Acknowledged without restarting anything, like the upstream example.
    private void OnReinitializeDevice(BacnetClient sender, BacnetAddress adr, byte invokeId, BacnetReinitializedStates state,
        string password, BacnetMaxSegments maxSegments)
    {
        Console.Error.WriteLine($"sysiobacnet ReinitializeDevice state={state}");
        sender.SimpleAckResponse(adr, BacnetConfirmedServices.SERVICE_CONFIRMED_REINITIALIZE_DEVICE, invokeId);
        Program.EmitOperation("reinitialize-device");
    }

    private void OnTimeSynchronize(BacnetClient sender, BacnetAddress adr, DateTime dateTime, bool utc)
    {
        Program.EmitOperation(utc ? "utc-time-synchronization" : "time-synchronization");
    }
}
