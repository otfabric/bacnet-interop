// SPDX-License-Identifier: MIT

// Command ulbios is the ulbios/bacnet peer of bacnet-interop.
//
// github.com/ulbios/bacnet (MIT, pinned by commit in go.mod) is a small Go
// BACnet/IP library: bacnet.Parse decodes Who-Is, I-Am, ReadProperty,
// WriteProperty, Simple-ACK, Complex-ACK and Error, and its encoders build
// the same messages. It has no transport, no transaction state machine, no
// object model, no segmentation, no Reject or Abort and no BBMD functions.
//
// Without arguments the command serves the device fixture as a device: every
// message on the wire is parsed by bacnet.Parse and encoded by ulbios'
// services and objects packages; the object model, the dispatch and what
// ulbios' service decoders refuse are adapter code. With "client" as first
// argument it runs the client-driver contract
// (docs/CLIENT_DRIVER_CONTRACT.md) with ulbios' request encoders. It must not
// import go-bacnet.
package main

import (
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/signal"
	"strconv"
	"syscall"
)

const adapterName = "ulbios"

// Set at build time from adapters/ulbios/go.mod.
var (
	adapterVersion = "dev"
	ulbiosVersion  = "unknown"
)

func main() {
	if len(os.Args) > 1 && os.Args[1] == "client" {
		os.Exit(clientMain(os.Args[2:]))
	}
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "ulbios device_server: %v\n", err)
		os.Exit(1)
	}
}

func peerVersion() string { return "ulbios-bacnet-" + ulbiosVersion }

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
	conn, err := net.ListenUDP("udp4", &net.UDPAddr{Port: port})
	if err != nil {
		return err
	}
	defer func() { _ = conn.Close() }()

	d := &device{m: newModel(f), op: operation, keepSA: os.Getenv("ULBIOS_KEEP_SA") == "1"}
	go d.serve(conn, port)

	emit(map[string]any{
		"event":        "ready",
		"adapter":      adapterName,
		"version":      adapterVersion,
		"fixture":      f.Fixture,
		"address":      listen,
		"peer_version": peerVersion(),
	})
	fmt.Fprintf(os.Stderr, "ulbios serving fixture=%s device=%d on %s\n", f.Fixture, f.DeviceInstance, listen)

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig
	return nil
}

// emit writes one JSON line to stdout.
func emit(v map[string]any) {
	b, err := json.Marshal(v)
	if err != nil {
		return
	}
	fmt.Println(string(b))
}

// operation reports a request that has no observable reply, or one the
// device applied.
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
