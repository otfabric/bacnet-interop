// SPDX-License-Identifier: MIT

package main

import (
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"math"
	"net"
	"os"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/ulbios/bacnet"
	"github.com/ulbios/bacnet/common"
	"github.com/ulbios/bacnet/objects"
	"github.com/ulbios/bacnet/plumbing"
	"github.com/ulbios/bacnet/services"
)

// Client mode (docs/CLIENT_DRIVER_CONTRACT.md). Requests are ulbios'
// encoders: bacnet.NewWhois, bacnet.NewReadProperty and
// bacnet.NewWriteProperty where one fits the scenario exactly, otherwise a
// request assembled from ulbios' objects.Enc* encoders in the parameter
// order of clause 15.9 (adapter-shim). Answers are decoded by bacnet.Parse
// and ulbios' Decode methods and objects.Dec* decoders. ulbios has no
// transaction layer: sending, the APDU timeout, retries and matching the
// answer to the request are adapter code.

var outcomes = []string{"pass", "fail", "unsupported", "not-tested", "known-difference", "infra-error"}

// outcomeError ends a scenario with an outcome other than pass or fail.
type outcomeError struct {
	outcome string
	detail  string
}

func (e *outcomeError) Error() string { return e.outcome + ": " + e.detail }

func unsupported(format string, a ...any) error {
	return &outcomeError{"unsupported", fmt.Sprintf(format, a...)}
}

func infra(format string, a ...any) error {
	return &outcomeError{"infra-error", fmt.Sprintf(format, a...)}
}

// knownDifference is an answer ulbios cannot decode, or decodes wrongly, for
// a reason recorded in PEER_SUPPORT.md ("ulbios", "Client mode").
func knownDifference(reason string, raw []byte, format string, a ...any) error {
	d := fmt.Sprintf(format, a...)
	if raw != nil {
		d += "; answer octets " + hex.EncodeToString(raw)
	}
	return &outcomeError{"known-difference", reason + ": " + d}
}

// Recorded ulbios limits (PEER_SUPPORT.md, ulbios).
const (
	kdShortACK     = "ulbios-short-complex-ack"
	kdNoDecoder    = "ulbios-no-decoder"
	kdObjectIDType = "ulbios-object-identifier-type"
	kdRejectAbort  = "ulbios-no-reject-abort"
	kdRealNull     = "ulbios-write-real-null"
)

type clientEnv struct {
	conn      *net.UDPConn
	target    *net.UDPAddr
	broadcast *net.UDPAddr
	timeout   time.Duration
	retries   int
	ifaces    []net.Addr
}

var ipPort = regexp.MustCompile(`^[0-9]{1,3}(\.[0-9]{1,3}){3}:[0-9]+$`)

