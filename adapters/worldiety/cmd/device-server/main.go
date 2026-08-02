// SPDX-License-Identifier: MIT

// Command device-server is the Worldiety fixture-driven BACnet/IP peer for bacnet-interop.
//
// It must not import go-bacnet. Worldiety owns BVLC/NPDU/APDU/segmentation;
// this adapter owns fixture object-model and service payload handlers.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/netip"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/otfabric/bacnet-interop/adapters/worldiety/internal/fixture"
	"github.com/otfabric/bacnet-interop/adapters/worldiety/internal/service"
	"github.com/worldiety/bacnet"
	"github.com/worldiety/bacnet/apdu"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "worldiety device-server: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	fixturePath := envOr("DEVICE_FIXTURE_FILE", "/fixtures/device/device-baseline-v2.json")
	adapterVersion := envOr("ADAPTER_VERSION", "dev")
	peerVersion := envOr("WORLDIETY_COMMIT", "3cb2aa80efbb8a489abb9978c7f6e5dc603535a7")

	store, err := fixture.LoadFile(fixturePath)
	if err != nil {
		return fmt.Errorf("load fixture: %w", err)
	}

	cfg := bacnet.DefaultClientRuntimeConfig()
	cfg.ASE = apdu.ASEConfig{
		InvokeTimeout:           10 * time.Second,
		SegmentedRequestTimeout: 5 * time.Second,
		APDURetries:             3,
		MaxSegmentDuplicates:    3,
		MaxConcurrentInvokes:    16,
		Segmentation:            apdu.SegmentationSupportBoth,
		PreferredWindowSize:     16,
		MaxAPDUSizeAccepted:     1476,
	}

	runtime, err := bacnet.NewClientRuntime(netip.MustParseAddr("0.0.0.0"), cfg)
	if err != nil {
		return fmt.Errorf("runtime: %w", err)
	}
	defer runtime.Close()

	srv := &service.Server{Store: store, ASE: runtime.ASE()}
	if err := srv.Register(); err != nil {
		return fmt.Errorf("register handlers: %w", err)
	}

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	errCh := make(chan error, 1)
	go func() {
		errCh <- runtime.Run(ctx)
	}()

	// Emit ready after bind; NewClientRuntime listens before return.
	fixtureID := store.FixtureID
	if fixtureID == "" {
		fixtureID = envOr("FIXTURE", "device-baseline-v2")
	}
	emitReady(adapterVersion, fixtureID, store.Port, peerVersion)
	log.Printf("worldiety serving fixture=%s device=%d port=%d", fixtureID, store.DeviceInstance, store.Port)

	select {
	case <-ctx.Done():
		return nil
	case err := <-errCh:
		if err == nil || err == context.Canceled {
			return nil
		}
		return err
	}
}

func emitReady(version, fixtureID string, port int, peerVersion string) {
	line := map[string]any{
		"event":        "ready",
		"adapter":      "worldiety",
		"version":      version,
		"fixture":      fixtureID,
		"address":      fmt.Sprintf("0.0.0.0:%d", port),
		"peer_version": peerVersion,
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(line)
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
