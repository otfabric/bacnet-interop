// SPDX-License-Identifier: MIT

package main

import (
	"bytes"
	"encoding/hex"
	"errors"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ulbios/bacnet"
	"github.com/ulbios/bacnet/objects"
	"github.com/ulbios/bacnet/services"
)

func frame(t *testing.T, s string) []byte {
	t.Helper()
	b, err := hex.DecodeString(strings.ReplaceAll(s, " ", ""))
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func testDevice(t *testing.T) (*device, *[]map[string]any) {
	t.Helper()
	f, err := loadFixture("../../fixtures/device/device-baseline-v2.json")
	if err != nil {
		t.Skipf("fixture not next to the adapter (image build): %v", err)
	}
	var ops []map[string]any
	d := &device{m: newModel(f), op: func(name string, fields map[string]any) {
		fields["operation"] = name
		ops = append(ops, fields)
	}}
	return d, &ops
}

// one returns the single datagram the device sends.
func one(t *testing.T, d *device, req string) out {
	t.Helper()
	res := d.handle(frame(t, req))
	if len(res) != 1 {
		t.Fatalf("%s: %d datagrams, want 1", req, len(res))
	}
	return res[0]
}

// Every device fixture the image ships loads.
func TestFixturesLoad(t *testing.T) {
	paths, err := filepath.Glob("../../fixtures/device/*.json")
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) == 0 {
		t.Skip("no fixtures next to the adapter (image build)")
	}
	for _, p := range paths {
		f, err := loadFixture(p)
		if err != nil {
			t.Errorf("%s: %v", p, err)
			continue
		}
		newModel(f)
	}
}

// The upstream behaviours the adapter works around. A candidate upstream
// that changes one of them fails here, so the shim is revisited.
func TestUpstreamBehaviour(t *testing.T) {
	id, err := objects.DecObjectIdentifier(objects.EncObjectIdentifier(true, 0, 2, 1))
	if err != nil || id.ObjectType != 8 || id.InstanceNumber != 1 {
		t.Errorf("DecObjectIdentifier(analog-value,1) = %+v, %v; the adapter shifts the type right by two", id, err)
	}
	iam, _ := bacnet.NewIAm(1234, 999)
	if !bytes.Contains(iam, []byte{0xc4, 0x02, 0x00, 0x01, 0x41}) {
		t.Errorf("bacnet.NewIAm(1234) = %x; expected the hard-coded device 321", iam)
	}
	if _, err := objects.DecNull(objects.EncNull()); err == nil {
		t.Error("DecNull now decodes a NULL; the relinquish path can use it")
	}
	rp, _ := bacnet.NewReadProperty(2, 1, 85)
	if want := "810a001101040005010c0c008000011955"; hex.EncodeToString(rp) != want {
		t.Errorf("NewReadProperty = %x, want %s", rp, want)
	}
	wp, _ := bacnet.NewWriteProperty(2, 1, 85, 42)
	if want := "810a001b01040005010f0c0080000119553e4442280000003f4910"; hex.EncodeToString(wp) != want {
		t.Errorf("NewWriteProperty = %x, want %s (REAL, NULL, priority 16)", wp, want)
	}
}

// A request with segmented-response-accepted set is answered; with
// ULBIOS_KEEP_SA=1 bacnet.Parse sees the octet unchanged and refuses it.
func TestSegmentedResponseAccepted(t *testing.T) {
	d, ops := testDevice(t)
	req := "810a0011 0104 02050a0c 0c00800001 1955"
	if c := readAnswer(t, d, req); c.APDU.InvokeID != 10 {
		t.Fatalf("invoke ID %d", c.APDU.InvokeID)
	}
	d.keepSA = true
	if res := d.handle(frame(t, req)); len(res) != 0 {
		t.Fatalf("answered with ULBIOS_KEEP_SA: %x", res[0].frame)
	}
	if r := (*ops)[len(*ops)-1]["reason"]; r != "bacnet.Parse: not implemented type" {
		t.Errorf("reason %v", r)
	}
}

