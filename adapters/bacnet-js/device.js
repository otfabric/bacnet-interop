// SPDX-License-Identifier: MIT
'use strict'

// bacnet-js device mode (docs/CONTAINER_CONTRACT.md).
//
// One upstream BACnetClient (@bacnet-js/client, unmodified) bound to UDP
// 47808 serves a fixture's objects. Upstream decodes every request (its
// confirmed and unconfirmed service maps, client.ts) and the adapter answers
// with upstream encoders: the response methods (iAmResponse, iHaveResponse,
// simpleAckResponse, errorResponse, unconfirmedCOVNotification,
// confirmedCOVNotification) and, for ComplexACKs, apdu.encodeComplexAck
// plus the service's own encodeAcknowledge. Upstream has no object model, no
// dispatch and no service procedures: the objects, the property tables, the
// write, COV, event, file and object-lifecycle procedures below are adapter
// code (adapter-shim in adapters/inventory.yaml). Services upstream cannot
// decode or encode are not answered by the adapter; upstream's own
// behaviour for them stands (README.md, "What upstream lacks").

const fs = require('fs')
const os = require('os')
const L = require('./lib')

const { pkg, services: S, asn1: A } = L
const T = pkg.ApplicationTag
const P = pkg.PropertyIdentifier
const O = pkg.ObjectType
const EC = pkg.ErrorClass
const E = pkg.ErrorCode
const C = pkg.ConfirmedServiceChoice
const ARRAY_ALL = pkg.ASN1_ARRAY_ALL
const ADAPTER = 'bacnet-js'
const VENDOR_ID = 999
const DEVICE_MAX_APDU = 1476
// Upstream reassembles segmented requests (client.ts _processSegment) and
// never sends a segmented message.
const SEGMENTATION = pkg.Segmentation.SEGMENTED_RECEIVE

class Fail extends Error {
	constructor(cls, code) {
		super(`${pkg.ErrorClass[cls]}/${pkg.ErrorCode[code]}`)
		this.cls = cls
		this.code = code
	}
}

const fail = (cls, code) => {
	throw new Fail(cls, code)
}

function emitOperation(operation, result = 'accepted', fields) {
	const line = { event: 'operation', adapter: ADAPTER, operation, result }
	if (fields) Object.assign(line, fields)
	L.emit(line)
}

const real = (v) => ({ type: T.REAL, value: v })
const uns = (v) => ({ type: T.UNSIGNED_INTEGER, value: v })
const enm = (v) => ({ type: T.ENUMERATED, value: v })
const bool = (v) => ({ type: T.BOOLEAN, value: !!v })
const str = (v) => ({ type: T.CHARACTER_STRING, value: v })
const oidv = (type, instance) => ({ type: T.OBJECTIDENTIFIER, value: { type, instance } })
const bits = (n, set) => ({ type: T.BIT_STRING, value: L.bitString(n, set) })
const stamp = (ts) => ({ type: T.TIMESTAMP, value: ts })

// BACnetTimeStamp values are kept at hundredths of a second, the
// resolution of a BACnet Time (clause 20.2.13), so that a stamp read back
// and echoed in an AcknowledgeAlarm compares equal.
function nowStamp() {
	const d = new Date()
	d.setMilliseconds(Math.floor(d.getMilliseconds() / 10) * 10)
	return { type: pkg.TimeStamp.DATETIME, value: d }
}

function sameStamp(a, b) {
	if (!a || !b) return false
	const av = a instanceof Date ? a.getTime() : a
	const bv = b.value instanceof Date ? b.value.getTime() : b.value
	if (typeof av === 'number' && typeof bv === 'number') {
		return a instanceof Date ? Math.abs(av - bv) < 10 : av === bv
	}
	return false
}

function localDate(text) {
	const m = /^(\d+)-(\d+)-(\d+)T(\d+):(\d+):(\d+)/.exec(text)
	if (!m) throw new Error(`timestamp ${text} is not YYYY-MM-DDTHH:MM:SS`)
	return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6])
}

// --- object model (adapter-shim) ------------------------------------------

class BObject {
	constructor(dev, type, instance, name, description) {
		this.dev = dev
		this.type = type
		this.instance = instance
		this.name = name
		this.description = description
		this.props = new Map()
		this.arrays = new Set()
		this.writable = new Map()
	}

	key() {
		return `${this.type}:${this.instance}`
	}

	define(pid, get, { array = false, write } = {}) {
		this.props.set(pid, get)
		if (array) this.arrays.add(pid)
		if (write) this.writable.set(pid, write)
	}

	base() {
		this.define(P.OBJECT_IDENTIFIER, () => [oidv(this.type, this.instance)])
		this.define(P.OBJECT_NAME, () => [str(this.name)])
		this.define(P.OBJECT_TYPE, () => [enm(this.type)])
		if (this.description !== undefined) this.define(P.DESCRIPTION, () => [str(this.description)])
	}

	// Property_List: every property but the four clause 12.1.1.4.1 leaves out.
	finish() {
		const skip = new Set([P.OBJECT_IDENTIFIER, P.OBJECT_NAME, P.OBJECT_TYPE, P.PROPERTY_LIST])
		this.define(P.PROPERTY_LIST, () => [...this.props.keys()].filter((p) => !skip.has(p)).map(enm), { array: true })
	}

	// ReadProperty semantics: clause 15.5.1.3, array access clause 15.5.1.1.3.
	read(pid, index) {
		const get = this.props.get(pid)
		if (!get) fail(EC.PROPERTY, E.UNKNOWN_PROPERTY)
		if (pid === P.LOG_BUFFER) fail(EC.PROPERTY, E.READ_ACCESS_DENIED)
		const values = get()
		if (index === undefined || index === ARRAY_ALL) return values
		if (!this.arrays.has(pid)) fail(EC.PROPERTY, E.PROPERTY_IS_NOT_AN_ARRAY)
		if (index === 0) return [uns(values.length)]
		if (index > values.length) fail(EC.PROPERTY, E.INVALID_ARRAY_INDEX)
		return [values[index - 1]]
	}

	// WriteProperty semantics: clause 15.9.1.3.
	write(pid, index, values, priority) {
		if (!this.props.has(pid)) fail(EC.PROPERTY, E.UNKNOWN_PROPERTY)
		const w = this.writable.get(pid)
		if (!w) fail(EC.PROPERTY, E.WRITE_ACCESS_DENIED)
		if (index !== undefined && index !== ARRAY_ALL && !this.arrays.has(pid)) fail(EC.PROPERTY, E.PROPERTY_IS_NOT_AN_ARRAY)
		if (!values || values.length !== 1) fail(EC.PROPERTY, E.INVALID_DATA_TYPE)
		w(values[0], priority, index)
	}
}

const statusFlags = (o) => bits(4, [...(o.eventState && o.eventState !== pkg.EventState.NORMAL ? [0] : []), ...(o.outOfService ? [3] : [])])

