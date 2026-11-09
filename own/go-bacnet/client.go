// SPDX-License-Identifier: MIT

package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/netip"
	"os"
	"strings"
	"time"

	"github.com/otfabric/go-bacnet/bip"
	"github.com/otfabric/go-bacnet/client"
)

// Client mode (docs/CLIENT_DRIVER_CONTRACT.md). Each scenario is one call of
// go-bacnet's public client API. Where a typed method cannot express the
// scenario (a subscriber process identifier, a single subscription without
// renewal, the parameters of a ChangeList-Error or
// SubscribeCOVPropertyMultiple-Error), the request is encoded by go-bacnet's
// service package and sent with Client.InvokeConfirmed, whose answer is
// decoded by go-bacnet's apdu and service packages. What go-bacnet refuses to
// send is `unsupported`, never a pass.

var outcomes = []string{"pass", "fail", "unsupported", "not-tested", "known-difference", "infra-error"}

// The client's own device instance: not one a scenario file names (the
// BACnet4J and BACpypes3 drivers use 4001, legacy BACpypes 4002).
const clientInstance = 4003

// outcomeError ends a scenario with an outcome other than pass or fail.
type outcomeError struct {
	outcome string
	detail  string
}

func (e *outcomeError) Error() string { return e.outcome + ": " + e.detail }

func unsupported(format string, a ...any) error {
	return &outcomeError{"unsupported", fmt.Sprintf(format, a...)}
}

func infra(format string, a ...any) error {
	return &outcomeError{"infra-error", fmt.Sprintf(format, a...)}
}

type clientArgs struct {
	target    string
	device    int
	scenarios string
	only      string
	broadcast string
	bbmd      string
	fdTTL     int
}

// clientConfig is what a run needs besides the arguments; tests set the
// transport.
type clientConfig struct {
	timeout   time.Duration
	retries   int
	transport bip.Transport
	port      int
}

func clientMain(argv []string) int {
	fs := flag.NewFlagSet("client", flag.ContinueOnError)
	var a clientArgs
	fs.StringVar(&a.target, "target", "", "DUT HOST:PORT")
	fs.IntVar(&a.device, "device", -1, "DUT device instance")
	fs.StringVar(&a.scenarios, "scenarios", "", "scenario file")
	fs.StringVar(&a.only, "only", "", "comma-separated scenario ids")
	fs.StringVar(&a.broadcast, "broadcast", "", "HOST:PORT discovery requests are sent to")
	fs.StringVar(&a.bbmd, "bbmd", "", "register as a foreign device with this BBMD (HOST:PORT)")
	fs.IntVar(&a.fdTTL, "fd-ttl", 60, "foreign-device time to live, seconds")
	if err := fs.Parse(argv); err != nil {
		return 2
	}
	timeoutMS, err1 := envInt("BACNET_CLIENT_TIMEOUT_MS", 3000)
	retries, err2 := envInt("BACNET_CLIENT_RETRIES", 1)
	if err1 != nil || err2 != nil || timeoutMS < 1 || retries < 0 {
		fmt.Fprintln(os.Stderr, "client: BACNET_CLIENT_TIMEOUT_MS and BACNET_CLIENT_RETRIES must be integers (timeout > 0)")
		return 2
	}
	return runClient(a, clientConfig{timeout: time.Duration(timeoutMS) * time.Millisecond, retries: retries, port: 47808}, os.Stdout)
}

type scenarioDoc struct {
	ID           string           `json:"id"`
	RequiresBBMD bool             `json:"requires_bbmd"`
	Scenarios    []map[string]any `json:"scenarios"`
}

