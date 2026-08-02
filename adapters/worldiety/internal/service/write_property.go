// SPDX-License-Identifier: MIT

package service

import (
	"context"

	"github.com/otfabric/bacnet-interop/adapters/worldiety/internal/fixture"
	"github.com/worldiety/bacnet/apdu"
	"github.com/worldiety/bacnet/common/types"
	"github.com/worldiety/bacnet/encoding"
)

func (s *Server) handleWriteProperty(_ context.Context, ind apdu.ConfirmedIndicationICI) (apdu.ConfirmedResponseICI, error) {
	key, prop, value, err := decodeWriteProperty(ind.ServiceRequest.Payload)
	if err != nil {
		return errorResponse(ind, ErrorClassServices, ErrorCodeInconsistentParameters), nil
	}
	if class, code, err := writePropertyValue(s.Store, key, prop, value); err != nil {
		return errorResponse(ind, class, code), nil
	}
	return ackResponse(ind, nil), nil
}

func decodeWriteProperty(payload []byte) (fixture.ObjectKey, propertyRef, encoding.ApplicationValue, error) {
	id, offset, err := decodeContextObjectID(payload, 0, 0)
	if err != nil {
		return fixture.ObjectKey{}, propertyRef{}, nil, err
	}
	propID, offset, err := decodeContextUnsigned(payload, offset, 1)
	if err != nil {
		return fixture.ObjectKey{}, propertyRef{}, nil, err
	}
	ref := propertyRef{ID: types.PropertyIdentifier(propID)}
	tag, hdr, _, err := peekTag(payload, offset)
	if err != nil {
		return fixture.ObjectKey{}, propertyRef{}, nil, err
	}
	if tag.ContextSpecific && !tag.Opening && !tag.Closing && tag.TagNumber == 2 {
		idx, next, err := decodeContextUnsigned(payload, offset, 2)
		if err != nil {
			return fixture.ObjectKey{}, propertyRef{}, nil, err
		}
		ref.Index = &idx
		offset = next
		tag, hdr, _, err = peekTag(payload, offset)
		if err != nil {
			return fixture.ObjectKey{}, propertyRef{}, nil, err
		}
	}
	if !tag.Opening || tag.TagNumber != 3 {
		return fixture.ObjectKey{}, propertyRef{}, nil, errBadTag("propertyValue opening")
	}
	offset += hdr
	value, next, err := encoding.DecodeApplicationValue(payload, offset)
	if err != nil {
		return fixture.ObjectKey{}, propertyRef{}, nil, err
	}
	offset = next
	if _, err := encoding.ExpectClosingTag(payload, offset, 3); err != nil {
		return fixture.ObjectKey{}, propertyRef{}, nil, err
	}
	return fixture.ObjectKey{Type: id.ObjectType(), Instance: id.Instance()}, ref, value, nil
}

func errBadTag(msg string) error { return &tagError{msg: msg} }

type tagError struct{ msg string }

func (e *tagError) Error() string { return e.msg }