func TestWhoIs(t *testing.T) {
	d, _ := testDevice(t)
	o := one(t, d, "810a0008 0100 1008")
	msg, err := bacnet.Parse(o.frame)
	if err != nil || o.broadcast {
		t.Fatalf("unicast I-Am: %v broadcast=%v", err, o.broadcast)
	}
	dec, err := msg.(*services.UnconfirmedIAm).Decode()
	if err != nil || dec.DeviceId != 1234 || dec.MaxAPDULength != 1024 || dec.SegmentationSupported != 3 || dec.VendorId != 999 {
		t.Fatalf("I-Am %+v %v", dec, err)
	}
	if b := one(t, d, "810b0008 0100 1008"); !b.broadcast || b.frame[1] != 0x0b || b.frame[5] != 0x20 {
		t.Fatalf("broadcast Who-Is: %x broadcast=%v", b.frame, b.broadcast)
	}
	one(t, d, "810a000e 0100 1008 0a04d2 1a04d2")
	one(t, d, "810a0010 0100 1008 0b000001 1b3fffff")
	for _, req := range []string{
		"810a000e 0100 1008 0a1388 1a1388", // outside the range
		"810a000b 0100 1008 0a04d2",        // one limit only
		"810a000e 0100 1008 1a04d2 0a04d2", // tags swapped
	} {
		if res := d.handle(frame(t, req)); len(res) != 0 {
			t.Errorf("%s: answered %x", req, res[0].frame)
		}
	}
}

func readAnswer(t *testing.T, d *device, req string) *services.ComplexACK {
	t.Helper()
	msg, err := bacnet.Parse(one(t, d, req).frame)
	if err != nil {
		t.Fatalf("%s: %v", req, err)
	}
	c, ok := msg.(*services.ComplexACK)
	if !ok {
		t.Fatalf("%s: %T", req, msg)
	}
	return c
}

func errorAnswer(t *testing.T, d *device, req string) services.ErrorDec {
	t.Helper()
	msg, err := bacnet.Parse(one(t, d, req).frame)
	if err != nil {
		t.Fatalf("%s: %v", req, err)
	}
	e, ok := msg.(*services.Error)
	if !ok {
		t.Fatalf("%s: %T", req, msg)
	}
	dec, err := e.Decode()
	if err != nil {
		t.Fatal(err)
	}
	return dec
}

func TestReadProperty(t *testing.T) {
	d, ops := testDevice(t)
	c := readAnswer(t, d, "810a0011 0104 0005070c 0c00800001 1955")
	if c.APDU.InvokeID != 7 {
		t.Errorf("invoke ID %d, want 7", c.APDU.InvokeID)
	}
	dec, err := c.Decode()
	if err != nil || dec.PresentValue != 21.5 || dec.PropertyId != 85 {
		t.Fatalf("AV-1 present-value %+v %v", dec, err)
	}
	if typ, inst, err := objectID(c.APDU.Objects[0]); err != nil || typ != 2 || inst != 1 {
		t.Errorf("object %d,%d %v", typ, inst, err)
	}
	list := readAnswer(t, d, "810a0011 0104 0005010c 0c020004d2 194c")
	if len(list.APDU.Objects) != 2+4 {
		t.Errorf("object-list: %d tokens", len(list.APDU.Objects))
	}
	pa := readAnswer(t, d, "810a0011 0104 0005010c 0c00800001 1957")
	if len(pa.APDU.Objects) != 2+16 {
		t.Errorf("priority-array: %d tokens", len(pa.APDU.Objects))
	}
	if e := errorAnswer(t, d, "810a0011 0104 0005010c 0c008003e7 1955"); e.ErrorClass != 1 || e.ErrorCode != 31 {
		t.Errorf("unknown object: %+v", e)
	}
	if e := errorAnswer(t, d, "810a0011 0104 0005010c 0c00800001 194d"); e.ErrorClass != 2 || e.ErrorCode != 32 {
		t.Errorf("object-name (not encodable): %+v", e)
	}
	for _, req := range []string{
		"810a0013 0104 0005010c 0c00800001 1955 2901", // array index
		"810a0013 0104 0005010c 0c00800001 1a270f",    // property 9999
		"810a000a 0104 0005010c",                      // no parameters
		"810a0013 0104 08050100010c 0c00800001 1955",  // segmented
		"810a000e 0104 0005010e 0c00800001",           // ReadPropertyMultiple
	} {
		if res := d.handle(frame(t, req)); len(res) != 0 {
			t.Errorf("%s: answered %x", req, res[0].frame)
		}
	}
	if len(*ops) != 5 {
		t.Errorf("unanswered operations: %v", *ops)
	}
}