func clientMain(argv []string) int {
	fs := flag.NewFlagSet("client", flag.ContinueOnError)
	target := fs.String("target", "", "DUT HOST:PORT")
	dev := fs.Int("device", -1, "DUT device instance")
	scen := fs.String("scenarios", "", "scenario file")
	only := fs.String("only", "", "comma-separated scenario ids")
	bcast := fs.String("broadcast", "", "HOST:PORT discovery requests are sent to")
	bbmd := fs.String("bbmd", "", "BBMD HOST:PORT (ulbios cannot register as a foreign device)")
	ttl := fs.Int("fd-ttl", 60, "foreign-device TTL in seconds")
	if err := fs.Parse(argv); err != nil {
		return 2
	}
	if *dev < 0 || *scen == "" {
		fmt.Fprintln(os.Stderr, "client: --device and --scenarios are required")
		return 2
	}
	if *ttl < 1 || *ttl > 65535 {
		fmt.Fprintln(os.Stderr, "client: --fd-ttl must be 1..65535")
		return 2
	}
	for name, v := range map[string]string{"target": *target, "broadcast": *bcast, "bbmd": *bbmd} {
		if v != "" && !ipPort.MatchString(v) {
			fmt.Fprintf(os.Stderr, "client: --%s must be IPv4:PORT\n", name)
			return 2
		}
	}
	raw, err := os.ReadFile(*scen)
	var doc struct {
		ID           string           `json:"id"`
		RequiresBBMD bool             `json:"requires_bbmd"`
		Scenarios    []map[string]any `json:"scenarios"`
	}
	if err == nil {
		err = json.Unmarshal(raw, &doc)
	}
	if err != nil || doc.Scenarios == nil {
		fmt.Fprintf(os.Stderr, "client: cannot read scenarios: %v\n", err)
		return 2
	}
	if doc.RequiresBBMD && *bbmd == "" {
		fmt.Fprintf(os.Stderr, "client: %s requires --bbmd\n", doc.ID)
		return 2
	}
	timeoutMS, err1 := strconv.Atoi(envOr("BACNET_CLIENT_TIMEOUT_MS", "3000"))
	retries, err2 := strconv.Atoi(envOr("BACNET_CLIENT_RETRIES", "1"))
	if err1 != nil || err2 != nil || timeoutMS < 1 || retries < 0 {
		fmt.Fprintln(os.Stderr, "client: BACNET_CLIENT_TIMEOUT_MS and BACNET_CLIENT_RETRIES must be integers")
		return 2
	}
	if v := os.Getenv("ADAPTER_VERSION"); v != "" {
		adapterVersion = v
	}
	if *bbmd != "" {
		fmt.Fprintln(os.Stderr, "client: ulbios has no Register-Foreign-Device; --bbmd is not used and requests go to --target directly")
	}

	env := &clientEnv{timeout: time.Duration(timeoutMS) * time.Millisecond, retries: retries}
	var startErr error
	if *target != "" {
		env.target, startErr = net.ResolveUDPAddr("udp4", *target)
	}
	if startErr == nil && *bcast != "" {
		env.broadcast, startErr = net.ResolveUDPAddr("udp4", *bcast)
	}
	if startErr == nil {
		// Port 47808: a broadcast Who-Is is answered with a broadcast I-Am
		// to that port.
		env.conn, startErr = net.ListenUDP("udp4", &net.UDPAddr{Port: 47808})
	}
	if startErr == nil {
		defer func() { _ = env.conn.Close() }()
		env.ifaces, _ = net.InterfaceAddrs()
	}

	emit(map[string]any{"event": "ready", "mode": "client", "adapter": adapterName, "version": adapterVersion,
		"peer_version": peerVersion(), "scenarios": doc.ID})
	want := map[string]bool{}
	for _, id := range strings.Split(*only, ",") {
		if id != "" {
			want[id] = true
		}
	}
	summary := map[string]int{}
	for _, o := range outcomes {
		summary[o] = 0
	}
	for _, sc := range doc.Scenarios {
		id, _ := sc["id"].(string)
		if len(want) > 0 && !want[id] {
			continue
		}
		svc, _ := sc["service"].(string)
		begin := time.Now()
		line := map[string]any{"event": "result", "scenario": id, "service": svc}
		var observed map[string]any
		err := startErr
		if err != nil {
			err = infra("cannot start: %v", err)
		} else {
			observed, err = runScenario(env, sc, uint32(*dev))
		}
		var oe *outcomeError
		switch {
		case err == nil:
			line["observed"] = observed
			if compare(sc["expect"], observed) {
				line["outcome"] = "pass"
			} else {
				line["outcome"] = "fail"
			}
		case errors.As(err, &oe):
			line["outcome"], line["detail"] = oe.outcome, oe.detail
		default:
			line["outcome"], line["detail"] = "fail", err.Error()
		}
		line["durationMs"] = time.Since(begin).Milliseconds()
		summary[line["outcome"].(string)]++
		emit(line)
	}
	emit(map[string]any{"event": "done", "summary": summary})
	return 0
}

func runScenario(env *clientEnv, sc map[string]any, dev uint32) (map[string]any, error) {
	switch sc["service"] {
	case "who-is":
		return whoIsScenario(env, sc)
	case "read-property":
		return readPropertyScenario(env, sc)
	case "write-property":
		return writePropertyScenario(env, sc)
	}
	return nil, unsupported("ulbios has no %v: bacnet.Parse and its encoders know Who-Is, I-Am, ReadProperty, WriteProperty, Simple-ACK, Complex-ACK and Error only", sc["service"])
}

