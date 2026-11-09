// SPDX-License-Identifier: MIT

package main

import (
	"context"
	"encoding/base64"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/otfabric/go-bacnet"
	"github.com/otfabric/go-bacnet/apdu"
	"github.com/otfabric/go-bacnet/bip"
	"github.com/otfabric/go-bacnet/bvlc"
	"github.com/otfabric/go-bacnet/client"
	"github.com/otfabric/go-bacnet/server/object"
	"github.com/otfabric/go-bacnet/service"
)

type serviceFunc func(e *clientEnv, sc map[string]any) (map[string]any, error)

var services = map[string]serviceFunc{
	"who-is":                          (*clientEnv).whoIs,
	"who-has":                         (*clientEnv).whoHas,
	"read-property":                   (*clientEnv).readProperty,
	"read-property-multiple":          (*clientEnv).readPropertyMultiple,
	"write-property":                  (*clientEnv).writeProperty,
	"write-property-multiple":         (*clientEnv).writePropertyMultiple,
	"subscribe-cov":                   (*clientEnv).subscribeCOV,
	"subscribe-cov-property":          (*clientEnv).subscribeCOVProperty,
	"subscribe-cov-property-multiple": (*clientEnv).subscribeCOVPropertyMultiple,
	"read-range":                      (*clientEnv).readRange,
	"device-communication-control":    (*clientEnv).deviceCommunicationControl,
	"reinitialize-device":             (*clientEnv).reinitializeDevice,
	"atomic-read-file":                (*clientEnv).atomicReadFile,
	"atomic-write-file":               (*clientEnv).atomicWriteFile,
	"add-list-element": func(e *clientEnv, sc map[string]any) (map[string]any, error) {
		return e.listElement(sc, apdu.ServiceAddListElement)
	},
	"remove-list-element": func(e *clientEnv, sc map[string]any) (map[string]any, error) {
		return e.listElement(sc, apdu.ServiceRemoveListElement)
	},
	"create-object":                (*clientEnv).createObject,
	"delete-object":                (*clientEnv).deleteObject,
	"get-event-information":        (*clientEnv).getEventInformation,
	"acknowledge-alarm":            (*clientEnv).acknowledgeAlarm,
	"get-alarm-summary":            (*clientEnv).getAlarmSummary,
	"get-enrollment-summary":       (*clientEnv).getEnrollmentSummary,
	"time-synchronization":         func(e *clientEnv, sc map[string]any) (map[string]any, error) { return e.timeSync(false) },
	"utc-time-synchronization":     func(e *clientEnv, sc map[string]any) (map[string]any, error) { return e.timeSync(true) },
	"unconfirmed-private-transfer": (*clientEnv).unconfirmedPrivateTransfer,
	"confirmed-private-transfer":   (*clientEnv).confirmedPrivateTransfer,
	"confirmed-text-message":       func(e *clientEnv, sc map[string]any) (map[string]any, error) { return e.textMessage(sc, true) },
	"unconfirmed-text-message":     func(e *clientEnv, sc map[string]any) (map[string]any, error) { return e.textMessage(sc, false) },
	"write-group":                  (*clientEnv).writeGroup,
	"read-bdt":                     (*clientEnv).readBDT,
	"read-fdt":                     (*clientEnv).readFDT,
	"write-bdt":                    (*clientEnv).writeBDT,
}