class Device extends BObject {
	constructor(dev, fx) {
		super(dev, O.DEVICE, fx.device_instance, fx.device_name, fx.description_device)
		this.base()
		this.define(P.SYSTEM_STATUS, () => [enm(pkg.DeviceStatus.OPERATIONAL)])
		this.define(P.VENDOR_NAME, () => [str('otfabric bacnet-interop')])
		this.define(P.VENDOR_IDENTIFIER, () => [uns(VENDOR_ID)])
		this.define(P.MODEL_NAME, () => [str('bacnet-interop bacnet-js adapter')])
		this.define(P.FIRMWARE_REVISION, () => [str(L.PEER_VERSION)])
		this.define(P.APPLICATION_SOFTWARE_VERSION, () => [str(L.ADAPTER_VERSION)])
		this.define(P.PROTOCOL_VERSION, () => [uns(1)])
		this.define(P.PROTOCOL_REVISION, () => [uns(14)])
		this.define(P.PROTOCOL_SERVICES_SUPPORTED, () => [{ type: T.BIT_STRING, value: servicesSupported() }])
		this.define(P.PROTOCOL_OBJECT_TYPES_SUPPORTED, () => [{ type: T.BIT_STRING, value: objectTypesSupported(dev) }])
		this.define(P.OBJECT_LIST, () => dev.list().map((o) => oidv(o.type, o.instance)), { array: true })
		this.define(P.MAX_APDU_LENGTH_ACCEPTED, () => [uns(DEVICE_MAX_APDU)])
		this.define(P.SEGMENTATION_SUPPORTED, () => [enm(SEGMENTATION)])
		this.define(P.APDU_TIMEOUT, () => [uns(3000)])
		// Upstream retransmits nothing (request-manager.ts).
		this.define(P.NUMBER_OF_APDU_RETRIES, () => [uns(0)])
		this.define(P.DEVICE_ADDRESS_BINDING, () => [])
		this.define(P.DATABASE_REVISION, () => [uns(dev.databaseRevision)])
		this.finish()
	}
}

// Upstream's bit string classes (bitstring.ts) for the two Device bit
// strings; the bit numbers are the upstream ServicesSupported and
// ObjectTypesSupported enumerations.
function servicesSupported() {
	const X = pkg.ServicesSupported
	const bs = new pkg.ServicesSupportedBitString(
		X.WHO_IS,
		X.WHO_HAS,
		X.READ_PROPERTY,
		X.READ_PROPERTY_MULTIPLE,
		X.WRITE_PROPERTY,
		X.WRITE_PROPERTY_MULTIPLE,
		X.SUBSCRIBE_COV,
		X.SUBSCRIBE_COV_PROPERTY,
		X.READ_RANGE,
		X.DEVICE_COMMUNICATION_CONTROL,
		X.REINITIALIZE_DEVICE,
		X.ATOMIC_READ_FILE,
		X.ATOMIC_WRITE_FILE,
		X.CREATE_OBJECT,
		X.DELETE_OBJECT,
		X.GET_EVENT_INFORMATION,
		X.ACKNOWLEDGE_ALARM,
		X.GET_ALARM_SUMMARY,
		X.GET_ENROLLMENT_SUMMARY,
		X.TIME_SYNCHRONIZATION,
		X.UTC_TIME_SYNCHRONIZATION,
		X.CONFIRMED_PRIVATE_TRANSFER,
		X.UNCONFIRMED_PRIVATE_TRANSFER,
	)
	return { bitsUsed: bs.bitsUsed, value: bs.value }
}

function objectTypesSupported(dev) {
	const types = [...new Set(dev.list().map((o) => o.type))]
	const bs = new pkg.ObjectTypesSupportedBitString(...types)
	return { bitsUsed: bs.bitsUsed, value: bs.value }
}

// Analog Value (clause 12.4), commandable (clause 19.2) unless the fixture
// says "commandable": false, as in the other device adapters, and with
// OUT_OF_RANGE intrinsic reporting (clause 13.3.6).
class AnalogValue extends BObject {
	constructor(dev, o) {
		super(dev, O.ANALOG_VALUE, o.instance, o.object_name, o.description)
		this.relinquish = typeof o.present_value === 'number' ? o.present_value : 0
		this.pv = this.relinquish
		this.commandable = o.commandable !== false
		this.priority = new Array(16).fill(null)
		this.outOfService = false
		this.covIncrement = o.cov_increment !== undefined ? o.cov_increment : 1.0
		this.eventState = pkg.EventState.NORMAL
		this.base()
		this.define(P.PRESENT_VALUE, () => [real(this.value())], { write: (v, prio) => this.writePV(v, prio) })
		this.define(P.STATUS_FLAGS, () => [statusFlags(this)])
		this.define(P.EVENT_STATE, () => [enm(this.eventState)])
		this.define(P.OUT_OF_SERVICE, () => [bool(this.outOfService)], {
			write: (v) => {
				if (v.type !== T.BOOLEAN) fail(EC.PROPERTY, E.INVALID_DATA_TYPE)
				this.outOfService = !!v.value
			},
		})
		this.define(P.DESCRIPTION, () => [str(this.description || '')], {
			write: (v) => {
				if (v.type !== T.CHARACTER_STRING) fail(EC.PROPERTY, E.INVALID_DATA_TYPE)
				this.description = v.value
			},
		})
		this.define(P.UNITS, () => [enm(pkg.EngineeringUnits.NO_UNITS)])
		this.define(P.COV_INCREMENT, () => [real(this.covIncrement)], {
			write: (v) => {
				if (v.type !== T.REAL) fail(EC.PROPERTY, E.INVALID_DATA_TYPE)
				if (v.value < 0) fail(EC.PROPERTY, E.VALUE_OUT_OF_RANGE)
				this.covIncrement = v.value
			},
		})
		if (this.commandable) {
			this.define(P.PRIORITY_ARRAY, () => this.priority.map((v) => (v === null ? { type: T.NULL, value: null } : real(v))), { array: true })
			this.define(P.RELINQUISH_DEFAULT, () => [real(this.relinquish)])
		}
		const ir = o.intrinsic_reporting
		if (ir) {
			this.ir = {
				nc: ir.notification_class,
				high: ir.high_limit,
				low: ir.low_limit,
				deadband: ir.deadband,
				timeDelay: ir.time_delay || 0,
				acked: [true, true, true],
				stamps: [0, 0, 0].map(() => ({ type: pkg.TimeStamp.SEQUENCE_NUMBER, value: 0 })),
			}
			this.define(P.HIGH_LIMIT, () => [real(this.ir.high)])
			this.define(P.LOW_LIMIT, () => [real(this.ir.low)])
			this.define(P.DEADBAND, () => [real(this.ir.deadband)])
			this.define(P.TIME_DELAY, () => [uns(this.ir.timeDelay)])
			this.define(P.NOTIFICATION_CLASS, () => [uns(this.ir.nc)])
			this.define(P.LIMIT_ENABLE, () => [bits(2, [0, 1])])
			this.define(P.EVENT_ENABLE, () => [bits(3, [0, 1, 2])])
			this.define(P.ACKED_TRANSITIONS, () => [this.ackedBits()])
			this.define(P.NOTIFY_TYPE, () => [enm(pkg.NotifyType.ALARM)])
			this.define(P.EVENT_TIME_STAMPS, () => this.ir.stamps.map(stamp), { array: true })
			this.define(P.EVENT_DETECTION_ENABLE, () => [bool(true)])
		}
		this.finish()
	}

	ackedBits() {
		return bits(3, [0, 1, 2].filter((i) => this.ir.acked[i]))
	}

	value() {
		if (!this.commandable) return this.pv
		const v = this.priority.find((x) => x !== null)
		return v === undefined ? this.relinquish : v
	}

