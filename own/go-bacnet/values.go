// SPDX-License-Identifier: MIT

package main

import (
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"sort"

	"github.com/otfabric/go-bacnet"
)

// appValue turns a scenario value ({"type": …, "value": …}) into a go-bacnet
// application value.
func appValue(v any) (bacnet.ApplicationValue, error) {
	m, _ := v.(map[string]any)
	t, _ := m["type"].(string)
	x := m["value"]
	num := func() (float64, error) {
		f, ok := x.(float64)
		if !ok {
			return 0, fmt.Errorf("%s value %v is not a number", t, x)
		}
		return f, nil
	}
	switch t {
	case "null":
		return bacnet.NullValue(), nil
	case "boolean":
		b, ok := x.(bool)
		if !ok {
			return bacnet.ApplicationValue{}, fmt.Errorf("boolean value %v", x)
		}
		return bacnet.BoolValue(b), nil
	case "real":
		f, err := num()
		return bacnet.RealValue(float32(f)), err
	case "double":
		f, err := num()
		return bacnet.DoubleValue(f), err
	case "unsigned":
		f, err := num()
		if err == nil && (f < 0 || f != math.Trunc(f)) {
			err = fmt.Errorf("unsigned value %v", f)
		}
		return bacnet.UnsignedValue(uint64(f)), err
	case "signed":
		f, err := num()
		if err == nil && f != math.Trunc(f) {
			err = fmt.Errorf("signed value %v", f)
		}
		return bacnet.SignedValue(int64(f)), err
	case "enumerated":
		f, err := num()
		if err == nil && (f < 0 || f != math.Trunc(f)) {
			err = fmt.Errorf("enumerated value %v", f)
		}
		return bacnet.EnumValue(uint32(f)), err
	case "character-string":
		s, ok := x.(string)
		if !ok {
			return bacnet.ApplicationValue{}, fmt.Errorf("character-string value %v", x)
		}
		return bacnet.ApplicationValue{Kind: bacnet.ValueCharacterString, Character: bacnet.CharacterString{Value: s}}, nil
	case "object-identifier":
		id, err := objectRef(x)
		return bacnet.ObjectIDValue(id), err
	case "octet-string":
		s, _ := x.(string)
		b, err := hex.DecodeString(s)
		return bacnet.ApplicationValue{Kind: bacnet.ValueOctetString, OctetString: b}, err
	}
	return bacnet.ApplicationValue{}, fmt.Errorf("value type %q: not one this driver encodes", t)
}

// observedValue is a decoded value as the scenario files write values.
// Enumerated values are named where the property's datatype names them:
// Object_Type, and the Present_Value of a binary object.
func observedValue(v bacnet.ApplicationValue, obj bacnet.ObjectType, prop bacnet.PropertyIdentifier) map[string]any {
	switch v.Kind {
	case bacnet.ValueNull:
		return map[string]any{"type": "null"}
	case bacnet.ValueBoolean:
		return map[string]any{"type": "boolean", "value": v.Boolean}
	case bacnet.ValueUnsigned:
		return map[string]any{"type": "unsigned", "value": v.Unsigned}
	case bacnet.ValueSigned:
		return map[string]any{"type": "signed", "value": v.Signed}
	case bacnet.ValueReal:
		return map[string]any{"type": "real", "value": v.Real}
	case bacnet.ValueDouble:
		return map[string]any{"type": "double", "value": v.Double}
	case bacnet.ValueOctetString:
		return map[string]any{"type": "octet-string", "value": hex.EncodeToString(v.OctetString)}
	case bacnet.ValueCharacterString:
		s, err := v.Character.Text()
		if err != nil {
			s = v.Character.Value
		}
		return map[string]any{"type": "character-string", "value": s}
	case bacnet.ValueBitString:
		bits := []int{}
		n := len(v.BitString.Bytes)*8 - int(v.BitString.UnusedBits)
		for i := 0; i < n; i++ {
			if v.BitString.Bytes[i/8]&(0x80>>(i%8)) != 0 {
				bits = append(bits, 1)
			} else {
				bits = append(bits, 0)
			}
		}
		return map[string]any{"type": "bit-string", "value": bits}
	case bacnet.ValueEnumerated:
		return map[string]any{"type": "enumerated", "value": enumName(v.Enumerated, obj, prop)}
	case bacnet.ValueObjectID:
		return map[string]any{"type": "object-identifier", "value": objectText(v.ObjectID)}
	case bacnet.ValueDate:
		return map[string]any{"type": "date", "value": fmt.Sprintf("%+v", v.Date)}
	case bacnet.ValueTime:
		return map[string]any{"type": "time", "value": timeText(v.Time)}
	case bacnet.ValueConstructed:
		list := []any{}
		for _, el := range v.Elements {
			list = append(list, observedValue(el.Value, obj, prop))
		}
		return map[string]any{"type": "list", "value": list}
	}
	return map[string]any{"type": "unknown", "value": fmt.Sprint(v)}
}

func enumName(n uint32, obj bacnet.ObjectType, prop bacnet.PropertyIdentifier) any {
	switch {
	case prop == bacnet.PropertyObjectType:
		return bacnet.ObjectType(n).String()
	case prop == bacnet.PropertyPresentValue &&
		(obj == bacnet.ObjectTypeBinaryInput || obj == bacnet.ObjectTypeBinaryOutput || obj == bacnet.ObjectTypeBinaryValue):
		switch n {
		case 0:
			return "inactive"
		case 1:
			return "active"
		}
	case prop == bacnet.PropertyEventState:
		return eventStateName(n)
	}
	return n
}

