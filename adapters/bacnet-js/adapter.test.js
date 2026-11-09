// SPDX-License-Identifier: MIT
'use strict'

// Unit tests of the adapter code (node:test, run in the image build).
// Wire behaviour is tested against peers (scripts/smoke-test.sh,
// scripts/client-matrix.py, the consumers' interop suites).

const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('path')
const fs = require('fs')
const L = require('./lib')
const client = require('./client')
const device = require('./device')

const { pkg, services: S, asn1: A } = L
const P = pkg.PropertyIdentifier
const O = pkg.ObjectType
const T = pkg.ApplicationTag

const FIXTURES = process.env.FIXTURES_DIR || path.join(__dirname, '..', '..', 'fixtures', 'device')
const fixture = (id) => JSON.parse(fs.readFileSync(path.join(FIXTURES, `${id}.json`), 'utf8'))

test('enumeration names round-trip', () => {
	assert.equal(L.enumValue(pkg.ObjectType, 'analog-value'), O.ANALOG_VALUE)
	assert.equal(L.enumName(pkg.ObjectType, O.ANALOG_VALUE), 'analog-value')
	assert.equal(L.propertyId(9999), 9999)
	assert.deepEqual(L.objectId('trend-log,1'), { type: O.TREND_LOG, instance: 1 })
	assert.throws(() => L.enumValue(pkg.ObjectType, 'no-such-type'))
})

test('bit strings are LSB first per octet', () => {
	const bs = L.bitString(10, [0, 9])
	assert.deepEqual(bs, { bitsUsed: 10, value: [1, 2] })
	assert.deepEqual(L.bits(bs), [1, 0, 0, 0, 0, 0, 0, 0, 0, 1])
})

test('sender addresses always carry the port', () => {
	assert.equal(L.hostport('10.0.0.1'), '10.0.0.1:47808')
	assert.equal(L.hostport('10.0.0.1:47809'), '10.0.0.1:47809')
})

test('client arguments follow the driver contract', () => {
	const a = client.parseArgs(['--target', '10.0.0.2:47808', '--device', '1234', '--scenarios', 'x.json'])
	assert.equal(a.device, 1234)
	assert.equal(a.fdTtl, 60)
	assert.throws(() => client.parseArgs(['--device', '1', '--scenarios', 'x', '--fd-ttl', '0']))
	assert.throws(() => client.parseArgs(['--device', '1', '--scenarios', 'x', '--target', 'host:47808']))
	assert.throws(() => client.parseArgs(['--scenarios', 'x']))
})

test('comparison', () => {
	assert.ok(client.compare({ value: { type: 'real', value: 21.5 } }, { value: { type: 'real', value: 21.500001 } }))
	assert.ok(!client.compare({ value: { type: 'real', value: 21.5 } }, { value: { type: 'unsigned', value: 21.5 } }))
	assert.ok(client.compare({ reject: 'Undefined Enumeration' }, { reject: 'undefined-enumeration' }))
	assert.ok(client.compare({ error: { class: 'object', code: 'unknown-object' } }, { error: { class: 'object', code: 'unknown-object' } }))
	assert.ok(!client.compare({ error: { class: 'object', code: 'unknown-object', first_failed: {} } }, { error: { class: 'object', code: 'unknown-object' } }))
	assert.ok(client.compare({ 'i-am': [1234] }, { 'i-am': [1234] }))
	assert.ok(!client.compare({ 'i-am': [] }, { 'i-am': [1234] }))
	assert.ok(client.compare({ subscribed: { notification: false } }, { subscribed: { notification: true } }))
	assert.ok(!client.compare({ subscribed: { notification: true } }, { subscribed: { notification: false } }))
	assert.ok(client.compare({ 'i-have': [{ device: 1, object: 'analog-value,1' }] }, { 'i-have': [{ device: 1, object: 'analog-value,1' }] }))
})

test('log-datum choices are recovered from ReadRange item data', () => {
	const b = { buffer: Buffer.alloc(256), offset: 0 }
	for (const [tag, enc] of [
		[2, (x) => A.encodeContextReal(x, 2, 1.5)],
		[4, (x) => A.encodeContextUnsigned(x, 4, 7)],
	]) {
		A.encodeOpeningTag(b, 0)
		A.encodeApplicationDate(b, new Date(2009, 0, 1))
		A.encodeApplicationTime(b, new Date(2009, 0, 1))
		A.encodeClosingTag(b, 0)
		A.encodeOpeningTag(b, 1)
		enc(b)
		A.encodeClosingTag(b, 1)
		void tag
	}
	assert.deepEqual(client.datumChoices(b.buffer.subarray(0, b.offset)), [2, 4])
})

