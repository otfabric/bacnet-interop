// SPDX-License-Identifier: MIT

package main

import (
	"fmt"
	"os"

	"github.com/cB-Sigma/bacnet"
	"github.com/cB-Sigma/bacnet/device"
)

// Property identifiers (clause 21) the adapter sets beyond the ones the
// device package names.
const (
	propEventState   = 36
	propOutOfService = 81
	propUnits        = 117
	propRecordCount  = 141
	propTotalRecords = 145
	propLogEnable    = 133
	propBufferSize   = 126
)

// serveDevice serves the fixture with github.com/cB-Sigma/bacnet/device.
// The package answers ReadProperty, ReadPropertyMultiple (ALL, REQUIRED,
// OPTIONAL, array indexes), WriteProperty, WritePropertyMultiple,
// SubscribeCOV, Who-Is and Who-Has, and segments; everything else is
// rejected (unrecognized-service) by the package.
func serveDevice(f *fixture, listen string) (func(), error) {
	maxAPDU, err := envInt("CBSIGMA_MAX_APDU", 1476)
	if err != nil {
		return nil, err
	}
	window, err := envInt("CBSIGMA_WINDOW", 4)
	if err != nil {
		return nil, err
	}
	name := f.DeviceName
	for _, o := range f.Objects {
		if o.Type == "device" && o.ObjectName != "" {
			name = o.ObjectName
		}
	}
	d := device.New(device.Config{
		Instance:   f.DeviceInstance,
		Name:       name,
		VendorID:   999, // the cB-Sigma default; no vendor identifier is registered for it
		VendorName: "cB-Sigma",
		ModelName:  "bacnet-interop cbsigma",
		Firmware:   bacnetVersion,
		Software:   adapterVersion,
		MaxAPDU:    maxAPDU,
		Window:     byte(window),
		OnWrite: func(o bacnet.ObjectID, prop uint32, index int, value any, priority int) error {
			operation("write-property", map[string]any{
				"object": fmt.Sprintf("%d:%d", o.Type, o.Instance), "property": prop, "priority": priority, "value": fmt.Sprint(value),
			})
			return nil
		},
	})
	for _, o := range f.Objects {
		if o.Type == "device" {
			continue
		}
		obj := &device.Object{ID: o.id(), Name: o.ObjectName, Props: map[uint32]any{
			propEventState: bacnet.Enumerated(0), propOutOfService: false, device.PropDescription: "",
		}, Writable: map[uint32]bool{device.PropDescription: true}}
		if o.Description != "" {
			obj.Props[device.PropDescription] = o.Description
		}
		if v, ok := o.value(); ok {
			obj.Props[bacnet.PropPresentValue] = v
			switch o.Type {
			case "analog-value", "analog-output", "binary-value", "binary-output", "multi-state-value", "multi-state-output":
				obj.Commandable = true
			}
			switch o.Type {
			case "analog-input", "analog-output", "analog-value":
				obj.Props[propUnits] = bacnet.Enumerated(95) // no-units
			}
		}
		if o.Type == "trend-log" {
			// The device package has no ReadRange: the trend log is
			// listed with its counters only.
			n := uint64(len(trendRecords()))
			obj.Props[propLogEnable] = true
			obj.Props[propRecordCount] = n
			obj.Props[propTotalRecords] = n
			obj.Props[propBufferSize] = n
		}
		d.AddObject(obj)
	}
	if _, err := d.Listen(listen); err != nil {
		return nil, fmt.Errorf("listen %s: %w", listen, err)
	}
	fmt.Fprintf(os.Stderr, "cbsigma device role: max APDU %d, window %d\n", maxAPDU, window)
	return d.Close, nil
}