	// Clause 19.2: a NULL relinquishes a commandable slot; priority 6 is
	// reserved for Minimum On/Off (clause 19.2.3).
	writePV(v, prio) {
		const before = this.value()
		if (this.commandable) {
			const p = prio >= 1 && prio <= 16 ? prio : 16
			if (p === 6) fail(EC.PROPERTY, E.WRITE_ACCESS_DENIED)
			if (v.type === T.NULL) this.priority[p - 1] = null
			else if (v.type === T.REAL) this.priority[p - 1] = v.value
			else fail(EC.PROPERTY, E.INVALID_DATA_TYPE)
		} else {
			if (v.type !== T.REAL) fail(EC.PROPERTY, E.INVALID_DATA_TYPE)
			this.pv = v.value
		}
		this.dev.changed(this, before)
		this.evaluate()
	}

	// OUT_OF_RANGE (clause 13.3.6) with Time_Delay 0 (the fixtures'), so
	// transitions are immediate.
	evaluate() {
		if (!this.ir) return
		const v = this.value()
		const ES = pkg.EventState
		let next = this.eventState
		if (this.eventState === ES.NORMAL) {
			if (v > this.ir.high) next = ES.HIGH_LIMIT
			else if (v < this.ir.low) next = ES.LOW_LIMIT
		} else if (this.eventState === ES.HIGH_LIMIT) {
			if (v < this.ir.high - this.ir.deadband) next = ES.NORMAL
		} else if (this.eventState === ES.LOW_LIMIT) {
			if (v > this.ir.low + this.ir.deadband) next = ES.NORMAL
		}
		if (next === this.eventState) return
		const before = this.eventState
		this.eventState = next
		const slot = next === ES.NORMAL ? 2 : 0
		this.ir.stamps[slot] = nowStamp()
		const nc = this.dev.get(O.NOTIFICATION_CLASS, this.ir.nc)
		this.ir.acked[slot] = !(nc && nc.ackRequired[slot])
		emitOperation('event-state-transition', 'changed', {
			object: L.objectRef({ type: this.type, instance: this.instance }),
			from: L.enumName(pkg.EventState, before),
			to: L.enumName(pkg.EventState, next),
		})
		// Status_Flags changed: COV subscribers get it (clause 13.1.2).
		this.dev.notifyAll(this)
	}
}

class BinaryValue extends BObject {
	constructor(dev, o) {
		super(dev, O.BINARY_VALUE, o.instance, o.object_name, o.description)
		this.relinquish = o.present_value === 'active' ? pkg.BinaryPV.ACTIVE : pkg.BinaryPV.INACTIVE
		this.priority = new Array(16).fill(null)
		this.outOfService = false
		this.eventState = pkg.EventState.NORMAL
		this.base()
		this.define(P.PRESENT_VALUE, () => [enm(this.value())], {
			// Commandable (clause 19.2), as the Analog Value.
			write: (v, prio) => {
				const p = prio >= 1 && prio <= 16 ? prio : 16
				if (p === 6) fail(EC.PROPERTY, E.WRITE_ACCESS_DENIED)
				const before = this.value()
				if (v.type === T.NULL) this.priority[p - 1] = null
				else if (v.type !== T.ENUMERATED) fail(EC.PROPERTY, E.INVALID_DATA_TYPE)
				else if (v.value > 1) fail(EC.PROPERTY, E.VALUE_OUT_OF_RANGE)
				else this.priority[p - 1] = v.value
				this.dev.changed(this, before)
			},
		})
		this.define(P.STATUS_FLAGS, () => [statusFlags(this)])
		this.define(P.EVENT_STATE, () => [enm(this.eventState)])
		this.define(P.OUT_OF_SERVICE, () => [bool(this.outOfService)])
		this.define(P.PRIORITY_ARRAY, () => this.priority.map((v) => (v === null ? { type: T.NULL, value: null } : enm(v))), { array: true })
		this.define(P.RELINQUISH_DEFAULT, () => [enm(this.relinquish)])
		this.finish()
	}

	value() {
		const v = this.priority.find((x) => x !== null)
		return v === undefined ? this.relinquish : v
	}
}

// Notification Class (clause 12.21). Recipient_List stays empty: upstream
// has no BACnetDestination encoder, and AddListElement cannot be decoded
// into one (README.md).
class NotificationClass extends BObject {
	constructor(dev, o) {
		super(dev, O.NOTIFICATION_CLASS, o.instance, o.object_name, o.description)
		this.priorities = o.priority || [255, 255, 255]
		this.ackRequired = [true, true, true]
		this.base()
		this.define(P.NOTIFICATION_CLASS, () => [uns(this.instance)])
		this.define(P.PRIORITY, () => this.priorities.map(uns), { array: true })
		this.define(P.ACK_REQUIRED, () => [bits(3, [0, 1, 2].filter((i) => this.ackRequired[i]))])
		this.define(P.RECIPIENT_LIST, () => [])
		this.finish()
	}
}

// Trend Log (clause 12.25); Log_Buffer is read with ReadRange only.
class TrendLog extends BObject {
	constructor(dev, o) {
		super(dev, O.TREND_LOG, o.instance, o.object_name, o.description)
		this.records = (o.log_buffer || defaultLog()).map((r) => ({ at: localDate(r.timestamp), real: r.real }))
		this.eventState = pkg.EventState.NORMAL
		this.base()
		this.define(P.ENABLE, () => [bool(true)])
		this.define(P.STOP_WHEN_FULL, () => [bool(false)])
		this.define(P.BUFFER_SIZE, () => [uns(this.records.length)])
		this.define(P.LOG_BUFFER, () => [])
		this.define(P.RECORD_COUNT, () => [uns(this.records.length)])
		this.define(P.TOTAL_RECORD_COUNT, () => [uns(this.records.length)])
		this.define(P.LOGGING_TYPE, () => [enm(0)])
		this.define(P.LOG_INTERVAL, () => [uns(90000)])
		this.define(P.STATUS_FLAGS, () => [statusFlags(this)])
		this.define(P.EVENT_STATE, () => [enm(this.eventState)])
		this.finish()
	}
}

// A fixture trend log without log_buffer: ten REAL records every 15
// minutes from 2009-01-01T00:00:00, the shape device-server-v1 records.
function defaultLog() {
	return Array.from({ length: 10 }, (_, k) => {
		const m = k * 15
		return { timestamp: `2009-01-01T${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}:00`, real: k }
	})
}

// File (clause 12.13).
class FileObject extends BObject {
	constructor(dev, o) {
		super(dev, O.FILE, o.instance, o.object_name, o.description)
		this.stream = o.access_method !== 'record'
		this.data = this.stream ? Buffer.from(o.stream_data_base64 || '', 'base64') : null
		this.recs = this.stream ? null : (o.records || []).map((r) => Buffer.from(r))
		this.modified = new Date()
		this.base()
		this.define(P.FILE_TYPE, () => [str(this.stream ? 'stream' : 'record')])
		this.define(P.FILE_SIZE, () => [uns(this.stream ? this.data.length : this.recs.reduce((n, r) => n + r.length, 0))])
		this.define(P.MODIFICATION_DATE, () => [{ type: T.DATETIME, value: this.modified }])
		this.define(P.ARCHIVE, () => [bool(false)])
		this.define(P.READ_ONLY, () => [bool(false)])
		this.define(P.FILE_ACCESS_METHOD, () => [enm(this.stream ? 1 : 0)])
		if (!this.stream) this.define(P.RECORD_COUNT, () => [uns(this.recs.length)])
		this.finish()
	}
}

// --- the device ---------------------------------------------------------