test('each WriteAccessSpecification is decoded alone', () => {
	const b = { buffer: Buffer.alloc(256), offset: 0 }
	const v = (x) => [{ property: { id: P.PRESENT_VALUE, index: pkg.ASN1_ARRAY_ALL }, value: [{ type: T.REAL, value: x }], priority: 8 }]
	S.WritePropertyMultiple.encode(b, { type: O.ANALOG_VALUE, instance: 1 }, v(1))
	const first = b.offset
	S.WritePropertyMultiple.encode(b, { type: O.ANALOG_VALUE, instance: 999 }, v(2))
	assert.equal(device.specLength(b.buffer, 0, b.offset), first)
	const second = S.WritePropertyMultiple.decode(b.buffer, first, device.specLength(b.buffer, first, b.offset))
	assert.equal(second.objectId.instance, 999)
	assert.equal(second.values[0].value[0].value, 2)
})

test('device-server-v1 object model', () => {
	const m = new device.DeviceModel(fixture('device-server-v1'))
	const av1 = m.get(O.ANALOG_VALUE, 1)
	assert.equal(av1.read(P.PRESENT_VALUE)[0].value, 21.5)
	assert.throws(() => av1.read(P.PRESENT_VALUE, 1), (e) => e.code === pkg.ErrorCode.PROPERTY_IS_NOT_AN_ARRAY)
	assert.throws(() => av1.read(9999), (e) => e.code === pkg.ErrorCode.UNKNOWN_PROPERTY)
	assert.equal(av1.read(P.PRIORITY_ARRAY, 0)[0].value, 16)
	av1.write(P.PRESENT_VALUE, pkg.ASN1_ARRAY_ALL, [{ type: T.REAL, value: 42 }], 8)
	assert.equal(av1.read(P.PRESENT_VALUE)[0].value, 42)
	av1.write(P.PRESENT_VALUE, pkg.ASN1_ARRAY_ALL, [{ type: T.NULL, value: null }], 8)
	assert.equal(av1.read(P.PRESENT_VALUE)[0].value, 21.5)
	assert.throws(
		() => av1.write(P.PRESENT_VALUE, pkg.ASN1_ARRAY_ALL, [{ type: T.CHARACTER_STRING, value: 'x' }], 8),
		(e) => e.code === pkg.ErrorCode.INVALID_DATA_TYPE,
	)
	assert.throws(() => av1.write(P.OBJECT_NAME, pkg.ASN1_ARRAY_ALL, [{ type: T.CHARACTER_STRING, value: 'x' }]), (e) => e.code === pkg.ErrorCode.WRITE_ACCESS_DENIED)

	const av2 = m.get(O.ANALOG_VALUE, 2)
	av2.write(P.PRESENT_VALUE, pkg.ASN1_ARRAY_ALL, [{ type: T.REAL, value: 90 }], 16)
	assert.equal(av2.eventState, pkg.EventState.HIGH_LIMIT)
	assert.equal(av2.ir.acked[0], false)
	av2.write(P.PRESENT_VALUE, pkg.ASN1_ARRAY_ALL, [{ type: T.REAL, value: 50 }], 16)
	assert.equal(av2.eventState, pkg.EventState.NORMAL)

	const dev = m.get(O.DEVICE, 1234)
	assert.equal(dev.read(P.OBJECT_LIST, 0)[0].value, 9)
	assert.equal(m.get(O.DEVICE, 4194303), dev)
	assert.equal(m.get(O.TREND_LOG, 1).records.length, 10)
	assert.throws(() => m.get(O.TREND_LOG, 1).read(P.LOG_BUFFER), (e) => e.code === pkg.ErrorCode.READ_ACCESS_DENIED)
	for (const o of m.list()) {
		for (const pid of o.props.keys()) {
			if (pid === P.LOG_BUFFER) continue
			const buf = L.scratch()
			S.ReadProperty.encodeAcknowledge(buf, { type: o.type, instance: o.instance }, pid, pkg.ASN1_ARRAY_ALL, o.read(pid))
		}
	}
})

// A fake upstream client records what the Server sends.
function fakeServer(id) {
	const sent = []
	const handlers = {}
	const c = {
		on: (name, fn) => (handlers[name] = fn),
		sendBvlc: (r, buf) => sent.push({ kind: 'bvlc', buf: Buffer.from(buf.buffer.subarray(0, buf.offset)) }),
		simpleAckResponse: (r, service, invokeId) => sent.push({ kind: 'ack', service, invokeId }),
		errorResponse: (r, service, invokeId, cls, code) => sent.push({ kind: 'error', service, invokeId, cls, code }),
		iAmResponse: (r, inst) => sent.push({ kind: 'iam', inst }),
		iHaveResponse: (r, d, o, name) => sent.push({ kind: 'ihave', o, name }),
		unconfirmedCOVNotification: (...a) => sent.push({ kind: 'cov', a }),
		confirmedCOVNotification: () => Promise.resolve(),
	}
	const s = new device.Server(new device.DeviceModel(fixture(id)), c)
	s.install()
	const msg = (service, payload, extra = {}) => ({
		header: { sender: { address: '10.0.0.9', forwardedFrom: null }, expectingReply: true },
		invokeId: 5,
		service,
		maxApdu: 5,
		payload,
		...extra,
	})
	return { s, sent, handlers, msg }
}

const C = pkg.ConfirmedServiceChoice

