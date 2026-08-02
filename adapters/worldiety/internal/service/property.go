// SPDX-License-Identifier: MIT

package service

import (
	"fmt"

	"github.com/otfabric/bacnet-interop/adapters/worldiety/internal/fixture"
	"github.com/worldiety/bacnet/common/types"
	"github.com/worldiety/bacnet/encoding"
)

type propertyRef struct {
	ID    types.PropertyIdentifier
	Index *uint32
}

func readPropertyValue(store *fixture.Store, key fixture.ObjectKey, prop propertyRef) ([]byte, uint32, uint32, error) {
	obj, ok := store.Get(key)
	if !ok {
		return nil, ErrorClassObject, ErrorCodeUnknownObject, fmt.Errorf("unknown object")
	}
	id, err := key.Identifier()
	if err != nil {
		return nil, ErrorClassObject, ErrorCodeUnknownObject, err
	}

	switch prop.ID {
	case types.PropertyIdentifierObjectIdentifier:
		raw, err := encoding.EncodeApplicationValue(encoding.AppObjectIdentifier(id))
		return raw, 0, 0, err
	case types.PropertyIdentifierObjectName:
		raw, err := encoding.EncodeApplicationValue(encoding.AppCharacterString(obj.ObjectName))
		return raw, 0, 0, err
	case types.PropertyIdentifierObjectType:
		raw, err := encoding.EncodeApplicationValue(encoding.AppEnum(uint32(key.Type)))
		return raw, 0, 0, err
	case fixture.PropertyDescription:
		desc := obj.Description
		if desc == "" {
			desc = obj.ObjectName
		}
		raw, err := encoding.EncodeApplicationValue(encoding.AppCharacterString(desc))
		return raw, 0, 0, err
	case types.PropertyIdentifierPresentValue:
		pv := obj.GetPresentValue()
		if pv == nil {
			return nil, ErrorClassProperty, ErrorCodeUnknownProperty, fmt.Errorf("no present-value")
		}
		raw, err := fixture.EncodeApp(pv)
		return raw, 0, 0, err
	case types.PropertyIdentifierStatusFlags:
		// in-alarm=0 fault=0 overridden=0 out-of-service=0
		bs := encoding.AppBitString{Bits: []bool{false, false, false, false}}
		raw, err := encoding.EncodeApplicationValue(bs)
		return raw, 0, 0, err
	case fixture.PropertyObjectList:
		if key.Type != types.ObjectTypeDevice {
			return nil, ErrorClassProperty, ErrorCodeUnknownProperty, fmt.Errorf("object-list")
		}
		return encodeObjectList(store, prop.Index)
	case fixture.PropertyMaxAPDULengthAccepted:
		raw, err := encoding.EncodeApplicationValue(encoding.AppUnsignedInteger(1476))
		return raw, 0, 0, err
	case fixture.PropertySegmentationSupported:
		// segmented-both = 0
		raw, err := encoding.EncodeApplicationValue(encoding.AppEnum(0))
		return raw, 0, 0, err
	case fixture.PropertyVendorIdentifier:
		raw, err := encoding.EncodeApplicationValue(encoding.AppUnsignedInteger(uint32(store.VendorID)))
		return raw, 0, 0, err
	case fixture.PropertySystemStatus:
		raw, err := encoding.EncodeApplicationValue(encoding.AppEnum(0)) // operational
		return raw, 0, 0, err
	case fixture.PropertyProtocolVersion:
		raw, err := encoding.EncodeApplicationValue(encoding.AppUnsignedInteger(1))
		return raw, 0, 0, err
	case fixture.PropertyProtocolRevision:
		raw, err := encoding.EncodeApplicationValue(encoding.AppUnsignedInteger(24))
		return raw, 0, 0, err
	case fixture.PropertyLogBuffer:
		return nil, ErrorClassProperty, ErrorCodeUnknownProperty, fmt.Errorf("use ReadRange for Log_Buffer")
	case fixture.PropertyRecordCount, fixture.PropertyTotalRecordCount:
		if key.Type != fixture.ObjectTypeTrendLog {
			return nil, ErrorClassProperty, ErrorCodeUnknownProperty, fmt.Errorf("not trend-log")
		}
		n := uint32(len(obj.LogRecords()))
		raw, err := encoding.EncodeApplicationValue(encoding.AppUnsignedInteger(n))
		return raw, 0, 0, err
	default:
		return nil, ErrorClassProperty, ErrorCodeUnknownProperty, fmt.Errorf("unknown property %d", prop.ID)
	}
}

func encodeObjectList(store *fixture.Store, index *uint32) ([]byte, uint32, uint32, error) {
	keys := store.Keys()
	if index != nil {
		if *index == 0 {
			raw, err := encoding.EncodeApplicationValue(encoding.AppUnsignedInteger(uint32(len(keys))))
			return raw, 0, 0, err
		}
		i := int(*index) - 1
		if i < 0 || i >= len(keys) {
			return nil, ErrorClassProperty, ErrorCodeInvalidArrayIndex, fmt.Errorf("array index")
		}
		id, err := keys[i].Identifier()
		if err != nil {
			return nil, ErrorClassObject, ErrorCodeUnknownObject, err
		}
		raw, err := encoding.EncodeApplicationValue(encoding.AppObjectIdentifier(id))
		return raw, 0, 0, err
	}
	var out []byte
	for _, k := range keys {
		id, err := k.Identifier()
		if err != nil {
			return nil, ErrorClassObject, ErrorCodeUnknownObject, err
		}
		raw, err := encoding.EncodeApplicationValue(encoding.AppObjectIdentifier(id))
		if err != nil {
			return nil, ErrorClassObject, ErrorCodeUnknownObject, err
		}
		out = append(out, raw...)
	}
	return out, 0, 0, nil
}

func writePropertyValue(store *fixture.Store, key fixture.ObjectKey, prop propertyRef, value encoding.ApplicationValue) (uint32, uint32, error) {
	obj, ok := store.Get(key)
	if !ok {
		return ErrorClassObject, ErrorCodeUnknownObject, fmt.Errorf("unknown object")
	}
	switch prop.ID {
	case types.PropertyIdentifierPresentValue:
		switch key.Type {
		case types.ObjectTypeAnalogValue, types.ObjectTypeAnalogOutput:
			if _, err := fixture.AsReal(value); err != nil {
				return ErrorClassProperty, ErrorCodeValueOutOfRange, err
			}
			obj.SetPresentValue(value)
			return 0, 0, nil
		case types.ObjectTypeBinaryValue, types.ObjectTypeBinaryOutput:
			if _, err := fixture.AsEnum(value); err != nil {
				return ErrorClassProperty, ErrorCodeValueOutOfRange, err
			}
			obj.SetPresentValue(value)
			return 0, 0, nil
		default:
			return ErrorClassProperty, ErrorCodeWriteAccessDenied, fmt.Errorf("not writable")
		}
	case fixture.PropertyDescription:
		cs, ok := value.(encoding.AppCharacterString)
		if !ok {
			return ErrorClassProperty, ErrorCodeValueOutOfRange, fmt.Errorf("description type")
		}
		obj.Description = string(cs)
		return 0, 0, nil
	default:
		return ErrorClassProperty, ErrorCodeWriteAccessDenied, fmt.Errorf("not writable")
	}
}
