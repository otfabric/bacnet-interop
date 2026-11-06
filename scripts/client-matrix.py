#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""client-matrix.py: every client-mode image against every device image.

Runs one scenario file (default server-baseline-v1, which the device images
serve with device-baseline-v2) with each client image against the
bacnet-stack device image, or with --all-devices against every device
image, on a private docker network, and prints one table row per client.

The scenario expectations record bacnet-stack's answers where the standard
leaves the error open, so the bacnet-stack device is the gate. The other
device images answer some scenarios differently (PEER_SUPPORT.md, "Client
mode"); --all-devices reports those pairs and fails only on the gate.

A pair passes when no result line is `fail` or `infra-error`. A pair listed
in EXPECTED_DIFFERENCES may have the named scenarios fail, each with the
reason recorded in PEER_SUPPORT.md; any other failure, a listed scenario
that now passes, or a run with no `pass` at all fails the matrix.

Usage:
    BACNET_STACK_IMAGE=... BACNET4J_IMAGE=... BACPYPES3_IMAGE=... \\
        scripts/client-matrix.py [--scenarios server-baseline-v1]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid

# Images with client mode, and the device images they are run against.
CLIENTS = {
    "bacnet-stack": "BACNET_STACK_IMAGE",
    "bacnet4j": "BACNET4J_IMAGE",
    "bacpypes3": "BACPYPES3_IMAGE",
}
DEVICES = dict(CLIENTS)
GATE_DEVICE = "bacnet-stack"

# (client, device) -> {scenario: reason}. Filled from runs; each reason is
# a recorded behaviour of the device or client in PEER_SUPPORT.md.
EXPECTED_DIFFERENCES: dict[tuple[str, str], dict[str, str]] = {}

READY_TIMEOUT = 120
RUN_TIMEOUT = 600


def docker(*args: str, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], check=check, capture_output=True, text=True, timeout=timeout)


def wait_ready(name: str) -> None:
    deadline = time.time() + READY_TIMEOUT
    while time.time() < deadline:
        logs = docker("logs", name, check=False)
        for line in (logs.stdout + logs.stderr).splitlines():
            if '"event":"ready"' in line.replace(" ", ""):
                return
        state = docker("inspect", "-f", "{{.State.Running}}", name, check=False).stdout.strip()
        if state != "true":
            raise RuntimeError(f"device container {name} exited:\n{logs.stdout}{logs.stderr}")
        time.sleep(1)
    raise RuntimeError(f"device container {name} not ready in {READY_TIMEOUT} s")


def run_pair(client_image: str, device_image: str, scenarios: str) -> list[dict]:
    tag = uuid.uuid4().hex[:8]
    net, dev = f"cm-{tag}-net", f"cm-{tag}-dev"
    docker("network", "create", net)
    try:
        docker("run", "-d", "--name", dev, "--network", net, device_image)
        wait_ready(dev)
        ip = docker("inspect", "-f", f"{{{{(index .NetworkSettings.Networks \"{net}\").IPAddress}}}}", dev).stdout.strip()
        out = docker("run", "--rm", "--network", net, client_image, "client",
                     "--target", f"{ip}:47808", "--device", "1234",
                     "--scenarios", f"/scenarios/{scenarios}.json", check=False, timeout=RUN_TIMEOUT)
        lines = []
        for raw in out.stdout.splitlines():
            try:
                ev = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if ev.get("event") == "result":
                lines.append(ev)
        if not lines:
            raise RuntimeError(f"client {client_image} printed no result lines (exit {out.returncode}):\n{out.stderr[-2000:]}")
        return lines
    finally:
        docker("rm", "-f", dev, check=False)
        docker("network", "rm", net, check=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default="server-baseline-v1")
    ap.add_argument("--all-devices", action="store_true", help="also run against the other device images (reported, not gated)")
    args = ap.parse_args()
    devices = list(DEVICES) if args.all_devices else [GATE_DEVICE]

    images = {k: os.environ.get(v, f"bacnet-interop-{k}:local") for k, v in CLIENTS.items()}
    failed = False
    print(f"| client \\ device | {' | '.join(devices)} |")
    print(f"|---|{'---|' * len(devices)}")
    for client in CLIENTS:
        cells = []
        for device in devices:
            gated = device == GATE_DEVICE
            expected = EXPECTED_DIFFERENCES.get((client, device), {})
            try:
                lines = run_pair(images[client], images[device], args.scenarios)
            except Exception as exc:  # noqa: BLE001 - report and go on
                print(f"{client} -> {device}: {exc}", file=sys.stderr)
                cells.append("error")
                failed = failed or gated
                continue
            counts: dict[str, int] = {}
            bad = []
            for ev in lines:
                counts[ev["outcome"]] = counts.get(ev["outcome"], 0) + 1
                scen = ev["scenario"]
                if ev["outcome"] in ("fail", "infra-error") and scen not in expected:
                    bad.append(f"{scen}: {ev['outcome']} {json.dumps(ev.get('observed', ev.get('detail', '')))[:300]}")
                if ev["outcome"] == "pass" and scen in expected:
                    bad.append(f"{scen}: listed as a difference ({expected[scen]}) but passes")
            if counts.get("pass", 0) == 0:
                bad.append("no scenario passed")
            for b in bad:
                print(f"{client} -> {device}: {b}", file=sys.stderr)
            failed = failed or (gated and bool(bad))
            mark = (" FAIL" if gated else " (differs)") if bad else ""
            cells.append(" ".join(f"{k} {v}" for k, v in sorted(counts.items())) + mark)
        print(f"| {client} | {' | '.join(cells)} |")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
