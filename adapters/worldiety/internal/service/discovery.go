// SPDX-License-Identifier: MIT

package service

import (
	"context"

	"github.com/otfabric/bacnet-interop/adapters/worldiety/internal/fixture"
	"github.com/worldiety/bacnet/apdu"
	"github.com/worldiety/bacnet/common/types"
	"github.com/worldiety/bacnet/encoding"
)

// Server binds fixture store + ASE for discovery responses.
type Server struct {
	Store *fixture.Store
	ASE   apdu.ASE
}

func (s *Server) handleWhoIs(_ context.Context, ind apdu.UnconfirmedIndicationICI) error {
	low, high, err := decodeWhoIs(ind.ServiceRequest.Payload)
	if err != nil {
		return nil // ignore malformed
	}
	inst := s.Store.DeviceInstance
	if low != nil && inst < *low {
		return nil
	}
	if high != nil && inst > *high {
		return nil
	}
	payload, err := encodeIAm(s.Store)
	if err != nil {
		return err
	}
	return s.ASE.SendUnconfirmed(context.Background(), apdu.UnconfirmedRequestICI{
		Destination: ind.Source,
		Priority:    ind.Priority,
		ServiceRequest: apdu.UnconfirmedRequest{
			ServiceChoice: apdu.ServiceChoiceIAm,
			Payload:       payload,
		},
	})
}

func (s *Server) handleWhoHas(_ context.Context, ind apdu.UnconfirmedIndicationICI) error {
	matches := decodeWhoHasMatches(s.Store, ind.ServiceRequest.Payload)
	if len(matches) == 0 {
		return nil
	}
	devID, err := s.Store.DeviceKey().Identifier()
	if err != nil {
		return err
	}
	for _, obj := range matches {
		oid, err := obj.Key.Identifier()
		if err != nil {
			continue
		}
		payload, err := encodeIHave(devID, oid, obj.ObjectName)
		if err != nil {
			continue
		}
		_ = s.ASE.SendUnconfirmed(context.Background(), apdu.UnconfirmedRequestICI{
			Destination: ind.Source,
			Priority:    ind.Priority,
			ServiceRequest: apdu.UnconfirmedRequest{
				ServiceChoice: apdu.ServiceChoiceIHave,
				Payload:       payload,
			},
		})
	}
	return nil
}

func decodeWhoIs(payload []byte) (low, high *uint32, err error) {
	offset := 0
	if offset >= len(payload) {
		return nil, nil, nil
	}
	tag, _, _, err := peekTag(payload, offset)
	if err != nil {
		return nil, nil, err
	}
	if tag.ContextSpecific && !tag.Opening && !tag.Closing && tag.TagNumber == 0 {
		v, next, err := decodeContextUnsigned(payload, offset, 0)
		if err != nil {
			return nil, nil, err
		}
		low = &v
		offset = next
	}
	if offset >= len(payload) {
		return low, high, nil
	}
	tag, _, _, err = peekTag(payload, offset)
	if err != nil {
		return nil, nil, err
	}
	if tag.ContextSpecific && !tag.Opening && !tag.Closing && tag.TagNumber == 1 {
		v, _, err := decodeContextUnsigned(payload, offset, 1)
		if err != nil {
			return nil, nil, err
		}
		high = &v
	}
	return low, high, nil
}

func encodeIAm(store *fixture.Store) ([]byte, error) {
	id, err := store.DeviceKey().Identifier()
	if err != nil {
		return nil, err
	}
	var out []byte
	raw, err := encoding.EncodeApplicationValue(encoding.AppObjectIdentifier(id))
	if err != nil {
		return nil, err
	}
	out = append(out, raw...)
	raw, err = encoding.EncodeApplicationValue(encoding.AppUnsignedInteger(1476))
	if err != nil {
		return nil, err
	}
	out = append(out, raw...)
	raw, err = encoding.EncodeApplicationValue(encoding.AppEnum(0)) // segmented-both
	if err != nil {
		return nil, err
	}
	out = append(out, raw...)
	raw, err = encoding.EncodeApplicationValue(encoding.AppUnsignedInteger(uint32(store.VendorID)))
	if err != nil {
		return nil, err
	}
	out = append(out, raw...)
	return out, nil
}

func decodeWhoHasMatches(store *fixture.Store, payload []byte) []*fixture.Object {
	offset := 0
	for offset < len(payload) {
		tag, hdr, vlen, err := peekTag(payload, offset)
		if err != nil {
			return nil
		}
		switch {
		case tag.Opening && tag.TagNumber == 0:
			next, err := skipToClosing(payload, offset+hdr, 0)
			if err != nil {
				return nil
			}
			offset = next
		case tag.ContextSpecific && !tag.Opening && !tag.Closing && tag.TagNumber == 2:
			id, _, err := decodeContextObjectID(payload, offset, 2)
			if err != nil {
				return nil
			}
			key := fixture.ObjectKey{Type: id.ObjectType(), Instance: id.Instance()}
			if obj, ok := store.Get(key); ok {
				return []*fixture.Object{obj}
			}
			return nil
		case tag.ContextSpecific && !tag.Opening && !tag.Closing && tag.TagNumber == 3:
			_, value, _, err := encoding.DecodeExpectedContextPrimitive(payload, offset, 3)
			if err != nil {
				return nil
			}
			name := ""
			if len(value) > 1 {
				// character-string value: charset byte + data
				name = string(value[1:])
			} else if len(value) == 1 {
				name = ""
			}
			return store.FindByName(name)
		default:
			offset += hdr + vlen
		}
	}
	return nil
}

func encodeIHave(device, object types.ObjectIdentifier, name string) ([]byte, error) {
	var out []byte
	raw, err := encoding.EncodeApplicationValue(encoding.AppObjectIdentifier(device))
	if err != nil {
		return nil, err
	}
	out = append(out, raw...)
	raw, err = encoding.EncodeApplicationValue(encoding.AppObjectIdentifier(object))
	if err != nil {
		return nil, err
	}
	out = append(out, raw...)
	raw, err = encoding.EncodeApplicationValue(encoding.AppCharacterString(name))
	if err != nil {
		return nil, err
	}
	out = append(out, raw...)
	return out, nil
}
