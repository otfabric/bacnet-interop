// SPDX-License-Identifier: MIT

package service

import (
	"context"
	"time"

	"github.com/otfabric/bacnet-interop/adapters/worldiety/internal/fixture"
	"github.com/worldiety/bacnet/apdu"
	"github.com/worldiety/bacnet/common/types"
	"github.com/worldiety/bacnet/encoding"
)

// handleReadRange serves ReadRange on the seeded Log_Buffer. The range
// selection is this adapter's own (clause 15.8 as the BACnet4J peer applies
// it), not upstream behaviour:
//
//   - no range: the whole buffer.
//   - byPosition: count records from the reference position on, or (negative
//     count) the records up to and including it. A reference outside the
//     buffer is Error property/invalid-array-index.
//   - bySequenceNumber: the same, from the record with that sequence number.
//     A sequence number that is not in the buffer selects nothing.
//   - byTime: the records after the reference time, or (negative count) the
//     records before it. A reference time with an unspecified field is Error
//     property/datatype-not-supported.
//
// bySequenceNumber and byTime replies carry firstSequenceNumber when they
// hold a record. MORE_ITEMS is never set: every selection fits one reply.
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
	n := len(records)
	if req.By != rangeAll && req.Count == 0 {
		return errorResponse(ind, ErrorClassServices, ErrorCodeInconsistentParameters), nil
	}

	// index is the 0-based record the selection starts from (count > 0) or
	// ends at (count < 0); -1 selects nothing.
	index := 0
	count := n
	withSequence := false
	switch req.By {
	case rangeByPosition:
		if req.Reference < 1 || int64(req.Reference) > int64(n) {
			return errorResponse(ind, ErrorClassProperty, ErrorCodeInvalidArrayIndex), nil
		}
		index, count = int(req.Reference)-1, int(req.Count)
	case rangeBySequence:
		// The record at position k has sequence number k.
		withSequence = true
		index, count = -1, int(req.Count)
		if req.Reference >= 1 && int64(req.Reference) <= int64(n) {
			index = int(req.Reference) - 1
		}
	case rangeByTime:
		withSequence = true
		ref, ok := req.referenceTime()
		if !ok {
			return errorResponse(ind, ErrorClassProperty, ErrorCodeDatatypeNotSupported), nil
		}
		count = int(req.Count)
		// after = number of seeded records stamped at or before ref.
		after := 0
		for after < n && !fixture.LogSeedStart.Add(time.Duration(after)*fixture.LogSeedInterval).After(ref) {
			after++
		}
		if count > 0 {
			index = after // first record after ref
		} else {
			index = after - 1 // last record at or before ref ...
			if index >= 0 && fixture.LogSeedStart.Add(time.Duration(index)*fixture.LogSeedInterval).Equal(ref) {
				index-- // ... but not the one stamped exactly at it
			}
		}
		if index >= n {
			index = -1
		}
	}

	start, end := 0, 0 // records[start:end]
	if index >= 0 {
		if count > 0 {
			start, end = index, min(index+count, n)
		} else {
			start, end = max(index+count+1, 0), index+1
		}
	}
	selected := records[start:end]
	var firstSeq *uint32
	if withSequence && len(selected) > 0 {
		seq := uint32(start + 1)
		firstSeq = &seq
	}
	first := len(selected) > 0 && start == 0
	last := len(selected) > 0 && end == n
	ack, err := encodeReadRangeACK(req.Key, req.Prop, first, last, false, selected, firstSeq)
	if err != nil {
		return errorResponse(ind, ErrorClassServices, ErrorCodeOther), nil
	}
	return ackResponse(ind, ack), nil
}

type rangeForm uint8

const (
	rangeAll rangeForm = iota
	rangeByPosition
	rangeBySequence
	rangeByTime
)

type readRangeReq struct {
	Key       fixture.ObjectKey
	Prop      propertyRef
	By        rangeForm
	Reference uint32 // byPosition, bySequenceNumber
	Date      encoding.AppDate
	Time      encoding.AppTime
	Count     int32
}

// referenceTime converts the byTime reference; ok is false when a field is
// unspecified (the day of week is ignored).
func (r readRangeReq) referenceTime() (time.Time, bool) {
	const any = 255
	d, t := r.Date, r.Time
	if d.Year == any || d.Month < 1 || d.Month > 12 || d.Day < 1 || d.Day > 31 ||
		t.Hour > 23 || t.Minute > 59 || t.Second > 59 || t.Hundredths > 99 {
		return time.Time{}, false
	}
	return time.Date(int(d.Year), time.Month(d.Month), int(d.Day),
		int(t.Hour), int(t.Minute), int(t.Second), int(t.Hundredths)*10_000_000, time.UTC), true
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
	if !tag.Opening {
		return req, errBadTag("range opening")
	}
	offset += hdr
	// range CHOICE:
	//   byPosition       [3] SEQUENCE { referenceIndex Unsigned, count INTEGER }
	//   bySequenceNumber [6] SEQUENCE { referenceSequenceNumber Unsigned, count INTEGER }
	//   byTime           [7] SEQUENCE { referenceTime BACnetDateTime, count INTEGER }
	switch tag.TagNumber {
	case 3, 6:
		req.By = rangeByPosition
		if tag.TagNumber == 6 {
			req.By = rangeBySequence
		}
		ref, next, err := decodeAppUnsigned(payload, offset)
		if err != nil {
			return req, err
		}
		req.Reference = ref
		offset = next
	case 7:
		req.By = rangeByTime
		v, next, err := encoding.DecodeApplicationValue(payload, offset)
		if err != nil {
			return req, err
		}
		d, ok := v.(encoding.AppDate)
		if !ok {
			return req, errBadTag("referenceTime date")
		}
		v, next, err = encoding.DecodeApplicationValue(payload, next)
		if err != nil {
			return req, err
		}
		tm, ok := v.(encoding.AppTime)
		if !ok {
			return req, errBadTag("referenceTime time")
		}
		req.Date, req.Time = d, tm
		offset = next
	default:
		return req, errBadTag("range choice")
	}
	count, next, err := decodeAppSigned(payload, offset)
	if err != nil {
		return req, err
	}
	if _, err := encoding.ExpectClosingTag(payload, next, tag.TagNumber); err != nil {
		return req, err
	}
	req.Count = count
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

func encodeReadRangeACK(key fixture.ObjectKey, prop propertyRef, first, last, more bool, records [][]byte, firstSeq *uint32) ([]byte, error) {
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
	if firstSeq != nil {
		out = append(out, encodeContextUnsigned(6, *firstSeq)...)
	}
	return out, nil
}