// whoIsScenario sends bacnet.NewWhois (a Who-Is without limits, as an
// Original-Broadcast-NPDU) and collects I-Am answers with
// UnconfirmedIAm.Decode.
func whoIsScenario(env *clientEnv, sc map[string]any) (map[string]any, error) {
	if _, ok := sc["low"]; ok {
		return nil, unsupported("ulbios' Who-Is has no device instance range (services.NewUnconfirmedWhoIs has no limit parameters)")
	}
	frame, err := bacnet.NewWhois()
	if err != nil {
		return nil, err
	}
	dst := env.broadcast
	if dst == nil {
		dst = &net.UDPAddr{IP: localBroadcast(), Port: 47808}
	}
	if _, err := env.conn.WriteToUDP(frame, dst); err != nil {
		return nil, infra("send Who-Is: %v", err)
	}
	found := []int{}
	seen := map[int]bool{}
	deadline := time.Now().Add(env.timeout)
	buf := make([]byte, 2048)
	for {
		_ = env.conn.SetReadDeadline(deadline)
		n, from, err := env.conn.ReadFromUDP(buf)
		if err != nil {
			break
		}
		if common.IsLocalAddr(env.ifaces, from) {
			continue // our own broadcast
		}
		msg, err := parse(buf[:n])
		iam, ok := msg.(*services.UnconfirmedIAm)
		if err != nil || !ok {
			continue
		}
		dec, err := iam.Decode()
		if err != nil {
			return nil, fmt.Errorf("UnconfirmedIAm.Decode from %s: %v (%x)", from, err, buf[:n])
		}
		if env.target != nil && from.String() != env.target.String() {
			return nil, infra("I-Am for device %d from %s, not the target %s", dec.DeviceId, from, env.target)
		}
		if !seen[int(dec.DeviceId)] {
			seen[int(dec.DeviceId)] = true
			found = append(found, int(dec.DeviceId))
		}
	}
	sort.Ints(found)
	return map[string]any{"i-am": found}, nil
}

var propertyIDs = map[string]int{
	"description":       28,
	"event-state":       36,
	"log-buffer":        131,
	"object-identifier": 75,
	"object-list":       76,
	"object-name":       77,
	"object-type":       79,
	"present-value":     85,
	"priority-array":    87,
	"recipient-list":    102,
	"units":             117,
	"vendor-identifier": 120,
}

func objectRef(v any) (uint16, uint32, error) {
	s, _ := v.(string)
	name, inst, ok := strings.Cut(s, ",")
	t, known := objectTypes[name]
	n, err := strconv.ParseUint(inst, 10, 32)
	if !ok || !known || err != nil {
		return 0, 0, unsupported("object %q is not one this driver names", s)
	}
	return t, uint32(n), nil
}

// propertyRef is the property identifier, which ulbios encodes in one octet.
func propertyRef(v any) (uint8, error) {
	var id int
	switch p := v.(type) {
	case string:
		n, ok := propertyIDs[p]
		if !ok {
			return 0, unsupported("property %q is not one this driver names", p)
		}
		id = n
	case float64:
		id = int(p)
	}
	if id < 0 || id > 255 {
		return 0, unsupported("property identifier %d: ulbios encodes a property identifier in one octet (objects.EncPropertyIdentifier takes a uint8)", id)
	}
	return uint8(id), nil
}

// transact sends a confirmed request to the target and returns the answer
// with the invoke ID of the request. ulbios' request encoders fix the invoke
// ID to 1; every request here uses it.
func transact(env *clientEnv, frame []byte) (plumbing.BACnet, []byte, error) {
	if env.target == nil {
		return nil, nil, infra("no --target")
	}
	buf := make([]byte, 2048)
	for attempt := 0; attempt <= env.retries; attempt++ {
		if _, err := env.conn.WriteToUDP(frame, env.target); err != nil {
			return nil, nil, infra("send: %v", err)
		}
		deadline := time.Now().Add(env.timeout)
		for {
			_ = env.conn.SetReadDeadline(deadline)
			n, from, err := env.conn.ReadFromUDP(buf)
			if err != nil {
				break
			}
			if from.String() != env.target.String() {
				continue
			}
			raw := append([]byte(nil), buf[:n]...)
			off, ok := apduOffset(raw)
			if !ok || len(raw) < off+2 {
				continue
			}
			if t := raw[off] >> 4; t < plumbing.SimpleAck || t > plumbing.Abort || t == plumbing.SegmentAck || raw[off+1] != 1 {
				continue // not an answer to invoke ID 1
			}
			msg, err := parse(raw)
			return msg, raw, err
		}
	}
	return nil, nil, infra("no answer after %d attempt(s) of %v", env.retries+1, env.timeout)
}

