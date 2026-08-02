// SPDX-License-Identifier: MIT

package service

import (
	"encoding/binary"
	"fmt"

	"github.com/worldiety/bacnet/common/types"
	"github.com/worldiety/bacnet/encoding"
)

func decodeContextObjectID(payload []byte, offset int, tag uint8) (types.ObjectIdentifier, int, error) {
	_, value, next, err := encoding.DecodeExpectedContextPrimitive(payload, offset, encoding.AppTag(tag))
	if err != nil {
		return 0, offset, err
	}
	if len(value) != 4 {
		return 0, offset, fmt.Errorf("object-id length %d", len(value))
	}
	raw := binary.BigEndian.Uint32(value)
	return types.ObjectIdentifier(raw), next, nil
}

func decodeContextUnsigned(payload []byte, offset int, tag uint8) (uint32, int, error) {
	_, value, next, err := encoding.DecodeExpectedContextPrimitive(payload, offset, encoding.AppTag(tag))
	if err != nil {
		return 0, offset, err
	}
	var n uint32
	for _, b := range value {
		n = (n << 8) | uint32(b)
	}
	return n, next, nil
}

func peekTag(payload []byte, offset int) (encoding.Tag, int, int, error) {
	if offset >= len(payload) {
		return encoding.Tag{}, 0, 0, fmt.Errorf("eof")
	}
	tag, hdr, vlen, err := encoding.ParseTag(payload[offset:])
	return tag, hdr, vlen, err
}

func encodeContextObjectID(tag uint8, id types.ObjectIdentifier) []byte {
	return encoding.EncodeContextPrimitive(tag, encoding.EncodeObjectIdentifierValue(id))
}

func encodeContextUnsigned(tag uint8, v uint32) []byte {
	return encoding.EncodeContextPrimitive(tag, encoding.EncodeUnsigned(v))
}

func encodeContextEnum(tag uint8, v uint32) []byte {
	return encoding.EncodeContextPrimitive(tag, encoding.EncodeEnumeratedValue(v))
}

func encodeOpening(tag uint8) []byte { return encoding.EncodeOpeningTag(tag) }
func encodeClosing(tag uint8) []byte { return encoding.EncodeClosingTag(tag) }

func skipToClosing(payload []byte, offset int, tagNumber uint8) (int, error) {
	depth := 1
	for offset < len(payload) {
		tag, hdr, vlen, err := encoding.ParseTag(payload[offset:])
		if err != nil {
			return offset, err
		}
		next := offset + hdr
		if tag.Opening {
			if tag.TagNumber == encoding.AppTag(tagNumber) {
				depth++
			}
			offset = next
			continue
		}
		if tag.Closing {
			if tag.TagNumber == encoding.AppTag(tagNumber) {
				depth--
				if depth == 0 {
					return next, nil
				}
			}
			offset = next
			continue
		}
		offset = next + vlen
	}
	return offset, fmt.Errorf("missing closing tag %d", tagNumber)
}
