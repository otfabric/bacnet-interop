// SPDX-License-Identifier: MIT

package service

// The answers of the service handlers are adapter code (adapter-shim in
// adapters/inventory.yaml). These tests serve the baseline fixture over
// loopback UDP and decode every answer with Worldiety's own client, so that an
// encoding defect shows here and not first in a consumer.

import (
	"context"
	"errors"
	"math"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/otfabric/bacnet-interop/adapters/worldiety/internal/fixture"
	"github.com/worldiety/bacnet"
	"github.com/worldiety/bacnet/apdu"
	"github.com/worldiety/bacnet/common/netprim"
	"github.com/worldiety/bacnet/common/types"
	"github.com/worldiety/bacnet/encoding"
)

const objectTypeTrendLog types.ObjectType = 20

// fixtureFile is fixtures/device/device-baseline-v2.json (FIXTURES_DIR in the
// image build).
func fixtureFile(t *testing.T) string {
	t.Helper()
	dir := os.Getenv("FIXTURES_DIR")
	if dir == "" {
		dir = filepath.Join("..", "..", "..", "..", "fixtures")
	}
	path := filepath.Join(dir, "device", "device-baseline-v2.json")
	if _, err := os.Stat(path); err != nil {
		t.Fatalf("fixture: %v (set FIXTURES_DIR)", err)
	}
	return path
}

func runtime(t *testing.T) (*bacnet.ClientRuntime, netprim.Address) {
	t.Helper()
	conn, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatal(err)
	}
	cfg := bacnet.DefaultClientRuntimeConfig()
	cfg.ASE = apdu.ASEConfig{
		InvokeTimeout:           2 * time.Second,
		SegmentedRequestTimeout: 2 * time.Second,
		APDURetries:             1,
		MaxSegmentDuplicates:    3,
		MaxConcurrentInvokes:    4,
		Segmentation:            apdu.SegmentationSupportBoth,
		PreferredWindowSize:     16,
		MaxAPDUSizeAccepted:     1476,
	}
	rt, err := bacnet.NewClientRuntimeWithConn(conn, cfg)
	if err != nil {
		_ = conn.Close()
		t.Fatal(err)
	}
	return rt, netprim.NewAddressFromAddrPort(conn.LocalAddr().(*net.UDPAddr).AddrPort())
}

func run(t *testing.T, rt *bacnet.ClientRuntime) {
	t.Helper()
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		_ = rt.Run(ctx)
	}()
	t.Cleanup(func() {
		cancel()
		_ = rt.Close()
		<-done
	})
}

// serve starts the adapter on the fixture and returns a Worldiety client and
// the adapter's address.
func serve(t *testing.T) (apdu.Client, netprim.Address) {
	t.Helper()
	store, err := fixture.LoadFile(fixtureFile(t))
	if err != nil {
		t.Fatal(err)
	}
	srv, addr := runtime(t)
	if err := (&Server{Store: store, ASE: srv.ASE()}).Register(); err != nil {
		t.Fatal(err)
	}
	run(t, srv)
	cli, _ := runtime(t)
	run(t, cli)
	return cli.Client(), addr
}

func ctx(t *testing.T) context.Context {
	c, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	t.Cleanup(cancel)
	return c
}

func oid(t *testing.T, ot types.ObjectType, instance uint32) types.ObjectIdentifier {
	t.Helper()
	id, err := types.NewObjectIdentifier(ot, instance)
	if err != nil {
		t.Fatal(err)
	}
	return id
}

func value(t *testing.T, raw []byte) encoding.ApplicationValue {
	t.Helper()
	v, next, err := encoding.DecodeApplicationValue(raw, 0)
	if err != nil {
		t.Fatalf("decode %x: %v", raw, err)
	}
	if next != len(raw) {
		t.Fatalf("decode %x: %d trailing bytes", raw, len(raw)-next)
	}
	return v
}

