// SPDX-License-Identifier: MIT

package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"net"
	"net/netip"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/otfabric/go-bacnet/bip"
)

// fixturesDir is the repository's fixtures/ (FIXTURES_DIR in the image
// build).
func fixturesDir(t *testing.T) string {
	t.Helper()
	dir := os.Getenv("FIXTURES_DIR")
	if dir == "" {
		dir = filepath.Join("..", "..", "fixtures")
	}
	if _, err := os.Stat(filepath.Join(dir, "device")); err != nil {
		t.Fatalf("fixtures: %v (set FIXTURES_DIR)", err)
	}
	return dir
}

func TestEveryFixture(t *testing.T) {
	dir := fixturesDir(t)
	supported := map[string]bool{}
	for _, f := range supportedFixtures {
		supported[f] = true
	}
	files, _ := filepath.Glob(filepath.Join(dir, "device", "*.json"))
	if len(files) == 0 {
		t.Fatal("no device fixtures")
	}
	for _, path := range files {
		name := strings.TrimSuffix(filepath.Base(path), ".json")
		t.Run(name, func(t *testing.T) {
			f, err := loadFixture(path)
			if err != nil {
				t.Fatal(err)
			}
			_, err = buildDevice(f)
			switch {
			case supported[name] && err != nil:
				t.Fatalf("supported fixture: %v", err)
			case !supported[name] && err == nil:
				t.Fatal("builds, but is not in supportedFixtures")
			case !supported[name] && !strings.Contains(err.Error(), "no constructor"):
				t.Fatalf("unsupported fixture fails for another reason: %v", err)
			}
		})
	}
}

// redirect sends every broadcast of the device to the client: there are no
// broadcasts on the loopback interface.
type redirect struct {
	bip.Transport
	to bip.Endpoint
}

func (r redirect) Send(ctx context.Context, p bip.OutboundPacket) error {
	if p.Broadcast {
		p.Broadcast, p.Destination = false, r.to
	}
	return r.Transport.Send(ctx, p)
}

func freePort(t *testing.T) int {
	t.Helper()
	c, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close() }()
	return c.LocalAddr().(*net.UDPAddr).Port
}

func loopback(port int) bip.Endpoint {
	return bip.NewEndpoint(netip.AddrPortFrom(netip.AddrFrom4([4]byte{127, 0, 0, 1}), uint16(port)))
}

type resultLine struct {
	Event    string          `json:"event"`
	Scenario string          `json:"scenario"`
	Outcome  string          `json:"outcome"`
	Detail   string          `json:"detail"`
	Observed json.RawMessage `json:"observed"`
	Summary  map[string]int  `json:"summary"`
}

