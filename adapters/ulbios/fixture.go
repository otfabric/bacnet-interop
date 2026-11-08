// SPDX-License-Identifier: MIT

package main

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"

	"github.com/ulbios/bacnet/objects"
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
}

// objectTypes are the BACnetObjectType values (clause 21) of the types the
// fixtures use, and the names the scenario files use.
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

func objectTypeName(t uint16) string {
	for name, v := range objectTypes {
		if v == t {
			return name
		}
	}
	return fmt.Sprintf("%d", t)
}

// Property identifiers (clause 21) the adapter serves. ulbios encodes and
// decodes a property identifier in one octet only (objects.EncPropertyIdentifier
// and DecPropertyIdentifier take a uint8), so every identifier here is below 256.
const (
	propEventState            uint8  = 36
	propMaxAPDULengthAccepted uint8  = 62
	propObjectIdentifier      uint8  = 75
	propObjectList            uint8  = 76
	propObjectName            uint8  = 77
	propObjectType            uint8  = 79
	propPresentValue          uint8  = 85
	propPriorityArray         uint8  = 87
	propProtocolVersion       uint8  = 98
	propRelinquishDefault     uint8  = 104
	propSegmentationSupported uint8  = 107
	propSystemStatus          uint8  = 112
	propUnits                 uint8  = 117
	propVendorIdentifier      uint8  = 120
	maxAPDULengthAccepted            = 1024 // bacnet.DEFAULT_ACCEPTED_SIZE
	segmentationNone                 = 3    // bacnet.DEFAULT_SEGMENTATION_SUPPORT
	vendorID                  uint16 = 999
)

// value is a present value in one of the encodings ulbios has an encoder
// for: REAL (objects.EncReal), Enumerated (objects.EncEnumerated, one
// octet) and Unsigned (objects.EncUnsignedInteger16, always two octets).
type value struct {
	kind byte // 'r' real, 'e' enumerated, 'u' unsigned
	real float32
	enum uint8
	u    uint16
}

func (v value) payload() objects.APDUPayload {
	switch v.kind {
	case 'r':
		return objects.EncReal(v.real)
	case 'e':
		return objects.EncEnumerated(v.enum)
	default:
		return objects.EncUnsignedInteger16(v.u)
	}
}

// object is one object of the served model. Only properties ulbios can
// encode exist; reading any other property is Error property/unknown-property.
type object struct {
	typ         uint16
	inst        uint32
	commandable bool
	relinquish  value
	slots       [16]*value
}

func (o *object) presentValue() value {
	for _, s := range o.slots {
		if s != nil {
			return *s
		}
	}
	return o.relinquish
}

type model struct {
	fx      *fixture
	objects []*object
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

func newModel(f *fixture) *model {
	m := &model{fx: f}
	for _, fo := range f.Objects {
		o := &object{typ: objectTypes[fo.Type], inst: fo.Instance}
		switch v := fo.PresentValue.(type) {
		case float64:
			switch fo.Type {
			case "multi-state-input", "multi-state-output", "multi-state-value":
				o.relinquish = value{kind: 'u', u: uint16(v)}
			default:
				o.relinquish = value{kind: 'r', real: float32(v)}
			}
			o.commandable = fo.Type == "analog-value"
		case string:
			o.relinquish = value{kind: 'e'}
			if v == "active" {
				o.relinquish.enum = 1
			}
			o.commandable = fo.Type == "binary-value"
		}
		m.objects = append(m.objects, o)
	}
	sort.SliceStable(m.objects, func(i, j int) bool { return m.objects[i].typ == 8 && m.objects[j].typ != 8 })
	return m
}

func (m *model) find(typ uint16, inst uint32) *object {
	for _, o := range m.objects {
		if o.typ == typ && o.inst == inst {
			return o
		}
	}
	return nil
}

// read returns the property value as ulbios tokens, or false when the
// object does not have the property.
func (m *model) read(o *object, prop uint8) ([]objects.APDUPayload, bool) {
	switch prop {
	case propObjectIdentifier:
		return []objects.APDUPayload{objects.EncObjectIdentifier(false, objects.TagBACnetObjectIdentifier, o.typ, o.inst)}, true
	case propObjectType:
		if o.typ > 255 {
			return nil, false
		}
		return []objects.APDUPayload{objects.EncEnumerated(uint8(o.typ))}, true
	}
	if o.typ == 8 {
		switch prop {
		case propObjectList:
			var out []objects.APDUPayload
			for _, x := range m.objects {
				out = append(out, objects.EncObjectIdentifier(false, objects.TagBACnetObjectIdentifier, x.typ, x.inst))
			}
			return out, true
		case propVendorIdentifier:
			return []objects.APDUPayload{objects.EncUnsignedInteger16(vendorID)}, true
		case propMaxAPDULengthAccepted:
			return []objects.APDUPayload{objects.EncUnsignedInteger16(maxAPDULengthAccepted)}, true
		case propSegmentationSupported:
			return []objects.APDUPayload{objects.EncEnumerated(segmentationNone)}, true
		case propProtocolVersion:
			return []objects.APDUPayload{objects.EncUnsignedInteger16(1)}, true
		case propSystemStatus:
			return []objects.APDUPayload{objects.EncEnumerated(0)}, true // operational
		}
		return nil, false
	}
	if o.relinquish.kind == 0 {
		return nil, false
	}
	switch prop {
	case propPresentValue:
		return []objects.APDUPayload{o.presentValue().payload()}, true
	case propEventState:
		return []objects.APDUPayload{objects.EncEnumerated(0)}, true // normal
	case propUnits:
		if o.relinquish.kind != 'r' {
			return nil, false
		}
		return []objects.APDUPayload{objects.EncEnumerated(95)}, true // no-units
	}
	if !o.commandable {
		return nil, false
	}
	switch prop {
	case propRelinquishDefault:
		return []objects.APDUPayload{o.relinquish.payload()}, true
	case propPriorityArray:
		out := make([]objects.APDUPayload, 0, 16)
		for _, s := range o.slots {
			if s == nil {
				out = append(out, objects.EncNull())
			} else {
				out = append(out, s.payload())
			}
		}
		return out, true
	}
	return nil, false
}
