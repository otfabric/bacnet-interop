// SPDX-License-Identifier: MIT

package main

import (
	"fmt"
	"os"
	"time"

	"github.com/cB-Sigma/bacnet"
	"github.com/cB-Sigma/bacnet-sim/sim"
)

// Confirmed and unconfirmed service choices (clause 21) the simulator
// records without an observable reply.
var unconfirmedNames = map[byte]string{
	2:  "unconfirmed-event-notification",
	4:  "unconfirmed-private-transfer",
	5:  "unconfirmed-text-message",
	6:  "time-synchronization",
	9:  "utc-time-synchronization",
	10: "write-group",
}

var mgmtNames = map[byte]string{
	17: "device-communication-control",
	20: "reinitialize-device",
}

// serveSim serves the fixture with github.com/cB-Sigma/bacnet-sim/sim.
//
// Switches (environment), all off by default:
//
//	BACNET_BBMD=1             BBMD mode: Register-Foreign-Device, Distribute-Broadcast-To-Network
//	CBSIGMA_FD_NAK=1          refuse Register-Foreign-Device (Result NAK)
//	CBSIGMA_FORWARD=1         send every reply as a Forwarded-NPDU
//	CBSIGMA_MAX_APDU=n        largest reply sent unsegmented (default 1476)
//	CBSIGMA_WINDOW=n          window proposed for segmented replies (default 4)
//	CBSIGMA_DROP_SEG=k        leave reply segment k out, once
//	CBSIGMA_STALL_SEG=k       stop a segmented reply before segment k, once
//	CBSIGMA_REJECT_RPM=1      reject ReadPropertyMultiple (unrecognized-service)
//	CBSIGMA_REJECT_WPM=1      reject WritePropertyMultiple (unrecognized-service)
//	CBSIGMA_REJECT_SEQ=1      refuse ReadRange by sequence number
//	CBSIGMA_EVENTS=1          answer GetEventInformation and GetAlarmSummary
//	                          with one active alarm (AV-1 high-limit); without
//	                          it GetEventInformation is rejected and
//	                          GetAlarmSummary is answered with an empty list
func serveSim(f *fixture, listen string) (func(), error) {
	s := sim.New()
	s.Addr = listen
	s.Iam.Device = bacnet.ObjectID{Type: 8, Instance: f.DeviceInstance}
	var err error
	if s.MaxAPDU, err = envInt("CBSIGMA_MAX_APDU", 1476); err != nil {
		return nil, err
	}
	window, err := envInt("CBSIGMA_WINDOW", 4)
	if err != nil {
		return nil, err
	}
	s.Window = byte(window)
	if s.DropSeg, err = envInt("CBSIGMA_DROP_SEG", -1); err != nil {
		return nil, err
	}
	if s.StallSeg, err = envInt("CBSIGMA_STALL_SEG", -1); err != nil {
		return nil, err
	}
	s.BBMD = envBool("BACNET_BBMD")
	s.FDNAK = envBool("CBSIGMA_FD_NAK")
	s.Forward = envBool("CBSIGMA_FORWARD")
	s.RejectRPM = envBool("CBSIGMA_REJECT_RPM")
	s.RejectWPM = envBool("CBSIGMA_REJECT_WPM")
	s.RejectSeq = envBool("CBSIGMA_REJECT_SEQ")

	var alarmed *bacnet.ObjectID
	for _, o := range f.Objects {
		id := o.id()
		switch o.Type {
		case "device":
			continue // the simulator has no Device object
		case "trend-log":
			s.Add(id, &sim.Object{})
			for _, r := range trendRecords() {
				s.LogAdd(id, r)
			}
			continue
		}
		obj := &sim.Object{}
		if v, ok := o.value(); ok {
			if o.Type == "analog-input" || o.Type == "binary-input" || o.Type == "multi-state-input" {
				obj.Pv = v
			} else {
				obj.Relinq = v
			}
			if o.Type == "analog-input" || o.Type == "analog-output" || o.Type == "analog-value" {
				obj.Units, obj.HasUnits = 95, true // no-units
				if alarmed == nil {
					alarmed = &id
				}
			}
		}
		s.Add(id, obj)
	}
	if envBool("CBSIGMA_EVENTS") && alarmed != nil {
		s.AlarmSum = alarmSummary(*alarmed)
		s.EventInfo = eventInformation(*alarmed)
	}

	if err := s.Start(); err != nil {
		return nil, fmt.Errorf("listen %s: %w", listen, err)
	}
	fmt.Fprintf(os.Stderr, "cbsigma sim role: bbmd=%v max APDU %d window %d drop %d stall %d\n",
		s.BBMD, s.MaxAPDU, s.Window, s.DropSeg, s.StallSeg)

	done := make(chan struct{})
	go reportSim(s, done)
	return func() { close(done); s.Stop() }, nil
}

