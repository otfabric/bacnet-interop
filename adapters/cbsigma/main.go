// SPDX-License-Identifier: MIT

// Command device_server is the cB-Sigma BACnet/IP peer of bacnet-interop.
//
// CBSIGMA_ROLE selects the upstream code that answers:
//
//	device (default)  github.com/cB-Sigma/bacnet/device: a BACnet device
//	                  with its Device object, object-list and names
//	sim               github.com/cB-Sigma/bacnet-sim/sim: the simulated
//	                  device, with ReadRange, files, alarms and events, BBMD
//	                  mode and switches that make it misbehave
//
// The adapter only fills the upstream object table from the fixture,
// seeds trend logs, encodes the canned alarm and event answers of the
// simulator and reports what it received as operation lines. It must not
// import go-bacnet.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/signal"
	"strconv"
	"syscall"
)

const adapterName = "cbsigma"

// Set at build time from adapters/cbsigma/go.mod.
var (
	adapterVersion = "dev"
	bacnetVersion  = "unknown"
	simVersion     = "unknown"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "cbsigma device_server: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	if v := os.Getenv("ADAPTER_VERSION"); v != "" {
		adapterVersion = v
	}
	f, err := loadFixture(envOr("DEVICE_FIXTURE_FILE", "/fixtures/device/device-baseline-v2.json"))
	if err != nil {
		return fmt.Errorf("load fixture: %w", err)
	}
	port, err := envInt("BACNET_IP_PORT", 47808)
	if err != nil {
		return err
	}
	listen := fmt.Sprintf("0.0.0.0:%d", port)

	var stop func()
	role := envOr("CBSIGMA_ROLE", "device")
	switch role {
	case "device":
		stop, err = serveDevice(f, listen)
	case "sim":
		stop, err = serveSim(f, listen)
	default:
		return fmt.Errorf("CBSIGMA_ROLE %q: want device or sim", role)
	}
	if err != nil {
		return err
	}
	defer stop()

	emit(map[string]any{
		"event":        "ready",
		"adapter":      adapterName,
		"version":      adapterVersion,
		"fixture":      f.Fixture,
		"address":      listen,
		"role":         role,
		"peer_version": peerVersion(role),
	})
	fmt.Fprintf(os.Stderr, "cbsigma serving fixture=%s device=%d role=%s on %s\n", f.Fixture, f.DeviceInstance, role, listen)

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	return nil
}

func peerVersion(role string) string {
	if role == "sim" {
		return "bacnet-sim-" + simVersion + "+bacnet-" + bacnetVersion
	}
	return "bacnet-" + bacnetVersion
}

// emit writes one JSON line to stdout.
func emit(v map[string]any) {
	b, err := json.Marshal(v)
	if err != nil {
		return
	}
	fmt.Println(string(b))
}

// operation reports a request that has no observable reply.
func operation(name string, fields map[string]any) {
	ev := map[string]any{"event": "operation", "adapter": adapterName, "operation": name, "result": "received"}
	for k, v := range fields {
		ev[k] = v
	}
	emit(ev)
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envInt(key string, def int) (int, error) {
	v := os.Getenv(key)
	if v == "" {
		return def, nil
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return 0, fmt.Errorf("%s=%q: %w", key, v, err)
	}
	return n, nil
}

func envBool(key string) bool {
	switch os.Getenv(key) {
	case "1", "true", "yes":
		return true
	}
	return false
}
