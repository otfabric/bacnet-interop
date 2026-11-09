// SPDX-License-Identifier: MIT

package main

import (
	"encoding/base64"
	"encoding/json"
	"fmt"
	"os"
	"time"

	"github.com/otfabric/go-bacnet"
	"github.com/otfabric/go-bacnet/server/object"
)

// supportedFixtures are the device fixtures whose object types the
// go-bacnet server has. device-baseline-v3 (Event Enrollment), -v7 (Audit
// Log) and -v8 (Life Safety Point and Zone) name object types it does not
// implement; loading one fails at start instead of serving part of it.
var supportedFixtures = []string{
	"device-baseline-v1", "device-baseline-v2", "device-baseline-v4", "device-baseline-v5",
	"device-baseline-v6", "device-baseline-v9", "device-server-v1",
}

// fixture is a bacnet-interop device fixture (fixtures/device/*.json) with
// the fields the object model needs.
type fixture struct {
	Fixture        string          `json:"fixture"`
	DeviceInstance uint32          `json:"device_instance"`
	DeviceName     string          `json:"device_name"`
	Objects        []fixtureObject `json:"objects"`
	Lifecycle      *struct {
		CreatableTypes      []string `json:"creatable_types"`
		PrecreatedDeletable []struct {
			Type     string `json:"type"`
			Instance uint32 `json:"instance"`
		} `json:"precreated_deletable"`
	} `json:"object_lifecycle"`
}

type fixtureObject struct {
	Type             string   `json:"type"`
	Instance         uint32   `json:"instance"`
	ObjectName       string   `json:"object_name"`
	Description      string   `json:"description"`
	PresentValue     any      `json:"present_value"`
	Commandable      *bool    `json:"commandable"`
	AccessMethod     string   `json:"access_method"`
	StreamDataBase64 string   `json:"stream_data_base64"`
	Records          []string `json:"records"`
	LogBuffer        []struct {
		Timestamp string  `json:"timestamp"`
		Real      float32 `json:"real"`
	} `json:"log_buffer"`
	IntrinsicReporting *struct {
		NotificationClass uint32  `json:"notification_class"`
		HighLimit         float32 `json:"high_limit"`
		LowLimit          float32 `json:"low_limit"`
		Deadband          float32 `json:"deadband"`
		TimeDelay         uint32  `json:"time_delay"`
	} `json:"intrinsic_reporting"`
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
	if f.Fixture == "" || f.DeviceName == "" {
		return nil, fmt.Errorf("%s: no fixture id or device name", path)
	}
	return &f, nil
}

// usesCommandable reports whether any object of the fixture states
// "commandable". The fixtures that predate the field (device-baseline-v1 to
// -v9) are served with commandable Analog Values, because the scenarios of
// server-baseline-v1 write and relinquish AV-1 at priority 8 on
// device-baseline-v2.
func (f *fixture) usesCommandable() bool {
	for _, o := range f.Objects {
		if o.Commandable != nil {
			return true
		}
	}
	return false
}

// buildDevice builds the fixture's object model with go-bacnet's
// server/object constructors.
func buildDevice(f *fixture) (*object.Device, error) {
	d, err := object.NewDevice(object.DeviceConfig{
		Instance:                   f.DeviceInstance,
		Name:                       f.DeviceName,
		VendorID:                   999,
		VendorName:                 "OT Fabric",
		ModelName:                  "go-bacnet server (bacnet-interop otfabric)",
		FirmwareRevision:           upstreamVersion,
		ApplicationSoftwareVersion: adapterVersion,
		Description:                "go-bacnet serving " + f.Fixture,
	})
	if err != nil {
		return nil, err
	}
	deletable := map[bacnet.ObjectIdentifier]bool{}
	if lc := f.Lifecycle; lc != nil {
		for _, p := range lc.PrecreatedDeletable {
			t, ok := objectTypeByName(p.Type)
			if !ok {
				return nil, fmt.Errorf("precreated_deletable: object type %q", p.Type)
			}
			deletable[bacnet.ObjectIdentifier{Type: t, Instance: p.Instance}] = true
		}
	}
	defaultCommandable := !f.usesCommandable()
	for _, o := range f.Objects {
		if o.Type == "device" {
			continue
		}
		obj, err := buildObject(o, defaultCommandable)
		if err != nil {
			return nil, fmt.Errorf("%s %d: %w", o.Type, o.Instance, err)
		}
		if p, ok := obj.(*object.Point); ok && deletable[obj.Identifier()] {
			p.SetDeletable(true)
		}
		if err := d.Add(obj); err != nil {
			return nil, fmt.Errorf("%s %d: %w", o.Type, o.Instance, err)
		}
	}
	if lc := f.Lifecycle; lc != nil {
		for _, name := range lc.CreatableTypes {
			if err := registerFactory(d, name); err != nil {
				return nil, err
			}
		}
	}
	return d, nil
}