func readProperty(t *testing.T, c apdu.Client, dst netprim.Address, id types.ObjectIdentifier, prop types.PropertyIdentifier) (encoding.ApplicationValue, error) {
	t.Helper()
	req, err := apdu.NewReadPropertyRequest(id, prop, nil)
	if err != nil {
		t.Fatal(err)
	}
	ack, err := c.ReadProperty(ctx(t), dst, req)
	if err != nil {
		return nil, err
	}
	if ack.ObjectIdentifier != id || ack.PropertyIdentifier != prop || ack.ArrayIndex != nil {
		t.Fatalf("ReadProperty-ACK for %v %v, want %v %v", ack.ObjectIdentifier, ack.PropertyIdentifier, id, prop)
	}
	return value(t, ack.PropertyValue), nil
}

func remoteError(t *testing.T, err error, class apdu.ErrorClass, code apdu.ErrorCode) {
	t.Helper()
	var re apdu.RemoteErrorAPDU
	if !errors.As(err, &re) {
		t.Fatalf("got %v, want Error %v/%v", err, class, code)
	}
	if re.ParseFailed || re.ErrorClass != class || re.ErrorCode != code {
		t.Fatalf("got Error %v/%v (malformed: %v), want %v/%v", re.ErrorClass, re.ErrorCode, re.ParseFailed, class, code)
	}
}

func TestReadProperty(t *testing.T) {
	c, dst := serve(t)
	av1 := oid(t, types.ObjectTypeAnalogValue, 1)
	got, err := readProperty(t, c, dst, av1, types.PropertyIdentifierPresentValue)
	if err != nil {
		t.Fatal(err)
	}
	if got != encoding.AppReal(21.5) {
		t.Errorf("AV-1 Present_Value = %#v, want REAL 21.5", got)
	}
	got, err = readProperty(t, c, dst, av1, types.PropertyIdentifierObjectName)
	if err != nil {
		t.Fatal(err)
	}
	if got != encoding.AppCharacterString("AV-1") {
		t.Errorf("AV-1 Object_Name = %#v, want AV-1", got)
	}
	_, err = readProperty(t, c, dst, oid(t, types.ObjectTypeAnalogValue, 999), types.PropertyIdentifierPresentValue)
	remoteError(t, err, apdu.ErrorClassObject, apdu.ErrorCodeObjectUnknownObject)
}

func TestReadPropertyMultiple(t *testing.T) {
	c, dst := serve(t)
	av1 := oid(t, types.ObjectTypeAnalogValue, 1)
	req, err := apdu.NewReadPropertyMultipleRequest([]apdu.ReadAccessSpecification{{
		ObjectIdentifier: av1,
		Properties: []apdu.PropertyReference{
			{PropertyIdentifier: types.PropertyIdentifierPresentValue},
			{PropertyIdentifier: types.PropertyIdentifierObjectName},
			{PropertyIdentifier: fixture.PropertyLogBuffer},
		},
	}})
	if err != nil {
		t.Fatal(err)
	}
	ack, err := c.ReadPropertyMultiple(ctx(t), dst, req)
	if err != nil {
		t.Fatal(err)
	}
	if len(ack.Results) != 1 || ack.Results[0].ObjectIdentifier != av1 || len(ack.Results[0].Results) != 3 {
		t.Fatalf("ReadPropertyMultiple-ACK: %+v", ack)
	}
	r := ack.Results[0].Results
	if r[0].Error != nil || value(t, r[0].PropertyValue) != encoding.AppReal(21.5) {
		t.Errorf("Present_Value: %+v", r[0])
	}
	if r[1].Error != nil || value(t, r[1].PropertyValue) != encoding.AppCharacterString("AV-1") {
		t.Errorf("Object_Name: %+v", r[1])
	}
	class, code, err := r[2].DecodeError()
	if err != nil || r[2].PropertyIdentifier != fixture.PropertyLogBuffer || class != apdu.ErrorClassProperty || code != apdu.ErrorCodePropertyUnknownProperty {
		t.Errorf("Log_Buffer of an analog value: %v/%v %v, want property/unknown-property", class, code, err)
	}
}

