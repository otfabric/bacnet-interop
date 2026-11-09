// SPDX-License-Identifier: MIT

package main

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/netip"
	"os"
	"os/signal"
	"syscall"

	"github.com/otfabric/go-bacnet"
	"github.com/otfabric/go-bacnet/bbmd"
	"github.com/otfabric/go-bacnet/bip"
	"github.com/otfabric/go-bacnet/bvlc"
	"github.com/otfabric/go-bacnet/server"
	"github.com/otfabric/go-bacnet/service"
)

// deviceMain serves the fixture until SIGINT or SIGTERM.
func deviceMain() error {
	path := envOr("DEVICE_FIXTURE_FILE", "/fixtures/device/"+envOr("FIXTURE", "device-baseline-v2")+".json")
	f, err := loadFixture(path)
	if err != nil {
		return fmt.Errorf("load fixture: %w", err)
	}
	port, err := envInt("BACNET_IP_PORT", 47808)
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	cfg := deviceConfig{
		port:     port,
		bbmd:     os.Getenv("BACNET_BBMD") == "1",
		password: os.Getenv("BACNET_DCC_PASSWORD"),
	}
	return serveDevice(ctx, f, cfg, nil)
}

type deviceConfig struct {
	port      int
	localAddr string        // bind address; empty binds every address on port
	bbmd      bool          // run a BBMD with its own BDT entry
	self      bip.Endpoint  // the BBMD's own address; zero finds it
	password  string        // DeviceCommunicationControl and ReinitializeDevice
	transport bip.Transport // instead of a UDP socket (tests)
}

// serveDevice serves f until ctx ends. ready, when not nil, is called after
// the ready line with the server's local endpoint.
func serveDevice(ctx context.Context, f *fixture, cfg deviceConfig, ready func(bip.Endpoint)) error {
	d, err := buildDevice(f)
	if err != nil {
		return err
	}
	opts := []server.Option{server.WithPort(cfg.port), server.WithHooks(operationHooks())}
	if cfg.localAddr != "" {
		opts = append(opts, server.WithLocalAddr(cfg.localAddr))
	}
	if cfg.transport != nil {
		opts = append(opts, server.WithTransport(cfg.transport))
	}
	if cfg.password != "" {
		opts = append(opts, server.WithPassword(cfg.password))
	}
	if cfg.bbmd {
		self := cfg.self
		if !self.IsValid() {
			if self, err = ownEndpoint(cfg.port); err != nil {
				return err
			}
		}
		b, err := bbmd.New(bbmd.Config{Self: self, BDT: []bvlc.BDTEntry{{Endpoint: self, Mask: bvlc.IPv4Mask{255, 255, 255, 255}}}})
		if err != nil {
			return fmt.Errorf("bbmd: %w", err)
		}
		opts = append(opts, server.WithBBMD(b))
	}
	s, err := server.New(d, opts...)
	if err != nil {
		return err
	}
	defer func() { _ = s.Close() }()
	if err := s.IAm(); err != nil {
		fmt.Fprintf(os.Stderr, "otfabric: I-Am at start: %v\n", err)
	}
	ev := map[string]any{
		"event":              "ready",
		"adapter":            adapterName,
		"version":            adapterVersion,
		"fixture":            f.Fixture,
		"address":            fmt.Sprintf("0.0.0.0:%d", cfg.port),
		"peer_version":       peerVersion(),
		"independent_engine": false,
	}
	if cfg.bbmd {
		ev["bbmd"] = true
	}
	emit(ev)
	fmt.Fprintf(os.Stderr, "otfabric: go-bacnet %s serving %s (device %d) on %s\n", upstreamVersion, f.Fixture, f.DeviceInstance, s.Local())
	if ready != nil {
		ready(s.Local())
	}
	<-ctx.Done()
	return nil
}

// operationHooks reports the requests that have no observable reply as
// operation lines (docs/CONTAINER_CONTRACT.md, Output); the services that act
// only through a hook are enabled by them.
func operationHooks() server.Hooks {
	op := func(name string) {
		emit(map[string]any{"event": "operation", "adapter": adapterName, "operation": name, "result": "accepted"})
	}
	return server.Hooks{
		TimeSync: func(_ service.TimeSynchronization, utc bool) {
			if utc {
				op("utc-time-synchronization")
				return
			}
			op("time-synchronization")
		},
		PrivateTransfer: func(_ context.Context, _ service.PrivateTransfer, confirmed bool) ([]bacnet.Element, error) {
			if confirmed {
				op("confirmed-private-transfer")
			} else {
				op("unconfirmed-private-transfer")
			}
			return nil, nil
		},
		TextMessage: func(_ context.Context, _ service.TextMessage, confirmed bool) error {
			if confirmed {
				op("confirmed-text-message")
			} else {
				op("unconfirmed-text-message")
			}
			return nil
		},
		WriteGroup: func(context.Context, service.WriteGroup) { op("write-group") },
	}
}

// ownEndpoint is the first non-loopback IPv4 address of the container on
// port, the BBMD's own B/IP address (bbmd.Config.Self cannot be the wildcard
// address the socket binds).
func ownEndpoint(port int) (bip.Endpoint, error) {
	addrs, err := net.InterfaceAddrs()
	if err != nil {
		return bip.Endpoint{}, err
	}
	for _, a := range addrs {
		ipn, ok := a.(*net.IPNet)
		if !ok || ipn.IP.IsLoopback() || ipn.IP.To4() == nil {
			continue
		}
		ip, _ := netip.AddrFromSlice(ipn.IP.To4())
		return bip.NewEndpoint(netip.AddrPortFrom(ip, uint16(port))), nil
	}
	return bip.Endpoint{}, errors.New("no IPv4 address for the BBMD")
}