func buildObject(o fixtureObject, defaultCommandable bool) (object.Object, error) {
	commandable := defaultCommandable
	if o.Commandable != nil {
		commandable = *o.Commandable
	}
	switch o.Type {
	case "analog-value":
		v, _ := o.PresentValue.(float64)
		cfg := object.PointConfig{Instance: o.Instance, Name: o.ObjectName, Description: o.Description,
			Units: 95, Value: float32(v), Commandable: commandable}
		if ir := o.IntrinsicReporting; ir != nil {
			cfg.Events = &object.EventConfig{
				NotificationClass: ir.NotificationClass,
				EventEnable:       object.EnableToOffNormal | object.EnableToFault | object.EnableToNormal,
				NotifyType:        object.NotifyAlarm,
				TimeDelay:         ir.TimeDelay,
				HighLimit:         ir.HighLimit,
				LowLimit:          ir.LowLimit,
				Deadband:          ir.Deadband,
				LimitEnable:       object.LimitEnableHigh | object.LimitEnableLow,
			}
		}
		return object.NewAnalogValue(cfg)
	case "binary-value":
		return object.NewBinaryValue(object.PointConfig{Instance: o.Instance, Name: o.ObjectName,
			Description: o.Description, Active: o.PresentValue == "active"})
	case "trend-log":
		tl, err := object.NewTrendLog(object.TrendLogConfig{Instance: o.Instance, Name: o.ObjectName,
			Description: o.Description, Enable: len(o.LogBuffer) > 0})
		if err != nil {
			return nil, err
		}
		for _, r := range o.LogBuffer {
			at, err := time.ParseInLocation("2006-01-02T15:04:05", r.Timestamp, time.Local)
			if err != nil {
				return nil, fmt.Errorf("log_buffer: %w", err)
			}
			if err := tl.Log(at, bacnet.RealValue(r.Real), nil); err != nil {
				return nil, fmt.Errorf("log_buffer: %w", err)
			}
		}
		return tl, nil
	case "notification-class":
		return object.NewNotificationClass(object.NotificationClassConfig{Instance: o.Instance,
			Name: o.ObjectName, Description: o.Description})
	case "file":
		cfg := object.FileConfig{Instance: o.Instance, Name: o.ObjectName, Description: o.Description,
			Record: o.AccessMethod == "record"}
		if cfg.Record {
			for _, r := range o.Records {
				cfg.Records = append(cfg.Records, []byte(r))
			}
		} else {
			data, err := base64.StdEncoding.DecodeString(o.StreamDataBase64)
			if err != nil {
				return nil, fmt.Errorf("stream_data_base64: %w", err)
			}
			cfg.Data = data
		}
		return object.NewFile(cfg)
	}
	return nil, fmt.Errorf("object type %q: go-bacnet's server/object has no constructor for it", o.Type)
}

// registerFactory lets CreateObject make objects of a fixture's creatable
// type; the created objects are deletable.
func registerFactory(d *object.Device, name string) error {
	switch name {
	case "analog-value":
		d.RegisterFactory(bacnet.ObjectTypeAnalogValue, func(instance uint32, objName string) (object.Object, error) {
			av, err := object.NewAnalogValue(object.PointConfig{Instance: instance, Name: objName, Units: 95})
			if err == nil {
				av.SetDeletable(true)
			}
			return av, err
		})
	case "binary-value":
		d.RegisterFactory(bacnet.ObjectTypeBinaryValue, func(instance uint32, objName string) (object.Object, error) {
			bv, err := object.NewBinaryValue(object.PointConfig{Instance: instance, Name: objName})
			if err == nil {
				bv.SetDeletable(true)
			}
			return bv, err
		})
	default:
		return fmt.Errorf("creatable type %q: no factory in this adapter", name)
	}
	return nil
}
