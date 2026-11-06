// SPDX-License-Identifier: MIT

package main

import (
	"encoding/json"
	"fmt"
	"os"
	"time"

	"github.com/cB-Sigma/bacnet"
)

// fixture is the part of a device fixture (fixtures/device/*.json) the
// adapter serves.
type fixture struct {
	Fixture        string          `json:"fixture"`
	DeviceInstance uint32          `json:"device_instance"`
	DeviceName     string          `json:"device_name"`
	Port           int             `json:"port"`
	Objects        []fixtureObject `json:"objects"`
}

type fixtureObject struct {
	Type         string `json:"type"`
	Instance     uint32 `json:"instance"`
	ObjectName   string `json:"object_name"`
	PresentValue any    `json:"present_value"`
	Description  string `json:"description"`
}

// objectTypes are the BACnetObjectType values (clause 21) of the types the
// fixtures use.
var objectTypes = map[string]uint16{
	"analog-input":       0,
	"analog-output":      1,
	"analog-value":       2,
	"binary-input":       3,
	"binary-output":      4,
	"binary-value":       5,
	"device":             8,
	"event-enrollment":   9,
	"file":               10,
	"multi-state-input":  13,
	"multi-state-output": 14,
	"notification-class": 15,
	"multi-state-value":  19,
	"trend-log":          20,
	"life-safety-point":  21,
	"life-safety-zone":   22,
	"audit-log":          61,
}

func loadFixture(path string) (*fixture, error) {
	b, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var f fixture
	if err := json.Unmarshal(b, &f); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	if f.Fixture == "" || f.DeviceInstance > 4194302 {
		return nil, fmt.Errorf("%s: no fixture id or a device instance out of range", path)
	}
	for _, o := range f.Objects {
		if _, ok := objectTypes[o.Type]; !ok {
			return nil, fmt.Errorf("%s: object type %q is not served", path, o.Type)
		}
	}
	return &f, nil
}

func (o fixtureObject) id() bacnet.ObjectID {
	return bacnet.ObjectID{Type: objectTypes[o.Type], Instance: o.Instance}
}

// value is the present value as the stacks encode it: REAL for an analog
// object, BACnetBinaryPV (enumerated) for a binary one, Unsigned for a
// multistate one.
func (o fixtureObject) value() (any, bool) {
	switch v := o.PresentValue.(type) {
	case float64:
		switch o.Type {
		case "multi-state-input", "multi-state-output", "multi-state-value":
			return uint64(v), true
		}
		return float32(v), true
	case string:
		switch v {
		case "inactive":
			return bacnet.Enumerated(0), true
		case "active":
			return bacnet.Enumerated(1), true
		}
	}
	return nil, false
}

// trendRecords is the Log_Buffer seed of every trend log, the one the
// BACnet4J and Worldiety adapters use: 36 records, record k (1-based) at
// 2024-01-01 00:00:00 UTC + (k-1) x 15 min with real value 20 + (k-1),
// no status flags.
func trendRecords() []bacnet.LogRecord {
	start := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	out := make([]bacnet.LogRecord, 36)
	for k := range out {
		out[k] = bacnet.LogRecord{At: start.Add(time.Duration(k) * 15 * time.Minute), Kind: "real", Value: float32(20 + k)}
	}
	return out
}
