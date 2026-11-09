// SPDX-License-Identifier: MIT

// Command bacnet-interop is OT Fabric's own BACnet/IP stack, go-bacnet,
// behind the bacnet-interop container contract (docs/CONTAINER_CONTRACT.md
// and docs/CLIENT_DRIVER_CONTRACT.md), so that other stacks can test against
// it. It is not an independent implementation (README.md).
//
// Without arguments it serves a device fixture with the go-bacnet server
// (server, server/object, bbmd). With "client" as the first argument it runs
// a scenario file with the go-bacnet client. "version" and
// "print-capabilities" describe the image.
//
// Every request and every answer is encoded and decoded by go-bacnet's public
// API. The adapter builds the object model from the fixture, maps scenario
// files to client calls and turns what the client decoded into result lines.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
)

const (
	adapterName  = "otfabric"
	upstreamName = "go-bacnet"
	upstreamRepo = "https://github.com/otfabric/go-bacnet"
)

// Set at build time (Dockerfile): the go-bacnet release and its commit.
var (
	adapterVersion   = "dev"
	upstreamVersion  = "unknown"
	upstreamRevision = "unknown"
)

func main() {
	if v := os.Getenv("ADAPTER_VERSION"); v != "" {
		adapterVersion = v
	}
	cmd := ""
	if len(os.Args) > 1 {
		cmd = os.Args[1]
	}
	switch cmd {
	case "client":
		os.Exit(clientMain(os.Args[2:]))
	case "version":
		fmt.Printf("%s %s (%s %s, commit %s)\n", adapterName, adapterVersion, upstreamName, upstreamVersion, upstreamRevision)
	case "print-capabilities":
		printCapabilities()
	case "", "device":
		if err := deviceMain(); err != nil {
			fmt.Fprintf(os.Stderr, "otfabric device: %v\n", err)
			os.Exit(1)
		}
	default:
		fmt.Fprintf(os.Stderr, "usage: %s [device | client ... | version | print-capabilities]\n", os.Args[0])
		os.Exit(2)
	}
}

func peerVersion() string { return upstreamName + "-" + upstreamVersion }

// printCapabilities describes the image: what it runs and that it is not an
// independent engine (otfabric/engineering ADR-0012).
func printCapabilities() {
	emit(map[string]any{
		"adapter":          adapterName,
		"adapterVersion":   adapterVersion,
		"contractVersion":  "1.1",
		"roles":            []string{"device", "bbmd", "client"},
		"fixtures":         supportedFixtures,
		"scenarioServices": serviceNames(),
		"upstream": map[string]any{
			"name":              upstreamName,
			"repository":        upstreamRepo,
			"version":           upstreamVersion,
			"revision":          upstreamRevision,
			"independentEngine": false,
		},
	})
}

// emit writes one JSON line to stdout.
func emit(v map[string]any) {
	b, err := json.Marshal(v)
	if err != nil {
		fmt.Fprintf(os.Stderr, "emit: %v\n", err)
		return
	}
	fmt.Println(string(b))
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
