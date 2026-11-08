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
    BACNET_STACK_IMAGE=... BACNET4J_IMAGE=... BACPYPES3_IMAGE=... BACPYPES_IMAGE=... ULBIOS_IMAGE=... \\
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
    # Legacy BACpypes (PyPI bacpypes 0.x), not BACpypes3.
    "bacpypes": "BACPYPES_IMAGE",
    "ulbios": "ULBIOS_IMAGE",
}
DEVICES = dict(CLIENTS)
GATE_DEVICE = "bacnet-stack"

# (client, device) -> {scenario: reason}. Filled from runs; each reason is
# a recorded behaviour of the device or client in PEER_SUPPORT.md.
_NO_REPLY = "no Reject or Abort encoder in ulbios, so no reply (PEER_SUPPORT.md, ulbios)"
ULBIOS_DEVICE_DIFFERENCES = {
    "who-has.name": "ulbios has no Who-Has (bacnet.Parse: ErrNotImplemented), so no I-Have",
    "who-has.object": "ulbios has no Who-Has (bacnet.Parse: ErrNotImplemented), so no I-Have",
    "rp.device.object-name": "no CharacterString encoder in ulbios: Error property/unknown-property",
    "rp.av1.object-name": "no CharacterString encoder in ulbios: Error property/unknown-property",
    "rp.unknown-property": "property 9999 does not fit ulbios' one-octet property identifier; " + _NO_REPLY,
    "rp.not-an-array": "ConfirmedReadProperty.Decode refuses an array index; " + _NO_REPLY,
    "rpm.av1.name-and-type": "no ReadPropertyMultiple in bacnet.Parse; " + _NO_REPLY,
    "rpm.unknown-object": "no ReadPropertyMultiple in bacnet.Parse; " + _NO_REPLY,
    "wp.av1.pv.relinquish8": "objects.DecNull refuses every NULL; " + _NO_REPLY,
    "wp.av1.pv.wrong-type": "no CharacterString decoder in ulbios; " + _NO_REPLY,
    "wpm.av1.pv.priority8": "no WritePropertyMultiple in bacnet.Parse; " + _NO_REPLY,
    "wpm.unknown-object-second": "no WritePropertyMultiple in bacnet.Parse; " + _NO_REPLY,
    "wpm.wrong-type": "no WritePropertyMultiple in bacnet.Parse; " + _NO_REPLY,
}
_BP_WRONG_TYPE = {"wp.av1.pv.wrong-type": "legacy BACpypes device: Reject invalid-tag for a value of the wrong datatype"}
_BACNET4J_UNBOUND = "BACnet4J device: no I-Am reaches the client, so it cannot bind"
_BACNET4J_SCENARIOS = (
    "who-is.range", "who-is.global", "who-has.name", "who-has.object",
    "rp.device.object-name", "rp.av1.object-name", "rp.av1.object-type", "rp.av1.object-identifier",
    "rp.bv1.present-value", "rp.unknown-object", "rp.unknown-property", "rp.not-an-array",
    "rpm.av1.name-and-type", "rpm.unknown-object", "wp.av1.pv.priority8", "wp.av1.pv.relinquish8",
    "wp.av1.pv.wrong-type", "wp.unknown-object", "wpm.av1.pv.priority8", "wpm.unknown-object-second",
    "wpm.wrong-type",
)
EXPECTED_DIFFERENCES: dict[tuple[str, str], dict[str, str]] = {
    **{(c, "ulbios"): ULBIOS_DEVICE_DIFFERENCES for c in ("bacnet-stack", "bacnet4j", "bacpypes3")},
    # The ulbios client sends no Who-Has, RPM, WPM, character string or array
    # index (unsupported); of the rest only these differ against its device.
    ("ulbios", "ulbios"): {k: ULBIOS_DEVICE_DIFFERENCES[k]
                           for k in ("rp.device.object-name", "rp.av1.object-name", "wp.av1.pv.relinquish8")},
    ("ulbios", "bacnet4j"): {"who-is.global": "the BACnet4J device's I-Am does not reach the client (PEER_SUPPORT.md, BACnet4J device)"},
    # The pairs with legacy BACpypes (`bacpypes`), from `--all-devices` runs.
    ("bacnet-stack", "bacpypes"): dict(_BP_WRONG_TYPE),
    ("bacnet4j", "bacpypes"): dict(_BP_WRONG_TYPE),
    ("bacpypes3", "bacpypes"): dict(_BP_WRONG_TYPE),
    ("bacpypes", "bacpypes"): dict(_BP_WRONG_TYPE),
    ("bacpypes", "bacnet4j"): {s: _BACNET4J_UNBOUND for s in _BACNET4J_SCENARIOS},
    ("bacpypes", "bacpypes3"): {
        "wp.av1.pv.wrong-type": "BACpypes3 device: Reject invalid-tag for a value of the wrong datatype",
        "wpm.wrong-type": "BACpypes3 device: Reject invalid-tag for a value of the wrong datatype",
        "wpm.unknown-object-second": "BACpypes3 device: plain Error 91 01 91 1f, which the legacy BACpypes client cannot decode as a WritePropertyMultiple-Error",
    },
}

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
