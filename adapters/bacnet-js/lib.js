// SPDX-License-Identifier: MIT
'use strict'

// Shared helpers of the bacnet-js adapter: the upstream modules, enumeration
// names, scenario values and the raw-datagram tap.
//
// Everything that goes on the wire is encoded by @bacnet-js/client, and
// everything that comes off it is decoded by it. Its package exports the
// BACnetClient class, the enumerations and the types; the service, ASN.1,
// APDU, NPDU and BVLC modules are reached under dist/lib (the package has no
// "exports" map, so these paths are part of what npm installs). Nothing here
// changes upstream code.

const pkg = require('@bacnet-js/client')
const asn1 = require('@bacnet-js/client/dist/lib/asn1')
const apdu = require('@bacnet-js/client/dist/lib/apdu')
const npdu = require('@bacnet-js/client/dist/lib/npdu')
const bvlc = require('@bacnet-js/client/dist/lib/bvlc')
const services = require('@bacnet-js/client/dist/lib/services')
const Transport = require('@bacnet-js/client/dist/lib/transport').default

const BACnetClient = pkg.default
const PEER_VERSION = `bacnet-js-${require('@bacnet-js/client/package.json').version}`
const ADAPTER_VERSION = process.env.ADAPTER_VERSION || 'dev'

// Max_APDU_Length_Accepted codes (clause 20.1.2.5) in octets.
const MAX_APDU_OCTETS = [50, 128, 206, 480, 1024, 1476]

// kebab-case name <-> upstream UPPER_SNAKE enumeration member.
function enumValue(e, name) {
	if (typeof name === 'number') return name
	if (/^[0-9]+$/.test(String(name))) return Number(name)
	const key = String(name).toUpperCase().replace(/[- ]/g, '_')
	if (!(key in e)) throw new Error(`unknown enumeration name "${name}"`)
	return e[key]
}

function enumName(e, value) {
	const key = e[value]
	if (typeof key !== 'string') return value
	return key.toLowerCase().replace(/_/g, '-')
}

function objectId(ref) {
	const [type, instance] = String(ref).split(',')
	return { type: enumValue(pkg.ObjectType, type), instance: Number(instance) }
}

function objectRef(oid) {
	return `${enumName(pkg.ObjectType, oid.type)},${oid.instance}`
}

function propertyId(p) {
	return enumValue(pkg.PropertyIdentifier, p)
}

function propertyName(id) {
	return enumName(pkg.PropertyIdentifier, id)
}

// Names compare without case, spaces or hyphens (as the other drivers).
function normName(s) {
	return String(s).toLowerCase().replace(/[^a-z0-9]/g, '')
}

const T = pkg.ApplicationTag

// A scenario value ({type, value}) as upstream application data.
function appData(v) {
	switch (v.type) {
		case 'null':
			return { type: T.NULL, value: null }
		case 'boolean':
			return { type: T.BOOLEAN, value: !!v.value }
		case 'unsigned':
			return { type: T.UNSIGNED_INTEGER, value: Number(v.value) }
		case 'signed':
			return { type: T.SIGNED_INTEGER, value: Number(v.value) }
		case 'real':
			return { type: T.REAL, value: Number(v.value) }
		case 'double':
			return { type: T.DOUBLE, value: Number(v.value) }
		case 'character-string':
			return { type: T.CHARACTER_STRING, value: String(v.value) }
		case 'enumerated':
			return { type: T.ENUMERATED, value: Number(v.value) }
		case 'object-identifier':
			return { type: T.OBJECTIDENTIFIER, value: objectId(v.value) }
		default:
			throw new Error(`value type ${v.type} is not encoded by this driver`)
	}
}

// Enumerations whose names the scenarios use, by property.
function enumFor(objectType, prop) {
	const P = pkg.PropertyIdentifier
	const O = pkg.ObjectType
	switch (prop) {
		case P.OBJECT_TYPE:
			return pkg.ObjectType
		case P.EVENT_STATE:
			return pkg.EventState
		case P.PRESENT_VALUE:
		case P.RELINQUISH_DEFAULT:
			if (
				objectType === O.BINARY_VALUE ||
				objectType === O.BINARY_INPUT ||
				objectType === O.BINARY_OUTPUT
			)
				return pkg.BinaryPV
			return null
		case P.SYSTEM_STATUS:
			return pkg.DeviceStatus
		case P.SEGMENTATION_SUPPORTED:
			return pkg.Segmentation
		case P.NOTIFY_TYPE:
			return pkg.NotifyType
		default:
			return null
	}
}