test('server: discovery honours the Who-Is range', () => {
	const { sent, handlers } = fakeServer('device-baseline-v2')
	handlers.whoIs({ header: { sender: {} }, payload: { lowLimit: 5000, highLimit: 5000 } })
	handlers.whoIs({ header: { sender: {} }, payload: {} })
	handlers.whoHas({ header: { sender: {} }, payload: { objectName: 'AV-1' } })
	handlers.whoHas({ header: { sender: {} }, payload: { objectName: 'NoSuchName' } })
	assert.deepEqual(
		sent.map((x) => x.kind),
		['iam', 'ihave'],
	)
})

test('server: errors and rejects', () => {
	const { sent, handlers, msg } = fakeServer('device-server-v1')
	handlers.readProperty(msg(C.READ_PROPERTY, { objectId: { type: O.ANALOG_VALUE, instance: 999 }, property: { id: P.PRESENT_VALUE, index: pkg.ASN1_ARRAY_ALL } }))
	assert.equal(sent.pop().code, pkg.ErrorCode.UNKNOWN_OBJECT)
	handlers.reinitializeDevice(msg(C.REINITIALIZE_DEVICE, { state: 9 }))
	const rej = sent.pop().buf
	assert.equal(rej[rej.length - 3], pkg.PduType.REJECT)
	assert.equal(rej[rej.length - 1], pkg.RejectReason.UNDEFINED_ENUMERATION)
	handlers.deviceCommunicationControl(msg(C.DEVICE_COMMUNICATION_CONTROL, { enableDisable: pkg.EnableDisable.DISABLE, timeDuration: 1 }))
	assert.equal(sent.pop().code, pkg.ErrorCode.SERVICE_REQUEST_DENIED)
	handlers.readRange(msg(C.READ_RANGE, { objectId: { type: O.ANALOG_VALUE, instance: 1 }, property: { id: P.PRESENT_VALUE, index: pkg.ASN1_ARRAY_ALL }, requestType: 0, position: 1, count: 1 }))
	assert.equal(sent.pop().code, pkg.ErrorCode.PROPERTY_IS_NOT_A_LIST)
	handlers.deleteObject(msg(C.DELETE_OBJECT, { objectType: O.DEVICE, instance: 1234 }))
	assert.equal(sent.pop().code, pkg.ErrorCode.OBJECT_DELETION_NOT_PERMITTED)
	handlers.alarmAcknowledge(msg(C.ACKNOWLEDGE_ALARM, { eventObjectId: { type: O.ANALOG_VALUE, instance: 1 }, eventStateAcknowledged: 3 }))
	assert.equal(sent.pop().code, pkg.ErrorCode.NO_ALARM_CONFIGURED)
})

test('server: an ACK larger than the requester accepts is an Abort', () => {
	const { sent, handlers, msg } = fakeServer('device-server-v1')
	handlers.atomicReadFile(msg(C.ATOMIC_READ_FILE, { isStream: true, objectId: { type: O.FILE, instance: 3 }, position: 0, count: 3000 }))
	const abort = sent.pop().buf
	assert.equal(abort[abort.length - 3] & 0xf0, pkg.PduType.ABORT)
	assert.equal(abort[abort.length - 1], pkg.AbortReason.SEGMENTATION_NOT_SUPPORTED)
	handlers.atomicReadFile(msg(C.ATOMIC_READ_FILE, { isStream: false, objectId: { type: O.FILE, instance: 2 }, position: 0, count: 3 }))
	assert.equal(sent.pop().kind, 'bvlc')
	handlers.atomicReadFile(msg(C.ATOMIC_READ_FILE, { isStream: true, objectId: { type: O.FILE, instance: 2 }, position: 0, count: 3 }))
	assert.equal(sent.pop().code, pkg.ErrorCode.INVALID_FILE_ACCESS_METHOD)
})

test('server: object lifecycle', () => {
	const { s, sent, handlers, msg } = fakeServer('device-server-v1')
	handlers.createObject(msg(C.CREATE_OBJECT, { objectId: { type: O.ANALOG_VALUE, instance: 150 }, values: [] }))
	assert.equal(sent.pop().kind, 'bvlc')
	assert.ok(s.m.get(O.ANALOG_VALUE, 150))
	handlers.createObject(msg(C.CREATE_OBJECT, { objectId: { type: O.BINARY_VALUE, instance: 5 }, values: [] }))
	// BVLC (4, filled by sendBvlc) + NPDU (2), then the CreateObject-Error:
	// [0] { class object, code dynamic-creation-not-supported } [1] 0.
	const err = sent.pop().buf.subarray(6)
	assert.deepEqual([...err], [pkg.PduType.ERROR, 5, C.CREATE_OBJECT, 0x0e, 0x91, 1, 0x91, 4, 0x0f, 0x19, 0])
	handlers.deleteObject(msg(C.DELETE_OBJECT, { objectType: O.ANALOG_VALUE, instance: 150 }))
	assert.equal(sent.pop().kind, 'ack')
	handlers.deleteObject(msg(C.DELETE_OBJECT, { objectType: O.ANALOG_VALUE, instance: 150 }))
	assert.equal(sent.pop().code, pkg.ErrorCode.UNKNOWN_OBJECT)
})
