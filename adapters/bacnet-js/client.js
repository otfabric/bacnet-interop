// SPDX-License-Identifier: MIT
'use strict'

// bacnet-js client mode (docs/CLIENT_DRIVER_CONTRACT.md).
//
// Runs one upstream BACnetClient (@bacnet-js/client, unmodified) against a
// device under test (DUT) and turns what it decoded into result lines.
// Requests are the BACnetClient's public methods wherever one can express
// the scenario. Three requests the public API cannot express are assembled
// from upstream encoders (services/*, npdu, apdu) and sent through the
// client's own transaction machinery (marked adapter-shim in
// adapters/inventory.yaml): Who-Has (WhoHas.encode exists, no client
// method), SubscribeCOVProperty with a lifetime and COV increment
// (subscribeProperty() hard-codes lifetime 0 and no increment) and ReadRange
// of a property other than Log_Buffer (readRange() hard-codes Log_Buffer).
// What upstream cannot encode at all is `unsupported`, never a pass.
//
// Upstream reports a Reject and an Abort alike ("BacnetAbort - Reason:N",
// client.ts _handlePdu); the adapter tells them apart by the PDU type of
// the answer on the wire, read from the raw-datagram tap with upstream's
// BVLC, NPDU and APDU decoders.

const fs = require('fs')
const os = require('os')
const L = require('./lib')

const { pkg, services: S } = L
const ADAPTER = 'bacnet-js'
const OUTCOMES = ['pass', 'fail', 'unsupported', 'not-tested', 'known-difference', 'infra-error']
const CLIENT_PORT = 47808
const FILE_CHUNK = 480

class Infra extends Error {}
class Unsupported extends Error {}
class KnownDifference extends Error {
	constructor(message, observed) {
		super(message)
		this.observed = observed
	}
}

// A scenario whose precondition another scenario establishes: when that one
// did not pass, this one is not-tested (a read-back of a write this client
// could not issue proves nothing).
const DEPENDS_ON = {
	'rp.nc1.recipient-list': 'ale.nc1',
	'rp.nc1.recipient-list.after-remove': 'rle.nc1',
	'arf.file1.after-write': 'awf.file1',
	'arf.file3.after-write': 'awf.file3.segmented-request',
}

const { hostport } = L

function sleep(ms) {
	return new Promise((r) => setTimeout(r, ms))
}

// The directed broadcast address of the interface that reaches towards.
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

class Env {
	constructor(args, timeoutMs, retries) {
		this.args = args
		this.timeoutMs = timeoutMs
		this.retries = retries
		this.listenMs = Math.max(2000, timeoutMs)
		this.target = args.target ? { address: args.target } : null
		this.invoke = 0
		this.iAms = []
		this.iHaves = []
		this.covs = []
		this.bound = false
		this.bindDetail = ''
		this.dutMaxApdu = 1476
	}

	start() {
		// Transport.send() splits "ip:port"; a broadcast goes to this address.
		const broadcastAddress = this.args.broadcast || directedBroadcast()
		this.transport = new L.Transport({
			port: CLIENT_PORT,
			interface: '0.0.0.0',
			broadcastAddress,
			reuseAddr: true,
		})
		this.tap = new L.Tap(this.transport, 256)
		this.client = new L.BACnetClient({ transport: this.transport, apduTimeout: this.timeoutMs })
		this.client.on('error', (err) => L.log('bacnet-js error:', err.message))
		this.client.on('iAm', (m) => this.iAms.push({ at: Date.now(), from: hostport(m.header.sender.address), payload: m.payload }))
		this.client.on('iHave', (m) => this.iHaves.push({ at: Date.now(), from: hostport(m.header.sender.address), payload: m.payload }))
		this.client.on('covNotifyUnconfirmed', (m) => this.cov(m))
		this.client.on('covNotify', (m) => {
			this.cov(m)
			// A ConfirmedCOVNotification is acknowledged (clause 13.7).
			this.client.simpleAckResponse(m.header.sender, m.service, m.invokeId)
		})
		return new Promise((resolve, reject) => {
			this.transport.once('listening', resolve)
			this.transport.once('error', reject)
		})
	}

	cov(m) {
		this.covs.push({ at: Date.now(), from: hostport(m.header.sender.address), payload: m.payload })
	}

	async register() {
		if (!this.args.bbmd) return
		try {
			await this.client.registerForeignDevice({ address: this.args.bbmd }, this.args.fdTtl)
		} catch (e) {
			throw new Infra(`Register-Foreign-Device: ${e.message}`)
		}
	}

	// Invoke IDs 1..255: upstream treats 0 as "no invoke ID given" (options.invokeId || ...).
	nextInvoke() {
		this.invoke = (this.invoke % 255) + 1
		return this.invoke
	}

