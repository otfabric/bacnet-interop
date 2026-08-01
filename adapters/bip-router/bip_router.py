#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Minimal BACnet/IP ↔ BACnet/IP router for Horizon 1 interop topology tests.

Two UDP ports (typically two docker-network addresses) with distinct BACnet
network numbers. Supports:
  - Who-Is-Router-To-Network → I-Am-Router-To-Network
  - Forwarding unicast/broadcast NPDUs with DNET toward the other side
  - Hop-count decrement (ASHRAE order: hop immediately after DADR, before SNET)
  - Return-path assist for peers that reply without reverse DNET/DADR
  - Final unicast delivery omits SNET so non-routing peers reply locally
  - Local-broadcast forwarding with SNET (I-Am toward the originating net)

This is topology infrastructure for go-bacnet interop, not a product BBMD/router.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import signal
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from typing import Optional


BVLC_TYPE = 0x81
BVLC_ORIGINAL_UNICAST = 0x0A
BVLC_ORIGINAL_BROADCAST = 0x0B
BVLC_FORWARDED = 0x04

NPDU_VERSION = 0x01
NPDU_NETMSG = 0x80
NPDU_DNET = 0x20
NPDU_SNET = 0x08
NPDU_EXPECTING_REPLY = 0x04

NETMSG_WHO_IS_ROUTER = 0x00
NETMSG_I_AM_ROUTER = 0x01

RETURN_PATH_TTL_SEC = 30.0


@dataclass
class Port:
    name: str
    network: int
    addr: str
    port: int
    sock: Optional[socket.socket] = None

    @property
    def endpoint(self) -> tuple[str, int]:
        return (self.addr, self.port)


@dataclass
class ReturnPath:
    egress: Port
    dest: tuple[str, int]
    expires: float