// apduOffset finds the APDU in a BACnet/IP datagram (clause 6.2), for
// matching answers; decoding stays with bacnet.Parse.
func apduOffset(b []byte) (int, bool) {
	off := 4
	if len(b) > 1 && b[1] == 0x04 { // Forwarded-NPDU: the original source first
		off = 10
	}
	if len(b) < off+2 || b[0] != plumbing.BVLCType || b[off] != 1 {
		return 0, false
	}
	ctrl := b[off+1]
	off += 2
	if ctrl&0x80 != 0 {
		return 0, false
	}
	if ctrl&0x20 != 0 {
		if len(b) < off+3 {
			return 0, false
		}
		off += 3 + int(b[off+2])
	}
	if ctrl&0x08 != 0 {
		if len(b) < off+3 {
			return 0, false
		}
		off += 3 + int(b[off+2])
	}
	if ctrl&0x20 != 0 {
		off++ // hop count
	}
	return off, off < len(b)
}

// answer turns what bacnet.Parse returned into an observation; ack decodes
// a Complex-ACK.
func answer(msg plumbing.BACnet, raw []byte, perr error, ack func(*services.ComplexACK) (map[string]any, error)) (map[string]any, error) {
	if perr != nil {
		off, _ := apduOffset(raw)
		switch t := raw[off] >> 4; {
		case t == plumbing.Reject || t == plumbing.Abort:
			return nil, knownDifference(kdRejectAbort, raw, "bacnet.Parse has no Reject or Abort PDU (%v)", perr)
		case t == plumbing.ComplexAck && errors.Is(perr, common.ErrTooShortToParse):
			return nil, knownDifference(kdShortACK, raw, "ComplexACK.UnmarshalBinary refuses an APDU shorter than 17 octets, the length of its own REAL ReadProperty-ACK")
		}
		return nil, fmt.Errorf("bacnet.Parse: %v; answer octets %x", perr, raw)
	}
	switch m := msg.(type) {
	case *services.SimpleACK:
		return map[string]any{"ack": true}, nil
	case *services.Error:
		dec, err := m.Decode()
		if err != nil {
			return nil, fmt.Errorf("Error.Decode: %v; answer octets %x", err, raw)
		}
		return map[string]any{"error": map[string]any{"class": errorClassName(dec.ErrorClass), "code": errorCodeName(dec.ErrorCode)}}, nil
	case *services.ComplexACK:
		return ack(m)
	}
	return nil, fmt.Errorf("unexpected answer %T; octets %x", msg, raw)
}

// readPropertyScenario sends bacnet.NewReadProperty.
func readPropertyScenario(env *clientEnv, sc map[string]any) (map[string]any, error) {
	typ, inst, err := objectRef(sc["object"])
	if err != nil {
		return nil, err
	}
	prop, err := propertyRef(sc["property"])
	if err != nil {
		return nil, err
	}
	if _, ok := sc["array_index"]; ok {
		return nil, unsupported("ulbios' ReadProperty has no array index (services.ConfirmedReadPropertyObjects)")
	}
	frame, err := bacnet.NewReadProperty(typ, inst, prop)
	if err != nil {
		return nil, err
	}
	msg, raw, perr := transact(env, frame)
	if perr != nil && raw == nil {
		return nil, perr
	}
	expect, _ := sc["expect"].(map[string]any)
	return answer(msg, raw, perr, func(c *services.ComplexACK) (map[string]any, error) {
		return decodeReadACK(c, raw, expect, typ, prop)
	})
}