	// Unicast Who-Is to the target: the DUT must answer from --target.
	async bind() {
		if (this.bound) return
		if (!this.target) throw new Infra('--target is required for confirmed services')
		if (this.bindDetail) throw new Infra(this.bindDetail)
		const since = Date.now()
		this.client.whoIs(this.target, { lowLimit: this.args.device, highLimit: this.args.device })
		const deadline = since + this.timeoutMs * (this.retries + 1) + 2000
		while (Date.now() < deadline) {
			const got = this.iAms.find((i) => i.at >= since && i.payload.deviceId === this.args.device)
			if (got) {
				if (got.from !== this.args.target) {
					this.bindDetail = `I-Am for device ${this.args.device} from ${got.from}, not the target ${this.args.target}`
					throw new Infra(this.bindDetail)
				}
				this.dutMaxApdu = got.payload.maxApdu
				this.bound = true
				return
			}
			await sleep(50)
		}
		this.bindDetail = `device ${this.args.device} did not answer a Who-Is to ${this.args.target}`
		throw new Infra(this.bindDetail)
	}

	// Runs one confirmed upstream call with an invoke ID; turns its
	// rejection into an observation or an exception.
	async confirmed(fn) {
		await this.bind()
		const invokeId = this.nextInvoke()
		try {
			return { ack: await fn(invokeId), invokeId }
		} catch (e) {
			return { answer: this.answer(e, invokeId), invokeId }
		}
	}

	answer(e, invokeId) {
		const msg = String(e && e.message)
		let m = msg.match(/^BacnetError - Class:(\d+) - Code:(\d+)/)
		if (m) {
			return { error: { class: L.enumName(pkg.ErrorClass, Number(m[1])), code: L.enumName(pkg.ErrorCode, Number(m[2])) } }
		}
		m = msg.match(/^BacnetAbort - Reason:(\d+)/)
		if (m) {
			const reason = Number(m[1])
			const frame = this.tap.find(this.args.target, (a) => {
				const t = a.type & pkg.PDU_TYPE_MASK
				return (t === pkg.PduType.REJECT || t === pkg.PduType.ABORT) && a.buffer[a.offset + 1] === invokeId
			})
			if (!frame) throw new Infra(`"${msg}" with no Reject or Abort for invoke ID ${invokeId} on the wire`)
			if ((frame.type & pkg.PDU_TYPE_MASK) === pkg.PduType.REJECT) {
				return { reject: L.enumName(pkg.RejectReason, reason) }
			}
			return { abort: L.enumName(pkg.AbortReason, reason) }
		}
		if (msg === 'ERR_TIMEOUT') throw new Infra('no answer within the APDU timeout (bacnet-js has no retries)')
		if (msg === 'INVALID_DECODING') return { undecodable: 'bacnet-js could not decode the acknowledgement (INVALID_DECODING)' }
		throw new Infra(`bacnet-js: ${msg}`)
	}

	// A confirmed request assembled from upstream encoders and sent through
	// the client's request manager (the public methods do the same,
	// client.ts readProperty).
	raw(service, encodeBody) {
		return (invokeId) => {
			const buf = L.scratch()
			L.npdu.encode(buf, pkg.NpduControlPriority.NORMAL_MESSAGE | pkg.NpduControlBit.EXPECTING_REPLY, this.target)
			L.apdu.encodeConfirmedServiceRequest(
				buf,
				pkg.PduType.CONFIRMED_REQUEST | pkg.PduConReqBit.SEGMENTED_RESPONSE_ACCEPTED,
				service,
				pkg.MaxSegmentsAccepted.SEGMENTS_65,
				pkg.MaxApduLengthAccepted.OCTETS_1476,
				invokeId,
				0,
				0,
			)
			encodeBody(buf)
			const pending = this.client._requestManager.add(invokeId)
			this.client.sendBvlc(this.target, buf)
			return pending
		}
	}

	close() {
		try {
			this.client.close()
		} catch (e) {
			L.log('close:', e.message)
		}
	}
}

// --- services -----------------------------------------------------------

async function whoIs(sc, env) {
	const low = sc.low
	const high = sc.high !== undefined ? sc.high : sc.low
	const opts = low !== undefined ? { lowLimit: low, highLimit: high } : {}
	const since = Date.now()
	if (env.args.bbmd) {
		env.client.whoIsThroughBBMD({ address: env.args.bbmd }, opts)
	} else {
		env.client.whoIs(opts)
	}
	await sleep(env.listenMs)
	const devices = []
	for (const i of env.iAms.filter((x) => x.at >= since)) {
		const inst = i.payload.deviceId
		if (low !== undefined && !(low <= inst && inst <= high)) continue
		if (env.args.target && i.from !== env.args.target && !env.args.bbmd) {
			throw new Infra(`I-Am for device ${inst} from ${i.from}, not the target ${env.args.target}`)
		}
		if (!devices.includes(inst)) devices.push(inst)
	}
	return { 'i-am': devices.sort((a, b) => a - b) }
}

// Who-Has: upstream has the request encoder (services/WhoHas.ts) and the
// I-Have decoder ('iHave' event) but no client method.
async function whoHas(sc, env) {
	const buf = L.scratch()
	let receiver = null
	if (env.args.bbmd) receiver = { address: env.args.bbmd, distributeBroadcastToNetwork: true }
	// Otherwise an Original-Broadcast-NPDU to the transport's broadcast
	// address (--broadcast or the directed broadcast), as whoIs() does.
	L.npdu.encode(buf, pkg.NpduControlPriority.NORMAL_MESSAGE)
	L.apdu.encodeUnconfirmedServiceRequest(buf, pkg.PduType.UNCONFIRMED_REQUEST, pkg.UnconfirmedServiceChoice.WHO_HAS)
	const oid = sc.object ? L.objectId(sc.object) : { type: 0, instance: 0 }
	S.WhoHas.encode(buf, -1, -1, oid, sc.object ? undefined : sc.name)
	const since = Date.now()
	env.client.sendBvlc(receiver, buf)
	await sleep(env.listenMs)
	const out = []
	for (const h of env.iHaves.filter((x) => x.at >= since)) {
		const p = h.payload
		const entry = { device: p.deviceId.instance, object: L.objectRef(p.objectId) }
		if (!out.some((o) => o.device === entry.device && o.object === entry.object)) out.push(entry)
	}
	return { 'i-have': out }
}

