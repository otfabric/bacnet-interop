// SPDX-License-Identifier: MIT

package fixture

import (
	"fmt"

	"github.com/worldiety/bacnet/encoding"
)

// EncodeApp encodes an ApplicationValue to wire bytes.
func EncodeApp(v encoding.ApplicationValue) ([]byte, error) {
	if v == nil {
		return encoding.EncodeApplicationValue(encoding.AppNull{})
	}
	return encoding.EncodeApplicationValue(v)
}

// DecodeApp decodes one application value from payload at offset.
func DecodeApp(payload []byte, offset int) (encoding.ApplicationValue, int, error) {
	return encoding.DecodeApplicationValue(payload, offset)
}

// AsReal extracts a float32 present-value.
func AsReal(v encoding.ApplicationValue) (float32, error) {
	r, ok := v.(encoding.AppReal)
	if !ok {
		return 0, fmt.Errorf("want AppReal, got %T", v)
	}
	return float32(r), nil
}

// AsEnum extracts an enumerated value.
func AsEnum(v encoding.ApplicationValue) (uint32, error) {
	e, ok := v.(encoding.AppEnum)
	if !ok {
		return 0, fmt.Errorf("want AppEnum, got %T", v)
	}
	return uint32(e), nil
}