// runClient runs a scenario file and writes the result lines to out. It
// returns the exit code: 0 when the scenarios ran, 2 for a usage error.
func runClient(a clientArgs, cfg clientConfig, out io.Writer) int {
	if a.device < 0 || a.device > 4194302 || a.scenarios == "" {
		fmt.Fprintln(os.Stderr, "client: --device (0..4194302) and --scenarios are required")
		return 2
	}
	if a.fdTTL < 1 || a.fdTTL > 65535 {
		fmt.Fprintln(os.Stderr, "client: --fd-ttl must be 1..65535")
		return 2
	}
	var target, bcast, bbmdEP bip.Endpoint
	for name, p := range map[string]struct {
		v  string
		ep *bip.Endpoint
	}{"target": {a.target, &target}, "broadcast": {a.broadcast, &bcast}, "bbmd": {a.bbmd, &bbmdEP}} {
		if p.v == "" {
			continue
		}
		ap, err := netip.ParseAddrPort(p.v)
		if err != nil || !ap.Addr().Is4() {
			fmt.Fprintf(os.Stderr, "client: --%s must be IPv4:PORT\n", name)
			return 2
		}
		*p.ep = bip.NewEndpoint(ap)
	}
	raw, err := os.ReadFile(a.scenarios)
	var doc scenarioDoc
	if err == nil {
		err = json.Unmarshal(raw, &doc)
	}
	if err != nil || doc.Scenarios == nil {
		fmt.Fprintf(os.Stderr, "client: cannot read scenarios: %v\n", err)
		return 2
	}
	if doc.RequiresBBMD && a.bbmd == "" {
		fmt.Fprintf(os.Stderr, "client: %s requires --bbmd\n", doc.ID)
		return 2
	}

	write := func(v map[string]any) {
		b, err := json.Marshal(v)
		if err == nil {
			_, _ = fmt.Fprintln(out, string(b))
		}
	}
	env, startErr := newClientEnv(a, cfg, target, bcast, bbmdEP)
	if env != nil {
		defer env.close()
	}
	write(map[string]any{"event": "ready", "mode": "client", "adapter": adapterName, "version": adapterVersion,
		"peer_version": peerVersion(), "scenarios": doc.ID, "independent_engine": false})

	want := map[string]bool{}
	for _, id := range strings.Split(a.only, ",") {
		if id != "" {
			want[id] = true
		}
	}
	summary := map[string]int{}
	for _, o := range outcomes {
		summary[o] = 0
	}
	for _, sc := range doc.Scenarios {
		id, _ := sc["id"].(string)
		if len(want) > 0 && !want[id] {
			continue
		}
		svc, _ := sc["service"].(string)
		begin := time.Now()
		line := map[string]any{"event": "result", "scenario": id, "service": svc}
		var observed map[string]any
		err := startErr
		if err == nil {
			observed, err = env.run(sc)
		}
		var oe *outcomeError
		switch {
		case err == nil:
			line["observed"] = observed
			expect, _ := sc["expect"].(map[string]any)
			if compare(expect, observed) {
				line["outcome"] = "pass"
			} else {
				line["outcome"] = "fail"
			}
		case errors.As(err, &oe):
			line["outcome"], line["detail"] = oe.outcome, oe.detail
		default:
			line["outcome"], line["detail"] = "fail", err.Error()
		}
		line["durationMs"] = time.Since(begin).Milliseconds()
		summary[line["outcome"].(string)]++
		write(line)
	}
	write(map[string]any{"event": "done", "summary": summary})
	return 0
}

// clientEnv is one go-bacnet client and what the scenarios share.
type clientEnv struct {
	c        *client.Client
	tap      *tapTransport
	timeout  time.Duration
	retries  int
	listen   time.Duration // how long unconfirmed answers are collected
	device   uint32
	targetEP bip.Endpoint
	bbmdEP   bip.Endpoint
	bound    bool
	bindErr  error
	tgt      client.Target
}