// decodeReadACK decodes the value of a ReadProperty-ACK in the type the
// scenario expects, with ulbios' decoders. ComplexACK.Decode reads a REAL
// only; for the other types the third token is decoded directly.
func decodeReadACK(c *services.ComplexACK, raw []byte, expect map[string]any, typ uint16, prop uint8) (map[string]any, error) {
	want, _ := expect["value"].(map[string]any)
	if want == nil {
		if _, ok := expect["error"]; ok {
			return map[string]any{"ack": "complex-ack"}, nil
		}
		key := "?"
		for k := range expect {
			key = k
		}
		return nil, knownDifference(kdNoDecoder, raw, "ulbios has no decoder for %s", key)
	}
	wt, _ := want["type"].(string)
	toks := c.APDU.Objects
	if wt == "real" {
		dec, err := c.Decode()
		if err != nil {
			return nil, fmt.Errorf("ComplexACK.Decode: %v; answer octets %x", err, raw)
		}
		return map[string]any{"value": map[string]any{"type": "real", "value": dec.PresentValue}}, nil
	}
	if len(toks) != 3 {
		return nil, knownDifference(kdNoDecoder, raw, "ulbios has no decoder for %s (bacnet.Parse produced %d tokens: it reads a tag length of up to 4 octets only)", wt, len(toks))
	}
	switch wt {
	case "enumerated":
		n, err := objects.DecEnumerated(toks[2])
		if err != nil {
			return nil, fmt.Errorf("DecEnumerated: %v; answer octets %x", err, raw)
		}
		return map[string]any{"value": map[string]any{"type": "enumerated", "value": enumName(typ, prop, n)}}, nil
	case "unsigned":
		n, err := objects.DecUnisgnedInteger(toks[2])
		if err != nil {
			return nil, fmt.Errorf("DecUnisgnedInteger: %v; answer octets %x", err, raw)
		}
		return map[string]any{"value": map[string]any{"type": "unsigned", "value": n}}, nil
	case "object-identifier":
		id, err := objects.DecObjectIdentifier(toks[2])
		if err != nil {
			return nil, fmt.Errorf("DecObjectIdentifier: %v; answer octets %x", err, raw)
		}
		got := fmt.Sprintf("%s,%d", objectTypeName(id.ObjectType), id.InstanceNumber)
		if w, _ := want["value"].(string); got != w {
			return nil, knownDifference(kdObjectIDType, raw, "objects.DecObjectIdentifier decoded %s (type %d); the type shifted back by two is %s",
				got, id.ObjectType, fmt.Sprintf("%s,%d", objectTypeName(id.ObjectType>>2), id.InstanceNumber))
		}
		return map[string]any{"value": map[string]any{"type": "object-identifier", "value": got}}, nil
	}
	return nil, knownDifference(kdNoDecoder, raw, "ulbios has no decoder for %s", wt)
}

func enumName(typ uint16, prop uint8, n uint32) any {
	switch {
	case prop == propObjectType:
		return objectTypeName(uint16(n))
	case prop == propPresentValue && (typ == 3 || typ == 4 || typ == 5):
		if n == 0 {
			return "inactive"
		}
		if n == 1 {
			return "active"
		}
	}
	return n
}

// writePropertyScenario sends bacnet.NewWriteProperty when the scenario is
// a REAL at priority 16 or without one: ulbios' request carries the REAL
// followed by a NULL inside the value and always priority 16. Otherwise the
// request is assembled from ulbios' encoders (adapter-shim).
func writePropertyScenario(env *clientEnv, sc map[string]any) (map[string]any, error) {
	typ, inst, err := objectRef(sc["object"])
	if err != nil {
		return nil, err
	}
	prop, err := propertyRef(sc["property"])
	if err != nil {
		return nil, err
	}
	if _, ok := sc["array_index"]; ok {
		return nil, unsupported("ulbios' WriteProperty has no array index")
	}
	val, _ := sc["value"].(map[string]any)
	vt, _ := val["type"].(string)
	prio := -1
	if p, ok := sc["priority"].(float64); ok {
		prio = int(p)
	}
	var frame []byte
	native := vt == "real" && (prio == -1 || prio == 16)
	if native {
		f, _ := val["value"].(float64)
		frame, err = bacnet.NewWriteProperty(typ, inst, prop, float32(f))
	} else {
		var v objects.APDUPayload
		switch vt {
		case "real":
			f, _ := val["value"].(float64)
			v = objects.EncReal(float32(f))
		case "null":
			v = objects.EncNull()
		case "enumerated":
			n, ok := val["value"].(float64)
			if !ok || n < 0 || n > 255 {
				return nil, unsupported("enumerated %v: objects.EncEnumerated encodes one octet", val["value"])
			}
			v = objects.EncEnumerated(uint8(n))
		default:
			return nil, unsupported("ulbios has no encoder for %s", vt)
		}
		if prio < -1 || prio == 0 || prio > 255 {
			return nil, unsupported("priority %d", prio)
		}
		c := services.NewConfirmedWriteProperty(plumbing.NewBVLC(plumbing.BVLCFuncUnicast), plumbing.NewNPDU(false, false, false, true))
		c.APDU.MaxSize, c.APDU.InvokeID = 5, 1
		c.APDU.Objects = []objects.APDUPayload{
			objects.EncObjectIdentifier(true, 0, typ, inst),
			objects.EncPropertyIdentifier(true, 1, prop),
			objects.EncOpeningTag(3), v, objects.EncClosingTag(3),
		}
		if prio > 0 {
			c.APDU.Objects = append(c.APDU.Objects, objects.EncPriority(true, 4, uint8(prio)))
		}
		c.SetLength()
		frame, err = c.MarshalBinary()
	}
	if err != nil {
		return nil, err
	}
	msg, raw, perr := transact(env, frame)
	if perr != nil && raw == nil {
		return nil, perr
	}
	obs, err := answer(msg, raw, perr, func(*services.ComplexACK) (map[string]any, error) {
		return nil, fmt.Errorf("Complex-ACK to a WriteProperty; octets %x", raw)
	})
	if err == nil && native && refusesRealNull(sc, obs) {
		return nil, knownDifference(kdRealNull, raw,
			"bacnet.NewWriteProperty encodes the value as a REAL followed by a NULL (request octets %x); the device refused it with %v", frame, obs["error"])
	}
	return obs, err
}

