// SPDX-License-Identifier: MIT

package service

import (
	"github.com/worldiety/bacnet/apdu"
	"github.com/worldiety/bacnet/encoding"
)

// BACnet Error class / code (subset used by baseline services).
const (
	ErrorClassDevice   uint32 = 0
	ErrorClassObject   uint32 = 1
	ErrorClassProperty uint32 = 2
	ErrorClassServices uint32 = 5

	ErrorCodeOther                 uint32 = 0
	ErrorCodeUnknownObject         uint32 = 31
	ErrorCodeUnknownProperty       uint32 = 32
	ErrorCodeWriteAccessDenied     uint32 = 40
	ErrorCodeInvalidArrayIndex     uint32 = 42
	ErrorCodeValueOutOfRange       uint32 = 37
	ErrorCodePropertyIsNotAList    uint32 = 22
	ErrorCodeInconsistentParameters uint32 = 7
)

func ackResponse(ind apdu.ConfirmedIndicationICI, payload []byte) apdu.ConfirmedResponseICI {
	return apdu.ConfirmedResponseICI{
		Destination:           ind.Source,
		InvokeID:              ind.InvokeID,
		SegmentationSupported: apdu.SegmentationSupportBoth,
		ResponseType:          apdu.ConfirmedResponseTypeACK,
		ServiceResponse:       apdu.ServiceResult{Payload: payload},
	}
}

func errorResponse(ind apdu.ConfirmedIndicationICI, class, code uint32) apdu.ConfirmedResponseICI {
	payload := append(
		encoding.EncodeApplicationPrimitive(uint8(encoding.AppTagEnum), encoding.EncodeEnumeratedValue(class)),
		encoding.EncodeApplicationPrimitive(uint8(encoding.AppTagEnum), encoding.EncodeEnumeratedValue(code))...,
	)
	return apdu.ConfirmedResponseICI{
		Destination:           ind.Source,
		InvokeID:              ind.InvokeID,
		SegmentationSupported: apdu.SegmentationSupportBoth,
		ResponseType:          apdu.ConfirmedResponseTypeError,
		ServiceResponse:       apdu.ServiceResult{Payload: payload},
	}
}