// A BACnetDestination list as upstream decodes it: seven values per entry
// (valid days, from, to, recipient, process, confirmed, transitions).
function recipients(values) {
	const out = []
	const t = (d) => {
		const v = new Date(d.value)
		const hh = Math.round(v.getMilliseconds() / 10)
		return `${v.getHours()}:${String(v.getMinutes()).padStart(2, '0')}:${String(v.getSeconds()).padStart(2, '0')}.${String(hh).padStart(2, '0')}`
	}
	for (let i = 0; i + 7 <= values.length; i += 7) {
		const [days, from, to, rcpt, proc, conf, trans] = values.slice(i, i + 7)
		const r = rcpt.value && rcpt.value.type !== undefined ? { device: rcpt.value.instance } : { raw: rcpt.value }
		const db = L.bits(days.value)
		const tb = L.bits(trans.value)
		out.push({
			valid_days: db.map((b, k) => (b ? k + 1 : 0)).filter(Boolean),
			from_time: t(from),
			to_time: t(to),
			recipient: r,
			process_id: proc.value,
			confirmed: !!conf.value,
			transitions: ['to-offnormal', 'to-fault', 'to-normal'].filter((_, k) => tb[k]),
		})
	}
	return out
}

async function readProperty(sc, env) {
	const oid = L.objectId(sc.object)
	const pid = L.propertyId(sc.property)
	const opts = {}
	if (sc.array_index !== undefined) opts.arrayIndex = sc.array_index
	const r = await env.confirmed((invokeId) => env.client.readProperty(env.target, oid, pid, { ...opts, invokeId }))
	if (r.answer) return r.answer
	const values = r.ack.values || []
	if ('recipients' in sc.expect) return { recipients: recipients(values) }
	if (values.length === 1) return { value: L.observedValue(values[0], oid.type, pid) }
	return { value: { type: 'list', value: values.map((v) => L.observedValue(v, oid.type, pid)) } }
}

async function readPropertyMultiple(sc, env) {
	const specs = sc.reads.map((r) => ({
		objectId: L.objectId(r.object),
		properties: r.properties.map((p) => ({ id: L.propertyId(p), index: pkg.ASN1_ARRAY_ALL })),
	}))
	const r = await env.confirmed((invokeId) => env.client.readPropertyMultiple(env.target, specs, { invokeId }))
	if (r.answer) return r.answer
	const values = []
	for (const res of r.ack.values) {
		for (const p of res.values) {
			const e = { object: L.objectRef(res.objectId), property: L.propertyName(p.id) }
			const v = p.value || []
			if (v[0] && v[0].type === pkg.ApplicationTag.ERROR) {
				e.error = { class: L.enumName(pkg.ErrorClass, v[0].value.errorClass), code: L.enumName(pkg.ErrorCode, v[0].value.errorCode) }
			} else {
				e.value = L.observedValue(v[0], res.objectId.type, p.id)
			}
			values.push(e)
		}
	}
	return { values }
}

async function writeProperty(sc, env) {
	const oid = L.objectId(sc.object)
	const pid = L.propertyId(sc.property)
	const opts = {}
	if (sc.priority !== undefined) opts.priority = sc.priority
	if (sc.array_index !== undefined) opts.arrayIndex = sc.array_index
	const r = await env.confirmed((invokeId) => env.client.writeProperty(env.target, oid, pid, [L.appData(sc.value)], { ...opts, invokeId }))
	return r.answer || { ack: true }
}

async function writePropertyMultiple(sc, env) {
	const objects = []
	for (const w of sc.writes) {
		const oid = L.objectId(w.object)
		const v = {
			property: { id: L.propertyId(w.property), index: pkg.ASN1_ARRAY_ALL },
			value: [L.appData(w.value)],
			priority: w.priority !== undefined ? w.priority : pkg.ASN1_NO_PRIORITY,
		}
		const last = objects[objects.length - 1]
		if (last && last.objectId.type === oid.type && last.objectId.instance === oid.instance) last.values.push(v)
		else objects.push({ objectId: oid, values: [v] })
	}
	const r = await env.confirmed((invokeId) => env.client.writePropertyMultiple(env.target, objects, { invokeId }))
	if (r.answer && r.answer.error && sc.expect.error && sc.expect.error.first_failed) {
		// The WritePropertyMultiple-Error reaches the caller as a plain
		// error: upstream decodes every Error PDU with services/Error.ts
		// (client.ts _processError), which has no firstFailedWriteAttempt.
		throw new KnownDifference(
			'bacnet-js decodes a WritePropertyMultiple-Error with the plain Error decoder (client.ts _processError, services/Error.ts): no firstFailedWriteAttempt, and the [0] constructed errorType is read as if it were application-tagged',
			r.answer,
		)
	}
	return r.answer || { ack: true }
}