class DeviceModel {
	constructor(fx) {
		this.fx = fx
		this.objects = new Map()
		this.databaseRevision = 1
		this.subs = []
		this.dcc = { state: pkg.EnableDisable.ENABLE, until: 0 }
		this.created = new Set()
		const life = fx.object_lifecycle || {}
		this.creatable = new Set((life.creatable_types || []).map((t) => L.enumValue(O, t)))
		this.protected = new Set((life.protected_objects || []).map((p) => `${L.enumValue(O, p.type)}:${p.instance}`))
		this.range = life.allocated_instance_range || { minimum: 100, maximum: 199 }
		this.add(new Device(this, fx))
		for (const o of fx.objects || []) {
			if (o.type === 'device') continue
			const make = {
				'analog-value': AnalogValue,
				'binary-value': BinaryValue,
				'notification-class': NotificationClass,
				'trend-log': TrendLog,
				file: FileObject,
			}[o.type]
			if (!make) {
				L.log(`fixture object ${o.type},${o.instance} skipped: the adapter models no ${o.type}`)
				continue
			}
			this.add(new make(this, o))
		}
	}

	add(o) {
		this.objects.set(o.key(), o)
		if (o.type === O.DEVICE) this.device = o
	}

	list() {
		return [...this.objects.values()]
	}

	get(type, instance) {
		// The Device can be addressed with the wildcard instance 4194303
		// (clause 12.11.1).
		if (type === O.DEVICE && instance === 4194303) return this.device
		return this.objects.get(`${type}:${instance}`)
	}

	need(oid) {
		const o = oid && this.get(oid.type, oid.instance)
		if (!o) fail(EC.OBJECT, E.UNKNOWN_OBJECT)
		return o
	}

	initiationDisabled() {
		if (this.dcc.until && Date.now() >= this.dcc.until) this.dcc = { state: pkg.EnableDisable.ENABLE, until: 0 }
		return this.dcc.state !== pkg.EnableDisable.ENABLE
	}

	// COV reporting (clause 13.1): Present_Value by COV_Increment for
	// Analog Value (13.1.4), any change for Binary Value.
	changed(o, before) {
		const after = o.value()
		for (const s of this.live()) {
			if (s.object !== o) continue
			const inc = s.increment !== undefined ? s.increment : o.covIncrement
			const moved = o.type === O.ANALOG_VALUE ? Math.abs(after - s.last) >= (inc || 0) && after !== s.last : after !== s.last
			if (moved) this.notify(s)
		}
		void before
	}

	notifyAll(o) {
		for (const s of this.live()) if (s.object === o) this.notify(s)
	}

	live() {
		const now = Date.now()
		this.subs = this.subs.filter((s) => !s.expires || s.expires > now)
		return this.subs
	}

	notify(s) {
		const o = s.object
		s.last = o.value ? o.value() : undefined
		if (this.initiationDisabled()) return
		const pid = s.property !== undefined ? s.property : P.PRESENT_VALUE
		const values = [
			{ property: { id: pid }, value: o.read(pid) },
			{ property: { id: P.STATUS_FLAGS }, value: o.read(P.STATUS_FLAGS) },
		]
		if (pid === P.STATUS_FLAGS) values.pop()
		const remaining = s.expires ? Math.max(0, Math.round((s.expires - Date.now()) / 1000)) : 0
		const oid = { type: o.type, instance: o.instance }
		if (s.confirmed) {
			this.client
				.confirmedCOVNotification(s.address, oid, s.processId, this.device.instance, remaining, values)
				.then(() => emitOperation('confirmed-cov-notification', 'acknowledged', { process_id: s.processId }))
				.catch((e) => emitOperation('confirmed-cov-notification', `failed:${e.message}`, { process_id: s.processId }))
		} else {
			this.client.unconfirmedCOVNotification(s.address, s.processId, this.device.instance, oid, remaining, values)
		}
	}
}

// --- replies ------------------------------------------------------------

class Server {
	constructor(model, client) {
		this.m = model
		this.c = client
		model.client = client
	}

	// A ComplexACK built with upstream encoders into a buffer the adapter
	// sizes, checked against the requester's Max_APDU_Length_Accepted
	// before it is sent (upstream's response methods write into a
	// 1482-octet buffer and check nothing). A reply that does not fit is
	// an Abort segmentation-not-supported (clauses 5.2, 5.4.5): upstream
	// cannot send a segmented message.
	complexAck(msg, service, body) {
		const buf = L.scratch()
		L.npdu.encode(buf, pkg.NpduControlPriority.NORMAL_MESSAGE, msg.header.sender)
		const start = buf.offset
		L.apdu.encodeComplexAck(buf, pkg.PduType.COMPLEX_ACK, service, msg.invokeId)
		body(buf)
		const limit = Math.min(L.MAX_APDU_OCTETS[msg.maxApdu] || 50, DEVICE_MAX_APDU)
		if (buf.offset - start > limit) {
			emitOperation('reply-too-long', 'abort', { service: L.enumName(C, service), octets: buf.offset - start, limit })
			return this.abort(msg, pkg.AbortReason.SEGMENTATION_NOT_SUPPORTED)
		}
		this.c.sendBvlc(msg.header.sender, buf)
	}

	abort(msg, reason) {
		const buf = L.scratch()
		L.npdu.encode(buf, pkg.NpduControlPriority.NORMAL_MESSAGE, msg.header.sender)
		// Server-originated Abort: SRV bit set (clause 20.1.9).
		L.apdu.encodeAbort(buf, pkg.PduType.ABORT | 1, msg.invokeId, reason)
		this.c.sendBvlc(msg.header.sender, buf)
	}

	// Upstream encodes no Reject PDU (apdu.ts has encodeAbort only); the
	// three octets of clause 20.1.8 are written here (adapter-shim).
	reject(msg, reason) {
		const buf = L.scratch()
		L.npdu.encode(buf, pkg.NpduControlPriority.NORMAL_MESSAGE, msg.header.sender)
		buf.buffer[buf.offset++] = pkg.PduType.REJECT
		buf.buffer[buf.offset++] = msg.invokeId
		buf.buffer[buf.offset++] = reason
		this.c.sendBvlc(msg.header.sender, buf)
	}

	ack(msg) {
		this.c.simpleAckResponse(msg.header.sender, msg.service, msg.invokeId)
	}

	error(msg, f) {
		this.c.errorResponse(msg.header.sender, msg.service, msg.invokeId, f.cls, f.code)
	}

	// An Error PDU whose service has its own error type (WritePropertyMultiple-
	// Error, CreateObject-Error, clause 21): upstream's errorResponse writes
	// the plain Error, so the sequence is written with upstream's asn1
	// primitives (adapter-shim).
	errorWith(msg, f, extra) {
		const buf = L.scratch()
		L.npdu.encode(buf, pkg.NpduControlPriority.NORMAL_MESSAGE, msg.header.sender)
		L.apdu.encodeError(buf, pkg.PduType.ERROR, msg.service, msg.invokeId)
		A.encodeOpeningTag(buf, 0)
		A.encodeApplicationEnumerated(buf, f.cls)
		A.encodeApplicationEnumerated(buf, f.code)
		A.encodeClosingTag(buf, 0)
		extra(buf)
		this.c.sendBvlc(msg.header.sender, buf)
	}

	// Runs a confirmed handler: a Fail becomes an Error PDU; anything else
	// is logged and becomes an Abort other, never silence.
	confirmed(name, fn) {
		this.c.on(name, (msg) => {
			try {
				fn(msg)
			} catch (e) {
				if (e instanceof Fail) {
					if (msg.header.expectingReply) this.error(msg, e)
					return
				}
				L.log(`${name}: ${e.stack || e.message}`)
				if (msg.header.expectingReply) this.abort(msg, pkg.AbortReason.OTHER)
			}
		})
	}

