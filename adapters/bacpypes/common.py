# SPDX-License-Identifier: MIT
"""Helpers shared by the legacy BACpypes device server and client driver.

Nothing in here talks BACnet: it finds the container's address and writes
JSON Lines. The BACnet work is done by the upstream ``bacpypes`` package.
"""

import fcntl
import json
import socket
import struct
import sys
import threading

ADAPTER = "bacpypes"

_out_lock = threading.Lock()


def emit(line):
    """One JSON Lines event on stdout (the contract output)."""
    text = json.dumps(line, separators=(",", ":"))
    with _out_lock:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()


def log(msg):
    """A diagnostic on stderr."""
    with _out_lock:
        sys.stderr.write("bacpypes: %s\n" % (msg,))
        sys.stderr.flush()


def local_ipv4(towards="192.0.2.1:47808"):
    """This container's address on the route towards HOST:PORT (no packet is sent)."""
    host, _, port = towards.rpartition(":")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((host, int(port)))
        return s.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())
    finally:
        s.close()


def interface_prefix(ip):
    """Prefix length of the local IPv4 subnet that holds ip, or None."""
    siocgifaddr, siocgifnetmask = 0x8915, 0x891B
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for _, name in socket.if_nameindex():
            ifreq = struct.pack("256s", name.encode()[:15])
            try:
                addr = socket.inet_ntoa(fcntl.ioctl(probe.fileno(), siocgifaddr, ifreq)[20:24])
                if addr != ip:
                    continue
                mask = fcntl.ioctl(probe.fileno(), siocgifnetmask, ifreq)[20:24]
            except OSError:
                continue
            return bin(int.from_bytes(mask, "big")).count("1")
    finally:
        probe.close()
    return None


def truthy(v):
    return v is not None and v.strip().lower() in ("1", "true", "yes")