async function waitCov(env, since, oid, pid) {
	const deadline = Date.now() + env.listenMs
	while (Date.now() < deadline) {
		const got = env.covs.find(
			(c) =>
				c.at >= since &&
				c.from === env.args.target &&
				c.payload.subscriberProcessId === pid &&
				c.payload.monitoredObjectId.type === oid.type &&
				c.payload.monitoredObjectId.instance === oid.instance,
		)
		if (got) return true
		await sleep(50)
	}
	return false
}

async function subscribeCov(sc, env) {
	const oid = L.objectId(sc.object)
	const since = Date.now()
	const r = await env.confirmed((invokeId) =>
		env.client.subscribeCov(env.target, oid, sc.process_id, !!sc.cancel, !!sc.confirmed, sc.lifetime !== undefined ? sc.lifetime : 60, { invokeId }),
	)
	if (r.answer) return r.answer
	const got = sc.cancel ? false : await waitCov(env, since, oid, sc.process_id)
	return { subscribed: { notification: got } }
}

// SubscribeCOVProperty: the public subscribeProperty() hard-codes lifetime 0
// and no COV increment (client.ts subscribeProperty), so the request is
// assembled with upstream's SubscribeProperty.encode, which has both.
async function subscribeCovProperty(sc, env) {
	const oid = L.objectId(sc.object)
	const prop = { id: L.propertyId(sc.property), index: sc.array_index !== undefined ? sc.array_index : pkg.ASN1_ARRAY_ALL }
	const since = Date.now()
	const cancel = !!sc.cancel
	const r = await env.confirmed(
		env.raw(pkg.ConfirmedServiceChoice.SUBSCRIBE_COV_PROPERTY, (buf) =>
			S.SubscribeProperty.encode(
				buf,
				sc.process_id,
				oid,
				cancel,
				!!sc.confirmed,
				sc.lifetime !== undefined ? sc.lifetime : 60,
				prop,
				sc.cov_increment !== undefined,
				sc.cov_increment || 0,
			),
		),
	)
	if (r.answer) return r.answer
	const got = cancel ? false : await waitCov(env, since, oid, sc.process_id)
	return { subscribed: { notification: got } }
}

// The log-datum CHOICE tag of every record in the ReadRange-ACK itemData
// (clause 12.25.14): upstream's decodeRange returns the datum value without
// its choice, so the choice is read from the octets it returned.
const DATUM_TYPE = { 0: 'bit-string', 1: 'boolean', 2: 'real', 3: 'enumerated', 4: 'unsigned', 5: 'signed', 6: 'bit-string', 7: 'null', 8: 'error', 9: 'real', 10: 'any' }

function datumChoices(buf) {
	const A = L.asn1
	const out = []
	let depth = 0
	let off = 0
	let take = false
	while (off < buf.length) {
		const t = A.decodeTagNumberAndValue(buf, off)
		if (A.decodeIsOpeningTag(buf, off)) {
			if (take) out.push(t.tagNumber)
			take = depth === 0 && t.tagNumber === 1
			depth++
			off += t.len
			continue
		}
		if (A.decodeIsClosingTag(buf, off)) {
			depth--
			take = false
			off += t.len
			continue
		}
		if (take) out.push(t.tagNumber)
		take = false
		// A primitive: tag octets plus the length in the tag (a boolean
		// application tag carries its value in the tag).
		const appBoolean = !A.decodeIsContextTag(buf, off, t.tagNumber) && t.tagNumber === 1
		off += t.len + (appBoolean ? 0 : t.value)
	}
	return out
}

function observedRecords(ack) {
	if (!ack.values) throw new Infra('bacnet-js returned the ReadRange-ACK item data undecoded (asn1.decodeRange failed)')
	const choices = datumChoices(ack.rangeBuffer)
	const p = (n) => String(n).padStart(2, '0')
	return ack.values.map((rec, i) => {
		const ts = rec.timestamp
		const text = `${ts.getFullYear()}-${p(ts.getMonth() + 1)}-${p(ts.getDate())}T${p(ts.getHours())}:${p(ts.getMinutes())}:${p(ts.getSeconds())}`
		return { timestamp: text, value: { type: DATUM_TYPE[choices[i]] || 'unknown', value: rec.value } }
	})
}

async function readRange(sc, env) {
	const oid = L.objectId(sc.object)
	const pid = L.propertyId(sc.property)
	const rg = sc.range
	if (rg.by !== 'position') {
		throw new Unsupported(`readRange() sends by-position only (client.ts readRange); ${rg.by} is not issued`)
	}
	let r
	if (pid === pkg.PropertyIdentifier.LOG_BUFFER) {
		r = await env.confirmed((invokeId) => env.client.readRange(env.target, oid, rg.index, rg.count, { invokeId }))
	} else {
		// readRange() hard-codes Log_Buffer; the request for another
		// property is assembled with upstream's ReadRange.encode.
		r = await env.confirmed(async (invokeId) => {
			const data = await env.raw(pkg.ConfirmedServiceChoice.READ_RANGE, (buf) =>
				S.ReadRange.encode(buf, oid, pid, pkg.ASN1_ARRAY_ALL, pkg.ReadRangeType.BY_POSITION, rg.index, new Date(), rg.count),
			)(invokeId)
			const ack = S.ReadRange.decodeAcknowledge(data.buffer, data.offset, data.length)
			if (!ack) throw new Error('INVALID_DECODING')
			return ack
		})
	}
	if (r.answer) return r.answer
	return { records: observedRecords(r.ack) }
}