func TestWriteProperty(t *testing.T) {
	d, ops := testDevice(t)
	ack := func(req string) {
		t.Helper()
		msg, err := bacnet.Parse(one(t, d, req).frame)
		if _, ok := msg.(*services.SimpleACK); err != nil || !ok {
			t.Fatalf("%s: %T %v", req, msg, err)
		}
	}
	pv := func() float32 {
		t.Helper()
		dec, err := readAnswer(t, d, "810a0011 0104 0005010c 0c00800001 1955").Decode()
		if err != nil {
			t.Fatal(err)
		}
		return dec.PresentValue
	}
	ack("810a001a 0104 0005010f 0c00800001 1955 3e 4442280000 3f 4908") // 42 at 8
	if v := pv(); v != 42 {
		t.Fatalf("present-value %v after write at 8", v)
	}
	ack("810a0018 0104 0005010f 0c00800001 1955 3e 4441200000 3f") // 10 at 16
	if v := pv(); v != 42 {
		t.Fatalf("present-value %v: priority 8 wins over 16", v)
	}
	ack("810a001b 0104 0005010f 0c00800001 1955 3e 443f800000 00 3f 4907") // ulbios' own form, 1 at 7
	if v := pv(); v != 1 {
		t.Fatalf("present-value %v after ulbios' own request at 7", v)
	}
	if got := (*ops)[len(*ops)-1]["decoder"]; got != "ulbios" {
		t.Errorf("decoder of ulbios' own form: %v", got)
	}
	ack("810a0015 0104 0005010f 0c01400001 1955 3e 9101 3f") // BV-1 active
	errs := map[string][2]uint8{
		"810a0018 0104 0005010f 0c008003e7 1955 3e 443f800000 3f": {1, 31},
		"810a0015 0104 0005010f 0c00800001 1955 3e 9101 3f":       {2, 9},
		"810a0015 0104 0005010f 0c01400001 1955 3e 9102 3f":       {2, 37},
		"810a0018 0104 0005010f 0c00800001 194b 3e 443f800000 3f": {2, 40},
		"810a0018 0104 0005010f 0c00800001 194d 3e 443f800000 3f": {2, 32},
	}
	for req, want := range errs {
		if e := errorAnswer(t, d, req); e.ErrorClass != want[0] || e.ErrorCode != want[1] {
			t.Errorf("%s: %+v, want %v", req, e, want)
		}
	}
	before := len(*ops)
	for _, req := range []string{
		"810a0014 0104 0005010f 0c00800001 1955 3e 00 3f 4908",           // NULL (relinquish)
		"810a0018 0104 0005010f 0c00800001 1955 3e 4441200000 3f 4911",   // priority 17
		"810a001d 0104 0005010f 0c00800001 194d 3e 7506 0068656c6c6f 3f", // character string
		"810a001a 0104 0005010f 0c00800001 1955 2901 3e 4441200000 3f",   // array index
	} {
		if res := d.handle(frame(t, req)); len(res) != 0 {
			t.Errorf("%s: answered %x", req, res[0].frame)
		}
	}
	if len(*ops)-before != 4 {
		t.Errorf("unanswered: %v", (*ops)[before:])
	}
}

func TestFramingRefused(t *testing.T) {
	d, _ := testDevice(t)
	for _, req := range []string{
		"810400120a0000020bac 0100 1008",         // Forwarded-NPDU
		"810a000b 0180 0000 01",                  // network-layer message
		"810a0010 0108 0002 06c0a8000100 1008",   // SNET
		"810a0010 0120 0002 06c0a8000100ff 1008", // DNET with a DADR
		"820a0008 0100 1008",                     // not BACnet/IP
	} {
		if res := d.handle(frame(t, req)); len(res) != 0 {
			t.Errorf("%s: answered %x", req, res[0].frame)
		}
	}
	if res := d.handle(frame(t, "810b000c 0120ffff00ff 1008")); len(res) != 1 {
		t.Error("global-broadcast Who-Is not answered")
	}
}