// reportSim turns what the simulator recorded into operation lines.
func reportSim(s *sim.Device, done chan struct{}) {
	var nw, nm, nu, na, nr int
	tick := time.NewTicker(50 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case <-done:
			return
		case <-tick.C:
		}
		s.Mu.Lock()
		writes := append([]sim.Write(nil), s.Writes[nw:]...)
		mgmt := append([]bacnet.APDU(nil), s.Mgmt[nm:]...)
		unconf := append([]bacnet.APDU(nil), s.Unconf[nu:]...)
		acks := len(s.Acks) - na
		regs := append([]uint16(nil), s.Registrations[nr:]...)
		nw, nm, nu, na, nr = len(s.Writes), len(s.Mgmt), len(s.Unconf), len(s.Acks), len(s.Registrations)
		s.Mu.Unlock()
		for _, w := range writes {
			operation("write-property", map[string]any{
				"object": fmt.Sprintf("%d:%d", w.Object.Type, w.Object.Instance), "priority": w.Priority, "value": fmt.Sprint(w.Value),
			})
		}
		for _, a := range mgmt {
			if n, ok := mgmtNames[a.Service]; ok {
				operation(n, nil)
			}
		}
		for _, a := range unconf {
			if n, ok := unconfirmedNames[a.Service]; ok {
				operation(n, nil)
			}
		}
		for range acks {
			operation("acknowledge-alarm", nil)
		}
		for _, ttl := range regs {
			operation("register-foreign-device", map[string]any{"ttl": ttl})
		}
	}
}

// alarmSummary is a GetAlarmSummary-ACK body (clause 13.10): o in
// high-limit, the to-offnormal transition not acknowledged.
func alarmSummary(o bacnet.ObjectID) []byte {
	var e bacnet.Enc
	_ = e.App(o)
	_ = e.App(bacnet.Enumerated(3)) // high-limit
	_ = e.App(bacnet.BitString{Len: 3, Bits: []bool{false, true, true}})
	return e.B
}

// eventInformation is a GetEventInformation-ACK body (clause 13.12) with
// the same alarm: sequence-number time stamps, notify type alarm, every
// transition enabled, priorities 100.
func eventInformation(o bacnet.ObjectID) []byte {
	ctxBits := func(e *bacnet.Enc, num byte, b bacnet.BitString) {
		c := bacnet.BitContent(b)
		e.Header(num, true, len(c))
		e.B = append(e.B, c...)
	}
	var e bacnet.Enc
	e.Open(0)
	e.CtxObjectID(0, o)
	e.CtxUnsigned(1, 3) // event-state high-limit
	ctxBits(&e, 2, bacnet.BitString{Len: 3, Bits: []bool{false, true, true}})
	e.Open(3)
	for _, seq := range []uint64{1, 0, 0} {
		e.B = append(e.B, bacnet.SequenceStamp(seq)...)
	}
	e.Close(3)
	e.CtxUnsigned(4, 0) // notify-type alarm
	ctxBits(&e, 5, bacnet.AllTransitions())
	e.Open(6)
	for range 3 {
		_ = e.App(uint64(100))
	}
	e.Close(6)
	e.Close(0)
	e.CtxBool(1, false) // more-events
	return e.B
}