async function deviceCommunicationControl(sc, env) {
	const state = L.enumValue(pkg.EnableDisable, sc.state)
	const r = await env.confirmed((invokeId) =>
		env.client.deviceCommunicationControl(env.target, sc.duration || 0, state, { password: sc.password, invokeId }),
	)
	return r.answer || { ack: true }
}

async function reinitializeDevice(sc, env) {
	const r = await env.confirmed((invokeId) => env.client.reinitializeDevice(env.target, sc.state, { password: sc.password, invokeId }))
	return r.answer || { ack: true }
}

// Stream access (readFile() sends stream access only, client.ts readFile).
async function atomicReadFile(sc, env) {
	const oid = L.objectId(sc.object)
	let pos = sc.start || 0
	const single = sc.count !== undefined
	const chunks = []
	for (;;) {
		const count = single ? sc.count : FILE_CHUNK
		// readFile() leaves SEGMENTED_RESPONSE_ACCEPTED clear (client.ts
		// readFile; only readProperty and readPropertyMultiple set it), so
		// a DUT must refuse a reply that does not fit one APDU (clause
		// 5.4.5). A read that large is assembled with upstream's
		// AtomicReadFile.encode in a request that accepts segments; upstream
		// reassembles the segmented ComplexACK (client.ts _processSegment).
		const r =
			count > FILE_CHUNK
				? await env.confirmed(async (invokeId) => {
						const data = await env.raw(pkg.ConfirmedServiceChoice.ATOMIC_READ_FILE, (buf) => S.AtomicReadFile.encode(buf, true, oid, pos, count))(invokeId)
						const ack = S.AtomicReadFile.decodeAcknowledge(data.buffer, data.offset)
						if (!ack) throw new Error('INVALID_DECODING')
						return ack
					})
				: await env.confirmed((invokeId) => env.client.readFile(env.target, oid, pos, count, { invokeId }))
		if (r.answer) return r.answer
		const data = Buffer.from(r.ack.buffer)
		chunks.push(data)
		pos += data.length
		if (single || r.ack.endOfFile || data.length === 0) break
	}
	return { octets_base64: Buffer.concat(chunks).toString('base64') }
}

async function atomicWriteFile(sc, env) {
	const data = Buffer.from(sc.data_base64, 'base64')
	await env.bind()
	// BVLC 4 + NPDU 2 + APDU header 4 + object id 5 + tags ~8.
	if (data.length + 23 > Math.min(env.dutMaxApdu, 1476) + 6) {
		throw new Unsupported(
			`the request (${data.length} octets of file data) exceeds the DUT's max APDU (${env.dutMaxApdu}); bacnet-js sends no segmented requests (no client method sets SEGMENTED_MESSAGE, client.ts)`,
		)
	}
	const oid = L.objectId(sc.object)
	const r = await env.confirmed((invokeId) => env.client.writeFile(env.target, oid, sc.start || 0, [Array.from(data)], { isStream: true, invokeId }))
	return r.answer || { ack: true }
}

function listElement() {
	throw new Unsupported(
		'AddListElement.encode (also used by removeListElement) encodes every list element with bacappEncodeApplicationData, which has no context-tagged form; a BACnetDestination recipient is a context-tagged CHOICE (clause 21), so the element cannot be encoded',
	)
}

// createObject() acknowledges without decoding the CreateObject-ACK
// (CreateObject.decodeAcknowledge throws "not implemented"); the created
// object identifier is read from the ACK on the wire with upstream's
// asn1.decodeObjectId.
async function createObject(sc, env) {
	if (sc.instance === undefined) {
		throw new Unsupported('CreateObject.encode always sends the objectIdentifier choice of objectSpecifier; the objectType choice (no instance) cannot be issued')
	}
	const oid = { type: L.enumValue(pkg.ObjectType, sc.object_type), instance: sc.instance }
	const r = await env.confirmed((invokeId) => env.client.createObject(env.target, oid, [], { invokeId }))
	if (r.answer) return r.answer
	const frame = env.tap.find(env.args.target, (a) => (a.type & pkg.PDU_TYPE_MASK) === pkg.PduType.COMPLEX_ACK && a.buffer[a.offset + 1] === r.invokeId)
	if (!frame) throw new Infra('no CreateObject-ACK on the wire')
	const body = frame.offset + 3
	const tag = L.asn1.decodeTagNumberAndValue(frame.buffer, body)
	const id = L.asn1.decodeObjectId(frame.buffer, body + tag.len)
	return { created: L.objectRef({ type: id.objectType, instance: id.instance }) }
}

async function deleteObject(sc, env) {
	const r = await env.confirmed((invokeId) => env.client.deleteObject(env.target, L.objectId(sc.object), { invokeId }))
	return r.answer || { ack: true }
}