func serviceNames() []string {
	out := make([]string, 0, len(services))
	for k := range services {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func (e *clientEnv) run(sc map[string]any) (map[string]any, error) {
	svc, _ := sc["service"].(string)
	fn, ok := services[svc]
	if !ok {
		return nil, unsupported("service %q: not in this driver", svc)
	}
	return fn(e, sc)
}

// confirmed binds to the DUT and runs one confirmed call; its error becomes
// an observation (Error, Reject, Abort) or an outcome.
func (e *clientEnv) confirmed(call func(ctx context.Context) error) (map[string]any, error) {
	if err := e.bind(); err != nil {
		return nil, err
	}
	ctx, cancel := e.ctx()
	defer cancel()
	before := e.tap.sentCount()
	err := call(ctx)
	if err == nil {
		return nil, nil
	}
	return e.answer(err, before)
}

// answer turns a call's error into what the DUT answered.
func (e *clientEnv) answer(err error, sentBefore int) (map[string]any, error) {
	var wpm *service.WritePropertyMultipleError
	var er *bacnet.ErrorResponse
	var rj *bacnet.RejectError
	var ab *bacnet.AbortError
	var ou *bacnet.OutcomeUnknownError
	switch {
	case errors.As(err, &wpm):
		return map[string]any{"error": map[string]any{
			"class": bacnet.ErrorClassName(wpm.Class), "code": bacnet.ErrorCodeName(wpm.Code),
			"first_failed": map[string]any{"object": objectText(wpm.FirstFailed), "property": propertyText(wpm.FirstProperty.Identifier)},
		}}, nil
	case errors.As(err, &er):
		return map[string]any{"error": map[string]any{"class": bacnet.ErrorClassName(er.Class), "code": bacnet.ErrorCodeName(er.Code)}}, nil
	case errors.As(err, &rj):
		return map[string]any{"reject": bacnet.RejectReasonName(rj.Reason)}, nil
	case errors.As(err, &ab):
		if !ab.Server {
			return nil, fmt.Errorf("go-bacnet aborted the transaction itself: %v", err)
		}
		return map[string]any{"abort": bacnet.AbortReasonName(ab.Reason)}, nil
	case e.tap.sentCount() == sentBefore:
		return nil, unsupported("go-bacnet refused the request before sending it: %v", err)
	case errors.As(err, &ou), errors.Is(err, bacnet.ErrTimeout), errors.Is(err, context.DeadlineExceeded):
		return nil, infra("no answer: %v", err)
	}
	return nil, err
}

func ack(obs map[string]any, err error) (map[string]any, error) {
	if obs == nil && err == nil {
		return map[string]any{"ack": true}, nil
	}
	return obs, err
}

func uintArg(sc map[string]any, key string) (uint32, bool) {
	f, ok := sc[key].(float64)
	if !ok || f < 0 || f > 4294967295 || f != float64(uint32(f)) {
		return 0, false
	}
	return uint32(f), true
}

func propRef(sc map[string]any) (bacnet.PropertyReference, error) {
	pid, err := propertyRef(sc["property"])
	if err != nil {
		return bacnet.PropertyReference{}, err
	}
	ref := bacnet.PropertyReference{Identifier: pid}
	if idx, ok := uintArg(sc, "array_index"); ok {
		ref.ArrayIndex = &idx
	}
	return ref, nil
}

// --- discovery ---------------------------------------------------------------

func limits(sc map[string]any) (*uint32, *uint32) {
	low, okL := uintArg(sc, "low")
	if !okL {
		return nil, nil
	}
	high, okH := uintArg(sc, "high")
	if !okH {
		high = low
	}
	return &low, &high
}

// whoIs broadcasts a Who-Is (through the BBMD when registered, to --broadcast
// when given) and collects the I-Ams of the window.
func (e *clientEnv) whoIs(sc map[string]any) (map[string]any, error) {
	low, high := limits(sc)
	ctx, cancel := context.WithTimeout(context.Background(), e.listen+e.timeout)
	defer cancel()
	devs, err := e.c.Discover(ctx, client.DiscoveryOptions{LowLimit: low, HighLimit: high, Window: e.listen})
	if err != nil {
		return nil, infra("Who-Is: %v", err)
	}
	found := []int{}
	seen := map[uint32]bool{}
	for _, d := range devs {
		if low != nil && (d.Instance < *low || d.Instance > *high) {
			continue
		}
		if e.targetEP.IsValid() && !e.bbmdEP.IsValid() && !d.ImmediatePeer.Equal(e.targetEP) {
			return nil, infra("I-Am for device %d from %s, not the target %s", d.Instance, d.ImmediatePeer, e.targetEP)
		}
		if !seen[d.Instance] {
			seen[d.Instance] = true
			found = append(found, int(d.Instance))
		}
	}
	sort.Ints(found)
	return map[string]any{"i-am": found}, nil
}

func (e *clientEnv) whoHas(sc map[string]any) (map[string]any, error) {
	opts := client.WhoHasOptions{Window: e.listen}
	if o, ok := sc["object"]; ok {
		id, err := objectRef(o)
		if err != nil {
			return nil, err
		}
		opts.Object = &id
	} else {
		name, _ := sc["name"].(string)
		opts.Name = &bacnet.CharacterString{Value: name}
	}
	ctx, cancel := context.WithTimeout(context.Background(), e.listen+e.timeout)
	defer cancel()
	objs, err := e.c.DiscoverObjects(ctx, opts)
	if err != nil {
		return nil, infra("Who-Has: %v", err)
	}
	out := []any{}
	seen := map[string]bool{}
	for _, o := range objs {
		entry := map[string]any{"device": o.DeviceInstance, "object": objectText(o.Object)}
		if k := canonical(entry); !seen[k] {
			seen[k] = true
			out = append(out, entry)
		}
	}
	return map[string]any{"i-have": out}, nil
}

// --- properties --------------------------------------------------------------

func (e *clientEnv) readProperty(sc map[string]any) (map[string]any, error) {
	obj, err := objectRef(sc["object"])
	if err != nil {
		return nil, err
	}
	ref, err := propRef(sc)
	if err != nil {
		return nil, err
	}
	var v bacnet.ApplicationValue
	obs, err := e.confirmed(func(ctx context.Context) error {
		var err error
		v, err = e.c.ReadProperty(ctx, e.tgt, obj, ref)
		return err
	})
	if obs != nil || err != nil {
		return obs, err
	}
	if expect, _ := sc["expect"].(map[string]any); expect["recipients"] != nil {
		return recipientsOf(v)
	}
	return map[string]any{"value": observedValue(v, obj.Type, ref.Identifier)}, nil
}

func (e *clientEnv) readPropertyMultiple(sc map[string]any) (map[string]any, error) {
	reads, _ := sc["reads"].([]any)
	var specs []service.ReadAccessSpecification
	for _, r := range reads {
		m, _ := r.(map[string]any)
		obj, err := objectRef(m["object"])
		if err != nil {
			return nil, err
		}
		spec := service.ReadAccessSpecification{Object: obj}
		props, _ := m["properties"].([]any)
		for _, p := range props {
			pid, err := propertyRef(p)
			if err != nil {
				return nil, err
			}
			spec.Properties = append(spec.Properties, bacnet.PropertyReference{Identifier: pid})
		}
		specs = append(specs, spec)
	}
	var res []service.ReadAccessResult
	obs, err := e.confirmed(func(ctx context.Context) error {
		var err error
		res, err = e.c.ReadPropertyMultiple(ctx, e.tgt, specs)
		return err
	})
	if obs != nil || err != nil {
		return obs, err
	}
	values := []any{}
	for _, r := range res {
		for _, p := range r.Properties {
			entry := map[string]any{"object": objectText(r.Object), "property": propertyText(p.Property.Identifier)}
			var er *bacnet.ErrorResponse
			switch {
			case p.Err == nil:
				entry["value"] = observedValue(p.Value, r.Object.Type, p.Property.Identifier)
			case errors.As(p.Err, &er):
				entry["error"] = map[string]any{"class": bacnet.ErrorClassName(er.Class), "code": bacnet.ErrorCodeName(er.Code)}
			default:
				return nil, fmt.Errorf("ReadPropertyMultiple result %s: %v", objectText(r.Object), p.Err)
			}
			values = append(values, entry)
		}
	}
	return map[string]any{"values": values}, nil
}

func priorityArg(m map[string]any) (*uint8, error) {
	f, ok := m["priority"].(float64)
	if !ok {
		return nil, nil
	}
	if f < 1 || f > 16 || f != float64(uint8(f)) {
		return nil, unsupported("priority %v: go-bacnet writes priorities 1..16", f)
	}
	p := uint8(f)
	return &p, nil
}

func (e *clientEnv) writeProperty(sc map[string]any) (map[string]any, error) {
	obj, err := objectRef(sc["object"])
	if err != nil {
		return nil, err
	}
	ref, err := propRef(sc)
	if err != nil {
		return nil, err
	}
	val, err := appValue(sc["value"])
	if err != nil {
		return nil, err
	}
	prio, err := priorityArg(sc)
	if err != nil {
		return nil, err
	}
	return ack(e.confirmed(func(ctx context.Context) error {
		return e.c.WriteProperty(ctx, e.tgt, obj, ref, val, prio)
	}))
}

func (e *clientEnv) writePropertyMultiple(sc map[string]any) (map[string]any, error) {
	writes, _ := sc["writes"].([]any)
	var specs []service.WriteAccessSpecification
	for _, w := range writes {
		m, _ := w.(map[string]any)
		obj, err := objectRef(m["object"])
		if err != nil {
			return nil, err
		}
		ref, err := propRef(m)
		if err != nil {
			return nil, err
		}
		val, err := appValue(m["value"])
		if err != nil {
			return nil, err
		}
		prio, err := priorityArg(m)
		if err != nil {
			return nil, err
		}
		pv := service.WritePropertyValue{Property: ref, Value: val, Priority: prio}
		if n := len(specs); n > 0 && specs[n-1].Object == obj {
			specs[n-1].Properties = append(specs[n-1].Properties, pv)
		} else {
			specs = append(specs, service.WriteAccessSpecification{Object: obj, Properties: []service.WritePropertyValue{pv}})
		}
	}
	return ack(e.confirmed(func(ctx context.Context) error {
		return e.c.WritePropertyMultiple(ctx, e.tgt, specs)
	}))
}

// --- COV ---------------------------------------------------------------------

// invoke sends one request encoded by go-bacnet's service package with
// InvokeConfirmed and returns the answer PDU, or the observation of an
// Error, Reject or Abort with the Error PDU.
func (e *clientEnv) invoke(choice uint8, payload []byte, sideEffecting bool) (apdu.PDU, map[string]any, error) {
	if err := e.bind(); err != nil {
		return apdu.PDU{}, nil, err
	}
	ctx, cancel := e.ctx()
	defer cancel()
	before := e.tap.sentCount()
	pdu, err := e.c.InvokeConfirmed(ctx, e.tgt, choice, payload, client.ConfirmedInvokeOptions{
		SegmentedResponseAccepted: true, Retransmit: client.RetransmitEnabled, SideEffecting: sideEffecting,
	})
	if err == nil {
		return pdu, nil, nil
	}
	obs, err := e.answer(err, before)
	return pdu, obs, err
}

func (e *clientEnv) subscribed(since time.Time, process uint32, obj bacnet.ObjectIdentifier, multiple, cancel bool) map[string]any {
	got := false
	if !cancel {
		got = e.tap.waitCOV(since, e.targetEP, process, obj, multiple, e.listen)
	}
	return map[string]any{"subscribed": map[string]any{"notification": got}}
}

func covRequest(sc map[string]any) (service.SubscribeCOVRequest, error) {
	obj, err := objectRef(sc["object"])
	if err != nil {
		return service.SubscribeCOVRequest{}, err
	}
	pid, _ := uintArg(sc, "process_id")
	req := service.SubscribeCOVRequest{ProcessIdentifier: pid, MonitoredObject: obj, Cancellation: sc["cancel"] == true}
	if !req.Cancellation {
		req.IssueConfirmed = sc["confirmed"] == true
		req.Lifetime = 60
		if lt, ok := uintArg(sc, "lifetime"); ok {
			req.Lifetime = lt
		}
	}
	return req, nil
}

func (e *clientEnv) subscribeCOV(sc map[string]any) (map[string]any, error) {
	req, err := covRequest(sc)
	if err != nil {
		return nil, err
	}
	payload, err := service.EncodeSubscribeCOV(req)
	if err != nil {
		return nil, unsupported("service.EncodeSubscribeCOV: %v", err)
	}
	since := time.Now()
	if _, obs, err := e.invoke(apdu.ServiceSubscribeCOV, payload, false); obs != nil || err != nil {
		return obs, err
	}
	return e.subscribed(since, req.ProcessIdentifier, req.MonitoredObject, false, req.Cancellation), nil
}

func (e *clientEnv) subscribeCOVProperty(sc map[string]any) (map[string]any, error) {
	base, err := covRequest(sc)
	if err != nil {
		return nil, err
	}
	ref, err := propRef(sc)
	if err != nil {
		return nil, err
	}
	req := service.SubscribeCOVPropertyRequest{SubscribeCOVRequest: base, Property: ref}
	if f, ok := sc["cov_increment"].(float64); ok {
		inc := float32(f)
		req.COVIncrement = &inc
	}
	payload, err := service.EncodeSubscribeCOVProperty(req)
	if err != nil {
		return nil, unsupported("service.EncodeSubscribeCOVProperty: %v", err)
	}
	since := time.Now()
	if _, obs, err := e.invoke(apdu.ServiceSubscribeCOVProperty, payload, false); obs != nil || err != nil {
		return obs, err
	}
	return e.subscribed(since, base.ProcessIdentifier, base.MonitoredObject, false, base.Cancellation), nil
}

func (e *clientEnv) subscribeCOVPropertyMultiple(sc map[string]any) (map[string]any, error) {
	pid, _ := uintArg(sc, "process_id")
	req := service.SubscribeCOVPropertyMultipleRequest{SubscriberProcessIdentifier: pid, Cancellation: sc["cancel"] == true}
	if !req.Cancellation {
		req.IssueConfirmedNotifications = sc["confirmed"] == true
		lt := uint32(60)
		if v, ok := uintArg(sc, "lifetime"); ok {
			lt = v
		}
		req.LifetimeRemaining = &lt
	}
	subs, _ := sc["subscriptions"].([]any)
	for _, s := range subs {
		m, _ := s.(map[string]any)
		obj, err := objectRef(m["object"])
		if err != nil {
			return nil, err
		}
		sub := service.COVMultipleSubscription{Object: obj}
		props, _ := m["properties"].([]any)
		for _, p := range props {
			pm, _ := p.(map[string]any)
			ref, err := propRef(pm)
			if err != nil {
				return nil, err
			}
			cp := service.COVPropertyReference{Property: ref}
			if f, ok := pm["cov_increment"].(float64); ok {
				inc := float32(f)
				cp.COVIncrement = &inc
			}
			sub.Properties = append(sub.Properties, cp)
		}
		req.Subscriptions = append(req.Subscriptions, sub)
	}
	if len(req.Subscriptions) == 0 {
		return nil, fmt.Errorf("no subscriptions")
	}
	payload, err := service.EncodeSubscribeCOVPropertyMultiple(req)
	if err != nil {
		return nil, unsupported("service.EncodeSubscribeCOVPropertyMultiple: %v", err)
	}
	since := time.Now()
	pdu, obs, err := e.invoke(apdu.ServiceSubscribeCOVPropertyMultiple, payload, false)
	if err != nil {
		return nil, err
	}
	if obs != nil {
		addFirstFailedSubscription(obs, pdu)
		return obs, nil
	}
	return e.subscribed(since, pid, req.Subscriptions[0].Object, true, req.Cancellation), nil
}

// addFirstFailedSubscription adds firstFailedSubscription [1] of a
// SubscribeCOVPropertyMultiple-Error (clause 13.16.1.5), decoded with
// apdu.DecodeError: monitoredObjectIdentifier [0] and
// monitoredPropertyReference [1].
func addFirstFailedSubscription(obs map[string]any, pdu apdu.PDU) {
	er, _ := obs["error"].(map[string]any)
	if er == nil || pdu.Error == nil {
		return
	}
	d, err := apdu.DecodeError(pdu.Error.Payload, bacnet.DefaultDecodeLimits())
	if err != nil {
		return
	}
	for _, p := range d.Parameters {
		if !p.Context || p.TagNumber != 1 || !bacnet.IsContextConstructed(p) {
			continue
		}
		ff := map[string]any{}
		for _, el := range p.Value.Elements {
			switch {
			case el.Context && el.TagNumber == 0 && !bacnet.IsContextConstructed(el):
				if id, err := bacnet.ContextObjectID(el); err == nil {
					ff["object"] = objectText(id)
				}
			case el.Context && el.TagNumber == 1 && bacnet.IsContextConstructed(el):
				for _, in := range el.Value.Elements {
					if in.Context && in.TagNumber == 0 {
						if n, err := bacnet.ContextUnsigned32(in); err == nil {
							ff["property"] = propertyText(bacnet.PropertyIdentifier(n))
						}
					}
				}
			}
		}
		er["first_failed"] = ff
	}
}

// --- ReadRange, device management, files ---------------------------------------

var datumTypes = map[service.LogDatumChoice]string{
	service.LogDatumBoolean: "boolean", service.LogDatumReal: "real", service.LogDatumEnumerated: "enumerated",
	service.LogDatumUnsigned: "unsigned", service.LogDatumSigned: "signed", service.LogDatumNull: "null",
}

func (e *clientEnv) readRange(sc map[string]any) (map[string]any, error) {
	obj, err := objectRef(sc["object"])
	if err != nil {
		return nil, err
	}
	ref, err := propRef(sc)
	if err != nil {
		return nil, err
	}
	rg, _ := sc["range"].(map[string]any)
	req := service.ReadRangeRequest{Object: obj, Property: ref}
	count, _ := rg["count"].(float64)
	req.Count = int32(count)
	switch rg["by"] {
	case "position":
		idx, _ := rg["index"].(float64)
		req.By, req.ReferenceIndex = service.ReadRangeByPosition, uint32(idx)
	case "sequence-number", "sequence":
		idx, _ := rg["index"].(float64)
		req.By, req.ReferenceIndex = service.ReadRangeBySequenceNumber, uint32(idx)
	default:
		return nil, unsupported("range %v: not one this driver sends", rg["by"])
	}
	var res service.ReadRangeACK
	obs, err := e.confirmed(func(ctx context.Context) error {
		var err error
		res, err = e.c.ReadRange(ctx, e.tgt, req)
		return err
	})
	if obs != nil || err != nil {
		return obs, err
	}
	records := []any{}
	for _, r := range res.LogRecords {
		v := observedValue(r.Datum, obj.Type, ref.Identifier)
		if t, ok := datumTypes[r.DatumChoice]; ok {
			v["type"] = t
		}
		d, t := r.Timestamp.Date, r.Timestamp.Time
		records = append(records, map[string]any{
			"timestamp": fmt.Sprintf("%04d-%02d-%02dT%02d:%02d:%02d", 1900+int(d.Year), d.Month, d.Day, t.Hour, t.Minute, t.Second),
			"value":     v,
		})
	}
	return map[string]any{"records": records}, nil
}

func password(sc map[string]any) *bacnet.CharacterString {
	if p, ok := sc["password"].(string); ok {
		return &bacnet.CharacterString{Value: p}
	}
	return nil
}

func (e *clientEnv) deviceCommunicationControl(sc map[string]any) (map[string]any, error) {
	states := map[string]service.EnableDisable{
		"enable": service.EnableDisableEnable, "disable": service.EnableDisableDisable,
		"disable-initiation": service.EnableDisableDisableInitiation,
	}
	st, ok := states[fmt.Sprint(sc["state"])]
	if !ok {
		return nil, unsupported("state %v: not an enable-disable name", sc["state"])
	}
	req := service.DeviceCommunicationControlRequest{EnableDisable: st, Password: password(sc)}
	if d, ok := uintArg(sc, "duration"); ok && d <= 65535 {
		m := uint16(d)
		req.TimeDuration = &m
	}
	return ack(e.confirmed(func(ctx context.Context) error {
		return e.c.DeviceCommunicationControl(ctx, e.tgt, req)
	}))
}

func (e *clientEnv) reinitializeDevice(sc map[string]any) (map[string]any, error) {
	st, ok := uintArg(sc, "state")
	if !ok || st > 255 {
		return nil, unsupported("state %v", sc["state"])
	}
	req := service.ReinitializeDeviceRequest{State: service.ReinitializedStateOfDevice(st), Password: password(sc)}
	return ack(e.confirmed(func(ctx context.Context) error {
		return e.c.ReinitializeDevice(ctx, e.tgt, req)
	}))
}

// atomicReadFile reads with stream access: one request of count octets when
// the scenario gives a count, else the whole file with ReadFileStream.
func (e *clientEnv) atomicReadFile(sc map[string]any) (map[string]any, error) {
	obj, err := objectRef(sc["object"])
	if err != nil {
		return nil, err
	}
	start, _ := sc["start"].(float64)
	var data []byte
	var obs map[string]any
	if count, ok := uintArg(sc, "count"); ok {
		obs, err = e.confirmed(func(ctx context.Context) error {
			res, err := e.c.AtomicReadFile(ctx, e.tgt, service.AtomicReadFileRequest{
				File: obj, Access: service.FileAccessStream, StartPosition: int32(start), Count: count})
			data = res.Data
			return err
		})
	} else {
		obs, err = e.confirmed(func(ctx context.Context) error {
			var err error
			data, err = e.c.ReadFileStream(ctx, e.tgt, obj, client.FileReadOptions{})
			return err
		})
	}
	if obs != nil || err != nil {
		return obs, err
	}
	return map[string]any{"octets_base64": base64.StdEncoding.EncodeToString(data)}, nil
}

// atomicWriteFile writes the data in one AtomicWriteFile-Request with stream
// access; go-bacnet segments a request larger than the DUT's Max APDU.
func (e *clientEnv) atomicWriteFile(sc map[string]any) (map[string]any, error) {
	obj, err := objectRef(sc["object"])
	if err != nil {
		return nil, err
	}
	s, _ := sc["data_base64"].(string)
	data, err := base64.StdEncoding.DecodeString(s)
	if err != nil {
		return nil, fmt.Errorf("data_base64: %v", err)
	}
	start, _ := sc["start"].(float64)
	return ack(e.confirmed(func(ctx context.Context) error {
		_, err := e.c.AtomicWriteFile(ctx, e.tgt, service.AtomicWriteFileRequest{
			File: obj, Access: service.FileAccessStream, StartPosition: int32(start), Data: data})
		return err
	}))
}

// --- lists and objects -----------------------------------------------------------

func parseTime(s string) (bacnet.Time, error) {
	var t bacnet.Time
	var h, m, sec, hh int
	n, _ := fmt.Sscanf(s, "%d:%d:%d.%d", &h, &m, &sec, &hh)
	if n < 3 || h > 23 || m > 59 || sec > 59 || hh > 99 {
		return t, fmt.Errorf("time %q", s)
	}
	return bacnet.Time{Hour: uint8(h), Minute: uint8(m), Second: uint8(sec), Hundredths: uint8(hh)}, nil
}

// destination is a scenario's BACnetDestination as go-bacnet's
// object.Destination (server/object), whose Elements encodes it.
func destination(v any) (object.Destination, error) {
	m, _ := v.(map[string]any)
	var d object.Destination
	days, _ := m["valid_days"].([]any)
	for _, x := range days {
		if f, ok := x.(float64); ok && f >= 1 && f <= 7 {
			d.ValidDays |= 1 << (uint(f) - 1)
		}
	}
	var err error
	if d.From, err = parseTime(fmt.Sprint(m["from_time"])); err != nil {
		return d, err
	}
	if d.To, err = parseTime(fmt.Sprint(m["to_time"])); err != nil {
		return d, err
	}
	r, _ := m["recipient"].(map[string]any)
	dev, ok := r["device"].(float64)
	if !ok {
		return d, unsupported("recipient %v: this driver encodes device recipients", r)
	}
	d.Device = &bacnet.ObjectIdentifier{Type: bacnet.ObjectTypeDevice, Instance: uint32(dev)}
	pid, _ := m["process_id"].(float64)
	d.ProcessID = uint32(pid)
	d.Confirmed = m["confirmed"] == true
	trans, _ := m["transitions"].([]any)
	for _, x := range trans {
		for i, n := range transitionNames {
			if x == n {
				d.Transitions |= 1 << i
			}
		}
	}
	return d, nil
}

func recipientsOf(v bacnet.ApplicationValue) (map[string]any, error) {
	var els []bacnet.Element
	switch v.Kind {
	case bacnet.ValueConstructed:
		els = v.Elements
	case bacnet.ValueNull:
	default:
		return nil, fmt.Errorf("Recipient_List decoded as %v, not a list", v.Kind)
	}
	ds, _, err := object.ParseDestinations(els)
	if err != nil {
		return nil, fmt.Errorf("Recipient_List: object.ParseDestinations: %v", err)
	}
	out := []any{}
	for _, d := range ds {
		days := []int{}
		for i := 0; i < 7; i++ {
			if d.ValidDays&(1<<i) != 0 {
				days = append(days, i+1)
			}
		}
		trans := []string{}
		for i, n := range transitionNames {
			if d.Transitions&(1<<i) != 0 {
				trans = append(trans, n)
			}
		}
		r := map[string]any{}
		if d.Device != nil {
			r["device"] = d.Device.Instance
		} else {
			r["network"], r["mac"] = d.Network, fmt.Sprintf("%x", d.MAC)
		}
		out = append(out, map[string]any{
			"valid_days": days, "from_time": timeText(d.From), "to_time": timeText(d.To), "recipient": r,
			"process_id": d.ProcessID, "confirmed": d.Confirmed, "transitions": trans,
		})
	}
	return map[string]any{"recipients": out}, nil
}

// listElement sends AddListElement or RemoveListElement with
// InvokeConfirmed, so that the first-failed-element-number of a
// ChangeList-Error is read with apdu.ErrorDetail.FirstFailedElementNumber
// (the typed methods return the class and code only).
func (e *clientEnv) listElement(sc map[string]any, choice uint8) (map[string]any, error) {
	obj, err := objectRef(sc["object"])
	if err != nil {
		return nil, err
	}
	ref, err := propRef(sc)
	if err != nil {
		return nil, err
	}
	req := service.ListElementRequest{Object: obj, Property: ref}
	elements, _ := sc["elements"].([]any)
	for _, x := range elements {
		d, err := destination(x)
		if err != nil {
			return nil, err
		}
		req.Elements = append(req.Elements, d.Elements()...)
	}
	payload, err := service.EncodeListElementRequest(req)
	if err != nil {
		return nil, unsupported("service.EncodeListElementRequest: %v", err)
	}
	pdu, obs, err := e.invoke(choice, payload, true)
	if err != nil {
		return nil, err
	}
	if obs == nil {
		if pdu.Type != apdu.TypeSimpleACK {
			return nil, fmt.Errorf("answer %v to a list request", pdu.Type)
		}
		return map[string]any{"ack": true}, nil
	}
	if er, _ := obs["error"].(map[string]any); er != nil && pdu.Error != nil {
		if d, err := apdu.DecodeError(pdu.Error.Payload, bacnet.DefaultDecodeLimits()); err == nil {
			if n, ok := d.FirstFailedElementNumber(); ok {
				er["first_failed_element"] = n
			}
		}
	}
	return obs, nil
}

func (e *clientEnv) createObject(sc map[string]any) (map[string]any, error) {
	name, _ := sc["object_type"].(string)
	t, ok := objectTypeByName(name)
	if !ok {
		return nil, unsupported("object type %q: not one go-bacnet names", name)
	}
	req := service.CreateObjectRequest{}
	if inst, ok := uintArg(sc, "instance"); ok {
		req.ObjectIdentifier = &bacnet.ObjectIdentifier{Type: t, Instance: inst}
	} else {
		req.ObjectType = &t
	}
	var res service.CreateObjectACK
	obs, err := e.confirmed(func(ctx context.Context) error {
		var err error
		res, err = e.c.CreateObject(ctx, e.tgt, req)
		return err
	})
	if obs != nil || err != nil {
		return obs, err
	}
	return map[string]any{"created": objectText(res.Object)}, nil
}

func (e *clientEnv) deleteObject(sc map[string]any) (map[string]any, error) {
	obj, err := objectRef(sc["object"])
	if err != nil {
		return nil, err
	}
	return ack(e.confirmed(func(ctx context.Context) error {
		return e.c.DeleteObject(ctx, e.tgt, service.DeleteObjectRequest{Object: obj})
	}))
}

// --- events and alarms -------------------------------------------------------------

func (e *clientEnv) getEventInformation(sc map[string]any) (map[string]any, error) {
	events := []any{}
	var last *bacnet.ObjectIdentifier
	for page := 0; page < 64; page++ {
		var res service.GetEventInformationACK
		obs, err := e.confirmed(func(ctx context.Context) error {
			var err error
			res, err = e.c.GetEventInformation(ctx, e.tgt, service.GetEventInformationRequest{LastReceived: last})
			return err
		})
		if obs != nil || err != nil {
			return obs, err
		}
		for _, s := range res.Summaries {
			events = append(events, map[string]any{"object": objectText(s.Object), "event_state": eventStateName(s.EventState)})
		}
		if !res.MoreEvents || len(res.Summaries) == 0 {
			break
		}
		id := res.Summaries[len(res.Summaries)-1].Object
		last = &id
	}
	return map[string]any{"events": events}, nil
}

// Event_Time_Stamps index of an acknowledged state: 1 TO_OFFNORMAL,
// 2 TO_FAULT, 3 TO_NORMAL (clause 12.1.x Event_Time_Stamps).
var timeStampIndex = map[string]uint32{"offnormal": 1, "high-limit": 1, "low-limit": 1, "fault": 2, "normal": 3}

func dateTimeOf(t time.Time) service.DateTime {
	wd := uint8(t.Weekday())
	if wd == 0 {
		wd = 7
	}
	return service.DateTime{
		Date: bacnet.Date{Year: uint8(t.Year() - 1900), Month: uint8(t.Month()), Day: uint8(t.Day()), Weekday: wd},
		Time: bacnet.Time{Hour: uint8(t.Hour()), Minute: uint8(t.Minute()), Second: uint8(t.Second()), Hundredths: uint8(t.Nanosecond() / 10_000_000)},
	}
}

func (e *clientEnv) acknowledgeAlarm(sc map[string]any) (map[string]any, error) {
	obj, err := objectRef(sc["object"])
	if err != nil {
		return nil, err
	}
	stateName, _ := sc["event_state_acked"].(string)
	state, ok := eventStateByName(stateName)
	if !ok {
		return nil, unsupported("event state %q", stateName)
	}
	pid, _ := uintArg(sc, "process_id")
	req := service.AcknowledgeAlarmRequest{
		ProcessIdentifier: pid, EventObject: obj, EventStateAcked: state,
		AcknowledgmentSource: bacnet.CharacterString{Value: "otfabric interop"},
		TimeOfAcknowledgment: service.TimeStamp{Choice: service.TimeStampDateTime, DateTime: dateTimeOf(time.Now())},
	}
	switch ts := sc["time_stamp"].(type) {
	case string:
		if ts == "event" {
			idx := timeStampIndex[stateName]
			var v bacnet.ApplicationValue
			obs, err := e.confirmed(func(ctx context.Context) error {
				var err error
				v, err = e.c.ReadProperty(ctx, e.tgt, obj, bacnet.PropertyReference{Identifier: bacnet.PropertyEventTimeStamps, ArrayIndex: &idx})
				return err
			})
			if obs != nil || err != nil {
				return nil, infra("Event_Time_Stamps[%d] of %s: %v %v", idx, objectText(obj), obs, err)
			}
			if v.Kind != bacnet.ValueConstructed || len(v.Elements) != 1 {
				return nil, infra("Event_Time_Stamps[%d] of %s decoded as %v", idx, objectText(obj), v.Kind)
			}
			if req.TimeStamp, err = service.DecodeTimeStamp(v.Elements[0]); err != nil {
				return nil, infra("Event_Time_Stamps[%d]: service.DecodeTimeStamp: %v", idx, err)
			}
		} else {
			at, err := time.ParseInLocation("2006-01-02T15:04:05", ts, time.Local)
			if err != nil {
				return nil, fmt.Errorf("time_stamp %q", ts)
			}
			req.TimeStamp = service.TimeStamp{Choice: service.TimeStampDateTime, DateTime: dateTimeOf(at)}
		}
	default:
		return nil, fmt.Errorf("time_stamp %v", ts)
	}
	return ack(e.confirmed(func(ctx context.Context) error {
		return e.c.AcknowledgeAlarm(ctx, e.tgt, req)
	}))
}

func (e *clientEnv) getAlarmSummary(sc map[string]any) (map[string]any, error) {
	var res service.GetAlarmSummaryACK
	obs, err := e.confirmed(func(ctx context.Context) error {
		var err error
		res, err = e.c.GetAlarmSummary(ctx, e.tgt)
		return err
	})
	if obs != nil || err != nil {
		return obs, err
	}
	alarms := []any{}
	for _, a := range res.Entries {
		alarms = append(alarms, map[string]any{"object": objectText(a.Object), "alarm_state": eventStateName(a.AlarmState)})
	}
	return map[string]any{"alarms": alarms}, nil
}

func (e *clientEnv) getEnrollmentSummary(sc map[string]any) (map[string]any, error) {
	req := service.GetEnrollmentSummaryRequest{} // acknowledgmentFilter all
	if f, ok := sc["event_state_filter"].(string); ok {
		n, known := enrollmentStateFilters[f]
		if !known {
			return nil, unsupported("event_state_filter %q", f)
		}
		req.EventStateFilter = &n
	}
	var res service.GetEnrollmentSummaryACK
	obs, err := e.confirmed(func(ctx context.Context) error {
		var err error
		res, err = e.c.GetEnrollmentSummary(ctx, e.tgt, req)
		return err
	})
	if obs != nil || err != nil {
		return obs, err
	}
	list := []any{}
	for _, s := range res.Entries {
		entry := map[string]any{
			"object": objectText(s.Object), "event_state": eventStateName(s.EventState),
			"event_type": eventTypeName(s.EventType), "priority": s.Priority,
		}
		if !s.NotificationClassAbsent {
			entry["notification_class"] = s.NotificationClass
		}
		list = append(list, entry)
	}
	return map[string]any{"enrollments": list}, nil
}

// --- unconfirmed services and messages ---------------------------------------

func sent(operation string) map[string]any {
	return map[string]any{"sent": map[string]any{"operation": operation}}
}

// unconfirmed sends to the bound DUT; the consumer checks what arrived.
func (e *clientEnv) unconfirmed(operation string, send func(ctx context.Context, dest bip.Endpoint) error) (map[string]any, error) {
	if err := e.bind(); err != nil {
		return nil, err
	}
	ctx, cancel := e.ctx()
	defer cancel()
	before := e.tap.sentCount()
	if err := send(ctx, e.targetEP); err != nil {
		if e.tap.sentCount() == before {
			return nil, unsupported("go-bacnet refused the request before sending it: %v", err)
		}
		return nil, infra("send: %v", err)
	}
	time.Sleep(200 * time.Millisecond)
	return sent(operation), nil
}

func (e *clientEnv) timeSync(utc bool) (map[string]any, error) {
	now := time.Now()
	if utc {
		now = now.UTC()
	}
	dt := dateTimeOf(now)
	ts := service.TimeSynchronization{Date: dt.Date, Time: dt.Time}
	if utc {
		return e.unconfirmed("utc-time-synchronization", func(ctx context.Context, dest bip.Endpoint) error {
			return e.c.UTCTimeSynchronization(ctx, dest, false, ts)
		})
	}
	return e.unconfirmed("time-synchronization", func(ctx context.Context, dest bip.Endpoint) error {
		return e.c.TimeSynchronization(ctx, dest, false, ts)
	})
}

func privateTransfer(sc map[string]any) (service.PrivateTransfer, error) {
	vendor, _ := uintArg(sc, "vendor_id")
	number, _ := uintArg(sc, "service_number")
	pt := service.PrivateTransfer{VendorID: uint16(vendor), ServiceNumber: number}
	params, _ := sc["parameters"].([]any)
	for _, p := range params {
		v, err := appValue(p)
		if err != nil {
			return pt, err
		}
		pt.ServiceParameters = append(pt.ServiceParameters, bacnet.Element{Value: v})
	}
	return pt, nil
}

func (e *clientEnv) unconfirmedPrivateTransfer(sc map[string]any) (map[string]any, error) {
	pt, err := privateTransfer(sc)
	if err != nil {
		return nil, err
	}
	return e.unconfirmed("unconfirmed-private-transfer", func(ctx context.Context, dest bip.Endpoint) error {
		return e.c.UnconfirmedPrivateTransfer(ctx, dest, false, pt)
	})
}

func (e *clientEnv) confirmedPrivateTransfer(sc map[string]any) (map[string]any, error) {
	pt, err := privateTransfer(sc)
	if err != nil {
		return nil, err
	}
	return ack(e.confirmed(func(ctx context.Context) error {
		return e.c.ConfirmedPrivateTransfer(ctx, e.tgt, pt)
	}))
}

func (e *clientEnv) textMessage(sc map[string]any, confirmed bool) (map[string]any, error) {
	msg, _ := sc["message"].(string)
	tm := service.TextMessage{
		TextMessageSourceDevice: bacnet.ObjectIdentifier{Type: bacnet.ObjectTypeDevice, Instance: clientInstance},
		Message:                 msg,
	}
	switch sc["message_priority"] {
	case "urgent":
		tm.MessagePriority = 1
	case nil, "normal":
	default:
		return nil, unsupported("message_priority %v", sc["message_priority"])
	}
	if confirmed {
		return ack(e.confirmed(func(ctx context.Context) error {
			return e.c.ConfirmedTextMessage(ctx, e.tgt, tm)
		}))
	}
	return e.unconfirmed("unconfirmed-text-message", func(ctx context.Context, dest bip.Endpoint) error {
		return e.c.UnconfirmedTextMessage(ctx, dest, false, tm)
	})
}

// writeGroup builds the changeList as service.WriteGroup takes it: one
// constructed element per BACnetGroupChannelValue (clause 15.11.1.1.3):
// channel [0], overridingPriority [1] when not 0, value.
func (e *clientEnv) writeGroup(sc map[string]any) (map[string]any, error) {
	group, _ := uintArg(sc, "group")
	prio, _ := uintArg(sc, "priority")
	w := service.WriteGroup{GroupNumber: group, WritePriority: uint8(prio)}
	if inh, ok := sc["inhibit"].(bool); ok {
		w.InhibitDelay = &inh
	}
	changes, _ := sc["changes"].([]any)
	for _, c := range changes {
		m, _ := c.(map[string]any)
		ch, _ := uintArg(m, "channel")
		v, err := appValue(m["value"])
		if err != nil {
			return nil, err
		}
		els := []bacnet.Element{{Context: true, TagNumber: 0, Value: bacnet.UnsignedValue(uint64(ch))}}
		if op, ok := uintArg(m, "overriding_priority"); ok && op != 0 {
			els = append(els, bacnet.Element{Context: true, TagNumber: 1, Value: bacnet.UnsignedValue(uint64(op))})
		}
		els = append(els, bacnet.Element{Value: v})
		w.ChangeList = append(w.ChangeList, els...)
	}
	return e.unconfirmed("write-group", func(ctx context.Context, dest bip.Endpoint) error {
		return e.c.WriteGroup(ctx, dest, false, w)
	})
}

// --- BVLC tables -------------------------------------------------------------

func (e *clientEnv) bvlcAnswer(err error) (map[string]any, error) {
	var rerr *client.BVLCResultError
	var oerr *client.BVLCOperationError
	switch {
	case errors.As(err, &rerr):
		return map[string]any{"bvlc_result": bvlcResultName(rerr.Code)}, nil
	case errors.As(err, &oerr):
		return map[string]any{"bvlc_result": bvlcResultName(oerr.Code)}, nil
	}
	return nil, infra("%v", err)
}

func (e *clientEnv) needBBMD() error {
	if !e.bbmdEP.IsValid() {
		return infra("--bbmd is required for this service")
	}
	return nil
}

func (e *clientEnv) readBDT(sc map[string]any) (map[string]any, error) {
	if err := e.needBBMD(); err != nil {
		return nil, err
	}
	ctx, cancel := e.ctx()
	defer cancel()
	entries, err := e.c.ReadBroadcastDistributionTable(ctx, e.bbmdEP)
	if err != nil {
		return e.bvlcAnswer(err)
	}
	out := []any{}
	for _, en := range entries {
		addr := en.Endpoint.String()
		if en.Endpoint.Equal(e.bbmdEP) {
			addr = "bbmd"
		}
		m := en.Mask
		out = append(out, map[string]any{"address": addr, "mask": fmt.Sprintf("%d.%d.%d.%d", m[0], m[1], m[2], m[3])})
	}
	return map[string]any{"bdt": out}, nil
}

func (e *clientEnv) readFDT(sc map[string]any) (map[string]any, error) {
	if err := e.needBBMD(); err != nil {
		return nil, err
	}
	ctx, cancel := e.ctx()
	defer cancel()
	entries, err := e.c.ReadForeignDeviceTable(ctx, e.bbmdEP)
	if err != nil {
		return e.bvlcAnswer(err)
	}
	ip, err := localIP(e.bbmdEP)
	if err != nil {
		return nil, infra("own address towards the BBMD: %v", err)
	}
	port := e.c.LocalEndpoint().Addr.Port()
	for _, en := range entries {
		if en.Address.Addr.Addr() == ip && en.Address.Addr.Port() == port {
			return map[string]any{"fdt": map[string]any{"contains_self": true, "ttl": en.TTL}}, nil
		}
	}
	return map[string]any{"fdt": map[string]any{"contains_self": false, "ttl": 0}}, nil
}

func (e *clientEnv) writeBDT(sc map[string]any) (map[string]any, error) {
	if err := e.needBBMD(); err != nil {
		return nil, err
	}
	var entries []bvlc.BDTEntry
	list, _ := sc["bdt"].([]any)
	for _, x := range list {
		ep := e.bbmdEP
		if s, _ := x.(string); s != "bbmd" {
			return nil, unsupported("BDT entry %v: this driver writes the BBMD's own entry", x)
		}
		entries = append(entries, bvlc.BDTEntry{Endpoint: ep, Mask: bvlc.IPv4Mask{255, 255, 255, 255}})
	}
	ctx, cancel := e.ctx()
	defer cancel()
	if err := e.c.WriteBroadcastDistributionTable(ctx, e.bbmdEP, entries); err != nil {
		return e.bvlcAnswer(err)
	}
	return map[string]any{"bvlc_result": bvlcResultName(bvlc.ResultSuccessfulCompletion)}, nil
}
