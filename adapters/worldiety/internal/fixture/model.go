// SPDX-License-Identifier: MIT

package fixture

import (
	"fmt"
	"sync"

	"github.com/worldiety/bacnet/common/types"
	"github.com/worldiety/bacnet/encoding"
)

// ObjectTypeTrendLog is ASHRAE ObjectType Trend Log (not yet named in worldiety/types).
const ObjectTypeTrendLog types.ObjectType = 20

// Property identifiers beyond the worldiety named set we need for baseline-v2.
const (
	PropertyDescription             types.PropertyIdentifier = 28
	PropertyMaxAPDULengthAccepted   types.PropertyIdentifier = 62
	PropertyObjectList              types.PropertyIdentifier = 76
	PropertyProtocolVersion         types.PropertyIdentifier = 98
	PropertySegmentationSupported   types.PropertyIdentifier = 107
	PropertySystemStatus            types.PropertyIdentifier = 112
	PropertyVendorIdentifier        types.PropertyIdentifier = 120
	PropertyLogBuffer               types.PropertyIdentifier = 131
	PropertyProtocolRevision        types.PropertyIdentifier = 139
	PropertyTotalRecordCount        types.PropertyIdentifier = 145
	PropertyRecordCount             types.PropertyIdentifier = 140
)

// ObjectKey identifies a BACnet object in the fixture store.
type ObjectKey struct {
	Type     types.ObjectType
	Instance uint32
}

func (k ObjectKey) String() string { return fmt.Sprintf("%s,%d", k.Type, k.Instance) }

func (k ObjectKey) Identifier() (types.ObjectIdentifier, error) {
	return types.NewObjectIdentifier(k.Type, k.Instance)
}

// Object is a mutable fixture-backed BACnet object.
type Object struct {
	Key        ObjectKey
	ObjectName string
	Description string

	mu           sync.Mutex
	presentValue encoding.ApplicationValue // nil when unused
	logRecords   [][]byte                  // pre-encoded BACnetLogRecord SEQUENCE bytes
}

// Store is the in-memory fixture object model.
type Store struct {
	mu             sync.RWMutex
	FixtureID      string
	DeviceInstance uint32
	DeviceName     string
	Port           int
	VendorID       uint16
	objects        map[ObjectKey]*Object
	order          []ObjectKey
}

// NewStore builds an empty store.
func NewStore() *Store {
	return &Store{
		VendorID: 999,
		objects:  make(map[ObjectKey]*Object),
	}
}

// Add inserts or replaces an object.
func (s *Store) Add(obj *Object) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.objects[obj.Key]; !ok {
		s.order = append(s.order, obj.Key)
	}
	s.objects[obj.Key] = obj
}

// Get returns an object or false.
func (s *Store) Get(key ObjectKey) (*Object, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	obj, ok := s.objects[key]
	return obj, ok
}

// Keys returns objects in fixture order.
func (s *Store) Keys() []ObjectKey {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]ObjectKey, len(s.order))
	copy(out, s.order)
	return out
}

// FindByName returns objects matching object-name (case-sensitive).
func (s *Store) FindByName(name string) []*Object {
	s.mu.RLock()
	defer s.mu.RUnlock()
	var out []*Object
	for _, k := range s.order {
		obj := s.objects[k]
		if obj.ObjectName == name {
			out = append(out, obj)
		}
	}
	return out
}

// DeviceKey returns the device object key.
func (s *Store) DeviceKey() ObjectKey {
	return ObjectKey{Type: types.ObjectTypeDevice, Instance: s.DeviceInstance}
}

// GetPresentValue returns a copy of the present value under lock.
func (o *Object) GetPresentValue() encoding.ApplicationValue {
	o.mu.Lock()
	defer o.mu.Unlock()
	return o.presentValue
}

// SetPresentValue replaces the present value.
func (o *Object) SetPresentValue(v encoding.ApplicationValue) {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.presentValue = v
}

// LogRecords returns a defensive copy of seeded log-record payloads.
func (o *Object) LogRecords() [][]byte {
	o.mu.Lock()
	defer o.mu.Unlock()
	out := make([][]byte, len(o.logRecords))
	for i, r := range o.logRecords {
		out[i] = append([]byte(nil), r...)
	}
	return out
}

// SetLogRecords replaces the seeded log buffer.
func (o *Object) SetLogRecords(records [][]byte) {
	o.mu.Lock()
	defer o.mu.Unlock()
	o.logRecords = records
}