// getEventInformation() returns the summaries of one ACK; moreEvents is
// dropped (client.ts getEventInformation), so later pages are not read.
async function getEventInformation(sc, env) {
	const r = await env.confirmed((invokeId) => env.client.getEventInformation(env.target, null, { invokeId }))
	if (r.answer) return r.answer
	return { events: r.ack.map((e) => ({ object: L.objectRef(e.objectId), event_state: L.enumName(pkg.EventState, e.eventState) })) }
}

const TIME_STAMP_INDEX = { offnormal: 1, 'high-limit': 1, 'low-limit': 1, fault: 2, normal: 3 }

// acknowledgeAlarm() sends acknowledging process identifier 57 whatever the
// caller wants (client.ts acknowledgeAlarm passes 57 to
// AlarmAcknowledge.encode); the scenario's process_id is not sent.
async function acknowledgeAlarm(sc, env) {
	const oid = L.objectId(sc.object)
	const state = L.enumValue(pkg.EventState, sc.event_state_acked)
	let stamp
	let decodedDatetime = false
	if (sc.time_stamp === 'event') {
		const r = await env.confirmed((invokeId) =>
			env.client.readProperty(env.target, oid, pkg.PropertyIdentifier.EVENT_TIME_STAMPS, { arrayIndex: TIME_STAMP_INDEX[sc.event_state_acked], invokeId }),
		)
		if (r.answer) throw new Infra(`Event_Time_Stamps of ${sc.object} not readable: ${JSON.stringify(r.answer)}`)
		const v = r.ack.values[0]
		if (!v) throw new Infra('Event_Time_Stamps decoded to no value')
		if (v.type === pkg.ApplicationTag.UNSIGNED_INTEGER) stamp = { type: pkg.TimeStamp.SEQUENCE_NUMBER, value: v.value }
		else {
			stamp = { type: pkg.TimeStamp.DATETIME, value: new Date(v.value) }
			decodedDatetime = true
		}
	} else {
		stamp = { type: pkg.TimeStamp.DATETIME, value: new Date(sc.time_stamp) }
	}
	const now = { type: pkg.TimeStamp.DATETIME, value: new Date() }
	const r = await env.confirmed((invokeId) => env.client.acknowledgeAlarm(env.target, oid, state, 'interop', stamp, now, { invokeId }))
	if (decodedDatetime && r.answer && r.answer.error && L.normName(r.answer.error.code) === 'invalidtimestamp') {
		// The stamp echoed is the one upstream decoded from Event_Time_Stamps,
		// and upstream decodes a BACnetDateTime with the day of the week as
		// the day of the month (asn1.ts decodeBacnetDatetime, date.getDay()).
		throw new KnownDifference(
			`bacnet-js decodes the Event_Time_Stamps BACnetDateTime with the weekday as the day of the month (asn1.ts decodeBacnetDatetime uses date.getDay()); it echoed ${stamp.value.toISOString()} and the device answered invalid-time-stamp`,
			r.answer,
		)
	}
	return r.answer || { ack: true }
}

async function getAlarmSummary(sc, env) {
	const r = await env.confirmed((invokeId) => env.client.getAlarmSummary(env.target, { invokeId }))
	if (r.answer) return r.answer
	return { alarms: r.ack.map((a) => ({ object: L.objectRef(a.objectId), alarm_state: L.enumName(pkg.EventState, a.alarmState) })) }
}

async function getEnrollmentSummary(sc, env) {
	if (sc.event_state_filter !== undefined) {
		throw new Unsupported(
			'GetEnrollmentSummary.encode drops eventStateFilter offnormal (0) ("if (eventStateFilter)") and wraps every other filter in opening/closing tags where clause 13.11.1.1 has a primitive [2] ENUMERATED, so the filtered request cannot be issued',
		)
	}
	// acknowledgmentFilter all (0), required (clause 13.11.1.1).
	const r = await env.confirmed((invokeId) => env.client.getEnrollmentSummary(env.target, 0, { invokeId }))
	if (r.answer) return r.answer
	return {
		enrollments: r.ack.enrollmentSummaries.map((s) => ({
			object: L.objectRef(s.objectId),
			event_state: L.enumName(pkg.EventState, s.eventState),
			event_type: L.enumName(pkg.EventType, s.eventType),
			priority: s.priority,
			notification_class: s.notificationClass,
		})),
	}
}

function sent(operation) {
	return { sent: { operation } }
}

async function timeSync(sc, env, utc) {
	await env.bind()
	if (utc) env.client.timeSyncUTC(env.target, new Date())
	else env.client.timeSync(env.target, new Date())
	await sleep(200)
	return sent(utc ? 'utc-time-synchronization' : 'time-synchronization')
}

// Service parameters: the octets inside [2], encoded with upstream's
// bacappEncodeApplicationData (PrivateTransfer.encode copies them in).
function privateParameters(sc) {
	const buf = { buffer: Buffer.alloc(1476), offset: 0 }
	for (const v of sc.parameters || []) L.asn1.bacappEncodeApplicationData(buf, L.appData(v))
	return Array.from(buf.buffer.subarray(0, buf.offset))
}

async function unconfirmedPrivateTransfer(sc, env) {
	await env.bind()
	env.client.unconfirmedPrivateTransfer(env.target, sc.vendor_id, sc.service_number, privateParameters(sc))
	await sleep(200)
	return sent('unconfirmed-private-transfer')
}