	install() {
		const c = this.c
		const m = this.m

		c.on('whoIs', (msg) => {
			const p = msg.payload || {}
			const id = m.device.instance
			if (p.lowLimit !== undefined && (id < p.lowLimit || id > p.highLimit)) return
			c.iAmResponse(msg.header.sender, id, SEGMENTATION, VENDOR_ID)
		})

		c.on('whoHas', (msg) => {
			const p = msg.payload || {}
			const id = m.device.instance
			if (p.lowLimit !== undefined && (id < p.lowLimit || id > p.highLimit)) return
			let o
			if (p.objectId) o = m.get(p.objectId.type, p.objectId.instance)
			else if (p.objectName !== undefined) o = m.list().find((x) => x.name === p.objectName)
			if (!o) return
			c.iHaveResponse(msg.header.sender, { type: O.DEVICE, instance: id }, { type: o.type, instance: o.instance }, o.name)
		})

		this.confirmed('readProperty', (msg) => {
			const p = msg.payload
			const o = m.need(p.objectId)
			const values = o.read(p.property.id, p.property.index)
			this.complexAck(msg, C.READ_PROPERTY, (buf) =>
				S.ReadProperty.encodeAcknowledge(buf, { type: o.type, instance: o.instance }, p.property.id, p.property.index, values),
			)
		})

		this.confirmed('readPropertyMultiple', (msg) => {
			const results = msg.payload.properties.map((spec) => this.readAccess(spec))
			this.complexAck(msg, C.READ_PROPERTY_MULTIPLE, (buf) => S.ReadPropertyMultiple.encodeAcknowledge(buf, results))
		})

		this.confirmed('writeProperty', (msg) => {
			const p = msg.payload
			const o = m.need(p.objectId)
			o.write(p.value.property.id, p.value.property.index, p.value.value, p.value.priority)
			this.ack(msg)
		})

		// Answered from the tap (wpmFromTap); the listener only keeps
		// upstream from answering a request it did decode.
		c.on('writePropertyMultiple', (msg) => {
			// A request upstream reassembled from segments is not on the tap
			// as one datagram: upstream's decoder read its first
			// specification, which is all a single-specification request has.
			if (this.unsegmentedOnTap(msg)) return
			try {
				this.applyWrites(msg, [msg.payload])
			} catch (e) {
				if (e instanceof Fail) return this.error(msg, e)
				L.log(`writePropertyMultiple: ${e.stack || e.message}`)
				this.abort(msg, pkg.AbortReason.OTHER)
			}
		})
		this.confirmed('subscribeCov', (msg) => this.subscribe(msg, false))
		this.confirmed('subscribeProperty', (msg) => this.subscribe(msg, true))
		this.confirmed('readRange', (msg) => this.readRange(msg))
		this.confirmed('deviceCommunicationControl', (msg) => this.dcc(msg))
		this.confirmed('reinitializeDevice', (msg) => this.reinitialize(msg))
		this.confirmed('atomicReadFile', (msg) => this.readFile(msg))
		this.confirmed('atomicWriteFile', (msg) => this.writeFile(msg))
		this.confirmed('createObject', (msg) => this.createObject(msg))
		this.confirmed('deleteObject', (msg) => this.deleteObject(msg))
		this.confirmed('getEventInformation', (msg) => this.eventInformation(msg))
		this.confirmed('alarmAcknowledge', (msg) => this.acknowledge(msg))
		this.confirmed('getAlarmSummary', (msg) => this.alarmSummary(msg))
		this.confirmed('getEnrollmentSummary', (msg) => this.enrollmentSummary(msg))

		c.on('timeSync', (msg) => emitOperation('time-synchronization', 'accepted', { time: msg.payload.value }))
		c.on('timeSyncUTC', (msg) => emitOperation('utc-time-synchronization', 'accepted', { time: msg.payload.value }))

		// One upstream event for both private transfers (client.ts service maps).
		this.confirmed('privateTransfer', (msg) => {
			const p = msg.payload
			const fields = { vendor_id: p.vendorId, service_number: p.serviceNumber, data: p.data }
			if (!msg.header.expectingReply) {
				emitOperation('unconfirmed-private-transfer', 'accepted', fields)
				return
			}
			emitOperation('confirmed-private-transfer', 'acknowledged', fields)
			// ConfirmedPrivateTransfer-ACK (clause 16.2.1.2) without a result
			// block; upstream has no encoder for it (adapter-shim).
			this.complexAck(msg, C.CONFIRMED_PRIVATE_TRANSFER, (buf) => {
				A.encodeContextUnsigned(buf, 0, p.vendorId)
				A.encodeContextUnsigned(buf, 1, p.serviceNumber)
			})
		})
	}

	// One ReadAccessResult (clause 15.7.1.3); a property error is reported in
	// the result, an unknown object as an error for each property.
	readAccess(spec) {
		const m = this.m
		const o = m.get(spec.objectId.type, spec.objectId.instance)
		const values = []
		const err = (f) => [{ value: { type: 'BacnetError', errorClass: f.cls, errorCode: f.code } }]
		for (const prop of spec.properties) {
			if (!o) {
				values.push({ property: prop, value: err(new Fail(EC.OBJECT, E.UNKNOWN_OBJECT)) })
				continue
			}
			let ids = [prop.id]
			if (prop.id === P.ALL || prop.id === P.REQUIRED || prop.id === P.OPTIONAL) {
				ids = [P.OBJECT_IDENTIFIER, P.OBJECT_NAME, P.OBJECT_TYPE, ...o.read(P.PROPERTY_LIST).map((v) => v.value)].filter((id) => id !== P.LOG_BUFFER)
			}
			for (const id of ids) {
				const index = ids.length === 1 ? prop.index : ARRAY_ALL
				try {
					values.push({ property: { id, index }, value: o.read(id, index) })
				} catch (e) {
					if (!(e instanceof Fail)) throw e
					values.push({ property: { id, index }, value: err(e) })
				}
			}
		}
		return { objectId: spec.objectId, values }
	}

	// WritePropertyMultiple (clause 15.10). Upstream's
	// WritePropertyMultiple.decode does not stop at the closing tag [1] of
	// the first WriteAccessSpecification (it loops on the APDU length), so a
	// request with two or more specifications does not decode and upstream
	// drops it without an event (client.ts _processServiceRequest). The
	// adapter takes the request from the raw-datagram tap, finds each
	// specification's end and decodes it alone with upstream's decoder
	// (adapter-shim). Segmented WPM requests are not handled.
	wpmFromTap(datagram, address) {
		const a = L.locateApdu(datagram)
		if (!a || (a.type & pkg.PDU_TYPE_MASK) !== pkg.PduType.CONFIRMED_REQUEST) return
		if (a.buffer[a.offset] & pkg.PduConReqBit.SEGMENTED_MESSAGE) return
		if (a.buffer[a.offset + 3] !== C.WRITE_PROPERTY_MULTIPLE) return
		const b = L.bvlc.decode(datagram, 0)
		const msg = {
			header: {
				sender: { address, forwardedFrom: b.func === pkg.BvlcResultPurpose.FORWARDED_NPDU ? b.originatingIP : null },
				expectingReply: true,
			},
			invokeId: a.buffer[a.offset + 2],
			service: C.WRITE_PROPERTY_MULTIPLE,
			maxApdu: a.buffer[a.offset + 1] & 0x0f,
		}
		try {
			this.writePropertyMultiple(msg, a.buffer, a.offset + 4, a.offset + a.length)
		} catch (e) {
			if (e instanceof Fail) return this.error(msg, e)
			L.log(`writePropertyMultiple: ${e.stack || e.message}`)
			this.abort(msg, pkg.AbortReason.OTHER)
		}
	}

