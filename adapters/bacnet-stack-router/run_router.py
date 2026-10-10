#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Configure and start upstream bacnet-stack apps/router; emit ready.

apps/router binds its ports by interface name. Docker does not guarantee
eth0/eth1 order after create + network connect, so the BACnet network numbers
are bound to addresses here (BACNET_ADDR_NET1 / BACNET_ADDR_NET2) and the
interface that carries each address is looked up at start.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ADAPTER = "bacnet-stack-router"
FIXTURE = "topology-router-v1"
PORT_DEFAULT = 47808
SIOCGIFADDR = 0x8915


def iface_ipv4(name: str) -> str | None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            raw = fcntl.ioctl(
                sock.fileno(), SIOCGIFADDR, struct.pack("256s", name.encode()[:15])
            )
        except OSError:
            return None
    return socket.inet_ntoa(raw[20:24])


def interfaces() -> dict[str, str]:
    """Map IPv4 address -> interface name (loopback left out)."""
    out: dict[str, str] = {}
    for _index, name in socket.if_nameindex():
        if name == "lo":
            continue
        addr = iface_ipv4(name)
        if addr:
            out[addr] = name
    return out


def resolve_ports(addrs: list[str], timeout: float = 30.0) -> list[tuple[str, str]]:
    """Return [(iface, addr)] in network order, waiting for both interfaces."""
    deadline = time.monotonic() + timeout
    while True:
        by_addr = interfaces()
        if all(addrs):
            if all(a in by_addr for a in addrs):
                return [(by_addr[a], a) for a in addrs]
        else:
            # No explicit addresses: eth0 / eth1 order (unsafe on Docker after
            # create + network connect; see README).
            by_name = {name: addr for addr, name in by_addr.items()}
            if "eth0" in by_name and "eth1" in by_name:
                return [("eth0", by_name["eth0"]), ("eth1", by_name["eth1"])]
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"timed out waiting for two interfaces (want {addrs}, have {by_addr}); "
                "connect the container to two docker networks and set "
                "BACNET_ADDR_NET1 / BACNET_ADDR_NET2"
            )
        time.sleep(0.2)


def write_config(path: Path, ports: list[tuple[str, str]], networks: list[int], port: int) -> None:
    entries = []
    for (iface, _addr), net in zip(ports, networks):
        entries.append(
            "    {\n"
            '        device_type = "bip";\n'
            f'        device = "{iface}";\n'
            f"        port = {port};\n"
            f"        network = {net};\n"
            "    }"
        )
    path.write_text("ports =\n(\n" + ",\n".join(entries) + "\n);\n", encoding="utf-8")


def udp_sockets(port: int) -> int:
    """Count UDP sockets bound to port in this network namespace."""
    suffix = f":{port:04X}"
    try:
        lines = Path("/proc/net/udp").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    count = 0
    for line in lines[1:]:
        fields = line.split()
        if len(fields) > 1 and fields[1].upper().endswith(suffix):
            count += 1
    return count


def emit_ready(version: str, peer_version: str, networks: list[int],
               ports: list[tuple[str, str]], port: int) -> None:
    addresses = [f"{addr}:{port}" for _iface, addr in ports]
    line = {
        "event": "ready",
        "adapter": ADAPTER,
        "version": version,
        "fixture": FIXTURE,
        "address": addresses[0],
        "networks": networks,
        "addresses": addresses,
        "interfaces": [iface for iface, _addr in ports],
        "peer_version": peer_version,
    }
    sys.stdout.write(json.dumps(line, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    port = int(os.environ.get("BACNET_IP_PORT", PORT_DEFAULT))
    version = os.environ.get("ADAPTER_VERSION", "dev")
    peer_version = os.environ.get("BACNET_STACK_VERSION", "unknown")
    try:
        networks = [int(n) for n in os.environ.get("BACNET_NETWORKS", "1,2").split(",")]
    except ValueError:
        networks = []
    if len(networks) != 2 or networks[0] == networks[1] or not all(1 <= n <= 65534 for n in networks):
        print(f"{ADAPTER}: BACNET_NETWORKS must name two distinct networks 1..65534", file=sys.stderr)
        return 2
    addrs = [os.environ.get("BACNET_ADDR_NET1", ""), os.environ.get("BACNET_ADDR_NET2", "")]

    try:
        ports = resolve_ports(addrs)
    except RuntimeError as exc:
        print(f"{ADAPTER}: {exc}", file=sys.stderr)
        return 1
    for (iface, addr), net in zip(ports, networks):
        print(f"{ADAPTER}: net={net} iface={iface} addr={addr}:{port}", file=sys.stderr)

    cfg = Path(tempfile.mkdtemp(prefix="bacnet-router-")) / "router.cfg"
    write_config(cfg, ports, networks, port)

    # stdin is a pipe that stays open and empty: the router polls stdin for an
    # ESC key with FIONREAD, which is undefined on /dev/null.
    # Its stdout carries configuration chatter, not JSON: send it to stderr.
    proc = subprocess.Popen(
        ["bacnet-router", "-c", str(cfg)],
        stdin=subprocess.PIPE,
        stdout=sys.stderr,
        stderr=sys.stderr,
    )

    def _stop(*_args: object) -> None:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    deadline = time.monotonic() + 15
    while udp_sockets(port) < len(ports):
        if proc.poll() is not None:
            print(f"{ADAPTER}: router exited before binding UDP {port}", file=sys.stderr)
            return proc.returncode or 1
        if time.monotonic() >= deadline:
            print(f"{ADAPTER}: timed out waiting for {len(ports)} UDP sockets on {port}", file=sys.stderr)
            _stop()
            proc.wait(timeout=5)
            return 1
        time.sleep(0.05)

    emit_ready(version, peer_version, networks, ports, port)
    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