async function confirmedPrivateTransfer(sc, env) {
	const r = await env.confirmed((invokeId) =>
		env.client.confirmedPrivateTransfer(env.target, sc.vendor_id, sc.service_number, privateParameters(sc), { invokeId }),
	)
	return r.answer || { ack: true }
}

function unsupported(reason) {
	return () => {
		throw new Unsupported(reason)
	}
}

const SERVICES = {
	'who-is': whoIs,
	'who-has': whoHas,
	'read-property': readProperty,
	'read-property-multiple': readPropertyMultiple,
	'write-property': writeProperty,
	'write-property-multiple': writePropertyMultiple,
	'subscribe-cov': subscribeCov,
	'subscribe-cov-property': subscribeCovProperty,
	'subscribe-cov-property-multiple': unsupported('bacnet-js 3.3.2 has no SubscribeCOVPropertyMultiple encoder and no COV-notification-multiple decoder'),
	'read-range': readRange,
	'device-communication-control': deviceCommunicationControl,
	'reinitialize-device': reinitializeDevice,
	'atomic-read-file': atomicReadFile,
	'atomic-write-file': atomicWriteFile,
	'add-list-element': listElement,
	'remove-list-element': listElement,
	'create-object': createObject,
	'delete-object': deleteObject,
	'get-event-information': getEventInformation,
	'acknowledge-alarm': acknowledgeAlarm,
	'get-alarm-summary': getAlarmSummary,
	'get-enrollment-summary': getEnrollmentSummary,
	'time-synchronization': (sc, env) => timeSync(sc, env, false),
	'utc-time-synchronization': (sc, env) => timeSync(sc, env, true),
	'unconfirmed-private-transfer': unconfirmedPrivateTransfer,
	'confirmed-private-transfer': confirmedPrivateTransfer,
	'confirmed-text-message': unsupported('bacnet-js 3.3.2 has no ConfirmedTextMessage encoder (no service in src/lib/services)'),
	'unconfirmed-text-message': unsupported('bacnet-js 3.3.2 has no UnconfirmedTextMessage encoder (no service in src/lib/services)'),
	'write-group': unsupported('bacnet-js 3.3.2 has no WriteGroup encoder (no service in src/lib/services)'),
	'read-bdt': unsupported('bacnet-js 3.3.2 has no Read-Broadcast-Distribution-Table encoder (bvlc.ts encodes the BVLC header only)'),
	'read-fdt': unsupported('bacnet-js 3.3.2 has no Read-Foreign-Device-Table encoder (bvlc.ts encodes the BVLC header only)'),
	'write-bdt': unsupported('bacnet-js 3.3.2 has no Write-Broadcast-Distribution-Table encoder (bvlc.ts encodes the BVLC header only)'),
}

// --- comparison (as in the other drivers) ----------------------------------

function normTime(s) {
	const [h, rest] = s.split(/:(.*)/s)
	return `${Number(h)}:${rest}`
}

function normDestinations(ds) {
	return ds.map((d) => ({
		...d,
		from_time: normTime(d.from_time),
		to_time: normTime(d.to_time),
		valid_days: [...d.valid_days].sort(),
		transitions: [...d.transitions].sort(),
	}))
}

function compare(expect, observed) {
	const key = Object.keys(expect)[0]
	if (!(key in observed)) return false
	const want = expect[key]
	const got = observed[key]
	const N = L.normName
	switch (key) {
		case 'value':
			return L.sameValue(got, want)
		case 'values':
			if (got.length !== want.length) return false
			return want.every((w, i) => {
				const g = got[i]
				if (g.object !== w.object || String(g.property) !== String(w.property)) return false
				if (w.error) return !!g.error && N(g.error.class) === N(w.error.class) && N(g.error.code) === N(w.error.code)
				return 'value' in g && L.sameValue(g.value, w.value)
			})
		case 'error':
			if (N(got.class) !== N(want.class) || N(got.code) !== N(want.code)) return false
			if (want.first_failed) return false // never observed (see writePropertyMultiple)
			if (want.first_failed_element !== undefined && got.first_failed_element !== want.first_failed_element) return false
			return true
		case 'reject':
		case 'abort':
			return N(got) === N(want)
		case 'records':
			return got.length === want.length && want.every((w, i) => got[i].timestamp === w.timestamp && L.sameValue(got[i].value, w.value))
		case 'subscribed':
			return !want.notification || got.notification
		case 'i-am':
			return JSON.stringify([...got].sort()) === JSON.stringify([...want].sort())
		case 'i-have': {
			const s = (l) => l.map((x) => JSON.stringify(x)).sort()
			return JSON.stringify(s(got)) === JSON.stringify(s(want))
		}
		case 'recipients':
			return JSON.stringify(normDestinations(got)) === JSON.stringify(normDestinations(want))
		case 'enrollments':
			return got.length === want.length && want.every((w, i) => Object.keys(w).every((k) => N(got[i][k]) === N(w[k])))
		case 'alarms':
		case 'events':
			return got.length === want.length && want.every((w, i) => Object.keys(w).every((k) => N(got[i][k]) === N(w[k])))
		default:
			return JSON.stringify(got) === JSON.stringify(want)
	}
}