	writePropertyMultiple(msg, buffer, body, end) {
		const specs = []
		let off = body
		while (off < end) {
			const len = specLength(buffer, off, end)
			const spec = S.WritePropertyMultiple.decode(buffer, off, len)
			if (!spec) return this.reject(msg, pkg.RejectReason.INVALID_TAG)
			specs.push(spec)
			off += len
		}
		if (!specs.length) return this.reject(msg, pkg.RejectReason.MISSING_REQUIRED_PARAMETER)
		this.applyWrites(msg, specs)
	}

	unsegmentedOnTap(msg) {
		return !!this.tap.find(msg.header.sender.address, (x) => {
			if ((x.type & pkg.PDU_TYPE_MASK) !== pkg.PduType.CONFIRMED_REQUEST) return false
			if (x.buffer[x.offset] & pkg.PduConReqBit.SEGMENTED_MESSAGE) return false
			return x.buffer[x.offset + 2] === msg.invokeId && x.buffer[x.offset + 3] === C.WRITE_PROPERTY_MULTIPLE
		})
	}

	applyWrites(msg, specs) {
		for (const spec of specs) {
			for (const v of spec.values) {
				try {
					const o = this.m.need(spec.objectId)
					o.write(v.property.id, v.property.index, v.value, v.priority === pkg.ASN1_NO_PRIORITY ? 16 : v.priority)
				} catch (e) {
					if (!(e instanceof Fail)) throw e
					// WritePropertyMultiple-Error (clause 15.10.1.3.1): writes
					// before the failed one stay done.
					return this.errorWith(msg, e, (buf) => {
						A.encodeOpeningTag(buf, 1)
						A.encodeContextObjectId(buf, 0, spec.objectId.type, spec.objectId.instance)
						A.encodeContextEnumerated(buf, 1, v.property.id)
						if (v.property.index !== ARRAY_ALL) A.encodeContextUnsigned(buf, 2, v.property.index)
						A.encodeClosingTag(buf, 1)
					})
				}
			}
		}
		this.ack(msg)
	}

	// SubscribeCOV (clause 13.14) and SubscribeCOVProperty (clause 13.15).
	subscribe(msg, byProperty) {
		const p = msg.payload
		const m = this.m
		const o = m.need(p.monitoredObjectId)
		const sender = msg.header.sender
		let pid
		if (byProperty) {
			pid = p.monitoredProperty.id
			if (!o.props.has(pid)) fail(EC.PROPERTY, E.UNKNOWN_PROPERTY)
			if (pid !== P.PRESENT_VALUE && pid !== P.STATUS_FLAGS) fail(EC.PROPERTY, E.NOT_COV_PROPERTY)
		}
		if (o.type !== O.ANALOG_VALUE && o.type !== O.BINARY_VALUE) fail(EC.OBJECT, E.OPTIONAL_FUNCTIONALITY_NOT_SUPPORTED)
		const same = (s) =>
			s.address.address === sender.address && s.processId === p.subscriberProcessId && s.object === o && s.property === pid
		m.subs = m.subs.filter((s) => !same(s))
		if (p.cancellationRequest) {
			this.ack(msg)
			return
		}
		const s = {
			address: { address: sender.address, forwardedFrom: sender.forwardedFrom },
			processId: p.subscriberProcessId,
			object: o,
			property: pid,
			confirmed: !!p.issueConfirmedNotifications,
			expires: p.lifetime ? Date.now() + p.lifetime * 1000 : 0,
			increment: byProperty && p.covIncrement !== undefined ? p.covIncrement : undefined,
			last: o.value(),
		}
		m.subs.push(s)
		this.ack(msg)
		// The initial notification after the subscription (clauses
		// 13.14.1.1.4, 13.15.1.1.5 ... a new subscription is answered with a
		// notification of the current value).
		setImmediate(() => m.notify(s))
	}

	// ReadRange (clause 15.8) on Log_Buffer by position, by sequence number
	// (positions are sequence numbers: nothing is purged) and by time.
	readRange(msg) {
		const p = msg.payload
		const o = this.m.need(p.objectId)
		const pid = p.property.id
		if (!o.props.has(pid)) fail(EC.PROPERTY, E.UNKNOWN_PROPERTY)
		if (o.type !== O.TREND_LOG || pid !== P.LOG_BUFFER) fail(EC.SERVICES, E.PROPERTY_IS_NOT_A_LIST)
		const recs = o.records
		const n = recs.length
		let first
		let last
		const RT = pkg.ReadRangeType
		if (p.requestType === undefined) {
			first = 1
			last = n
		} else if (p.requestType === RT.BY_POSITION || p.requestType === RT.BY_SEQUENCE_NUMBER) {
			if (p.count === 0) fail(EC.SERVICES, E.VALUE_OUT_OF_RANGE)
			if (p.count > 0) {
				first = p.position
				last = Math.min(n, p.position + p.count - 1)
			} else {
				first = Math.max(1, p.position + p.count + 1)
				last = Math.min(n, p.position)
			}
		} else {
			const t = p.time.getTime()
			if (p.count > 0) {
				first = recs.findIndex((r) => r.at.getTime() > t) + 1
				last = first ? Math.min(n, first + p.count - 1) : 0
			} else {
				let k = n
				while (k > 0 && recs[k - 1].at.getTime() >= t) k--
				last = k
				first = Math.max(1, k + p.count + 1)
			}
		}
		const items = first >= 1 && first <= last && first <= n ? recs.slice(first - 1, last) : []
		const data = { buffer: Buffer.alloc(64 * 1024), offset: 0 }
		for (const r of items) {
			// BACnetLogRecord (clause 12.25.14): timestamp [0], logDatum [1]
			// real-value [2]; upstream has the primitives but no encoder.
			A.encodeOpeningTag(data, 0)
			A.encodeApplicationDate(data, r.at)
			A.encodeApplicationTime(data, r.at)
			A.encodeClosingTag(data, 0)
			A.encodeOpeningTag(data, 1)
			A.encodeContextReal(data, 2, r.real)
			A.encodeClosingTag(data, 1)
		}
		// Result Flags of the ReadRange-ACK (clause 15.8): FIRST_ITEM and LAST_ITEM say
		// whether the first and last records of the buffer are returned;
		// MORE_ITEMS is for items that matched the request but could not be
		// returned. Every matching item is returned (or the reply Aborts as
		// too long), so MORE_ITEMS stays clear, as on the other peers.
		const set = []
		if (items.length && first === 1) set.push(0)
		if (items.length && last === n) set.push(1)
		this.complexAck(msg, C.READ_RANGE, (buf) =>
			S.ReadRange.encodeAcknowledge(
				buf,
				{ type: o.type, instance: o.instance },
				pid,
				p.property.index,
				L.bitString(3, set),
				items.length,
				data.buffer.subarray(0, data.offset),
				p.requestType,
				first,
			),
		)
	}

	// DeviceCommunicationControl (clause 16.1). DISABLE is refused: the
	// adapter cannot stop upstream from answering (and 135-2024 deprecates
	// it, clause 16.1.1.1.2).
	dcc(msg) {
		const p = msg.payload
		const ED = pkg.EnableDisable
		if (p.enableDisable === ED.DISABLE) fail(EC.SERVICES, E.SERVICE_REQUEST_DENIED)
		if (p.enableDisable !== ED.ENABLE && p.enableDisable !== ED.DISABLE_INITIATION) {
			return this.reject(msg, pkg.RejectReason.UNDEFINED_ENUMERATION)
		}
		this.m.dcc = { state: p.enableDisable, until: p.timeDuration ? Date.now() + p.timeDuration * 60000 : 0 }
		emitOperation('device-communication-control', L.enumName(ED, p.enableDisable), { duration: p.timeDuration || 0 })
		this.ack(msg)
	}