func timeText(t bacnet.Time) string {
	return fmt.Sprintf("%d:%02d:%02d.%02d", t.Hour, t.Minute, t.Second, t.Hundredths)
}

// --- comparison, as in the other client drivers ------------------------------

// jsonOf round-trips v through JSON, so that observed values compare with
// what a scenario file holds (numbers as float64, slices as []any).
func jsonOf(v any) any {
	b, err := json.Marshal(v)
	if err != nil {
		return nil
	}
	var out any
	_ = json.Unmarshal(b, &out)
	return out
}

func compare(expect map[string]any, observed map[string]any) bool {
	for key, want := range expect {
		got, ok := observed[key]
		if !ok {
			return false
		}
		got = jsonOf(got)
		switch key {
		case "value":
			return sameValue(got, want)
		case "values":
			g, _ := got.([]any)
			w, _ := want.([]any)
			if len(g) != len(w) {
				return false
			}
			for i := range w {
				gi, _ := g[i].(map[string]any)
				wi, _ := w[i].(map[string]any)
				if gi["object"] != wi["object"] || fmt.Sprint(gi["property"]) != fmt.Sprint(wi["property"]) {
					return false
				}
				if we, ok := wi["error"].(map[string]any); ok {
					ge, _ := gi["error"].(map[string]any)
					if ge == nil || normName(ge["class"]) != normName(we["class"]) || normName(ge["code"]) != normName(we["code"]) {
						return false
					}
				} else if _, ok := gi["value"]; !ok || !sameValue(gi["value"], wi["value"]) {
					return false
				}
			}
			return true
		case "error":
			g, _ := got.(map[string]any)
			w, _ := want.(map[string]any)
			if g == nil || normName(g["class"]) != normName(w["class"]) || normName(g["code"]) != normName(w["code"]) {
				return false
			}
			if wf, ok := w["first_failed"].(map[string]any); ok {
				gf, _ := g["first_failed"].(map[string]any)
				if gf == nil || gf["object"] != wf["object"] || fmt.Sprint(gf["property"]) != fmt.Sprint(wf["property"]) {
					return false
				}
			}
			if wf, ok := w["first_failed_element"]; ok && fmt.Sprint(g["first_failed_element"]) != fmt.Sprint(wf) {
				return false
			}
			return true
		case "reject", "abort":
			return normName(got) == normName(want)
		case "records":
			g, _ := got.([]any)
			w, _ := want.([]any)
			if len(g) != len(w) {
				return false
			}
			for i := range w {
				gi, _ := g[i].(map[string]any)
				wi, _ := w[i].(map[string]any)
				if gi["timestamp"] != wi["timestamp"] || !sameValue(gi["value"], wi["value"]) {
					return false
				}
			}
			return true
		case "subscribed":
			g, _ := got.(map[string]any)
			w, _ := want.(map[string]any)
			return w["notification"] != true || g["notification"] == true
		case "i-am":
			return sortedJSON(got) == sortedJSON(want)
		case "i-have":
			return sortedJSON(got) == sortedJSON(want)
		case "recipients":
			return canonical(normDestinations(got)) == canonical(normDestinations(want))
		case "enrollments", "alarms", "events":
			g, _ := got.([]any)
			w, _ := want.([]any)
			if len(g) != len(w) {
				return false
			}
			for i := range w {
				gi, _ := g[i].(map[string]any)
				wi, _ := w[i].(map[string]any)
				for k, wv := range wi {
					if normName(gi[k]) != normName(wv) {
						return false
					}
				}
			}
			return true
		}
		return canonical(got) == canonical(want)
	}
	return false
}

func sameValue(got, want any) bool {
	g, _ := got.(map[string]any)
	w, _ := want.(map[string]any)
	if g == nil || w == nil || g["type"] != w["type"] {
		return false
	}
	if w["type"] == "real" || w["type"] == "double" {
		gf, ok1 := g["value"].(float64)
		wf, ok2 := w["value"].(float64)
		return ok1 && ok2 && math.Abs(gf-wf) <= 1e-6*math.Max(1, math.Abs(wf))
	}
	if w["type"] == "enumerated" {
		return normName(g["value"]) == normName(w["value"])
	}
	return canonical(g["value"]) == canonical(w["value"])
}

func canonical(v any) string {
	b, _ := json.Marshal(v)
	return string(b)
}

// sortedJSON is a list compared without its order.
func sortedJSON(v any) string {
	l, _ := v.([]any)
	s := make([]string, len(l))
	for i, x := range l {
		s[i] = canonical(x)
	}
	sort.Strings(s)
	return canonical(s)
}

func normTime(v any) any {
	s, ok := v.(string)
	if !ok {
		return v
	}
	var h int
	var rest string
	if n, _ := fmt.Sscanf(s, "%d:%s", &h, &rest); n == 2 {
		return fmt.Sprintf("%d:%s", h, rest)
	}
	return s
}

func normDestinations(v any) []any {
	l, _ := v.([]any)
	out := make([]any, 0, len(l))
	for _, x := range l {
		d, _ := x.(map[string]any)
		c := map[string]any{}
		for k, val := range d {
			c[k] = val
		}
		c["from_time"], c["to_time"] = normTime(d["from_time"]), normTime(d["to_time"])
		for _, k := range []string{"valid_days", "transitions"} {
			if s, ok := d[k].([]any); ok {
				ss := make([]string, len(s))
				for i, e := range s {
					ss[i] = canonical(e)
				}
				sort.Strings(ss)
				c[k] = ss
			}
		}
		out = append(out, c)
	}
	return out
}