// --- main -------------------------------------------------------------------

function parseArgs(argv) {
	const a = { target: '', device: undefined, scenarios: '', only: '', broadcast: '', bbmd: '', fdTtl: 60 }
	for (let i = 0; i < argv.length; i++) {
		const k = argv[i]
		const v = argv[i + 1]
		switch (k) {
			case '--target':
				a.target = v
				i++
				break
			case '--device':
				a.device = Number(v)
				i++
				break
			case '--scenarios':
				a.scenarios = v
				i++
				break
			case '--only':
				a.only = v
				i++
				break
			case '--broadcast':
				a.broadcast = v
				i++
				break
			case '--bbmd':
				a.bbmd = v
				i++
				break
			case '--fd-ttl':
				a.fdTtl = Number(v)
				i++
				break
			default:
				throw new Error(`unknown argument ${k}`)
		}
	}
	if (!Number.isInteger(a.device)) throw new Error('--device N is required')
	if (!a.scenarios) throw new Error('--scenarios FILE is required')
	if (!Number.isInteger(a.fdTtl) || a.fdTtl < 1 || a.fdTtl > 65535) throw new Error('--fd-ttl must be 1..65535')
	for (const n of ['target', 'broadcast', 'bbmd']) {
		if (a[n] && !/^[0-9]{1,3}(\.[0-9]{1,3}){3}:[0-9]+$/.test(a[n])) throw new Error(`--${n} must be IPv4:PORT`)
	}
	return a
}

async function run(args, doc, timeoutMs, retries) {
	const env = new Env(args, timeoutMs, retries)
	let startError = ''
	try {
		await env.start()
		await env.register()
	} catch (e) {
		startError = e instanceof Infra ? e.message : `cannot start the bacnet-js client: ${e.message}`
	}
	L.emit({ event: 'ready', mode: 'client', adapter: ADAPTER, version: L.ADAPTER_VERSION, peer_version: L.PEER_VERSION, scenarios: String(doc.id || '') })
	const only = new Set(args.only.split(',').filter(Boolean))
	const summary = Object.fromEntries(OUTCOMES.map((o) => [o, 0]))
	const outcomes = {}
	for (const sc of doc.scenarios) {
		if (only.size && !only.has(sc.id)) continue
		const begin = Date.now()
		const line = { event: 'result', scenario: sc.id, service: sc.service }
		try {
			if (startError) throw new Infra(startError)
			const dep = DEPENDS_ON[sc.id]
			if (dep && outcomes[dep] !== undefined && outcomes[dep] !== 'pass') {
				line.outcome = 'not-tested'
				line.detail = `depends on ${dep}, which was ${outcomes[dep]} with this client`
			} else {
				const fn = SERVICES[sc.service]
				if (!fn) throw new Unsupported(`bacnet-js has no request for ${sc.service} in this driver`)
				const observed = await fn(sc, env)
				if (observed.undecodable) {
					line.outcome = 'fail'
					line.detail = observed.undecodable
				} else {
					line.outcome = compare(sc.expect, observed) ? 'pass' : 'fail'
				}
				line.observed = observed
			}
		} catch (e) {
			if (e instanceof Unsupported) {
				line.outcome = 'unsupported'
				line.detail = e.message
			} else if (e instanceof KnownDifference) {
				line.outcome = 'known-difference'
				line.detail = e.message
				if (e.observed) line.observed = e.observed
			} else if (e instanceof Infra) {
				line.outcome = 'infra-error'
				line.detail = e.message
			} else {
				line.outcome = 'infra-error'
				line.detail = `${e.name}: ${e.message}`
			}
		}
		line.durationMs = Date.now() - begin
		summary[line.outcome]++
		outcomes[sc.id] = line.outcome
		L.emit(line)
	}
	L.emit({ event: 'done', summary })
	env.close()
}

function main(argv) {
	let args
	try {
		args = parseArgs(argv)
	} catch (e) {
		L.log(`client: ${e.message}`)
		return Promise.resolve(2)
	}
	let doc
	try {
		doc = JSON.parse(fs.readFileSync(args.scenarios, 'utf8'))
		if (!Array.isArray(doc.scenarios)) throw new Error('no scenarios list')
	} catch (e) {
		L.log(`client: cannot read scenarios: ${e.message}`)
		return Promise.resolve(2)
	}
	if (doc.requires_bbmd && !args.bbmd) {
		L.log(`client: ${doc.id} requires --bbmd`)
		return Promise.resolve(2)
	}
	const timeoutMs = Number(process.env.BACNET_CLIENT_TIMEOUT_MS || '3000')
	const retries = Number(process.env.BACNET_CLIENT_RETRIES || '1')
	if (!Number.isInteger(timeoutMs) || !Number.isInteger(retries) || timeoutMs <= 0 || retries < 0) {
		L.log('client: BACNET_CLIENT_TIMEOUT_MS and BACNET_CLIENT_RETRIES must be integers')
		return Promise.resolve(2)
	}
	return run(args, doc, timeoutMs, retries).then(() => 0)
}

module.exports = { main, compare, parseArgs, recipients, datumChoices }

if (require.main === module) {
	main(process.argv.slice(2)).then((code) => process.exit(code))
}