// refusesRealNull: the scenario expects a SimpleACK and the device answered
// property/invalid-data-type to ulbios' own WriteProperty form, whose value
// [3] holds two application values (services.ConfirmedWritePropertyObjects).
// Clause 15.9.1.1.3 has one value of the property's datatype; bacnet-stack
// and BACnet4J take the first, a stricter device refuses it.
func refusesRealNull(sc, obs map[string]any) bool {
	exp, _ := sc["expect"].(map[string]any)
	if ack, _ := exp["ack"].(bool); !ack {
		return false
	}
	e, _ := obs["error"].(map[string]any)
	return e != nil && e["class"] == "property" && e["code"] == "invalid-data-type"
}

var errorClasses = map[uint8]string{0: "device", 1: "object", 2: "property", 3: "resources", 4: "security", 5: "services", 6: "vt", 7: "communication"}

var errorCodes = map[uint8]string{
	0: "other", 2: "configuration-in-progress", 3: "device-busy", 5: "file-access-denied", 9: "invalid-data-type",
	23: "no-space-for-object", 25: "operational-problem", 26: "password-failure", 27: "read-access-denied",
	29: "service-request-denied", 30: "timeout", 31: "unknown-object", 32: "unknown-property",
	37: "value-out-of-range", 40: "write-access-denied", 42: "invalid-array-index", 44: "not-cov-property",
	45: "optional-functionality-not-supported", 50: "property-is-not-an-array",
}

func errorClassName(n uint8) string {
	if s, ok := errorClasses[n]; ok {
		return s
	}
	return strconv.Itoa(int(n))
}

func errorCodeName(n uint8) string {
	if s, ok := errorCodes[n]; ok {
		return s
	}
	return strconv.Itoa(int(n))
}

// compare is the comparison of the other client drivers for the
// expectations this driver can observe.
func compare(expect any, observed map[string]any) bool {
	exp, _ := expect.(map[string]any)
	for key, want := range exp {
		got, ok := observed[key]
		if !ok {
			return false
		}
		switch key {
		case "value":
			return sameValue(want, got)
		case "error":
			w, _ := want.(map[string]any)
			g, _ := got.(map[string]any)
			return g != nil && w["class"] == g["class"] && w["code"] == g["code"]
		case "ack":
			return got == true
		case "i-am":
			w, _ := want.([]any)
			g, _ := got.([]int)
			if len(w) != len(g) {
				return false
			}
			ws := make([]int, len(w))
			for i, x := range w {
				f, _ := x.(float64)
				ws[i] = int(f)
			}
			sort.Ints(ws)
			for i := range ws {
				if ws[i] != g[i] {
					return false
				}
			}
			return true
		}
		return false
	}
	return false
}

func sameValue(want, got any) bool {
	w, _ := want.(map[string]any)
	g, _ := got.(map[string]any)
	if w == nil || g == nil || w["type"] != g["type"] {
		return false
	}
	if w["type"] == "real" {
		wf, _ := w["value"].(float64)
		gf, _ := g["value"].(float32)
		return math.Abs(wf-float64(gf)) < 1e-3
	}
	return fmt.Sprint(w["value"]) == fmt.Sprint(g["value"])
}
