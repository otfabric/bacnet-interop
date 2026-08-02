// SPDX-License-Identifier: MIT

package fixture

import (
	"encoding/json"
	"fmt"
	"os"
	"strings"

	"github.com/worldiety/bacnet/common/types"
	"github.com/worldiety/bacnet/encoding"
)

type fileModel struct {
	Fixture        string `json:"fixture"`
	DeviceInstance uint32 `json:"device_instance"`
	DeviceName     string `json:"device_name"`
	Port           int    `json:"port"`
	Objects        []struct {
		Type         string `json:"type"`
		Instance     uint32 `json:"instance"`
		ObjectName   string `json:"object_name"`
		PresentValue any    `json:"present_value"`
		Description  string `json:"description"`
	} `json:"objects"`
}

// LoadFile reads a device-baseline fixture JSON into a Store.
func LoadFile(path string) (*Store, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var fm fileModel
	if err := json.Unmarshal(raw, &fm); err != nil {
		return nil, fmt.Errorf("decode fixture: %w", err)
	}
	if fm.DeviceInstance == 0 && fm.DeviceName == "" {
		return nil, fmt.Errorf("fixture missing device_instance/device_name")
	}
	store := NewStore()
	store.FixtureID = fm.Fixture
	store.DeviceInstance = fm.DeviceInstance
	store.DeviceName = fm.DeviceName
	store.Port = fm.Port
	if store.Port == 0 {
		store.Port = 47808
	}

	for _, o := range fm.Objects {
		ot, err := parseObjectType(o.Type)
		if err != nil {
			return nil, err
		}
		obj := &Object{
			Key:         ObjectKey{Type: ot, Instance: o.Instance},
			ObjectName:  o.ObjectName,
			Description: o.Description,
		}
		switch ot {
		case types.ObjectTypeAnalogValue, types.ObjectTypeAnalogInput, types.ObjectTypeAnalogOutput:
			pv, err := parseAnalogPV(o.PresentValue)
			if err != nil {
				return nil, fmt.Errorf("%s: %w", obj.Key, err)
			}
			obj.SetPresentValue(pv)
		case types.ObjectTypeBinaryValue, types.ObjectTypeBinaryInput, types.ObjectTypeBinaryOutput:
			pv, err := parseBinaryPV(o.PresentValue)
			if err != nil {
				return nil, fmt.Errorf("%s: %w", obj.Key, err)
			}
			obj.SetPresentValue(pv)
		case ObjectTypeTrendLog:
			obj.SetLogRecords(seedTrendLogRecords())
		}
		store.Add(obj)
	}

	// Ensure a device object exists even if omitted from objects[].
	if _, ok := store.Get(store.DeviceKey()); !ok {
		store.Add(&Object{
			Key:        store.DeviceKey(),
			ObjectName: store.DeviceName,
		})
	}
	return store, nil
}

func parseObjectType(s string) (types.ObjectType, error) {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "device":
		return types.ObjectTypeDevice, nil
	case "analog-value":
		return types.ObjectTypeAnalogValue, nil
	case "analog-input":
		return types.ObjectTypeAnalogInput, nil
	case "analog-output":
		return types.ObjectTypeAnalogOutput, nil
	case "binary-value":
		return types.ObjectTypeBinaryValue, nil
	case "binary-input":
		return types.ObjectTypeBinaryInput, nil
	case "binary-output":
		return types.ObjectTypeBinaryOutput, nil
	case "trend-log":
		return ObjectTypeTrendLog, nil
	case "notification-class":
		return types.ObjectTypeNotificationClass, nil
	case "event-enrollment":
		// Worldiety has no native EventEnrollment object; keep as NotificationClass-typed
		// placeholder so device-baseline-v3 loads. Event semantics remain adapter-shim.
		return types.ObjectTypeNotificationClass, nil
	case "file", "audit-log", "life-safety-point", "life-safety-zone":
		return 0, fmt.Errorf("unsupported object type %q (fixture generation not served by Worldiety yet)", s)
	default:
		return 0, fmt.Errorf("unsupported object type %q", s)
	}
}

func parseAnalogPV(v any) (encoding.ApplicationValue, error) {
	switch x := v.(type) {
	case float64:
		return encoding.AppReal(float32(x)), nil
	case json.Number:
		f, err := x.Float64()
		if err != nil {
			return nil, err
		}
		return encoding.AppReal(float32(f)), nil
	case nil:
		return encoding.AppReal(0), nil
	default:
		return nil, fmt.Errorf("analog present_value type %T", v)
	}
}

func parseBinaryPV(v any) (encoding.ApplicationValue, error) {
	switch x := v.(type) {
	case string:
		switch strings.ToLower(x) {
		case "inactive", "0", "false":
			return encoding.AppEnum(0), nil
		case "active", "1", "true":
			return encoding.AppEnum(1), nil
		default:
			return nil, fmt.Errorf("binary present_value %q", x)
		}
	case bool:
		if x {
			return encoding.AppEnum(1), nil
		}
		return encoding.AppEnum(0), nil
	case float64:
		if x == 0 {
			return encoding.AppEnum(0), nil
		}
		return encoding.AppEnum(1), nil
	case nil:
		return encoding.AppEnum(0), nil
	default:
		return nil, fmt.Errorf("binary present_value type %T", v)
	}
}

// seedTrendLogRecords builds four deterministic BACnetLogRecord payloads
// (timestamp + real logDatum) matching the BACnet4J seeded buffer style.
func seedTrendLogRecords() [][]byte {
	out := make([][]byte, 0, 4)
	for i := 0; i < 4; i++ {
		out = append(out, encodeLogRecordReal(
			2024, 1, 1, // date
			12, byte(i), 0, 0, // time
			float32(20+i),
		))
	}
	return out
}

func encodeLogRecordReal(year uint16, month, day, hour, minute, second, hundredths uint8, value float32) []byte {
	// timestamp [0] BACnetDateTime = constructed context with Date + Time application tags
	dateBytes, err := encoding.EncodeDateValue(encoding.BACnetDate{
		Year: year, Month: month, Day: day, Weekday: encoding.BACnetDateUnspecified,
	})
	if err != nil {
		y := byte(255)
		if year >= 1900 {
			y = byte(year - 1900)
		}
		dateBytes = []byte{y, month, day, 255}
	}
	timeBytes := encoding.EncodeTimeValue(encoding.BACnetTime{
		Hour: hour, Minute: minute, Second: second, Hundredths: hundredths,
	})
	var out []byte
	out = append(out, encoding.EncodeOpeningTag(0)...)
	out = append(out, encoding.EncodeApplicationPrimitive(uint8(encoding.AppTagDate), dateBytes)...)
	out = append(out, encoding.EncodeApplicationPrimitive(uint8(encoding.AppTagTime), timeBytes)...)
	out = append(out, encoding.EncodeClosingTag(0)...)
	// logDatum [1] CHOICE real [2] (constructed)
	out = append(out, encoding.EncodeOpeningTag(1)...)
	out = append(out, encoding.EncodeContextPrimitive(2, encoding.EncodeReal(value))...)
	out = append(out, encoding.EncodeClosingTag(1)...)
	return out
}
