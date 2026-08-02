#!/usr/bin/env python3
"""Directed Who-Is → I-Am probe for adapter smoke tests.

Sends a BACnet/IP Original-Unicast Who-Is (no limits) to a peer and waits for
an I-Am. Many peers (notably bacnet-stack) answer with an Original-Broadcast
I-Am to UDP/47808 rather than unicasting to the Who-Is source port, so this
probe binds :47808 by default.

Used by scripts/smoke-test.sh; does not depend on go-bacnet.

Usage:
  python3 scripts/whois-probe.py --host 172.18.0.2 [--port 47808] [--timeout 5]
"""

from __future__ import annotations

import argparse
import socket
import sys
import time


# BVLC Original-Unicast-NPDU + NPDU (local) + Unconfirmed Who-Is (no limits).
WHO_IS = bytes.fromhex("810a000801001008")


def looks_like_iam(data: bytes) -> bool:
    """Best-effort I-Am detection on a BACnet/IP UDP datagram."""
    if len(data) < 8:
        return False
    if data[0] != 0x81:
        return False
    # Original-Unicast (0x0a) or Original-Broadcast (0x0b) or Forwarded (0x04).
    if data[1] not in (0x0A, 0x0B, 0x04):
        return False
    # Find APDU after BVLC (+ optional Forwarded origin) and NPDU.
    off = 4
    if data[1] == 0x04:
        # Forwarded-NPDU: 4 BVLC + 6 origin IP/port
        if len(data) < 12:
            return False
        off = 10
    if off + 2 > len(data) or data[off] != 0x01:
        return False
    # NPDU control at off+1; hop over optional DNET/DADR/SNET/SADR.
    ctrl = data[off + 1]
    apdu_off = off + 2
    if ctrl & 0x20:  # destination specifier
        if apdu_off + 3 > len(data):
            return False
        dlen = data[apdu_off + 2]
        apdu_off += 3 + dlen
        # Hop Count is present whenever a destination specifier is present,
        # including global broadcast (DNET=0xFFFF, DLEN=0).
        if apdu_off >= len(data):
            return False
        apdu_off += 1
    if ctrl & 0x08:  # source specifier
        if apdu_off + 3 > len(data):
            return False
        slen = data[apdu_off + 2]
        apdu_off += 3 + slen
    if apdu_off + 2 > len(data):
        return False
    # Unconfirmed-Request (0x10), service I-Am (0x00).
    return data[apdu_off] == 0x10 and data[apdu_off + 1] == 0x00


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", required=True, help="peer IPv4 address")
    p.add_argument("--port", type=int, default=47808, help="peer UDP port")
    p.add_argument(
        "--bind-port",
        type=int,
        default=47808,
        help="local UDP bind port (default 47808; needed for broadcast I-Am)",
    )
    p.add_argument("--timeout", type=float, default=5.0, help="seconds to wait for I-Am")
    args = p.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.bind(("0.0.0.0", args.bind_port))
    except OSError as exc:
        print(f"whois-probe: bind 0.0.0.0:{args.bind_port} failed: {exc}", file=sys.stderr)
        return 2
    sock.settimeout(0.25)
    try:
        # Discard any startup I-Am already in the socket buffer / network.
        deadline_flush = time.monotonic() + 0.3
        while time.monotonic() < deadline_flush:
            try:
                sock.recvfrom(2048)
            except socket.timeout:
                break

        sock.sendto(WHO_IS, (args.host, args.port))
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            try:
                data, src = sock.recvfrom(2048)
            except socket.timeout:
                continue
            if looks_like_iam(data):
                print(
                    f"whois-probe: I-Am from {src[0]}:{src[1]} ({len(data)} bytes)",
                    flush=True,
                )
                return 0
        print(
            f"whois-probe: no I-Am from {args.host}:{args.port} within {args.timeout}s",
            file=sys.stderr,
        )
        return 1
    finally:
        sock.close()


if __name__ == "__main__":
    raise SystemExit(main())