func newClientEnv(a clientArgs, cfg clientConfig, target, bcast, bbmdEP bip.Endpoint) (*clientEnv, error) {
	tr := cfg.transport
	if tr == nil {
		// Port 47808: a broadcast Who-Is is answered with a broadcast I-Am
		// to that port.
		var err error
		if tr, err = bip.ListenUDP(bip.UDPConfig{Port: cfg.port}); err != nil {
			return nil, infra("cannot open the BACnet/IP socket: %v", err)
		}
	}
	tap := newTap(tr, bcast)
	opts := []client.Option{
		client.WithTransport(tap),
		client.WithTransactionOptions(cfg.timeout, cfg.retries, cfg.timeout),
		client.WithDeviceManagementEnabled(client.DeviceManagementConfirm),
		client.WithNetworkManagementEnabled(client.NetworkManagementConfirm),
	}
	if bbmdEP.IsValid() {
		opts = append(opts, client.WithForeignDevice(client.ForeignDeviceConfig{BBMD: bbmdEP, TTL: time.Duration(a.fdTTL) * time.Second}))
	}
	c, err := client.New(opts...)
	if err != nil {
		_ = tr.Close()
		return nil, infra("go-bacnet client: %v", err)
	}
	env := &clientEnv{
		c: c, tap: tap, timeout: cfg.timeout, retries: cfg.retries,
		listen: max(2*time.Second, cfg.timeout), device: uint32(a.device), targetEP: target, bbmdEP: bbmdEP,
	}
	if bbmdEP.IsValid() {
		deadline := time.Now().Add(cfg.timeout*time.Duration(cfg.retries+1) + 2*time.Second)
		for !c.ForeignDeviceRegistered() {
			if time.Now().After(deadline) {
				return env, infra("no registration with the BBMD %s as a foreign device", bbmdEP)
			}
			time.Sleep(20 * time.Millisecond)
		}
	}
	return env, nil
}

func (e *clientEnv) close() { _ = e.c.Close() }

// ctx bounds one request: every attempt, and a segmented exchange.
func (e *clientEnv) ctx() (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), e.timeout*time.Duration(e.retries+1)*4+5*time.Second)
}

// bind finds the DUT with a Who-Is to --target for --device; its I-Am must
// come from --target.
func (e *clientEnv) bind() error {
	if e.bound {
		return nil
	}
	if e.bindErr != nil {
		return e.bindErr
	}
	if !e.targetEP.IsValid() {
		e.bindErr = infra("--target is required for this service")
		return e.bindErr
	}
	since := time.Now()
	dev := e.device
	deadline := since.Add(e.timeout*time.Duration(e.retries+1) + 2*time.Second)
	for attempt := 0; time.Now().Before(deadline); attempt++ {
		if attempt <= e.retries {
			ctx, cancel := e.ctx()
			err := e.c.SendWhoIs(ctx, e.targetEP, false, client.DiscoveryOptions{LowLimit: &dev, HighLimit: &dev})
			cancel()
			if err != nil {
				e.bindErr = infra("Who-Is to %s: %v", e.targetEP, err)
				return e.bindErr
			}
		}
		wait := time.Now().Add(e.timeout)
		for time.Now().Before(wait) && time.Now().Before(deadline) {
			for _, d := range e.c.Devices() {
				if d.Instance != dev || d.LastSeen.Before(since) {
					continue
				}
				if !d.ImmediatePeer.Equal(e.targetEP) {
					e.bindErr = infra("I-Am for device %d from %s, not the target %s", dev, d.ImmediatePeer, e.targetEP)
					return e.bindErr
				}
				tgt, err := e.c.ResolveTarget(d.Address, e.targetEP)
				if err != nil {
					e.bindErr = infra("target: %v", err)
					return e.bindErr
				}
				e.tgt, e.bound = tgt, true
				return nil
			}
			time.Sleep(20 * time.Millisecond)
		}
	}
	e.bindErr = infra("device %d did not answer a Who-Is to %s", dev, e.targetEP)
	return e.bindErr
}

// localIP is this client's IPv4 address on the route to peer, as the BBMD
// sees it in its FDT.
func localIP(peer bip.Endpoint) (netip.Addr, error) {
	conn, err := net.Dial("udp4", peer.String())
	if err != nil {
		return netip.Addr{}, err
	}
	defer func() { _ = conn.Close() }()
	ap, err := netip.ParseAddrPort(conn.LocalAddr().String())
	if err != nil {
		return netip.Addr{}, err
	}
	return ap.Addr(), nil
}
