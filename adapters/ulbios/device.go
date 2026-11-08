// SPDX-License-Identifier: MIT

package main

import (
	"errors"
	"fmt"
	"net"
	"sync"

	"github.com/ulbios/bacnet"
	"github.com/ulbios/bacnet/common"
	"github.com/ulbios/bacnet/objects"
	"github.com/ulbios/bacnet/plumbing"
	"github.com/ulbios/bacnet/services"
)

// BACnet constants the adapter checks (clause 20 and 18).
const (
	serviceReadProperty  uint8 = 12
	serviceWriteProperty uint8 = 15

	errClassObject   uint8 = 1
	errClassProperty uint8 = 2

	errCodeInvalidDataType   uint8 = 9
	errCodeUnknownObject     uint8 = 31
	errCodeUnknownProperty   uint8 = 32
	errCodeValueOutOfRange   uint8 = 37
	errCodeWriteAccessDenied uint8 = 40
)

// device answers requests with ulbios' parser and encoders. The object model
// and dispatch are adapter code (adapter-shim in adapters/inventory.yaml).
type device struct {
	m  *model
	mu sync.Mutex
	// op reports a request without an observable reply; nil in tests.
	op func(name string, fields map[string]any)
	// keepSA passes the first APDU octet to bacnet.Parse unchanged
	// (ULBIOS_KEEP_SA=1); see handle.
	keepSA bool
}

// out is one datagram the device sends: to the requester, or to the local
// broadcast address when broadcast is set.
type out struct {
	frame     []byte
	broadcast bool
}

func (d *device) report(name string, fields map[string]any) {
	if d.op != nil {
		d.op(name, fields)
	}
}

// unanswered records a request the device does not answer because ulbios
// cannot decode it or cannot encode the answer. ulbios has no Reject or
// Abort encoder (plumbing.APDU.MarshalTo has no case for PDU types 6 and
// 7), so such a request gets no reply and the client's APDU timer expires.
func (d *device) unanswered(service int, reason string) []out {
	d.report("unanswered", map[string]any{"result": "no-reply", "service": service, "reason": reason})
	return nil
}

// handle turns one received datagram into the datagrams to send.
func (d *device) handle(b []byte) (res []out) {
	// Framing checks ulbios does not make (its BVLC and NPDU decoders read
	// fixed offsets): only Original-Unicast-NPDU and Original-Broadcast-NPDU
	// (the two BVLC functions ulbios defines), no network-layer message, no
	// SNET/SADR, and DNET only with an empty DADR (the global broadcast).
	if len(b) < 8 || b[0] != plumbing.BVLCType {
		return nil
	}
	if b[1] != plumbing.BVLCFuncUnicast && b[1] != plumbing.BVLCFuncBroadcast {
		return d.unanswered(-1, fmt.Sprintf("BVLC function 0x%02x: ulbios defines Original-Unicast-NPDU and Original-Broadcast-NPDU only", b[1]))
	}
	ctrl := b[5]
	if b[4] != 1 || ctrl&0x80 != 0 || ctrl&0x08 != 0 || (ctrl&0x20 != 0 && (len(b) < 9 || b[8] != 0)) {
		return nil
	}
	apduOff := 6
	if ctrl&0x20 != 0 {
		apduOff = 10 // DNET, DLEN 0, hop count
	}
	if len(b) <= apduOff {
		return nil
	}
	pduType := b[apduOff] >> 4
	if pduType == plumbing.ConfirmedReq && len(b) > apduOff+3 && b[apduOff]&0x08 != 0 {
		// ulbios keeps only the low three bits of the first octet
		// (plumbing.APDU.UnmarshalBinary) and so cannot see a segmented
		// request; the answer would be Abort segmentation-not-supported.
		return d.unanswered(int(b[apduOff+3]), "segmented request: ulbios has no segmentation")
	}

	if pduType == plumbing.ConfirmedReq && b[apduOff]&0x02 != 0 && !d.keepSA {
		// bacnet.Parse identifies a confirmed request by its whole first
		// octet (parsing.go: combine(b[offset], b[offset+3])), so a request
		// with segmented-response-accepted set is not recognised at all.
		// The adapter clears the bit in a copy; the answer is never
		// segmented either way.
		b = append([]byte(nil), b...)
		b[apduOff] &^= 0x02
	}
	msg, err := parse(b)
	if err != nil {
		if pduType == plumbing.ConfirmedReq {
			svc := -1
			if len(b) > apduOff+3 {
				svc = int(b[apduOff+3])
			}
			return d.unanswered(svc, "bacnet.Parse: "+err.Error())
		}
		return nil
	}
	maxResp := 1476
	if pduType == plumbing.ConfirmedReq {
		maxResp = maxAPDU(b[apduOff+1] & 0x0f)
	}

	d.mu.Lock()
	defer d.mu.Unlock()
	switch m := msg.(type) {
	case *services.UnconfirmedWhoIs:
		return d.whoIs(m)
	case *services.ConfirmedReadProperty:
		return d.readProperty(m, maxResp)
	case *services.ConfirmedWriteProperty:
		return d.writeProperty(m)
	}
	return nil
}

