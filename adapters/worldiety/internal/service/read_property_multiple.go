// SPDX-License-Identifier: MIT

package service

import (
	"context"

	"github.com/otfabric/bacnet-interop/adapters/worldiety/internal/fixture"
	"github.com/worldiety/bacnet/apdu"
	"github.com/worldiety/bacnet/common/types"
	"github.com/worldiety/bacnet/encoding"
)

func (s *Server) handleReadPropertyMultiple(_ context.Context, ind apdu.ConfirmedIndicationICI) (apdu.ConfirmedResponseICI, error) {
	specs, err := decodeRPM(ind.ServiceRequest.Payload)
	if err != nil {
		return errorResponse(ind, ErrorClassServices, ErrorCodeInconsistentParameters), nil
	}
	ack, err := encodeRPMACK(s.Store, specs)
	if err != nil {
		return errorResponse(ind, ErrorClassServices, ErrorCodeOther), nil
	}
	return ackResponse(ind, ack), nil
}

type rpmSpec struct {
	Key   fixture.ObjectKey
	Props []propertyRef
	All   bool
}

func decodeRPM(payload []byte) ([]rpmSpec, error) {
	var specs []rpmSpec
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
			return nil, errBadTag("listOfPropertyReferences opening")
		}
		offset += hdr
		spec := rpmSpec{Key: fixture.ObjectKey{Type: id.ObjectType(), Instance: id.Instance()}}
		for {
			if offset >= len(payload) {
				return nil, errBadTag("truncated RPM")
			}
			tag, hdr, _, err = peekTag(payload, offset)
			if err != nil {
				return nil, err
			}
			if tag.Closing && tag.TagNumber == 1 {
				offset += hdr
				break
			}
			if tag.ContextSpecific && !tag.Opening && !tag.Closing && tag.TagNumber == 0 {
				propID, next, err := decodeContextUnsigned(payload, offset, 0)
				if err != nil {
					return nil, err
				}
				offset = next
				if propID == 8 { // all // special property
					spec.All = true
					continue
				}
				ref := propertyRef{ID: types.PropertyIdentifier(propID)}
				if offset < len(payload) {
					t2, _, _, e2 := peekTag(payload, offset)
					if e2 == nil && t2.ContextSpecific && !t2.Opening && !t2.Closing && t2.TagNumber == 1 {
						idx, next, err := decodeContextUnsigned(payload, offset, 1)
						if err != nil {
							return nil, err
						}
						ref.Index = &idx
						offset = next
					}
				}
				spec.Props = append(spec.Props, ref)
				continue
			}
			return nil, errBadTag("unexpected RPM tag")
		}
		specs = append(specs, spec)
	}
	return specs, nil
}

func encodeRPMACK(store *fixture.Store, specs []rpmSpec) ([]byte, error) {
	var out []byte
	for _, spec := range specs {
		id, err := spec.Key.Identifier()
		if err != nil {
			return nil, err
		}
		out = append(out, encodeContextObjectID(0, id)...)
		out = append(out, encodeOpening(1)...)
		props := spec.Props
		if spec.All {
			props = defaultAllProps(spec.Key)
		}
		for _, prop := range props {
			out = append(out, encodeContextUnsigned(2, uint32(prop.ID))...)
			if prop.Index != nil {
				out = append(out, encodeContextUnsigned(3, *prop.Index)...)
			}
			value, class, code, err := readPropertyValue(store, spec.Key, prop)
			if err != nil {
				out = append(out, encodeOpening(5)...)
				out = append(out,
					encoding.EncodeApplicationPrimitive(uint8(encoding.AppTagEnum), encoding.EncodeEnumeratedValue(class))...)
				out = append(out,
					encoding.EncodeApplicationPrimitive(uint8(encoding.AppTagEnum), encoding.EncodeEnumeratedValue(code))...)
				out = append(out, encodeClosing(5)...)
				continue
			}
			out = append(out, encodeOpening(4)...)
			out = append(out, value...)
			out = append(out, encodeClosing(4)...)
		}
		out = append(out, encodeClosing(1)...)
	}
	return out, nil
}

func defaultAllProps(key fixture.ObjectKey) []propertyRef {
	props := []propertyRef{
		{ID: types.PropertyIdentifierObjectIdentifier},
		{ID: types.PropertyIdentifierObjectName},
		{ID: types.PropertyIdentifierObjectType},
		{ID: fixture.PropertyDescription},
	}
	switch key.Type {
	case types.ObjectTypeAnalogValue, types.ObjectTypeBinaryValue,
		types.ObjectTypeAnalogInput, types.ObjectTypeBinaryInput,
		types.ObjectTypeAnalogOutput, types.ObjectTypeBinaryOutput:
		props = append(props, propertyRef{ID: types.PropertyIdentifierPresentValue})
		props = append(props, propertyRef{ID: types.PropertyIdentifierStatusFlags})
	case types.ObjectTypeDevice:
		props = append(props,
			propertyRef{ID: fixture.PropertyObjectList},
			propertyRef{ID: fixture.PropertyMaxAPDULengthAccepted},
			propertyRef{ID: fixture.PropertySegmentationSupported},
			propertyRef{ID: fixture.PropertyVendorIdentifier},
		)
	}
	return props
}
