// SPDX-License-Identifier: MIT

package main

import (
	"path/filepath"
	"testing"

	"github.com/cB-Sigma/bacnet"
)

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
		if _, err := loadFixture(p); err != nil {
			t.Errorf("%s: %v", p, err)
		}
	}
}

func TestPresentValue(t *testing.T) {
	cases := []struct {
		o    fixtureObject
		want any
	}{
		{fixtureObject{Type: "analog-value", PresentValue: 21.5}, float32(21.5)},
		{fixtureObject{Type: "binary-value", PresentValue: "inactive"}, bacnet.Enumerated(0)},
		{fixtureObject{Type: "binary-value", PresentValue: "active"}, bacnet.Enumerated(1)},
		{fixtureObject{Type: "multi-state-value", PresentValue: 2.0}, uint64(2)},
	}
	for _, c := range cases {
		got, ok := c.o.value()
		if !ok || got != c.want {
			t.Errorf("%s %v: got %v (%T), want %v (%T)", c.o.Type, c.o.PresentValue, got, got, c.want, c.want)
		}
	}
	if _, ok := (fixtureObject{Type: "trend-log"}).value(); ok {
		t.Error("an object without present_value has a value")
	}
}

// The canned answers decode with the upstream client's decoders.
func TestEventAnswersDecode(t *testing.T) {
	av := bacnet.ObjectID{Type: 2, Instance: 1}
	sum, err := bacnet.DecodeGetAlarmSummaryAck(alarmSummary(av))
	if err != nil || len(sum) != 1 || sum[0].Object != av || sum[0].State != 3 {
		t.Fatalf("GetAlarmSummary-ACK: %+v, %v", sum, err)
	}
	info, more, err := bacnet.DecodeGetEventInformationAck(eventInformation(av))
	if err != nil || more || len(info) != 1 || info[0].Object != av || info[0].State != 3 || len(info[0].Priorities) != 3 {
		t.Fatalf("GetEventInformation-ACK: %+v, %v, %v", info, more, err)
	}
}

func TestTrendRecords(t *testing.T) {
	r := trendRecords()
	if len(r) != 36 || r[0].Value != float32(20) || r[35].Value != float32(55) || r[35].At.Sub(r[0].At).Minutes() != 35*15 {
		t.Fatalf("seed: %d records, first %v, last %v", len(r), r[0], r[35])
	}
	for _, rec := range r {
		if _, err := bacnet.EncodeLogRecord(rec, nil); err != nil {
			t.Fatal(err)
		}
	}
}