// parse is bacnet.Parse, which panics on some truncated or extended-length
// input (it slices without bounds checks); a panic is an error here.
func parse(b []byte) (msg plumbing.BACnet, err error) {
	defer func() {
		if r := recover(); r != nil {
			msg, err = nil, fmt.Errorf("panic: %v", r)
		}
	}()
	return bacnet.Parse(b)
}

// maxAPDU is the max-APDU-length-accepted code of a confirmed request
// (clause 20.1.2.5). ulbios skips that octet when it decodes a request.
func maxAPDU(code byte) int {
	switch code {
	case 0:
		return 50
	case 1:
		return 128
	case 2:
		return 206
	case 3:
		return 480
	case 4:
		return 1024
	}
	return 1476
}

// whoIs answers a Who-Is (clause 16.10) for the device instance. ulbios'
// UnconfirmedWhoIs has no range decoder: the two context tags are read from
// the tokens bacnet.Parse produced (adapter-shim). A unicast Who-Is gets a
// unicast I-Am (Addendum 135-2004q), a broadcast one ulbios' own broadcast
// I-Am (bacnet.NewIAm: Original-Broadcast-NPDU, DNET 0xFFFF).
func (d *device) whoIs(m *services.UnconfirmedWhoIs) []out {
	inst := d.m.fx.DeviceInstance
	switch toks := m.APDU.Objects; len(toks) {
	case 0:
	case 2:
		low, ok1 := contextUnsigned(toks[0], 0)
		high, ok2 := contextUnsigned(toks[1], 1)
		if !ok1 || !ok2 {
			return nil
		}
		if inst < low || inst > high {
			return nil
		}
	default:
		return nil
	}
	broadcast := m.BVLC.Function == plumbing.BVLCFuncBroadcast
	frame, err := iAm(inst, broadcast)
	if err != nil {
		return nil
	}
	return []out{{frame: frame, broadcast: broadcast}}
}

// iAm builds the I-Am like bacnet.NewIAm, with the device instance:
// services.IAmObjects ignores its instance argument and always encodes
// device 321, so its first token is replaced.
func iAm(inst uint32, broadcast bool) ([]byte, error) {
	var bvlc *plumbing.BVLC
	var npdu *plumbing.NPDU
	if broadcast {
		bvlc = plumbing.NewBVLC(plumbing.BVLCFuncBroadcast)
		npdu = plumbing.NewNPDU(false, true, false, false)
		npdu.DNET, npdu.DLEN, npdu.Hop = 0xFFFF, 0, 0xFF
	} else {
		bvlc = plumbing.NewBVLC(plumbing.BVLCFuncUnicast)
		npdu = plumbing.NewNPDU(false, false, false, false)
	}
	u := services.NewUnconfirmedIAm(bvlc, npdu)
	u.APDU.Objects = services.IAmObjects(inst, maxAPDULengthAccepted, segmentationNone, vendorID)
	u.APDU.Objects[0] = objects.EncObjectIdentifier(false, objects.TagBACnetObjectIdentifier, 8, inst)
	u.SetLength()
	return u.MarshalBinary()
}

// contextUnsigned reads a context-tagged Unsigned of one to four octets
// from a ulbios token.
func contextUnsigned(p objects.APDUPayload, tag uint8) (uint32, bool) {
	o, ok := p.(*objects.Object)
	if !ok || !o.TagClass || o.TagNumber != tag || o.Length < 1 || o.Length > 4 || len(o.Data) != int(o.Length) {
		return 0, false
	}
	var v uint32
	for _, c := range o.Data {
		v = v<<8 | uint32(c)
	}
	return v, true
}

// objectID decodes an object identifier with ulbios' DecObjectIdentifier,
// which returns the object type shifted left by two: it computes
// (v & 0xFFC00000) >> 20 instead of >> 22 (objects/oid.go). The adapter
// shifts it back.
func objectID(p objects.APDUPayload) (uint16, uint32, error) {
	id, err := objects.DecObjectIdentifier(p)
	if err != nil {
		return 0, 0, err
	}
	return id.ObjectType >> 2, id.InstanceNumber, nil
}