	// ReinitializeDevice (clause 16.4): coldstart and warmstart are
	// acknowledged and logged (the process does not restart); backup and
	// restore are not supported; other values are no BACnetReinitializedState.
	reinitialize(msg) {
		const st = msg.payload.state
		const RS = pkg.ReinitializedState
		if (st === RS.COLDSTART || st === RS.WARMSTART) {
			emitOperation('reinitialize-device', L.enumName(RS, st))
			return this.ack(msg)
		}
		if (st >= RS.STARTBACKUP && st <= RS.ACTIVATE_CHANGES) fail(EC.SERVICES, E.OPTIONAL_FUNCTIONALITY_NOT_SUPPORTED)
		this.reject(msg, pkg.RejectReason.UNDEFINED_ENUMERATION)
	}

	// AtomicReadFile (clause 14.1).
	readFile(msg) {
		const p = msg.payload
		const o = this.m.need(p.objectId)
		if (o.type !== O.FILE) fail(EC.SERVICES, E.INCONSISTENT_OBJECT_TYPE)
		if (p.isStream !== o.stream) fail(EC.SERVICES, E.INVALID_FILE_ACCESS_METHOD)
		if (o.stream) {
			if (p.position < 0 || p.position > o.data.length) fail(EC.SERVICES, E.INVALID_FILE_START_POSITION)
			const chunk = o.data.subarray(p.position, p.position + Math.max(0, p.count))
			const eof = p.position + chunk.length >= o.data.length
			return this.complexAck(msg, C.ATOMIC_READ_FILE, (buf) =>
				S.AtomicReadFile.encodeAcknowledge(buf, true, eof, p.position, 1, [Array.from(chunk)], [chunk.length]),
			)
		}
		if (p.position < 0 || p.position >= o.recs.length) fail(EC.SERVICES, E.INVALID_FILE_START_POSITION)
		const recs = o.recs.slice(p.position, p.position + Math.max(0, p.count))
		const eof = p.position + recs.length >= o.recs.length
		this.complexAck(msg, C.ATOMIC_READ_FILE, (buf) =>
			S.AtomicReadFile.encodeAcknowledge(
				buf,
				false,
				eof,
				p.position,
				recs.length,
				recs.map((r) => Array.from(r)),
				recs.map((r) => r.length),
			),
		)
	}

	// AtomicWriteFile (clause 14.2); a start position of -1 appends.
	writeFile(msg) {
		const p = msg.payload
		const o = this.m.need(p.objectId)
		if (o.type !== O.FILE) fail(EC.SERVICES, E.INCONSISTENT_OBJECT_TYPE)
		if (p.isStream !== o.stream) fail(EC.SERVICES, E.INVALID_FILE_ACCESS_METHOD)
		let start = p.position
		if (o.stream) {
			if (start === -1) start = o.data.length
			if (start < 0 || start > o.data.length) fail(EC.SERVICES, E.INVALID_FILE_START_POSITION)
			const data = Buffer.from(p.blocks[0] || [])
			const out = Buffer.alloc(Math.max(o.data.length, start + data.length))
			o.data.copy(out)
			data.copy(out, start)
			o.data = out
		} else {
			if (start === -1) start = o.recs.length
			if (start < 0 || start > o.recs.length) fail(EC.SERVICES, E.INVALID_FILE_START_POSITION)
			p.blocks.forEach((b, i) => {
				o.recs[start + i] = Buffer.from(b)
			})
		}
		o.modified = new Date()
		emitOperation('atomic-write-file', 'written', { object: L.objectRef(p.objectId), start, octets: p.blocks.reduce((n, b) => n + b.length, 0) })
		this.complexAck(msg, C.ATOMIC_WRITE_FILE, (buf) => S.AtomicWriteFile.encodeAcknowledge(buf, o.stream, start))
	}

	// CreateObject (clause 15.3). Upstream's decoder reads the
	// objectIdentifier choice [1] only and requires listOfInitialValues.
	createObject(msg) {
		const m = this.m
		const p = msg.payload
		const coError = (f, element) =>
			this.errorWith(msg, f, (buf) => {
				A.encodeContextUnsigned(buf, 1, element)
			})
		const type = p.objectId.type
		if (!m.creatable.has(type)) return coError(new Fail(EC.OBJECT, E.DYNAMIC_CREATION_NOT_SUPPORTED), 0)
		let inst = p.objectId.instance
		if (inst === undefined || inst === 4194303) {
			inst = m.range.minimum
			while (inst <= m.range.maximum && m.get(type, inst)) inst++
			if (inst > m.range.maximum) return coError(new Fail(EC.RESOURCES, E.NO_SPACE_FOR_OBJECT), 0)
		} else if (m.get(type, inst)) {
			return coError(new Fail(EC.OBJECT, E.OBJECT_IDENTIFIER_ALREADY_EXISTS), 0)
		}
		const o = new AnalogValue(m, { instance: inst, object_name: `AV-${inst}`, present_value: 0 })
		for (let i = 0; i < (p.values || []).length; i++) {
			const v = p.values[i]
			try {
				if (v.property.id === P.OBJECT_NAME) {
					if (!v.value[0] || v.value[0].type !== T.CHARACTER_STRING) fail(EC.PROPERTY, E.INVALID_DATA_TYPE)
					o.name = v.value[0].value
				} else {
					o.write(v.property.id, v.property.index, v.value, v.priority)
				}
			} catch (e) {
				if (!(e instanceof Fail)) throw e
				return coError(e, i + 1)
			}
		}
		m.add(o)
		m.created.add(o.key())
		m.databaseRevision++
		emitOperation('create-object', 'created', { object: L.objectRef({ type, instance: inst }) })
		this.complexAck(msg, C.CREATE_OBJECT, (buf) => S.CreateObject.encodeAcknowledge(buf, { type, instance: inst }))
	}

	// DeleteObject (clause 15.4): only objects CreateObject made.
	deleteObject(msg) {
		const m = this.m
		const p = msg.payload
		const o = m.need({ type: p.objectType, instance: p.instance })
		if (m.protected.has(o.key()) || !m.created.has(o.key())) fail(EC.OBJECT, E.OBJECT_DELETION_NOT_PERMITTED)
		m.objects.delete(o.key())
		m.created.delete(o.key())
		m.subs = m.subs.filter((s) => s.object !== o)
		m.databaseRevision++
		emitOperation('delete-object', 'deleted', { object: L.objectRef({ type: o.type, instance: o.instance }) })
		this.ack(msg)
	}

	alarming() {
		return this.m.list().filter((o) => o.ir)
	}

	priorities(o) {
		const nc = this.m.get(O.NOTIFICATION_CLASS, o.ir.nc)
		return nc ? nc.priorities : [255, 255, 255]
	}