func TestWriteProperty(t *testing.T) {
	c, dst := serve(t)
	av1 := oid(t, types.ObjectTypeAnalogValue, 1)
	priority := uint8(8)
	req, err := apdu.NewWritePropertyRequest(av1, types.PropertyIdentifierPresentValue, nil,
		encoding.EncodeApplicationPrimitive(uint8(encoding.AppTagReal), encoding.EncodeReal(42)), &priority)
	if err != nil {
		t.Fatal(err)
	}
	if err := c.WriteProperty(ctx(t), dst, req); err != nil {
		t.Fatal(err)
	}
	if got, err := readProperty(t, c, dst, av1, types.PropertyIdentifierPresentValue); err != nil || got != encoding.AppReal(42) {
		t.Errorf("AV-1 Present_Value after the write = %#v %v, want REAL 42", got, err)
	}
	req, err = apdu.NewWritePropertyRequest(oid(t, types.ObjectTypeDevice, 1234), types.PropertyIdentifierObjectName, nil,
		encoding.EncodeApplicationPrimitive(uint8(encoding.AppTagCharacterString), []byte{0, 'x'}), nil)
	if err != nil {
		t.Fatal(err)
	}
	remoteError(t, c.WriteProperty(ctx(t), dst, req), apdu.ErrorClassProperty, apdu.ErrorCodePropertyWriteAccessDenied)
}

// walker reads a payload with Worldiety's tag and value decoders.
type walker struct {
	t   *testing.T
	p   []byte
	off int
}

func (w *walker) next(off int, err error) {
	w.t.Helper()
	if err != nil {
		w.t.Fatalf("%x at %d: %v", w.p, w.off, err)
	}
	w.off = off
}

func (w *walker) open(tag encoding.AppTag) {
	w.t.Helper()
	w.next(encoding.ExpectOpeningTag(w.p, w.off, tag))
}

func (w *walker) close(tag encoding.AppTag) {
	w.t.Helper()
	w.next(encoding.ExpectClosingTag(w.p, w.off, tag))
}

func (w *walker) context(tag encoding.AppTag) []byte {
	w.t.Helper()
	_, raw, off, err := encoding.DecodeExpectedContextPrimitive(w.p, w.off, tag)
	w.next(off, err)
	return raw
}

func (w *walker) application(tag encoding.AppTag) []byte {
	w.t.Helper()
	_, raw, off, err := encoding.DecodeExpectedApplicationPrimitive(w.p, w.off, tag)
	w.next(off, err)
	return raw
}

func (w *walker) end() {
	w.t.Helper()
	if w.off != len(w.p) {
		w.t.Fatalf("%x: %d trailing bytes", w.p, len(w.p)-w.off)
	}
}

func appReal(v float32) []byte {
	return encoding.EncodeApplicationPrimitive(uint8(encoding.AppTagReal), encoding.EncodeReal(v))
}

func appString(s string) []byte {
	return encoding.EncodeApplicationPrimitive(uint8(encoding.AppTagCharacterString), append([]byte{0}, s...))
}

// wpmRequest is a WritePropertyMultiple-Request for one property: [0] object
// [1] { [0] property [2] { value } }. Worldiety's WritePropertyMultiple puts
// each WriteAccessSpecification inside an extra [0] pair, which the standard
// does not have, so the request is encoded here and sent with
// InvokeConfirmedRaw.
func wpmRequest(id types.ObjectIdentifier, prop types.PropertyIdentifier, value []byte) []byte {
	var out []byte
	out = append(out, encoding.EncodeContextPrimitive(0, encoding.EncodeObjectIdentifierValue(id))...)
	out = append(out, encoding.EncodeOpeningTag(1)...)
	out = append(out, encoding.EncodeContextPrimitive(0, encoding.EncodeUnsigned(uint32(prop)))...)
	out = append(out, encoding.EncodeOpeningTag(2)...)
	out = append(out, value...)
	out = append(out, encoding.EncodeClosingTag(2)...)
	out = append(out, encoding.EncodeClosingTag(1)...)
	return out
}