// runAgainstOwnDevice serves the fixture a scenario file requires and runs
// the file with the client, both go-bacnet, over loopback UDP.
func runAgainstOwnDevice(t *testing.T, scenarios string) []resultLine {
	t.Helper()
	dir := fixturesDir(t)
	path := filepath.Join(dir, "scenarios", scenarios+".json")
	var doc struct {
		RequiresFixture string `json:"requires_fixture"`
		RequiresBBMD    bool   `json:"requires_bbmd"`
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	f, err := loadFixture(filepath.Join(dir, "device", doc.RequiresFixture+".json"))
	if err != nil {
		t.Fatal(err)
	}
	devPort, cliPort := freePort(t), freePort(t)
	devTr, err := bip.ListenUDP(bip.UDPConfig{Port: devPort, LocalAddr: loopback(devPort).String()})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	served := make(chan bip.Endpoint, 1)
	done := make(chan error, 1)
	go func() {
		done <- serveDevice(ctx, f, deviceConfig{port: devPort, bbmd: doc.RequiresBBMD, self: loopback(devPort),
			transport: redirect{devTr, loopback(cliPort)}}, func(ep bip.Endpoint) { served <- ep })
	}()
	t.Cleanup(func() {
		cancel()
		if err := <-done; err != nil {
			t.Errorf("device: %v", err)
		}
	})
	select {
	case <-served:
	case err := <-done:
		t.Fatalf("device: %v", err)
	case <-time.After(10 * time.Second):
		t.Fatal("device did not start")
	}

	cliTr, err := bip.ListenUDP(bip.UDPConfig{Port: cliPort, LocalAddr: loopback(cliPort).String()})
	if err != nil {
		t.Fatal(err)
	}
	a := clientArgs{target: loopback(devPort).String(), device: int(f.DeviceInstance), scenarios: path,
		broadcast: loopback(devPort).String(), fdTTL: 60}
	if doc.RequiresBBMD {
		a.bbmd = loopback(devPort).String()
	}
	var out bytes.Buffer
	if code := runClient(a, clientConfig{timeout: time.Second, retries: 1, transport: cliTr}, &out); code != 0 {
		t.Fatalf("exit %d", code)
	}
	var lines []resultLine
	s := bufio.NewScanner(&out)
	s.Buffer(make([]byte, 1<<20), 1<<20)
	for s.Scan() {
		var l resultLine
		if err := json.Unmarshal(s.Bytes(), &l); err != nil {
			t.Fatalf("not a JSON line: %q", s.Text())
		}
		lines = append(lines, l)
	}
	return lines
}

// clientUnsupported are the scenarios the go-bacnet client cannot issue, with
// the reason; the README lists them. Each must be reported unsupported, so
// that the list goes stale loudly when go-bacnet changes.
var clientUnsupported = map[string]string{
	"reinit.undefined-state": "service.EncodeReinitializeDevice refuses a state it does not define (9)",
}

// The client and the device of one go-bacnet release agree on every
// scenario the client can issue. This is not interoperability evidence: both
// sides are go-bacnet.
func TestScenarioFilesAgainstOwnDevice(t *testing.T) {
	if testing.Short() {
		t.Skip("runs every scenario file over loopback UDP")
	}
	for _, name := range []string{"server-baseline-v1", "server-services-v1", "server-extended-v1", "server-bbmd-v1"} {
		t.Run(name, func(t *testing.T) {
			lines := runAgainstOwnDevice(t, name)
			if len(lines) < 3 || lines[0].Event != "ready" || lines[len(lines)-1].Event != "done" {
				t.Fatalf("want ready, results, done; got %d lines", len(lines))
			}
			for _, l := range lines[1 : len(lines)-1] {
				if reason, ok := clientUnsupported[l.Scenario]; ok {
					if l.Outcome != "unsupported" {
						t.Errorf("%s: %s, want unsupported (%s)", l.Scenario, l.Outcome, reason)
					}
					continue
				}
				if l.Outcome != "pass" {
					t.Errorf("%s: %s %s %s", l.Scenario, l.Outcome, l.Detail, l.Observed)
				}
			}
		})
	}
}

func TestCompare(t *testing.T) {
	cases := []struct {
		expect, observed string
		want             bool
	}{
		{`{"value":{"type":"real","value":42}}`, `{"value":{"type":"real","value":42.0000001}}`, true},
		{`{"value":{"type":"enumerated","value":"analog-value"}}`, `{"value":{"type":"enumerated","value":"Analog_Value"}}`, true},
		{`{"error":{"class":"object","code":"unknown-object"}}`, `{"error":{"class":"object","code":"unknown-property"}}`, false},
		{`{"error":{"class":"object","code":"unknown-object","first_failed_element":0}}`, `{"error":{"class":"object","code":"unknown-object"}}`, false},
		{`{"i-am":[1234]}`, `{"i-am":[]}`, false},
		{`{"reject":"Undefined Enumeration"}`, `{"reject":"undefined-enumeration"}`, true},
		{`{"subscribed":{"notification":true}}`, `{"subscribed":{"notification":false}}`, false},
		{`{"ack":true}`, `{"error":{"class":"x","code":"y"}}`, false},
	}
	for _, c := range cases {
		var e, o map[string]any
		_ = json.Unmarshal([]byte(c.expect), &e)
		_ = json.Unmarshal([]byte(c.observed), &o)
		if got := compare(e, o); got != c.want {
			t.Errorf("compare(%s, %s) = %v, want %v", c.expect, c.observed, got, c.want)
		}
	}
}

func TestUsage(t *testing.T) {
	for _, a := range []clientArgs{
		{device: -1, scenarios: "x"},
		{device: 1, scenarios: ""},
		{device: 1, scenarios: "x", fdTTL: 0},
		{device: 1, scenarios: "x", fdTTL: 60, target: "not-an-address"},
		{device: 1, scenarios: "/nonexistent.json", fdTTL: 60},
	} {
		var out bytes.Buffer
		if code := runClient(a, clientConfig{timeout: time.Second}, &out); code != 2 {
			t.Errorf("%+v: exit %d, want 2", a, code)
		}
	}
}
