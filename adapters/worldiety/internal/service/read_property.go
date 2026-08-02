// SPDX-License-Identifier: MIT

package service

import (
	"context"

	"github.com/otfabric/bacnet-interop/adapters/worldiety/internal/fixture"
	"github.com/worldiety/bacnet/apdu"
	"github.com/worldiety/bacnet/common/types"
)

func (s *Server) handleReadProperty(_ context.Context, ind apdu.ConfirmedIndicationICI) (apdu.ConfirmedResponseICI, error) {
	key, prop, err := decodeReadProperty(ind.ServiceRequest.Payload)
	if err != nil {
		return errorResponse(ind, ErrorClassServices, ErrorCodeInconsistentParameters), nil
	}
	value, class, code, err := readPropertyValue(s.Store, key, prop)
	if err != nil {
		return errorResponse(ind, class, code), nil
	}
	ack, err := encodeReadPropertyACK(key, prop, value)
	if err != nil {
		return errorResponse(ind, ErrorClassServices, ErrorCodeOther), nil
	}
	return ackResponse(ind, ack), nil
}

func decodeReadProperty(payload []byte) (fixture.ObjectKey, propertyRef, error) {
	id, offset, err := decodeContextObjectID(payload, 0, 0)
	if err != nil {
		return fixture.ObjectKey{}, propertyRef{}, err
	}
	propID, offset, err := decodeContextUnsigned(payload, offset, 1)
	if err != nil {
		return fixture.ObjectKey{}, propertyRef{}, err
	}
	ref := propertyRef{ID: types.PropertyIdentifier(propID)}
	if offset < len(payload) {
		tag, _, _, err := peekTag(payload, offset)
		if err == nil && tag.ContextSpecific && !tag.Opening && !tag.Closing && tag.TagNumber == 2 {
			idx, _, err := decodeContextUnsigned(payload, offset, 2)
			if err != nil {
				return fixture.ObjectKey{}, propertyRef{}, err
			}
			ref.Index = &idx
		}
	}
	return fixture.ObjectKey{Type: id.ObjectType(), Instance: id.Instance()}, ref, nil
}

func encodeReadPropertyACK(key fixture.ObjectKey, prop propertyRef, value []byte) ([]byte, error) {
	id, err := key.Identifier()
	if err != nil {
		return nil, err
	}
	out := encodeContextObjectID(0, id)
	out = append(out, encodeContextUnsigned(1, uint32(prop.ID))...)
	if prop.Index != nil {
		out = append(out, encodeContextUnsigned(2, *prop.Index)...)
	}
	out = append(out, encodeOpening(3)...)
	out = append(out, value...)
	out = append(out, encodeClosing(3)...)
	return out, nil
}
