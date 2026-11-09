// SPDX-License-Identifier: MIT

package main

import (
	"context"
	"net/netip"
	"sync"
	"time"

	"github.com/otfabric/go-bacnet"
	"github.com/otfabric/go-bacnet/apdu"
	"github.com/otfabric/go-bacnet/bip"
	"github.com/otfabric/go-bacnet/bvlc"
	"github.com/otfabric/go-bacnet/npdu"
	"github.com/otfabric/go-bacnet/service"
)

// tapTransport sits between the go-bacnet client and its socket. It
// records the COV notifications that arrive, decoded with go-bacnet's bvlc,
// npdu, apdu and service decoders, because the client delivers a
// notification only to a Subscription it opened itself, and the
// subscriptions of the scenarios are sent with InvokeConfirmed. It counts
// datagrams sent, so that a request go-bacnet refused before sending is told
// apart from one the DUT did not answer. With --broadcast it sends
// broadcasts to that address.
type tapTransport struct {
	bip.Transport
	broadcast bip.Endpoint

	mu    sync.Mutex
	sent  int
	notes []covSeen
}

type covSeen struct {
	at       time.Time
	from     bip.Endpoint
	process  uint32
	objects  []bacnet.ObjectIdentifier
	multiple bool
}

func newTap(t bip.Transport, broadcast bip.Endpoint) *tapTransport {
	return &tapTransport{Transport: t, broadcast: broadcast}
}

func (t *tapTransport) Send(ctx context.Context, pkt bip.OutboundPacket) error {
	if pkt.Broadcast && t.broadcast.IsValid() {
		pkt.Broadcast, pkt.Destination = false, t.broadcast
	}
	t.mu.Lock()
	t.sent++
	t.mu.Unlock()
	return t.Transport.Send(ctx, pkt)
}

func (t *tapTransport) Recv(ctx context.Context) (bip.InboundPacket, error) {
	p, err := t.Transport.Recv(ctx)
	if err == nil {
		t.inspect(p)
	}
	return p, err
}

func (t *tapTransport) sentCount() int {
	t.mu.Lock()
	defer t.mu.Unlock()
	return t.sent
}

func (t *tapTransport) inspect(p bip.InboundPacket) {
	limits := bacnet.DefaultDecodeLimits()
	msg, err := bvlc.Parse(p.Data, limits)
	if err != nil {
		return
	}
	from := p.ImmediatePeer
	switch msg.Function {
	case bvlc.FunctionOriginalUnicastNPDU, bvlc.FunctionOriginalBroadcastNPDU:
	case bvlc.FunctionForwardedNPDU:
		from = bip.NewEndpoint(netip.AddrPortFrom(netip.AddrFrom4(msg.OriginIP), msg.OriginPort))
	default:
		return
	}
	n, _, err := npdu.Parse(msg.Payload, limits)
	if err != nil || n.NetworkMessage {
		return
	}
	pdu, err := apdu.Parse(n.APDU, limits)
	if err != nil {
		return
	}
	var choice uint8
	var payload []byte
	switch {
	case pdu.UnconfirmedRequest != nil:
		choice, payload = pdu.UnconfirmedRequest.ServiceChoice, pdu.UnconfirmedRequest.Payload
		switch choice {
		case apdu.ServiceUnconfirmedCOV:
			choice = apdu.ServiceConfirmedCOVNotification
		case apdu.ServiceUnconfirmedCOVNotificationMultiple:
			choice = apdu.ServiceConfirmedCOVNotificationMultiple
		default:
			return
		}
	case pdu.ConfirmedRequest != nil && !pdu.ConfirmedRequest.SegmentedMessage:
		choice, payload = pdu.ConfirmedRequest.ServiceChoice, pdu.ConfirmedRequest.Payload
	default:
		return
	}
	seen := covSeen{at: time.Now(), from: from}
	switch choice {
	case apdu.ServiceConfirmedCOVNotification:
		note, err := service.DecodeCOVNotification(payload, limits)
		if err != nil {
			return
		}
		seen.process, seen.objects = note.ProcessIdentifier, []bacnet.ObjectIdentifier{note.MonitoredObject}
	case apdu.ServiceConfirmedCOVNotificationMultiple:
		note, err := service.DecodeCOVNotificationMultiple(payload, limits)
		if err != nil {
			return
		}
		seen.process, seen.multiple = note.SubscriberProcessIdentifier, true
		for _, o := range note.Objects {
			seen.objects = append(seen.objects, o.Object)
		}
	default:
		return
	}
	t.mu.Lock()
	t.notes = append(t.notes, seen)
	t.mu.Unlock()
}

// waitCOV waits up to d for a notification since since, from from, for
// process and object.
func (t *tapTransport) waitCOV(since time.Time, from bip.Endpoint, process uint32, obj bacnet.ObjectIdentifier, multiple bool, d time.Duration) bool {
	deadline := time.Now().Add(d)
	for {
		t.mu.Lock()
		for _, n := range t.notes {
			if n.at.Before(since) || !n.from.Equal(from) || n.process != process || n.multiple != multiple {
				continue
			}
			for _, o := range n.objects {
				if o == obj {
					t.mu.Unlock()
					return true
				}
			}
		}
		t.mu.Unlock()
		if time.Now().After(deadline) {
			return false
		}
		time.Sleep(20 * time.Millisecond)
	}
}