func TestWritePropertyMultiple(t *testing.T) {
	c, dst := serve(t)
	av1 := oid(t, types.ObjectTypeAnalogValue, 1)
	ack, err := c.InvokeConfirmedRaw(ctx(t), dst, apdu.ServiceChoiceWritePropertyMultiple,
		wpmRequest(av1, types.PropertyIdentifierPresentValue, appReal(30)))
	if err != nil || ack != nil {
		t.Fatalf("got %x %v, want a SimpleACK", ack, err)
	}
	if got, err := readProperty(t, c, dst, av1, types.PropertyIdentifierPresentValue); err != nil || got != encoding.AppReal(30) {
		t.Errorf("AV-1 Present_Value after the write = %#v %v, want REAL 30", got, err)
	}
	_, err = c.InvokeConfirmedRaw(ctx(t), dst, apdu.ServiceChoiceWritePropertyMultiple,
		wpmRequest(oid(t, types.ObjectTypeDevice, 1234), types.PropertyIdentifierObjectName, appString("x")))
	if !errors.Is(err, apdu.ErrRemoteError) {
		t.Errorf("a write that fails: %v, want an Error PDU", err)
	}
}

// Worldiety's client reads an Error PDU as class and code only, so the
// WritePropertyMultiple-Error is read from the handler's answer: [0] {
// error-class, error-code } [1] { [0] object, [1] property }.
func TestWritePropertyMultipleError(t *testing.T) {
	store, err := fixture.LoadFile(fixtureFile(t))
	if err != nil {
		t.Fatal(err)
	}
	dev := oid(t, types.ObjectTypeDevice, 1234)
	resp, err := (&Server{Store: store}).handleWritePropertyMultiple(context.Background(), apdu.ConfirmedIndicationICI{
		ServiceRequest: apdu.ConfirmedRequest{
			ServiceChoice: apdu.ServiceChoiceWritePropertyMultiple,
			Payload:       wpmRequest(dev, types.PropertyIdentifierObjectName, appString("x")),
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	if resp.ResponseType != apdu.ConfirmedResponseTypeError {
		t.Fatalf("response type %v, want Error", resp.ResponseType)
	}
	w := &walker{t: t, p: resp.ServiceResponse.Payload}
	w.open(0)
	class, _ := encoding.DecodeEnumeratedValue(w.application(encoding.AppTagEnum))
	code, _ := encoding.DecodeEnumeratedValue(w.application(encoding.AppTagEnum))
	w.close(0)
	w.open(1)
	obj, err := encoding.DecodeObjectIdentifierValue(w.context(0))
	prop, _ := encoding.DecodeUnsigned(w.context(1))
	w.close(1)
	w.end()
	if apdu.ErrorClass(class) != apdu.ErrorClassProperty || apdu.ErrorCode(code) != apdu.ErrorCodePropertyWriteAccessDenied {
		t.Errorf("error %d/%d, want property/write-access-denied", class, code)
	}
	if err != nil || obj != dev || types.PropertyIdentifier(prop) != types.PropertyIdentifierObjectName {
		t.Errorf("firstFailedWriteAttempt %v %v %v, want %v Object_Name", obj, prop, err, dev)
	}
}

// readRangeRequest is a ReadRange-Request byPosition ([3]) or
// bySequenceNumber ([6]): { Unsigned reference, INTEGER count }. Worldiety's
// ReadRange encodes the two as context tags and the other choices as [4] and
// [5], so the request is encoded here and sent with InvokeConfirmedRaw.
func readRangeRequest(id types.ObjectIdentifier, prop types.PropertyIdentifier, choice uint8, ref uint32, count int32) []byte {
	var out []byte
	out = append(out, encoding.EncodeContextPrimitive(0, encoding.EncodeObjectIdentifierValue(id))...)
	out = append(out, encoding.EncodeContextPrimitive(1, encoding.EncodeUnsigned(uint32(prop)))...)
	out = append(out, encoding.EncodeOpeningTag(choice)...)
	out = append(out, encoding.EncodeApplicationPrimitive(uint8(encoding.AppTagUnsignedInteger), encoding.EncodeUnsigned(ref))...)
	out = append(out, encoding.EncodeApplicationPrimitive(uint8(encoding.AppTagInteger), encoding.EncodeSigned(count))...)
	out = append(out, encoding.EncodeClosingTag(choice)...)
	return out
}

func TestReadRange(t *testing.T) {
	c, dst := serve(t)
	tl0 := oid(t, objectTypeTrendLog, 0)
	got, err := readProperty(t, c, dst, tl0, fixture.PropertyRecordCount)
	if err != nil {
		t.Fatal(err)
	}
	if got != encoding.AppUnsignedInteger(fixture.LogSeedRecords) {
		t.Fatalf("TL-0 Record_Count = %#v, want %d", got, fixture.LogSeedRecords)
	}

	for _, tc := range []struct {
		name        string
		choice      uint8
		ref         uint32
		count       int32
		first       int     // the first record (1-based) of the answer
		flags       [3]bool // FIRST_ITEM, LAST_ITEM, MORE_ITEMS
		firstSeqNum bool
	}{
		{"byPosition 2 +3", 3, 2, 3, 2, [3]bool{false, false, false}, false},
		{"byPosition 3 -3", 3, 3, -3, 1, [3]bool{true, false, false}, false},
		{"bySequenceNumber 34 +5", 6, 34, 5, 34, [3]bool{false, true, false}, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			raw, err := c.InvokeConfirmedRaw(ctx(t), dst, apdu.ServiceChoiceReadRange,
				readRangeRequest(tl0, fixture.PropertyLogBuffer, tc.choice, tc.ref, tc.count))
			if err != nil {
				t.Fatal(err)
			}
			w := &walker{t: t, p: raw}
			if id, err := encoding.DecodeObjectIdentifierValue(w.context(0)); err != nil || id != tl0 {
				t.Errorf("objectIdentifier %v %v, want %v", id, err, tl0)
			}
			if prop, err := encoding.DecodeUnsigned(w.context(1)); err != nil || types.PropertyIdentifier(prop) != fixture.PropertyLogBuffer {
				t.Errorf("propertyIdentifier %v %v, want Log_Buffer", prop, err)
			}
			flags, err := encoding.DecodeBitStringValue(w.context(3))
			if err != nil || len(flags.Bits) != 3 || [3]bool(flags.Bits) != tc.flags {
				t.Errorf("resultFlags %v %v, want %v", flags.Bits, err, tc.flags)
			}
			n := 3
			if items, err := encoding.DecodeUnsigned(w.context(4)); err != nil || int(items) != n {
				t.Errorf("itemCount %v %v, want %d", items, err, n)
			}
			// Record k: [0] { date, time } [1] { [2] real 20 + (k-1) }.
			w.open(5)
			for k := tc.first; k < tc.first+n; k++ {
				w.open(0)
				w.application(encoding.AppTagDate)
				w.application(encoding.AppTagTime)
				w.close(0)
				w.open(1)
				datum, err := encoding.DecodeReal(w.context(2))
				if err != nil || math.Abs(float64(datum)-float64(20+k-1)) > 1e-6 {
					t.Errorf("record %d: logDatum %v %v, want %d", k, datum, err, 20+k-1)
				}
				w.close(1)
			}
			w.close(5)
			if tc.firstSeqNum {
				if seq, err := encoding.DecodeUnsigned(w.context(6)); err != nil || int(seq) != tc.first {
					t.Errorf("firstSequenceNumber %v %v, want %d", seq, err, tc.first)
				}
			}
			w.end()
		})
	}

	_, err = c.InvokeConfirmedRaw(ctx(t), dst, apdu.ServiceChoiceReadRange,
		readRangeRequest(tl0, fixture.PropertyLogBuffer, 3, fixture.LogSeedRecords+1, 1))
	remoteError(t, err, apdu.ErrorClassProperty, apdu.ErrorCodePropertyInvalidArrayIndex)
}