// Upstream application data as a scenario value.
function observedValue(d, objectType, prop) {
	if (!d) return { type: 'text', value: 'no value' }
	switch (d.type) {
		case T.NULL:
			return { type: 'null' }
		case T.BOOLEAN:
			return { type: 'boolean', value: !!d.value }
		case T.UNSIGNED_INTEGER:
			return { type: 'unsigned', value: d.value }
		case T.SIGNED_INTEGER:
			return { type: 'signed', value: d.value }
		case T.REAL:
		case T.DOUBLE:
			return { type: 'real', value: d.value }
		case T.CHARACTER_STRING:
			return { type: 'character-string', value: d.value }
		case T.ENUMERATED: {
			const e = enumFor(objectType, prop)
			return { type: 'enumerated', value: e ? enumName(e, d.value) : d.value }
		}
		case T.OBJECTIDENTIFIER:
			return { type: 'object-identifier', value: objectRef(d.value) }
		case T.OCTET_STRING:
			return { type: 'octet-string', value: Buffer.from(d.value).toString('hex') }
		case T.BIT_STRING:
			return { type: 'bit-string', value: bits(d.value) }
		default:
			return { type: 'text', value: JSON.stringify(d.value) }
	}
}

// An upstream bit string ({value: bytes, bitsUsed}) as a list of 0/1.
function bits(bs) {
	const out = []
	for (let i = 0; i < (bs.bitsUsed || 0); i++) {
		out.push((bs.value[i >> 3] >> (i & 7)) & 1)
	}
	return out
}

// A bit string with the given bits set, in upstream form.
function bitString(bitsUsed, set) {
	const value = new Array(Math.ceil(bitsUsed / 8) || 1).fill(0)
	for (const i of set) value[i >> 3] |= 1 << (i & 7)
	return { bitsUsed, value }
}

function sameValue(got, want) {
	if (!got || got.type !== want.type) return false
	if (want.type === 'real' && typeof got.value === 'number') {
		return Math.abs(got.value - Number(want.value)) <= 1e-6 * Math.max(1, Math.abs(Number(want.value)))
	}
	if (want.type === 'enumerated') return normName(got.value) === normName(want.value)
	return JSON.stringify(got.value) === JSON.stringify(want.value)
}

// Upstream names a sender "ip" when its port is 47808 and "ip:port"
// otherwise (transport.ts); the adapter always uses "ip:port".
function hostport(address) {
	if (!address) return ''
	return address.includes(':') ? address : `${address}:47808`
}

// A scratch encode buffer large enough for any APDU before the size check.
function scratch() {
	return { buffer: Buffer.alloc(64 * 1024), offset: 4 }
}

// Raw-datagram tap: the upstream Transport emits every datagram; the adapter
// registers its listener before BACnetClient does and keeps the last
// datagrams per sender, so that a handler can find the request octets
// upstream reported only partly (adapter-shim, README.md).
class Tap {
	constructor(transport, keep = 64) {
		this.keep = keep
		this.frames = []
		this.listeners = []
		transport.on('message', (msg, address) => {
			this.frames.push({ msg: Buffer.from(msg), address: hostport(address), at: Date.now() })
			if (this.frames.length > this.keep) this.frames.shift()
			for (const l of this.listeners) l(msg, address)
		})
	}

	// The APDU of the last frame from address whose APDU satisfies match,
	// located with the upstream BVLC and NPDU decoders.
	find(address, match) {
		address = hostport(address)
		for (let i = this.frames.length - 1; i >= 0; i--) {
			const f = this.frames[i]
			if (f.address !== address) continue
			const a = locateApdu(f.msg)
			if (a && match(a)) return a
		}
		return null
	}
}

// {buffer, offset, length, type} of the APDU in a B/IP datagram, or null.
function locateApdu(msg) {
	const b = bvlc.decode(msg, 0)
	if (!b) return null
	if (
		b.func !== pkg.BvlcResultPurpose.ORIGINAL_UNICAST_NPDU &&
		b.func !== pkg.BvlcResultPurpose.ORIGINAL_BROADCAST_NPDU &&
		b.func !== pkg.BvlcResultPurpose.FORWARDED_NPDU &&
		b.func !== pkg.BvlcResultPurpose.DISTRIBUTE_BROADCAST_TO_NETWORK
	)
		return null
	const n = npdu.decode(msg, b.len)
	if (!n || n.funct & pkg.NpduControlBit.NETWORK_LAYER_MESSAGE) return null
	const offset = b.len + n.len
	return { buffer: msg, offset, length: msg.length - offset, type: apdu.getDecodedType(msg, offset) }
}

function emit(line) {
	process.stdout.write(JSON.stringify(line) + '\n')
}

function log(...args) {
	process.stderr.write(args.join(' ') + '\n')
}

module.exports = {
	pkg,
	asn1,
	apdu,
	npdu,
	bvlc,
	services,
	Transport,
	BACnetClient,
	PEER_VERSION,
	ADAPTER_VERSION,
	MAX_APDU_OCTETS,
	enumValue,
	enumName,
	objectId,
	objectRef,
	propertyId,
	propertyName,
	normName,
	appData,
	observedValue,
	enumFor,
	bits,
	bitString,
	sameValue,
	scratch,
	hostport,
	Tap,
	locateApdu,
	emit,
	log,
}