func TestClientDecode(t *testing.T) {
	ackFrame := func(s string) (*services.ComplexACK, []byte) {
		b := frame(t, s)
		msg, err := bacnet.Parse(b)
		if err != nil {
			t.Fatal(err)
		}
		return msg.(*services.ComplexACK), b
	}
	c, raw := ackFrame("810a0017 0100 30010c 0c00800001 1955 3e 4441ac0000 3f")
	got, err := decodeReadACK(c, raw, map[string]any{"value": map[string]any{"type": "real"}}, 2, 85)
	if err != nil || !sameValue(map[string]any{"type": "real", "value": 21.5}, got["value"]) {
		t.Errorf("real: %v %v", got, err)
	}
	c, raw = ackFrame("810a0017 0100 30010c 0c00800001 194b 3e c400800001 3f")
	_, err = decodeReadACK(c, raw, map[string]any{"value": map[string]any{"type": "object-identifier", "value": "analog-value,1"}}, 2, 75)
	var oe *outcomeError
	if !errors.As(err, &oe) || oe.outcome != "known-difference" || !strings.Contains(oe.detail, "analog-value,1") {
		t.Errorf("object-identifier: %v", err)
	}
	c, raw = ackFrame("810a0019 0100 30010c 0c00800001 194d 3e 7505004156 2d31 3f")
	_, err = decodeReadACK(c, raw, map[string]any{"value": map[string]any{"type": "character-string"}}, 2, 77)
	if !errors.As(err, &oe) || oe.outcome != "known-difference" {
		t.Errorf("character-string: %v", err)
	}
	_, err = answer(nil, frame(t, "810a0014 0100 30010c 0c01400001 1955 3e 9100 3f"), errShort(t), nil)
	if !errors.As(err, &oe) || !strings.HasPrefix(oe.detail, kdShortACK) {
		t.Errorf("short ACK: %v", err)
	}
	obs, err := answer(mustParse(t, "810a000d 0100 50010c 9101 911f"), nil, nil, nil)
	if err != nil || !compare(map[string]any{"error": map[string]any{"class": "object", "code": "unknown-object"}}, obs) {
		t.Errorf("error: %v %v", obs, err)
	}
	if !compare(map[string]any{"i-am": []any{1234.0}}, map[string]any{"i-am": []int{1234}}) ||
		compare(map[string]any{"i-am": []any{}}, map[string]any{"i-am": []int{1234}}) {
		t.Error("i-am compare")
	}
}

func errShort(t *testing.T) error {
	t.Helper()
	_, err := bacnet.Parse(frame(t, "810a0014 0100 30010c 0c01400001 1955 3e 9100 3f"))
	if err == nil {
		t.Fatal("a short Complex-ACK parses")
	}
	return err
}

func mustParse(t *testing.T, s string) interface {
	MarshalBinary() ([]byte, error)
	MarshalTo([]byte) error
	UnmarshalBinary([]byte) error
	MarshalLen() int
} {
	t.Helper()
	m, err := bacnet.Parse(frame(t, s))
	if err != nil {
		t.Fatal(err)
	}
	return m
}

func TestApduOffset(t *testing.T) {
	for s, want := range map[string]int{
		"810a0008 0100 1008":                     6,
		"810b000c 0120ffff00ff 1008":             10,
		"810a0012 0108 0002 06c0a80001bac0 1008": 15,
		"810400120a0000020bac 0100 1008":         12,
	} {
		if got, ok := apduOffset(frame(t, s)); !ok || got != want {
			t.Errorf("%s: %d %v, want %d", s, got, ok, want)
		}
	}
	if _, ok := apduOffset(frame(t, "810a0008 0180 0000")); ok {
		t.Error("network message has an APDU")
	}
}

func TestPropertyRef(t *testing.T) {
	if p, err := propertyRef("present-value"); err != nil || p != 85 {
		t.Errorf("present-value: %d %v", p, err)
	}
	var oe *outcomeError
	if _, err := propertyRef(9999.0); !errors.As(err, &oe) || oe.outcome != "unsupported" {
		t.Errorf("9999: %v", err)
	}
	if _, _, err := objectRef("analog-value,x"); !errors.As(err, &oe) {
		t.Errorf("bad object: %v", err)
	}
}

func TestRefusesRealNull(t *testing.T) {
	ack := map[string]any{"expect": map[string]any{"ack": true}}
	idt := map[string]any{"error": map[string]any{"class": "property", "code": "invalid-data-type"}}
	if !refusesRealNull(ack, idt) {
		t.Fatal("invalid-data-type to an expected ack is the REAL+NULL difference")
	}
	if refusesRealNull(map[string]any{"expect": map[string]any{"error": map[string]any{}}}, idt) {
		t.Fatal("a scenario that expects an Error is compared as usual")
	}
	if refusesRealNull(ack, map[string]any{"error": map[string]any{"class": "object", "code": "unknown-object"}}) {
		t.Fatal("another Error is a fail")
	}
	if refusesRealNull(ack, map[string]any{"ack": true}) {
		t.Fatal("a SimpleACK is no difference")
	}
}