def emit_ready(version: str, networks: list[int], addresses: list[str]) -> None:
    line = {
        "event": "ready",
        "adapter": "bip-router",
        "version": version,
        "fixture": "topology-router-v1",
        "address": addresses[0] if addresses else "0.0.0.0:47808",
        "networks": networks,
        "addresses": addresses,
        "peer_version": "interop-bip-router",
    }
    sys.stdout.write(json.dumps(line, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def parse_port_spec(spec: str) -> Port:
    # format: name=eth0,network=1,addr=172.18.0.2,port=47808
    fields: dict[str, str] = {}
    for part in spec.split(","):
        if "=" not in part:
            raise ValueError(f"bad port spec fragment: {part!r}")
        k, v = part.split("=", 1)
        fields[k.strip()] = v.strip()
    return Port(
        name=fields.get("name", "port"),
        network=int(fields["network"]),
        addr=fields["addr"],
        port=int(fields.get("port", "47808")),
    )


def bvlc_wrap(function: int, payload: bytes) -> bytes:
    length = 4 + len(payload)
    return bytes([BVLC_TYPE, function, (length >> 8) & 0xFF, length & 0xFF]) + payload


def parse_bvlc(data: bytes) -> tuple[int, bytes] | None:
    if len(data) < 4 or data[0] != BVLC_TYPE:
        return None
    function = data[1]
    length = (data[2] << 8) | data[3]
    if length != len(data):
        return None
    return function, data[4:]


def encode_iam_router(networks: list[int], bvlc_fn: int = BVLC_ORIGINAL_BROADCAST) -> bytes:
    body = bytes([NPDU_VERSION, NPDU_NETMSG, NETMSG_I_AM_ROUTER])
    for net in networks:
        body += struct.pack(">H", net)
    return bvlc_wrap(bvlc_fn, body)


def decode_npdu(payload: bytes) -> dict | None:
    """Decode NPDU; hop count is immediately after DADR (before SNET)."""
    if len(payload) < 2 or payload[0] != NPDU_VERSION:
        return None
    control = payload[1]
    off = 2
    info: dict = {
        "control": control,
        "network_message": bool(control & NPDU_NETMSG),
        "expecting_reply": bool(control & NPDU_EXPECTING_REPLY),
        "dnet": None,
        "dadr": b"",
        "snet": None,
        "sadr": b"",
        "hop": None,
    }
    if control & NPDU_DNET:
        if off + 3 > len(payload):
            return None
        dnet = (payload[off] << 8) | payload[off + 1]
        dlen = payload[off + 2]
        off += 3
        if off + dlen > len(payload):
            return None
        info["dnet"] = dnet
        info["dadr"] = payload[off : off + dlen]
        off += dlen
        if off >= len(payload):
            return None
        info["hop"] = payload[off]
        off += 1
    if control & NPDU_SNET:
        if off + 3 > len(payload):
            return None
        snet = (payload[off] << 8) | payload[off + 1]
        slen = payload[off + 2]
        off += 3
        if off + slen > len(payload):
            return None
        info["snet"] = snet
        info["sadr"] = payload[off : off + slen]
        off += slen
    if info["network_message"]:
        if off >= len(payload):
            return None
        info["netmsg_type"] = payload[off]
        info["netmsg_data"] = payload[off + 1 :]
    else:
        info["apdu"] = payload[off:]
    return info


def encode_npdu(
    *,
    apdu: bytes = b"",
    netmsg_type: Optional[int] = None,
    netmsg_data: bytes = b"",
    dnet: Optional[int] = None,
    dadr: bytes = b"",
    snet: Optional[int] = None,
    sadr: bytes = b"",
    hop: Optional[int] = None,
    expecting_reply: bool = False,
) -> bytes:
    control = 0
    if netmsg_type is not None:
        control |= NPDU_NETMSG
    if expecting_reply:
        control |= NPDU_EXPECTING_REPLY
    body = bytearray([NPDU_VERSION, 0])
    if dnet is not None:
        control |= NPDU_DNET
        body += struct.pack(">HB", dnet, len(dadr)) + dadr
        body.append(255 if hop is None else hop)
    if snet is not None:
        control |= NPDU_SNET
        body += struct.pack(">HB", snet, len(sadr)) + sadr
    body[1] = control
    if netmsg_type is not None:
        body.append(netmsg_type)
        body += netmsg_data
    else:
        body += apdu
    return bytes(body)


def mac_to_endpoint(mac: bytes) -> tuple[str, int] | None:
    if len(mac) != 6:
        return None
    ip = socket.inet_ntoa(mac[:4])
    port = (mac[4] << 8) | mac[5]
    return ip, port


def endpoint_to_mac(ip: str, port: int) -> bytes:
    return socket.inet_aton(ip) + bytes([(port >> 8) & 0xFF, port & 0xFF])


class Router:
    def __init__(self, ports: list[Port]) -> None:
        if len(ports) != 2:
            raise ValueError("exactly two ports required")
        self.ports = ports
        self.by_net = {p.network: p for p in ports}
        self.running = True
        self.return_paths: dict[tuple[str, int], ReturnPath] = {}

    def start(self) -> None:
        for p in self.ports:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind((p.addr, p.port))
            p.sock = s
            print(
                f"router port {p.name} net={p.network} bind={p.addr}:{p.port}",
                file=sys.stderr,
                flush=True,
            )

    def stop(self) -> None:
        self.running = False
        for p in self.ports:
            if p.sock:
                p.sock.close()
                p.sock = None

    def other(self, port: Port) -> Port:
        return self.ports[1] if port is self.ports[0] else self.ports[0]

    def send(self, port: Port, dest: tuple[str, int], frame: bytes) -> None:
        assert port.sock is not None
        port.sock.sendto(frame, dest)

    def remember(self, device: tuple[str, int], egress: Port, dest: tuple[str, int]) -> None:
        self.return_paths[device] = ReturnPath(
            egress=egress, dest=dest, expires=time.time() + RETURN_PATH_TTL_SEC
        )

    def lookup_return(self, device: tuple[str, int]) -> Optional[ReturnPath]:
        ent = self.return_paths.get(device)
        if ent is None:
            return None
        if time.time() > ent.expires:
            del self.return_paths[device]
            return None
        return ent

    def handle_who_is_router(self, ingress: Port, src: tuple[str, int], netmsg_data: bytes) -> None:
        if len(netmsg_data) >= 2:
            want = (netmsg_data[0] << 8) | netmsg_data[1]
            if want not in self.by_net or want == ingress.network:
                return
            announce = [want]
        else:
            announce = [p.network for p in self.ports if p.network != ingress.network]
        if not announce:
            return
        # Directed reply as Original-Unicast so docker/ephemeral clients that
        # miss 255.255.255.255 still learn the next hop; also broadcast.
        self.send(ingress, src, encode_iam_router(announce, BVLC_ORIGINAL_UNICAST))
        self.send(
            ingress,
            ("255.255.255.255", ingress.port),
            encode_iam_router(announce, BVLC_ORIGINAL_BROADCAST),
        )

    def forward_with_dnet(self, ingress: Port, src: tuple[str, int], info: dict) -> None:
        dnet = info["dnet"]
        hop = info.get("hop")
        if hop is not None and hop <= 1:
            return
        new_hop = 255 if hop is None else hop - 1
        smac = endpoint_to_mac(src[0], src[1])
        apdu = info.get("apdu", b"")
        expecting = bool(info.get("expecting_reply"))

        if dnet == 0xFFFF:
            egress = self.other(ingress)
            forwarded = encode_npdu(
                apdu=apdu,
                dnet=0xFFFF,
                dadr=b"",
                snet=ingress.network,
                sadr=smac,
                hop=new_hop,
                expecting_reply=expecting,
            )
            self.send(
                egress,
                ("255.255.255.255", egress.port),
                bvlc_wrap(BVLC_ORIGINAL_BROADCAST, forwarded),
            )
            return

        egress = self.by_net.get(dnet)
        if egress is None or egress is ingress:
            return

        dadr = info.get("dadr") or b""
        if len(dadr) == 0:
            forwarded = encode_npdu(
                apdu=apdu,
                snet=ingress.network,
                sadr=smac,
                expecting_reply=expecting,
            )
            self.send(
                egress,
                ("255.255.255.255", egress.port),
                bvlc_wrap(BVLC_ORIGINAL_BROADCAST, forwarded),
            )
            return

        dest = mac_to_endpoint(dadr)
        if dest is None:
            return
        # Final unicast delivery omits SNET/SADR. Non-routing peers such as
        # bacnet-stack then treat the request as local and reply to this
        # router's BIP address; return-path assist forwards that reply.
        # Including SNET forces those peers to reverse-route via DNET/DADR,
        # which is unreliable without a learned router table.
        forwarded = encode_npdu(
            apdu=apdu,
            expecting_reply=expecting,
        )
        self.remember(dest, ingress, src)
        self.send(egress, dest, bvlc_wrap(BVLC_ORIGINAL_UNICAST, forwarded))

    def forward_local_broadcast(self, ingress: Port, src: tuple[str, int], info: dict) -> None:
        egress = self.other(ingress)
        smac = endpoint_to_mac(src[0], src[1])
        forwarded = encode_npdu(
            apdu=info.get("apdu", b""),
            snet=ingress.network,
            sadr=smac,
        )
        self.send(
            egress,
            ("255.255.255.255", egress.port),
            bvlc_wrap(BVLC_ORIGINAL_BROADCAST, forwarded),
        )

    def forward_return_path(self, ingress: Port, src: tuple[str, int], info: dict) -> bool:
        path = self.lookup_return(src)
        if path is None:
            return False
        smac = endpoint_to_mac(src[0], src[1])
        forwarded = encode_npdu(
            apdu=info.get("apdu", b""),
            snet=ingress.network,
            sadr=smac,
            expecting_reply=bool(info.get("expecting_reply")),
        )
        self.send(path.egress, path.dest, bvlc_wrap(BVLC_ORIGINAL_UNICAST, forwarded))
        return True

    def handle(self, ingress: Port, data: bytes, src: tuple[str, int]) -> None:
        parsed = parse_bvlc(data)
        if parsed is None:
            return
        function, payload = parsed
        if function not in (BVLC_ORIGINAL_UNICAST, BVLC_ORIGINAL_BROADCAST, BVLC_FORWARDED):
            return
        if function == BVLC_FORWARDED:
            if len(payload) < 6:
                return
            payload = payload[6:]
        info = decode_npdu(payload)
        if info is None:
            return
        if info["network_message"]:
            if info.get("netmsg_type") == NETMSG_WHO_IS_ROUTER:
                self.handle_who_is_router(ingress, src, info.get("netmsg_data", b""))
            return

        if info.get("dnet") is not None:
            self.forward_with_dnet(ingress, src, info)
            return

        if function == BVLC_ORIGINAL_BROADCAST:
            self.forward_local_broadcast(ingress, src, info)
            return

        if function == BVLC_ORIGINAL_UNICAST:
            self.forward_return_path(ingress, src, info)

    def serve(self) -> None:
        assert all(p.sock for p in self.ports)
        while self.running:
            rlist, _, _ = select.select([p.sock for p in self.ports], [], [], 0.5)
            for sock in rlist:
                ingress = next(p for p in self.ports if p.sock is sock)
                try:
                    data, src = sock.recvfrom(2048)
                except OSError:
                    continue
                try:
                    self.handle(ingress, data, src)
                except Exception as exc:  # noqa: BLE001
                    print(f"router handle error: {exc}", file=sys.stderr, flush=True)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="bacnet-interop BIP↔BIP router")
    p.add_argument(
        "--port",
        action="append",
        dest="ports",
        required=True,
        help="Port spec: name=eth0,network=1,addr=1.2.3.4,port=47808 (repeat twice)",
    )
    args = p.parse_args(argv)
    if len(args.ports) != 2:
        print("exactly two --port specs required", file=sys.stderr)
        return 2

    ports = [parse_port_spec(s) for s in args.ports]
    version = os.environ.get("ADAPTER_VERSION", "dev")
    router = Router(ports)

    def _stop(*_a: object) -> None:
        router.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    router.start()
    emit_ready(
        version,
        [p.network for p in ports],
        [f"{p.addr}:{p.port}" for p in ports],
    )

    def announce_routers() -> None:
        for ingress in ports:
            others = [p.network for p in ports if p is not ingress]
            frame = encode_iam_router(others)
            router.send(ingress, ("255.255.255.255", ingress.port), frame)

    # Repeat startup I-Am-Router: docker bridges occasionally drop the first
    # UDP broadcast after network connect.
    announce_routers()
    time.sleep(0.2)
    announce_routers()

    router.serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
