// SPDX-License-Identifier: MIT

package service

import (
	"context"

	"github.com/otfabric/bacnet-interop/adapters/worldiety/internal/fixture"
	"github.com/worldiety/bacnet/apdu"
	"github.com/worldiety/bacnet/common/types"
	"github.com/worldiety/bacnet/encoding"
)

func (s *Server) handleWritePropertyMultiple(_ context.Context, ind apdu.ConfirmedIndicationICI) (apdu.ConfirmedResponseICI, error) {
	writes, err := decodeWPM(ind.ServiceRequest.Payload)
	if err != nil {
		return errorResponse(ind, ErrorClassServices, ErrorCodeInconsistentParameters), nil
	}
	for _, w := range writes {
		if class, code, err := writePropertyValue(s.Store, w.Key, w.Prop, w.Value); err != nil {
			payload := encodeWPMError(w.Key, w.Prop, class, code)
			return apdu.ConfirmedResponseICI{
				Destination:           ind.Source,
				InvokeID:              ind.InvokeID,
				SegmentationSupported: apdu.SegmentationSupportBoth,
				ResponseType:          apdu.ConfirmedResponseTypeError,
				ServiceResponse:       apdu.ServiceResult{Payload: payload},
			}, nil
		}
	}
	return ackResponse(ind, nil), nil
}

type wpmWrite struct {
	Key   fixture.ObjectKey
	Prop  propertyRef
	Value encoding.ApplicationValue
}

func decodeWPM(payload []byte) ([]wpmWrite, error) {
	var out []wpmWrite
	offset := 0
	for offset < len(payload) {
		id, next, err := decodeContextObjectID(payload, offset, 0)
		if err != nil {
			return nil, err
		}
		offset = next
		tag, hdr, _, err := peekTag(payload, offset)
		if err != nil {
			return nil, err
		}
		if !tag.Opening || tag.TagNumber != 1 {
			return nil, errBadTag("listOfProperties opening")
		}
		offset += hdr
		key := fixture.ObjectKey{Type: id.ObjectType(), Instance: id.Instance()}
		for {
			if offset >= len(payload) {
				return nil, errBadTag("truncated WPM")
			}
			tag, hdr, _, err = peekTag(payload, offset)
			if err != nil {
				return nil, err
			}
			if tag.Closing && tag.TagNumber == 1 {
				offset += hdr
				break
			}
			propID, next, err := decodeContextUnsigned(payload, offset, 0)
			if err != nil {
				return nil, err
			}
			offset = next
			ref := propertyRef{ID: types.PropertyIdentifier(propID)}
			tag, hdr, _, err = peekTag(payload, offset)
			if err != nil {
				return nil, err
			}
			if tag.ContextSpecific && !tag.Opening && !tag.Closing && tag.TagNumber == 1 {
				idx, next, err := decodeContextUnsigned(payload, offset, 1)
				if err != nil {
					return nil, err
				}
				ref.Index = &idx
				offset = next
				tag, hdr, _, err = peekTag(payload, offset)
				if err != nil {
					return nil, err
				}
			}
			if !tag.Opening || tag.TagNumber != 2 {
				return nil, errBadTag("propertyValue opening")
			}
			offset += hdr
			value, next, err := encoding.DecodeApplicationValue(payload, offset)
			if err != nil {
				return nil, err
			}
			offset = next
			offset, err = encoding.ExpectClosingTag(payload, offset, 2)
			if err != nil {
				return nil, err
			}
			// optional priority [3]
			if offset < len(payload) {
				t2, h2, _, e2 := peekTag(payload, offset)
				if e2 == nil && t2.ContextSpecific && !t2.Opening && !t2.Closing && t2.TagNumber == 3 {
					_, next, err := decodeContextUnsigned(payload, offset, 3)
					if err != nil {
						return nil, err
					}
					offset = next
					_ = h2
				}
			}
			out = append(out, wpmWrite{Key: key, Prop: ref, Value: value})
		}
	}
	return out, nil
}

func encodeWPMError(key fixture.ObjectKey, prop propertyRef, class, code uint32) []byte {
	// Error PDU payload for WPM: errorType [0] { class, code } + firstFailed [1]
	id, _ := key.Identifier()
	var out []byte
	out = append(out, encodeOpening(0)...)
	out = append(out, encoding.EncodeApplicationPrimitive(uint8(encoding.AppTagEnum), encoding.EncodeEnumeratedValue(class))...)
	out = append(out, encoding.EncodeApplicationPrimitive(uint8(encoding.AppTagEnum), encoding.EncodeEnumeratedValue(code))...)
	out = append(out, encodeClosing(0)...)
	out = append(out, encodeOpening(1)...)
	out = append(out, encodeContextObjectID(0, id)...)
	out = append(out, encodeOpening(1)...)
	out = append(out, encodeContextUnsigned(0, uint32(prop.ID))...)
	if prop.Index != nil {
		out = append(out, encodeContextUnsigned(1, *prop.Index)...)
	}
	out = append(out, encodeClosing(1)...)
	out = append(out, encodeClosing(1)...)
	return out
}