func reply() (*plumbing.BVLC, *plumbing.NPDU) {
	return plumbing.NewBVLC(plumbing.BVLCFuncUnicast), plumbing.NewNPDU(false, false, false, false)
}

// errorPDU is an Error PDU with ulbios' encoder. bacnet.NewError fixes the
// invoke ID to 1, so the adapter fills services.Error itself.
func errorPDU(invokeID, service, class, code uint8) []out {
	bvlc, npdu := reply()
	e := services.NewError(bvlc, npdu)
	e.APDU.Service, e.APDU.InvokeID = service, invokeID
	e.APDU.Objects = services.ErrorObjects(class, code)
	e.SetLength()
	b, err := e.MarshalBinary()
	if err != nil {
		return nil
	}
	return []out{{frame: b}}
}

func (d *device) readProperty(m *services.ConfirmedReadProperty, maxResp int) []out {
	dec, err := m.Decode()
	if err != nil {
		// An array index (a third token) or a property identifier above 255.
		return d.unanswered(int(serviceReadProperty), "ConfirmedReadProperty.Decode: "+err.Error())
	}
	typ := dec.ObjectType >> 2 // see objectID
	o := d.m.find(typ, dec.InstanceId)
	if o == nil {
		return errorPDU(m.APDU.InvokeID, serviceReadProperty, errClassObject, errCodeUnknownObject)
	}
	vals, ok := d.m.read(o, dec.PropertyId)
	if !ok {
		return errorPDU(m.APDU.InvokeID, serviceReadProperty, errClassProperty, errCodeUnknownProperty)
	}
	bvlc, npdu := reply()
	c := services.NewComplexACK(bvlc, npdu)
	c.APDU.Service, c.APDU.InvokeID = serviceReadProperty, m.APDU.InvokeID
	objs := []objects.APDUPayload{
		objects.EncObjectIdentifier(true, 0, typ, dec.InstanceId),
		objects.EncPropertyIdentifier(true, 1, dec.PropertyId),
		objects.EncOpeningTag(3),
	}
	objs = append(objs, vals...)
	c.APDU.Objects = append(objs, objects.EncClosingTag(3))
	c.SetLength()
	b, err := c.MarshalBinary()
	if err != nil {
		return nil
	}
	if apdu := len(b) - 6; apdu > maxResp || apdu > maxAPDULengthAccepted {
		return d.unanswered(int(serviceReadProperty), fmt.Sprintf("answer of %d octets exceeds the max APDU and ulbios cannot segment", apdu))
	}
	return []out{{frame: b}}
}

// wpRequest is a decoded WriteProperty.
type wpRequest struct {
	typ      uint16
	inst     uint32
	prop     uint8
	val      value
	priority uint8
	decoder  string
}

// decodeWP decodes a WriteProperty. ConfirmedWriteProperty.Decode accepts
// exactly five tokens, the shape of ulbios' own request (REAL, NULL and a
// priority: services.ConfirmedWritePropertyObjects), and refuses a request
// with one value, with or without a priority. For three or four tokens the
// adapter assigns them itself and decodes each with ulbios' decoders.
func decodeWP(m *services.ConfirmedWriteProperty) (wpRequest, string) {
	dec, err := m.Decode()
	if err == nil {
		return wpRequest{typ: dec.ObjectType >> 2, inst: dec.InstanceId, prop: dec.PropertyId,
			val: value{kind: 'r', real: dec.Value}, priority: dec.Priority, decoder: "ulbios"}, ""
	}
	if !errors.Is(err, common.ErrWrongObjectCount) {
		return wpRequest{}, "ConfirmedWriteProperty.Decode: " + err.Error()
	}
	toks := m.APDU.Objects
	if len(toks) != 3 && len(toks) != 4 {
		return wpRequest{}, fmt.Sprintf("%d parameter tokens: not one primitive value (ulbios drops the opening and closing tags)", len(toks))
	}
	r := wpRequest{priority: 16, decoder: "adapter-shim"}
	var e error
	if r.typ, r.inst, e = objectID(toks[0]); e != nil {
		return wpRequest{}, "DecObjectIdentifier: " + e.Error()
	}
	if r.prop, e = objects.DecPropertyIdentifier(toks[1]); e != nil {
		return wpRequest{}, "DecPropertyIdentifier: " + e.Error()
	}
	vt, ok := toks[2].(*objects.Object)
	if !ok || vt.TagClass {
		return wpRequest{}, "the value is not an application-tagged primitive (array index?)"
	}
	switch vt.TagNumber {
	case objects.TagReal:
		f, e := objects.DecReal(vt)
		if e != nil {
			return wpRequest{}, "DecReal: " + e.Error()
		}
		r.val = value{kind: 'r', real: f}
	case objects.TagEnumerated:
		n, e := objects.DecEnumerated(vt)
		if e != nil || n > 255 {
			return wpRequest{}, fmt.Sprintf("DecEnumerated: %v (%d)", e, n)
		}
		r.val = value{kind: 'e', enum: uint8(n)}
	case objects.TagUnsignedInteger:
		n, e := objects.DecUnisgnedInteger(vt)
		if e != nil || n > 65535 {
			return wpRequest{}, fmt.Sprintf("DecUnisgnedInteger: %v (%d)", e, n)
		}
		r.val = value{kind: 'u', u: uint16(n)}
	case objects.TagNull:
		// objects.DecNull compares the tag number with TagReal and so
		// refuses every NULL: ulbios cannot decode a relinquish.
		if _, e := objects.DecNull(vt); e != nil {
			return wpRequest{}, "DecNull: " + e.Error() + " (it refuses every NULL)"
		}
		return wpRequest{}, "DecNull"
	default:
		return wpRequest{}, fmt.Sprintf("no ulbios decoder for application tag %d", vt.TagNumber)
	}
	if len(toks) == 4 {
		pt, ok := toks[3].(*objects.Object)
		if !ok || !pt.TagClass || pt.TagNumber != 4 {
			return wpRequest{}, "the fourth token is not the priority [4]"
		}
		if r.priority, e = objects.DecPriority(pt); e != nil {
			return wpRequest{}, "DecPriority: " + e.Error()
		}
	}
	return r, ""
}

