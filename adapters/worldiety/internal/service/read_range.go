// SPDX-License-Identifier: MIT

package service

import (
	"context"

	"github.com/otfabric/bacnet-interop/adapters/worldiety/internal/fixture"
	"github.com/worldiety/bacnet/apdu"
	"github.com/worldiety/bacnet/common/types"
	"github.com/worldiety/bacnet/encoding"
)

func (s *Server) handleReadRange(_ context.Context, ind apdu.ConfirmedIndicationICI) (apdu.ConfirmedResponseICI, error) {
	req, err := decodeReadRange(ind.ServiceRequest.Payload)
	if err != nil {
		return errorResponse(ind, ErrorClassServices, ErrorCodeInconsistentParameters), nil
	}
	obj, ok := s.Store.Get(req.Key)
	if !ok {
		return errorResponse(ind, ErrorClassObject, ErrorCodeUnknownObject), nil
	}
	if req.Prop.ID != fixture.PropertyLogBuffer {
		return errorResponse(ind, ErrorClassProperty, ErrorCodeUnknownProperty), nil
	}
	records := obj.LogRecords()
	if len(records) == 0 {
		return errorResponse(ind, ErrorClassProperty, ErrorCodeOther), nil
	}

	start := 0
	count := len(records)
	if req.ByPosition {
		// ReferenceIndex is 1-based.
		if req.Reference == 0 {
			return errorResponse(ind, ErrorClassServices, ErrorCodeInconsistentParameters), nil
		}
		start = int(req.Reference) - 1
		if start < 0 || start >= len(records) {
			return errorResponse(ind, ErrorClassProperty, ErrorCodeInvalidArrayIndex), nil
		}
		if req.Count > 0 {
			count = int(req.Count)
		} else if req.Count < 0 {
			// backward: ignore for baseline; treat absolute
			count = int(-req.Count)
		}
	}
	end := start + count
	if end > len(records) {
		end = len(records)
	}
	selected := records[start:end]
	first := start == 0
	last := end >= len(records)
	ack, err := encodeReadRangeACK(req.Key, req.Prop, first, last, false, selected)
	if err != nil {
		return errorResponse(ind, ErrorClassServices, ErrorCodeOther), nil
	}
	return ackResponse(ind, ack), nil
}

type readRangeReq struct {
	Key        fixture.ObjectKey
	Prop       propertyRef
	ByPosition bool
	Reference  uint32
	Count      int32
}

func decodeReadRange(payload []byte) (readRangeReq, error) {
	var req readRangeReq
	id, offset, err := decodeContextObjectID(payload, 0, 0)
	if err != nil {
		return req, err
	}
	req.Key = fixture.ObjectKey{Type: id.ObjectType(), Instance: id.Instance()}
	propID, offset, err := decodeContextUnsigned(payload, offset, 1)
	if err != nil {
		return req, err
	}
	req.Prop.ID = types.PropertyIdentifier(propID)
	if offset < len(payload) {
		tag, _, _, err := peekTag(payload, offset)
		if err == nil && tag.ContextSpecific && !tag.Opening && !tag.Closing && tag.TagNumber == 2 {
			idx, next, err := decodeContextUnsigned(payload, offset, 2)
			if err != nil {
				return req, err
			}
			req.Prop.Index = &idx
			offset = next
		}
	}
	if offset >= len(payload) {
		return req, nil // all
	}
	tag, hdr, _, err := peekTag(payload, offset)
	if err != nil {
		return req, err
	}
	// range CHOICE: byPosition [3] SEQUENCE { referenceIndex Unsigned, count INTEGER }
	if tag.Opening && tag.TagNumber == 3 {
		offset += hdr
		ref, next, err := decodeAppUnsigned(payload, offset)
		if err != nil {
			return req, err
		}
		offset = next
		count, next, err := decodeAppSigned(payload, offset)
		if err != nil {
			return req, err
		}
		offset = next
		if _, err := encoding.ExpectClosingTag(payload, offset, 3); err != nil {
			return req, err
		}
		req.ByPosition = true
		req.Reference = ref
		req.Count = count
	}
	return req, nil
}

func decodeAppUnsigned(payload []byte, offset int) (uint32, int, error) {
	v, next, err := encoding.DecodeApplicationValue(payload, offset)
	if err != nil {
		return 0, offset, err
	}
	u, ok := v.(encoding.AppUnsignedInteger)
	if !ok {
		return 0, offset, errBadTag("unsigned")
	}
	return uint32(u), next, nil
}

func decodeAppSigned(payload []byte, offset int) (int32, int, error) {
	v, next, err := encoding.DecodeApplicationValue(payload, offset)
	if err != nil {
		return 0, offset, err
	}
	switch t := v.(type) {
	case encoding.AppInteger:
		return int32(t), next, nil
	case encoding.AppUnsignedInteger:
		return int32(t), next, nil
	default:
		return 0, offset, errBadTag("signed")
	}
}

func encodeReadRangeACK(key fixture.ObjectKey, prop propertyRef, first, last, more bool, records [][]byte) ([]byte, error) {
	id, err := key.Identifier()
	if err != nil {
		return nil, err
	}
	out := encodeContextObjectID(0, id)
	out = append(out, encodeContextUnsigned(1, uint32(prop.ID))...)
	if prop.Index != nil {
		out = append(out, encodeContextUnsigned(2, *prop.Index)...)
	}
	// resultFlags [3] BIT STRING { first, last, more }
	flagVal := encoding.EncodeBitStringValue(encoding.BitString{Bits: []bool{first, last, more}})
	out = append(out, encoding.EncodeContextPrimitive(3, flagVal)...)
	out = append(out, encodeContextUnsigned(4, uint32(len(records)))...)
	out = append(out, encodeOpening(5)...)
	for _, r := range records {
		out = append(out, r...)
	}
	out = append(out, encodeClosing(5)...)
	return out, nil
}
