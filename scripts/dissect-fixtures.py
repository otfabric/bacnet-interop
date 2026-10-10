#!/usr/bin/env python3
"""Check the codec fixtures against Wireshark's BACnet dissector.

Every vector in fixtures/codec is wrapped into a BACnet/IP datagram (a service
payload gets the APDU header its `operation` implies), written to a pcap file
and dissected by tshark. A vector fails when tshark calls it malformed or
flags it with an expert warning or error, when it is dissected as another
service than the fixture says, or when a label listed for it in EXPECT is
missing from the decoded tree.

Why: hand-written vectors are derived from the implementation under test.
They guard against regressions but prove nothing about the layout. Wireshark
is a second, independent implementation. Its dissector walks tags leniently,
so "not malformed" is weak evidence; the EXPECT labels are what pins a layout
down, because Wireshark only assigns them when the tags sit where the standard
puts them. Add labels for every new vector of a service no peer serves.

Fixtures whose id contains "malformed" are expected to be rejected by a strict
decoder and are skipped. KNOWN lists vectors that fail this check and why.

    make dissect-fixtures            # needs tshark
    scripts/dissect-fixtures.py -v   # also print the decoded tree of each vector
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODEC = ROOT / "fixtures" / "codec"

# operation -> (PDU kind, service choice) for vectors that are service payloads.
SERVICE = {
    "decode_acknowledge_alarm": ("confirmed", 0),
    "decode_get_alarm_summary": ("confirmed", 3),
    "decode_get_enrollment_summary": ("confirmed", 4),
    "decode_subscribe_cov": ("confirmed", 5),
    "decode_atomic_read_file": ("confirmed", 6),
    "decode_atomic_write_file": ("confirmed", 7),
    "decode_list_element": ("confirmed", 8),
    "decode_create_object": ("confirmed", 10),
    "decode_delete_object": ("confirmed", 11),
    "decode_read_property": ("confirmed", 12),
    "decode_write_property": ("confirmed", 15),
    "decode_write_property_multiple": ("confirmed", 16),
    "decode_device_communication_control": ("confirmed", 17),
    "decode_private_transfer": ("confirmed", 18),
    "decode_reinitialize_device": ("confirmed", 20),
    "decode_vt_open": ("confirmed", 21),
    "decode_read_range": ("confirmed", 26),
    "decode_life_safety_operation": ("confirmed", 27),
    "decode_subscribe_cov_property": ("confirmed", 28),
    "decode_get_event_information": ("confirmed", 29),
    "decode_subscribe_cov_property_multiple": ("confirmed", 30),
    "decode_cov_notification_multiple": ("confirmed", 31),
    "decode_audit_log_query": ("confirmed", 33),
    "decode_event_notification": ("confirmed", 2),
    "decode_get_alarm_summary_ack": ("complex-ack", 3),
    "decode_get_enrollment_summary_ack": ("complex-ack", 4),
    "decode_atomic_read_file_ack": ("complex-ack", 6),
    "decode_atomic_write_file_ack": ("complex-ack", 7),
    "decode_create_object_ack": ("complex-ack", 10),
    "decode_read_property_ack": ("complex-ack", 12),
    "decode_rpm_ack": ("complex-ack", 14),
    "decode_read_range_ack": ("complex-ack", 26),
    "decode_get_event_information_ack": ("complex-ack", 29),
    "decode_write_property_multiple_error": ("error", 16),
    "decode_i_have": ("unconfirmed", 1),
    "decode_text_message": ("unconfirmed", 5),
    "decode_time_synchronization": ("unconfirmed", 6),
    "decode_who_has": ("unconfirmed", 7),
    "decode_write_group": ("unconfirmed", 10),
    "decode_who_am_i": ("unconfirmed", 13),
    "decode_you_are": ("unconfirmed", 14),
}

# Labels Wireshark must show for a vector (whitespace-insensitive). Keep to
# labels that are stable across Wireshark releases: object identifiers are
# rendered differently by 4.2 and 4.6, so they are not listed.
EXPECT: dict[str, list[str]] = {
    "service-subscribe-cov-property-multiple": [
        "subscriber Process Id: (Unsigned) 1",
        "life time (hh.mm.ss): 0.01.00",
        "list-of-cov-subscription-specifications",
        "list-of-cov-references",
        "timestamped: FALSE",
    ],
    "service-cov-notification-multiple": [
        "Time remaining: (hh.mm.ss): 0.01.00",
        "list-of-cov-notifications",
        "list-of-values",
        "Present Value (real): 21.5",
    ],
    "service-get-enrollment-summary-req": ["acknowledgment Filter: all (0)", "event State Filter: fault (1)"],
    "service-get-enrollment-summary-ack": [
        "event Type: out-of-range (5)",
        "event State: fault (1)",
        "Priority: (Unsigned) 100",
        "Notification Class: (Unsigned) 1",
    ],
    "service-get-event-information-ack": [
        "event State: fault (1)",
        "TO-OFFNORMAL timestamp: (Unsigned) 1",
        "TO-NORMAL Priority: (Unsigned) 3",
        "more Events: FALSE",
    ],
    "service-get-alarm-summary-ack": ["alarm State: fault (1)", "acknowledged Transitions"],
    "service-vt-open": ["vtClass: ansi-x3-64 (1)", "local VT Session ID: (Unsigned) 3"],
    "service-audit-log-query": [
        "query-parameters",
        "target-parameters",
        "Property Identifier: present-value (85)",
        "target-priority: (Unsigned) 8",
        "write = TRUE",
        "target-successful-action: successes-only (1)",
        "start-at-sequence-number: (Unsigned) 100",
        "requested-count: (Unsigned) 10",
    ],
    "service-who-am-i": ["Vendor ID: (Unsigned) 999", "Model name: UTF-8 'm'", "Serial number: UTF-8 's'"],
    "service-you-are": ["Vendor ID: (Unsigned) 999", "Serial number: UTF-8 's'"],
    "service-write-group": ["Group number: (Unsigned) 1", "Priority: (Unsigned) 8", "change-list"],
    "service-event-notification-seq": [
        "sequence number: (Unsigned) 7",
        "Notification Class: (Unsigned) 1",
        "Notify Type: alarm (0)",
        "To State: fault (1)",
    ],
    "service-rpm-ack-partial-error": ["Error Class: property (2)", "Error Code: unknown-property (32)"],
    "service-write-property-multiple-error": ["Error Class: property (2)", "Error Code: unknown-property (32)"],
    "apdu-error-unknown-property": ["Error Class: property (2)", "Error Code: unknown-property (32)"],
}

# Vectors known to fail, with the reason. They are reported, not failed.
KNOWN: dict[str, str] = {
    "bvlc-forwarded-npdu-empty": "BVLC framing vector: the NPDU carries neither an APDU nor a network message, which is not a complete frame",
    "bvlc-original-broadcast-npdu-empty": "BVLC framing vector: the NPDU carries neither an APDU nor a network message, which is not a complete frame",
    "bvlc-original-unicast-npdu-empty": "BVLC framing vector: the NPDU carries neither an APDU nor a network message, which is not a complete frame",
}

# Vectors that pass only because the dissector is lenient: Wireshark names the
# service but decodes no more than the first field, so nothing about the
# layout is confirmed. Reported as "weak".
WEAK: dict[str, str] = {}


def apdu_for(fixture: dict) -> tuple[str, bytes] | None:
    """Return (layer, bytes) with layer one of bvlc, npdu, apdu."""
    fid = fixture["id"]
    raw = bytes.fromhex(fixture.get("input_hex", ""))
    if fid.startswith("bvlc-"):
        return "bvlc", raw
    if fid.startswith("npdu-"):
        return "npdu", raw
    if fid.startswith("apdu-"):
        return "apdu", raw
    if fid.startswith("tag-"):
        return None
    kind_choice = SERVICE.get(fixture.get("operation", ""))
    if kind_choice is None:
        raise KeyError(f"{fid}: no APDU mapping for operation {fixture.get('operation')!r}")
    kind, choice = kind_choice
    if kind == "confirmed":
        # unsegmented, segmented response accepted, max segments 64, max APDU 1476
        return "apdu", bytes([0x02, 0x65, 0x01, choice]) + raw
    if kind == "complex-ack":
        return "apdu", bytes([0x30, 0x01, choice]) + raw
    if kind == "error":
        return "apdu", bytes([0x50, 0x01, choice]) + raw
    return "apdu", bytes([0x10, choice]) + raw


def datagram(layer: str, raw: bytes) -> bytes:
    if layer == "bvlc":
        return raw
    npdu = raw if layer == "npdu" else bytes([0x01, 0x00]) + raw
    return bytes([0x81, 0x0A]) + struct.pack(">H", len(npdu) + 4) + npdu


def pcap(frames: list[bytes]) -> bytes:
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    for i, payload in enumerate(frames):
        udp = struct.pack(">HHHH", 47808, 47808, 8 + len(payload), 0) + payload
        ip = bytearray(struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 0, 0, 64, 17, 0,
                                   bytes([10, 0, 0, 1]), bytes([10, 0, 0, 2])))
        total = sum(struct.unpack(">10H", bytes(ip)))
        while total >> 16:
            total = (total & 0xFFFF) + (total >> 16)
        struct.pack_into(">H", ip, 10, ~total & 0xFFFF)
        eth = bytes([2, 0, 0, 0, 0, 2, 2, 0, 0, 0, 0, 1, 0x08, 0x00])
        pkt = eth + bytes(ip) + udp
        out += struct.pack("<IIII", 1700000000 + i, 0, len(pkt), len(pkt)) + pkt
    return out


def squash(text: str) -> str:
    return " ".join(text.split())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-v", "--verbose", action="store_true", help="print the decoded tree of every vector")
    ap.add_argument("--only", help="check only fixtures whose id contains this text")
    args = ap.parse_args()

    tshark = shutil.which("tshark")
    if tshark is None:
        print("ERROR: tshark not found on PATH", file=sys.stderr)
        return 1

    ids: list[str] = []
    frames: list[bytes] = []
    skipped = 0
    for path in sorted(CODEC.glob("*.json")):
        fixture = json.loads(path.read_text())
        fid = fixture["id"]
        if args.only and args.only not in fid:
            continue
        if "malformed" in fid or not fixture.get("input_hex"):
            skipped += 1
            continue
        wrapped = apdu_for(fixture)
        if wrapped is None:
            skipped += 1
            continue
        ids.append(fid)
        frames.append(datagram(*wrapped))

    with tempfile.TemporaryDirectory() as tmp:
        cap = Path(tmp) / "fixtures.pcap"
        cap.write_bytes(pcap(frames))
        fields = subprocess.run(
            [tshark, "-r", str(cap), "-T", "fields", "-E", "separator=|",
             "-e", "_ws.col.info", "-e", "_ws.malformed", "-e", "_ws.expert.severity", "-e", "_ws.expert.message"],
            check=True, capture_output=True, text=True).stdout.rstrip("\n").split("\n")
        tree = subprocess.run([tshark, "-r", str(cap), "-V"], check=True, capture_output=True, text=True).stdout
        version = subprocess.run([tshark, "--version"], check=True, capture_output=True, text=True).stdout.split("\n")[0]

    trees = ("\n" + tree).split("\nFrame ")[1:]
    if len(fields) != len(frames) or len(trees) != len(frames):
        print(f"ERROR: tshark reported {len(fields)}/{len(trees)} frames for {len(frames)} written", file=sys.stderr)
        return 1

    failures = 0
    known = 0
    for fid, line, block in zip(ids, fields, trees):
        info, malformed, severity, message = (line.split("|") + ["", "", "", ""])[:4]
        problems: list[str] = []
        if malformed or "malformed" in info.lower():
            problems.append(f"malformed: {message or info}")
        # expert severities: warn 0x600000, error 0x800000
        if any(s in ("6291456", "8388608") for s in severity.split(",")):
            problems.append(f"expert: {message}")
        flat = squash(block)
        for label in EXPECT.get(fid, []):
            if squash(label) not in flat:
                problems.append(f"label not decoded: {label!r}")
        status = "ok"
        if problems:
            if fid in KNOWN:
                status = "known"
                known += 1
            else:
                status = "FAIL"
                failures += 1
        if status == "ok" and fid in WEAK:
            status = "weak"
        print(f"{status:5} {fid:52} {squash(info)}")
        if status == "weak":
            print(f"        weak: {WEAK[fid]}")
        for p in problems:
            print(f"        {p}")
        if status == "known":
            print(f"        known: {KNOWN[fid]}")
        if args.verbose:
            start = block.find("Building Automation and Control Network")
            print("\n".join("        | " + l for l in block[start if start >= 0 else 0:].rstrip().split("\n")))

    # A KNOWN entry that no longer fails is stale and must be removed.
    failing = {fid for fid, line, block in zip(ids, fields, trees)
               if line.split("|")[1:2] not in ([""], [])}
    for fid in KNOWN:
        if fid in ids and fid not in failing:
            print(f"FAIL  {fid}: listed in KNOWN but dissects cleanly; remove the entry")
            failures += 1
    print(f"\n{version}")
    print(f"dissect-fixtures: {len(ids)} checked, {failures} failed, {known} known, {skipped} skipped "
          f"(malformed-by-design, empty or tag-level), {sum(1 for i in ids if i in EXPECT)} with layout labels")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