	// GetEventInformation (clause 13.12): objects not normal or with an
	// unacknowledged transition, after lastReceivedObjectIdentifier.
	eventInformation(msg) {
		const last = msg.payload && msg.payload.lastReceivedObjectId
		let list = this.alarming().filter((o) => o.eventState !== pkg.EventState.NORMAL || o.ir.acked.includes(false))
		if (last) {
			const k = list.findIndex((o) => o.type === last.type && o.instance === last.instance)
			list = k >= 0 ? list.slice(k + 1) : list
		}
		const events = list.map((o) => ({
			objectId: { type: o.type, instance: o.instance },
			eventState: o.eventState,
			acknowledgedTransitions: o.ackedBits().value,
			eventTimeStamps: o.ir.stamps,
			notifyType: pkg.NotifyType.ALARM,
			eventEnable: L.bitString(3, [0, 1, 2]),
			eventPriorities: this.priorities(o),
		}))
		this.complexAck(msg, C.GET_EVENT_INFORMATION, (buf) => S.GetEventInformation.encodeAcknowledge(buf, events, false))
	}

	// AcknowledgeAlarm (clause 13.5).
	acknowledge(msg) {
		const p = msg.payload
		const o = this.m.need(p.eventObjectId)
		if (!o.ir) fail(EC.OBJECT, E.NO_ALARM_CONFIGURED)
		const ES = pkg.EventState
		const st = p.eventStateAcknowledged
		// The transition the acknowledged state belongs to (Event_Time_Stamps
		// and Acked_Transitions order: to-offnormal, to-fault, to-normal).
		const slot = st === ES.NORMAL ? 2 : st === ES.FAULT ? 1 : 0
		if (!sameStamp(p.eventTimeStamp, o.ir.stamps[slot])) fail(EC.SERVICES, E.INVALID_TIMESTAMP)
		o.ir.acked[slot] = true
		emitOperation('acknowledge-alarm', 'acknowledged', {
			object: L.objectRef(p.eventObjectId),
			process_id: p.acknowledgedProcessId,
			source: p.acknowledgeSource,
		})
		this.ack(msg)
	}

	// GetAlarmSummary (clause 13.10). upstream's AlarmSummary.encode writes
	// the three values with context tags 12, 9 and 8 where the ACK has
	// application tags (README.md); it is used as it is.
	alarmSummary(msg) {
		const alarms = this.alarming()
			.filter((o) => o.eventState !== pkg.EventState.NORMAL)
			.map((o) => ({ objectId: { type: o.type, instance: o.instance }, alarmState: o.eventState, acknowledgedTransitions: o.ackedBits().value }))
		this.complexAck(msg, C.GET_ALARM_SUMMARY, (buf) => S.AlarmSummary.encode(buf, alarms))
	}

	// GetEnrollmentSummary (clause 13.11) with the filters upstream decodes.
	enrollmentSummary(msg) {
		const p = msg.payload
		const ES = pkg.EventState
		const AF = { ALL: 0, ACKED: 1, NOT_ACKED: 2 }
		const SF = { OFFNORMAL: 0, FAULT: 1, NORMAL: 2, ALL: 3, ACTIVE: 4 }
		const summaries = []
		for (const o of this.alarming()) {
			const notAcked = o.ir.acked.includes(false)
			if (p.acknowledgmentFilter === AF.ACKED && notAcked) continue
			if (p.acknowledgmentFilter === AF.NOT_ACKED && !notAcked) continue
			const sf = p.eventStateFilter
			if (sf !== undefined && sf !== SF.ALL) {
				const off = o.eventState !== ES.NORMAL && o.eventState !== ES.FAULT
				if (sf === SF.OFFNORMAL && !off) continue
				if (sf === SF.FAULT && o.eventState !== ES.FAULT) continue
				if (sf === SF.NORMAL && o.eventState !== ES.NORMAL) continue
				if (sf === SF.ACTIVE && o.eventState === ES.NORMAL) continue
			}
			if (p.eventTypeFilter !== undefined && p.eventTypeFilter !== pkg.EventType.OUT_OF_RANGE) continue
			if (p.notificationClassFilter !== undefined && p.notificationClassFilter !== o.ir.nc) continue
			const prio = this.priorities(o)
			const priority = o.eventState === ES.NORMAL ? prio[2] : o.eventState === ES.FAULT ? prio[1] : prio[0]
			if (p.priorityFilter && (priority < p.priorityFilter.min || priority > p.priorityFilter.max)) continue
			summaries.push({
				objectId: { type: o.type, instance: o.instance },
				eventType: pkg.EventType.OUT_OF_RANGE,
				eventState: o.eventState,
				priority,
				notificationClass: o.ir.nc,
			})
		}
		this.complexAck(msg, C.GET_ENROLLMENT_SUMMARY, (buf) => S.GetEnrollmentSummary.encodeAcknowledge(buf, summaries))
	}
}

// The length of one WriteAccessSpecification at off: objectIdentifier [0]
// and the constructed listOfProperties [1] up to its closing tag.
function specLength(buf, off, end) {
	let p = off
	let depth = 0
	let started = false
	while (p < end) {
		const t = A.decodeTagNumberAndValue(buf, p)
		if (A.decodeIsOpeningTag(buf, p)) {
			depth++
			started = true
			p += t.len
			continue
		}
		if (A.decodeIsClosingTag(buf, p)) {
			depth--
			p += t.len
			if (started && depth === 0) return p - off
			continue
		}
		const appBoolean = !A.decodeIsContextTag(buf, p, t.tagNumber) && t.tagNumber === T.BOOLEAN
		p += t.len + (appBoolean ? 0 : t.value)
	}
	return end - off
}

function directedBroadcast() {
	for (const list of Object.values(os.networkInterfaces())) {
		for (const a of list || []) {
			if (a.family !== 'IPv4' || a.internal) continue
			const ip = a.address.split('.').map(Number)
			const mask = a.netmask.split('.').map(Number)
			return ip.map((o, i) => (o & mask[i]) | (~mask[i] & 255)).join('.')
		}
	}
	return '255.255.255.255'
}

function main() {
	const fixtureId = process.env.FIXTURE || 'device-baseline-v2'
	const file = process.env.DEVICE_FIXTURE_FILE || `/fixtures/device/${fixtureId}.json`
	const port = Number(process.env.BACNET_IP_PORT || '47808')
	let fx
	try {
		fx = JSON.parse(fs.readFileSync(file, 'utf8'))
		if (!Number.isInteger(fx.device_instance) || typeof fx.device_name !== 'string') {
			throw new Error('device fixture requires device_instance and device_name')
		}
	} catch (e) {
		L.log(`bacnet-js adapter: cannot load fixture ${file}: ${e.message}`)
		process.exit(1)
	}
	const model = new DeviceModel(fx)
	const transport = new L.Transport({ port, interface: '0.0.0.0', broadcastAddress: directedBroadcast(), reuseAddr: true })
	const tap = new L.Tap(transport, 64)
	const client = new L.BACnetClient({ transport, apduTimeout: 3000 })
	client.on('error', (e) => L.log('bacnet-js error:', e.message))
	const server = new Server(model, client)
	server.tap = tap
	server.install()
	tap.listeners.push((datagram, address) => server.wpmFromTap(datagram, address))
	transport.once('listening', () => {
		L.emit({
			event: 'ready',
			adapter: ADAPTER,
			version: L.ADAPTER_VERSION,
			fixture: String(fx.fixture || fixtureId),
			address: `0.0.0.0:${port}`,
			peer_version: L.PEER_VERSION,
		})
	})
	transport.once('error', (e) => {
		L.log(`bacnet-js adapter: cannot bind UDP ${port}: ${e.message}`)
		process.exit(1)
	})
	const stop = () => {
		client.close()
		process.exit(0)
	}
	process.on('SIGTERM', stop)
	process.on('SIGINT', stop)
}

module.exports = { DeviceModel, Server, specLength, Fail }

if (require.main === module) main()