func (d *device) writeProperty(m *services.ConfirmedWriteProperty) []out {
	r, why := decodeWP(m)
	if why != "" {
		return d.unanswered(int(serviceWriteProperty), why)
	}
	if r.priority < 1 || r.priority > 16 {
		return d.unanswered(int(serviceWriteProperty), fmt.Sprintf("priority %d outside 1..16", r.priority))
	}
	id := m.APDU.InvokeID
	o := d.m.find(r.typ, r.inst)
	if o == nil {
		return errorPDU(id, serviceWriteProperty, errClassObject, errCodeUnknownObject)
	}
	if _, ok := d.m.read(o, r.prop); !ok {
		return errorPDU(id, serviceWriteProperty, errClassProperty, errCodeUnknownProperty)
	}
	if r.prop != propPresentValue || !o.commandable {
		return errorPDU(id, serviceWriteProperty, errClassProperty, errCodeWriteAccessDenied)
	}
	if r.val.kind != o.relinquish.kind {
		return errorPDU(id, serviceWriteProperty, errClassProperty, errCodeInvalidDataType)
	}
	if r.val.kind == 'e' && r.val.enum > 1 {
		return errorPDU(id, serviceWriteProperty, errClassProperty, errCodeValueOutOfRange)
	}
	v := r.val
	o.slots[r.priority-1] = &v
	d.report("write-property", map[string]any{"result": "applied", "object": fmt.Sprintf("%s,%d", objectTypeName(r.typ), r.inst),
		"priority": r.priority, "decoder": r.decoder})
	bvlc, npdu := reply()
	s := services.NewSimpleACK(bvlc, npdu)
	s.APDU.Service, s.APDU.InvokeID = serviceWriteProperty, id
	s.SetLength()
	b, err := s.MarshalBinary()
	if err != nil {
		return nil
	}
	return []out{{frame: b}}
}

// serve answers datagrams on conn until it is closed.
func (d *device) serve(conn *net.UDPConn, port int) {
	buf := make([]byte, 2048)
	for {
		n, from, err := conn.ReadFromUDP(buf)
		if err != nil {
			return
		}
		for _, o := range d.handle(append([]byte(nil), buf[:n]...)) {
			dst := from
			if o.broadcast {
				dst = &net.UDPAddr{IP: localBroadcast(), Port: port}
			}
			_, _ = conn.WriteToUDP(o.frame, dst)
		}
	}
}

// localBroadcast is the directed broadcast address of the first IPv4
// interface, or 255.255.255.255.
func localBroadcast() net.IP {
	addrs, err := net.InterfaceAddrs()
	if err == nil {
		for _, a := range addrs {
			ipn, ok := a.(*net.IPNet)
			if !ok || ipn.IP.IsLoopback() || ipn.IP.To4() == nil {
				continue
			}
			ip, mask := ipn.IP.To4(), ipn.Mask
			if len(mask) == 16 {
				mask = mask[12:]
			}
			bc := make(net.IP, 4)
			for i := range bc {
				bc[i] = ip[i] | ^mask[i]
			}
			return bc
		}
	}
	return net.IPv4bcast
}
