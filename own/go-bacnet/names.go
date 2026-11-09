// SPDX-License-Identifier: MIT

package main

import (
	"fmt"
	"strconv"
	"strings"
	"unicode"

	"github.com/otfabric/go-bacnet"
)

// Names as the scenario files write them. Object types and properties are
// go-bacnet's own names (ObjectType.String, PropertyIdentifier.String),
// error classes, codes and reject and abort reasons those of
// bacnet.ErrorClassName and friends. The enumerations go-bacnet does not
// name are spelled out here from clause 21 (ASHRAE 135-2024).

var (
	objectTypesByName = map[string]bacnet.ObjectType{}
	propertiesByName  = map[string]bacnet.PropertyIdentifier{}
)

func init() {
	for t := 0; t < 1024; t++ {
		ot := bacnet.ObjectType(t)
		if s := ot.String(); !strings.HasPrefix(s, "ObjectType(") {
			objectTypesByName[s] = ot
		}
	}
	for p := 0; p < 4500; p++ {
		pid := bacnet.PropertyIdentifier(p)
		if s := pid.String(); !strings.HasPrefix(s, "PropertyIdentifier(") {
			propertiesByName[s] = pid
		}
	}
}

func objectTypeByName(s string) (bacnet.ObjectType, bool) {
	t, ok := objectTypesByName[s]
	return t, ok
}

// objectRef parses "type,instance".
func objectRef(v any) (bacnet.ObjectIdentifier, error) {
	s, _ := v.(string)
	name, inst, ok := strings.Cut(s, ",")
	t, known := objectTypesByName[name]
	n, err := strconv.ParseUint(inst, 10, 22)
	if !ok || !known || err != nil {
		return bacnet.ObjectIdentifier{}, fmt.Errorf("object %q: not type,instance with a type go-bacnet names", s)
	}
	return bacnet.ObjectIdentifier{Type: t, Instance: uint32(n)}, nil
}

func objectText(id bacnet.ObjectIdentifier) string {
	return fmt.Sprintf("%s,%d", id.Type, id.Instance)
}

// propertyRef parses a property name or number.
func propertyRef(v any) (bacnet.PropertyIdentifier, error) {
	switch p := v.(type) {
	case string:
		if id, ok := propertiesByName[p]; ok {
			return id, nil
		}
		return 0, fmt.Errorf("property %q: not a name go-bacnet has", p)
	case float64:
		if p < 0 || p > 4194303 || p != float64(uint32(p)) {
			return 0, fmt.Errorf("property %v: not a property identifier", p)
		}
		return bacnet.PropertyIdentifier(uint32(p)), nil
	}
	return 0, fmt.Errorf("property %v: neither a name nor a number", v)
}

// propertyText is the property as a scenario writes it: its name, or its
// number when go-bacnet does not name it.
func propertyText(p bacnet.PropertyIdentifier) any {
	s := p.String()
	if strings.HasPrefix(s, "PropertyIdentifier(") {
		return int(p)
	}
	return s
}

// normName compares names the way every client driver does: case and
// punctuation do not count.
func normName(v any) string {
	var b strings.Builder
	for _, r := range strings.ToLower(fmt.Sprint(v)) {
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			b.WriteRune(r)
		}
	}
	return b.String()
}

// BACnetEventState (clause 21).
var eventStates = []string{"normal", "fault", "offnormal", "high-limit", "low-limit", "life-safety-alarm"}

func eventStateName(n uint32) any {
	if int(n) < len(eventStates) {
		return eventStates[n]
	}
	return n
}

func eventStateByName(s string) (uint32, bool) {
	for i, n := range eventStates {
		if normName(n) == normName(s) {
			return uint32(i), true
		}
	}
	return 0, false
}

// BACnetEventType 0..5 (clause 21); the others are written as numbers.
var eventTypes = []string{
	"change-of-bitstring", "change-of-state", "change-of-value", "command-failure", "floating-limit", "out-of-range",
}

func eventTypeName(n uint32) any {
	if int(n) < len(eventTypes) {
		return eventTypes[n]
	}
	return n
}

// The eventStateFilter of GetEnrollmentSummary (clause 13.11.1.1.3).
var enrollmentStateFilters = map[string]uint32{"offnormal": 0, "fault": 1, "normal": 2, "all": 3, "active": 4}

// BVLC-Result codes as the scenario files name them (Annex J.2.1.1).
var bvlcResults = map[uint16]string{
	0x0000: "successful-completion",
	0x0010: "write-bdt-nak",
	0x0020: "read-bdt-nak",
	0x0030: "register-fd-nak",
	0x0040: "read-fdt-nak",
	0x0050: "delete-fdt-nak",
	0x0060: "distribute-broadcast-nak",
}

func bvlcResultName(code uint16) string {
	if s, ok := bvlcResults[code]; ok {
		return s
	}
	return fmt.Sprintf("0x%04x", code)
}

// The transitions of a BACnetDestination, bit 0 first (clause 21).
var transitionNames = []string{"to-offnormal", "to-fault", "to-normal"}
