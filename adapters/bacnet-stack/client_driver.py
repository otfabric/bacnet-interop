#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""bacnet-stack client mode (docs/CLIENT_DRIVER_CONTRACT.md).

Runs the upstream bacnet-stack command-line tools at the image's pin against
a device under test, one process per scenario, and turns their printed output
into result lines. The tools are not modified; what they print is what
bacnet-stack decoded.

The tools bind to the device by Who-Is (their --mac option is not used for
confirmed services: bound that way, bacrp at the pin never matches the
reply). --target must therefore be reachable by the Who-Is broadcast: on the
container's network, or through the BBMD given by --bbmd, with which every
service tool then registers as a foreign device (bacnet-stack dlenv.c
BACNET_BBMD_ADDRESS, BACNET_BBMD_PORT, BACNET_BBMD_TIMETOLIVE). The binding is
checked against --target: an I-Am from another address is infra-error.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

ADAPTER = "bacnet-stack"
OUTCOMES = ("pass", "fail", "unsupported", "not-tested", "known-difference", "infra-error")

# BACNET_APPLICATION_TAG numbers (bacenum.h) for bacwp / bacwpm / bacupt.
TAGS = {
    "null": 0,
    "boolean": 1,
    "unsigned": 2,
    "signed": 3,
    "real": 4,
    "character-string": 7,
    "enumerated": 9,
    "object-identifier": 12,
}
# BACNET_OBJECT_TYPE and BACNET_PROPERTY_ID numbers (bacenum.h) for the tools
# that take numbers only (bacrr, bacale, bacrle, bacwpm).
OBJECT_TYPES = {
    "analog-input": 0, "analog-output": 1, "analog-value": 2, "binary-input": 3,
    "binary-output": 4, "binary-value": 5, "calendar": 6, "device": 8,
    "event-enrollment": 9, "file": 10, "multi-state-input": 13, "multi-state-output": 14,
    "notification-class": 15, "schedule": 17, "multi-state-value": 19, "trend-log": 20,
}
OBJECT_NAMES = {v: k for k, v in OBJECT_TYPES.items()}
PROPERTY_NUMBERS = {
    "description": 28, "event-time-stamps": 130, "log-buffer": 131, "object-name": 77,
    "out-of-service": 81, "present-value": 85, "recipient-list": 102,
}
DCC_STATES = {"enable": 0, "disable": 1, "disable-initiation": 2}
EVENT_STATES = {"normal": 0, "fault": 1, "offnormal": 2, "high-limit": 3, "low-limit": 4}
# bacnet-stack h_getevent.c ge_ack_print_data abbreviations.
GE_STATES = {"NO": "normal", "FA": "fault", "ON": "offnormal", "HL": "high-limit", "LL": "low-limit"}
# Event_Time_Stamps index per acknowledged state (to-offnormal, to-fault,
# to-normal).
TIME_STAMP_INDEX = {"offnormal": 1, "high-limit": 1, "low-limit": 1, "fault": 2, "normal": 3}

ERROR_RE = re.compile(r"^BACnet Error: ([a-z0-9-]+): ([a-z0-9-]+)(?: \[first-failed=([0-9]+)\])?$")
FAILED_RE = re.compile(r"^BACnet Error: ([a-z0-9-]+) ([0-9]+): ([a-z0-9-]+|[0-9]+)$")
REJECT_RE = re.compile(r"^BACnet Reject: (.+)$")
ABORT_RE = re.compile(r"^BACnet Abort: (.+)$")
IHAVE_RE = re.compile(r"^I-Have: ([a-z0-9-]+) ([0-9]+) from device ([0-9]+)!$")
WHOIS_RE = re.compile(r"^\s+([0-9]+)\s+([0-9A-F:]+)\s+")
OBJID_RE = re.compile(r"^\(([a-z0-9-]+), ([0-9]+)\)$")
RPM_OBJECT_RE = re.compile(r"^([a-z0-9-]+) #([0-9]+)$")
RPM_PROP_RE = re.compile(r"^\s+([a-z0-9-]+|[0-9]+): (.*)$")
RECORD_RE = re.compile(r"\{\{([0-9]{4}-[0-9]{2}-[0-9]{2})-([0-9]{1,2}):([0-9]{2}:[0-9]{2})\.[0-9]{2}\}, ([a-z-]+):([^}]*)\}")
GE_ROW_RE = re.compile(r"^([0-9]+)\s+([0-9]+)\s+([0-9]+)\s+([A-Z?]{2})$")
BDT_RE = re.compile(r"^BDT-[0-9]+: ([0-9.]+:[0-9]+) ([0-9.]+)$")
FDT_RE = re.compile(r"^FDT-[0-9]+: ([0-9.]+:[0-9]+) ([0-9]+)s ([0-9]+)s$")
BVLC_RESULT_RE = re.compile(r"^BVLC Result: (.+)$")
DEST_RE = re.compile(
    r"\(ValidDays=\[([0-9,]*)\];FromTime=([0-9:.]+);ToTime=([0-9:.]+);"
    r"Recipient=Device\(type=8,instance=([0-9]+)\);ProcessIdentifier=([0-9]+);"
    r"ConfirmedNotify=(true|false);Transitions=\[([a-z,-]*)\]\)")
BVLC_RESULTS = {
    "Successful Completion": "successful-completion",
    "Write-Broadcast-Distribution-Table NAK": "write-bdt-nak",
    "Read-Broadcast-Distribution-Table NAK": "read-bdt-nak",
    "Register-Foreign-Device NAK": "register-fd-nak",
    "Read-Foreign-Device-Table NAK": "read-fdt-nak",
    "Delete-Foreign-Device-Table-Entry NAK": "delete-fdt-nak",
    "Distribute-Broadcast-To-Network NAK": "distribute-broadcast-nak",
}


class Infra(Exception):
    """The scenario could not be run (no binding, tool failure)."""


class KnownDifference(Exception):
    """A recorded upstream deviation (PEER_SUPPORT.md) hides the result."""


class Env:
    """What every scenario needs: the target, the device and the tool settings."""

    def __init__(self, args: argparse.Namespace, timeout_s: float) -> None:
        self.target = args.target
        self.device = args.device
        self.broadcast = args.broadcast
        self.bbmd = args.bbmd
        self.fd_ttl = args.fd_ttl
        self.timeout_s = timeout_s
        self.workdir = tempfile.mkdtemp(prefix="client-")

    def tool_env(self, register: bool) -> dict[str, str]:
        env = dict(os.environ)
        if register and self.bbmd:
            host, port = split_hostport(self.bbmd)
            env["BACNET_BBMD_ADDRESS"] = host
            env["BACNET_BBMD_PORT"] = str(port)
            env["BACNET_BBMD_TIMETOLIVE"] = str(self.fd_ttl)
        return env

    def run(self, argv: list[str], register: bool = True) -> tuple[int, list[str]]:
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout_s,
                                  cwd=self.workdir, env=self.tool_env(register))
        except subprocess.TimeoutExpired as exc:
            raise Infra(f"{argv[0]} did not exit within {self.timeout_s:.0f} s") from exc
        except OSError as exc:
            raise Infra(f"{argv[0]}: {exc}") from exc
        if proc.returncode < 0 or proc.returncode >= 128:
            raise Infra(f"{argv[0]} crashed (status {proc.returncode})")
        lines = [ln.strip("\r") for ln in (proc.stdout + proc.stderr).splitlines()]
        lines = [ln.lstrip("\r") for ln in lines if ln.strip()]
        for ln in lines:
            if ln.startswith("Error: APDU Timeout"):
                raise Infra("device not bound: no I-Am for the device instance")
            if ln.startswith("Usage:") or ln.startswith("Error: unable to parse") or re.match(r"^[a-z-]+=.* invalid$", ln):
                raise Infra(f"{argv[0]} refused its arguments: {ln}")
        return proc.returncode, lines

    def bbmd_hostport(self) -> tuple[str, int]:
        return split_hostport(self.bbmd or self.target)


def split_hostport(s: str) -> tuple[str, int]:
    host, _, port = s.rpartition(":")
    return host, int(port)


def obj_args(ref: str) -> list[str]:
    otype, inst = ref.split(",")
    return [otype, inst]


def obj_numbers(ref: str) -> list[str]:
    otype, inst = ref.split(",")
    if otype not in OBJECT_TYPES:
        raise Infra(f"no object type number for {otype} in this driver")
    return [str(OBJECT_TYPES[otype]), inst]


def property_number(p: str | int) -> int:
    if isinstance(p, int):
        return p
    if p not in PROPERTY_NUMBERS:
        raise Infra(f"no property number for {p} in this driver")
    return PROPERTY_NUMBERS[p]


def prop_name(p: str) -> str | int:
    return int(p) if p.isdigit() else p


def answer(lines: list[str]) -> dict[str, Any] | None:
    """An Error, Reject, Abort or timeout printed by a confirmed-service tool."""
    for i, ln in enumerate(lines):
        m = ERROR_RE.match(ln)
        if m:
            err: dict[str, Any] = {"class": m.group(1), "code": m.group(2)}
            if m.group(3) is not None:
                err["first_failed_element"] = int(m.group(3))
            if i + 1 < len(lines):
                f = FAILED_RE.match(lines[i + 1])
                if f:
                    err["first_failed"] = {"object": f"{f.group(1)},{f.group(2)}", "property": prop_name(f.group(3))}
            return {"error": err}
        # bacawf prints the error over three lines.
        if ln == "BACnet Error!" and i + 2 < len(lines):
            c = re.match(r"^Error Class: ([a-z0-9-]+)$", lines[i + 1])
            d = re.match(r"^Error Code: ([a-z0-9-]+)$", lines[i + 2])
            if c and d:
                return {"error": {"class": c.group(1), "code": d.group(1)}}
        m = REJECT_RE.match(ln)
        if m:
            return {"reject": m.group(1)}
        m = ABORT_RE.match(ln)
        if m:
            return {"abort": m.group(1)}
        if ln.startswith("Error: TSM Timeout"):
            return {"timeout": True}
    return None


def acked(lines: list[str], text: str, tool: str, rc: int) -> dict[str, Any]:
    a = answer(lines)
    if a is not None:
        return a
    if any(text in ln for ln in lines):
        return {"ack": True}
    raise Infra(f"{tool} exited {rc} without an answer")


def parse_value(text: str, want: str) -> dict[str, Any]:
    """Interpret a value printed by bacapp_print_value as the expected type."""
    text = text.strip()
    if want == "character-string":
        if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
            return {"type": want, "value": text[1:-1]}
    elif want == "real":
        try:
            return {"type": want, "value": float(text)}
        except ValueError:
            pass
    elif want in ("unsigned", "signed"):
        if re.fullmatch(r"-?[0-9]+", text):
            return {"type": want, "value": int(text)}
    elif want == "boolean":
        if text.lower() in ("true", "false"):
            return {"type": want, "value": text.lower() == "true"}
    elif want == "object-identifier":
        m = OBJID_RE.match(text)
        if m:
            return {"type": want, "value": f"{m.group(1)},{m.group(2)}"}
    elif want == "enumerated":
        return {"type": want, "value": int(text) if text.isdigit() else text}
    elif want == "null":
        if text.lower() == "null":
            return {"type": want}
    return {"type": "text", "value": text}


def same_value(got: dict[str, Any], want: dict[str, Any]) -> bool:
    if got.get("type") != want.get("type"):
        return False
    gv, wv = got.get("value"), want.get("value")
    if want["type"] == "real" and isinstance(gv, float) and isinstance(wv, (int, float)):
        return math.isclose(gv, float(wv), rel_tol=1e-6, abs_tol=1e-6)
    return gv == wv


def expected_type(expect: dict[str, Any]) -> str:
    v = expect.get("value")
    return v["type"] if isinstance(v, dict) else "text"


def value_text(v: dict[str, Any]) -> str:
    if v["type"] == "null":
        return "0"
    if v["type"] == "object-identifier":
        return v["value"].replace(",", ":")
    if v["type"] == "boolean":
        return "1" if v["value"] else "0"
    return str(v["value"])


def target_mac(target: str) -> str:
    """The B/IP MAC bacwi prints for HOST:PORT (0A:59:00:0A:BA:C0)."""
    if not target:
        return ""
    host, port = split_hostport(target)
    octets = [int(x) for x in host.split(".")] + [port >> 8, port & 0xFF]
    return ":".join(f"{o:02X}" for o in octets)


def own_address(env: Env) -> str:
    """This container's address towards the BBMD, as it appears in the FDT."""
    host, port = env.bbmd_hostport()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((host, port))
        return f"{s.getsockname()[0]}:47808"


def destination_ascii(d: dict[str, Any]) -> str:
    """BACnetDestination in the form bacnet-stack bacdest.c parses."""
    if "device" not in d["recipient"]:
        raise Infra("only device recipients are supported by this driver")
    return ("(ValidDays=[" + ",".join(str(x) for x in d["valid_days"]) + "];"
            f"FromTime={d['from_time']};ToTime={d['to_time']};"
            f"Recipient=Device(type=8,instance={d['recipient']['device']});"
            f"ProcessIdentifier={d['process_id']};"
            f"ConfirmedNotify={'true' if d['confirmed'] else 'false'};"
            "Transitions=[" + ",".join(d["transitions"]) + "])")


def parse_destinations(text: str) -> list[dict[str, Any]]:
    out = []
    for m in DEST_RE.finditer(text):
        out.append({
            "valid_days": [int(x) for x in m.group(1).split(",") if x],
            "from_time": m.group(2), "to_time": m.group(3),
            "recipient": {"device": int(m.group(4))},
            "process_id": int(m.group(5)),
            "confirmed": m.group(6) == "true",
            "transitions": [x for x in m.group(7).split(",") if x],
        })
    return out


# --- services ---------------------------------------------------------------


def who_is(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    argv = ["bacwi"]
    if "low" in sc:
        argv += [str(sc["low"]), str(sc.get("high", sc["low"]))]
    if env.broadcast:
        argv += ["--mac", env.broadcast]
    _, lines = env.run(argv)
    devices = []
    want_mac = target_mac(env.target)
    for ln in lines:
        m = WHOIS_RE.match(ln)
        if m:
            if want_mac and m.group(2) != want_mac:
                raise Infra(f"I-Am for device {m.group(1)} from {m.group(2)}, not the target {want_mac}")
            devices.append(int(m.group(1)))
    return {"i-am": sorted(devices)}


def who_has(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    argv = ["bacwh"] + (obj_args(sc["object"]) if "object" in sc else [sc["name"]])
    _, lines = env.run(argv)
    found = []
    for ln in lines:
        m = IHAVE_RE.match(ln)
        if m:
            found.append({"device": int(m.group(3)), "object": f"{m.group(1)},{m.group(2)}"})
    return {"i-have": found}


def read_property(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    argv = ["bacrp", str(env.device), *obj_args(sc["object"]), str(sc["property"])]
    if "array_index" in sc:
        argv.append(str(sc["array_index"]))
    rc, lines = env.run(argv)
    a = answer(lines)
    if a is not None:
        return a
    if rc != 0 or not lines:
        raise Infra(f"bacrp exited {rc} without an answer")
    text = "\n".join(lines)
    if "recipients" in sc["expect"]:
        if text.strip() not in ("{}", "") and not DEST_RE.search(text):
            return {"value": {"type": "text", "value": text}}
        return {"recipients": parse_destinations(text)}
    return {"value": parse_value(text, expected_type(sc["expect"]))}


def read_property_multiple(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    argv = ["bacrpm", str(env.device)]
    for r in sc["reads"]:
        argv += [*obj_args(r["object"]), ",".join(str(p) for p in r["properties"])]
    rc, lines = env.run(argv)
    if not any(RPM_OBJECT_RE.match(ln) for ln in lines):
        a = answer(lines)
        if a is not None:
            return a
        raise Infra(f"bacrpm exited {rc} without an answer")
    wants = {(w["object"], str(w["property"])): w for w in sc["expect"].get("values", [])}
    values = []
    obj = None
    for ln in lines:
        m = RPM_OBJECT_RE.match(ln)
        if m:
            obj = f"{m.group(1)},{m.group(2)}"
            continue
        m = RPM_PROP_RE.match(ln)
        if m and obj is not None:
            prop, text = m.group(1), m.group(2)
            entry: dict[str, Any] = {"object": obj, "property": prop_name(prop)}
            e = ERROR_RE.match(text)
            if e:
                entry["error"] = {"class": e.group(1), "code": e.group(2)}
            else:
                w = wants.get((obj, prop), {})
                entry["value"] = parse_value(text, w["value"]["type"] if "value" in w else "text")
            values.append(entry)
    return {"values": values}


def write_args(w: dict[str, Any], with_index: bool) -> list[str]:
    v = w["value"]
    args = [str(w["property"]), str(w.get("priority", 0))]
    if with_index:
        args.append("-1")
    return args + [str(TAGS[v["type"]]), value_text(v)]


def write_property(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    w = {"property": sc["property"], "priority": sc.get("priority", 0), "value": sc["value"]}
    argv = ["bacwp", str(env.device), *obj_args(sc["object"]), *write_args(w, True)]
    rc, lines = env.run(argv)
    return acked(lines, "WriteProperty Acknowledged", "bacwp", rc)


def write_property_multiple(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    argv = ["bacwpm", str(env.device)]
    for w in sc["writes"]:
        # bacwpm parses the property as a number (sscanf "%u[%u]").
        argv += [*obj_args(w["object"]), *write_args({**w, "property": property_number(w["property"])}, False)]
    rc, lines = env.run(argv)
    return acked(lines, "WriteProperty Acknowledged", "bacwpm", rc)


def subscribe_cov(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    argv = ["bacscov", str(env.device), *obj_args(sc["object"]), str(sc["process_id"])]
    if sc.get("cancel"):
        argv.append("cancel")
    else:
        argv += ["confirmed" if sc.get("confirmed") else "unconfirmed", str(sc.get("lifetime", 60))]
    rc, lines = env.run(argv)
    a = answer(lines)
    if a is not None:
        return a
    if not any("SubscribeCOV Acknowledged" in ln for ln in lines):
        raise Infra(f"bacscov exited {rc} without an answer")
    return {"subscribed": {"notification": any("Received Notification" in ln for ln in lines)}}


def read_range(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    r = sc["range"]
    by = {"position": 1, "sequence": 2, "all": 4}[r["by"]]
    argv = ["bacrr", str(env.device), *obj_numbers(sc["object"]), str(property_number(sc["property"])),
            str(by), str(r.get("index", 0)), str(r.get("count", 0))]
    rc, lines = env.run(argv)
    a = answer(lines)
    if a is not None:
        return a
    text = "\n".join(lines)
    if "log-buffer:" not in text:
        raise Infra(f"bacrr exited {rc} without an answer")
    records = []
    for m in RECORD_RE.finditer(text):
        records.append({"timestamp": f"{m.group(1)}T{int(m.group(2)):02d}:{m.group(3)}",
                        "value": parse_value(m.group(5), m.group(4))})
    return {"records": records}


def device_communication_control(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    argv = ["bacdcc", str(env.device), str(DCC_STATES[sc["state"]])]
    if "duration" in sc or "password" in sc:
        argv.append(str(sc.get("duration", 0)))
    if "password" in sc:
        argv.append(sc["password"])
    rc, lines = env.run(argv)
    return acked(lines, "DeviceCommunicationControl Acknowledged", "bacdcc", rc)


def reinitialize_device(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    argv = ["bacrd", str(env.device), str(sc["state"])]
    if "password" in sc:
        argv.append(sc["password"])
    rc, lines = env.run(argv)
    return acked(lines, "ReinitializeDevice Acknowledged", "bacrd", rc)


def atomic_read_file(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    _, inst = sc["object"].split(",")
    local = f"read-{sc['id']}"
    path = Path(env.workdir) / local
    path.unlink(missing_ok=True)
    rc, lines = env.run(["bacarf", str(env.device), inst, local])
    a = answer(lines)
    if a is not None:
        return a
    if rc != 0 or not path.exists():
        raise Infra(f"bacarf exited {rc} without a file")
    return {"octets_base64": base64.b64encode(path.read_bytes()).decode()}


def atomic_write_file(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    _, inst = sc["object"].split(",")
    local = f"write-{sc['id']}"
    (Path(env.workdir) / local).write_bytes(base64.b64decode(sc["data_base64"]))
    rc, lines = env.run(["bacawf", str(env.device), inst, local])
    a = answer(lines)
    if a is not None:
        return a
    if rc != 0:
        raise Infra(f"bacawf exited {rc} without an answer")
    # bacawf prints nothing for the AtomicWriteFile-ACK; status 0 after
    # "Sending N bytes" is the acknowledgement (apps/writefile/main.c).
    return {"ack": True}


def list_element(sc: dict[str, Any], env: Env, tool: str) -> dict[str, Any]:
    if len(sc["elements"]) != 1:
        raise Infra(f"{tool} sends one element per request")
    argv = [tool, str(env.device), *obj_numbers(sc["object"]), str(property_number(sc["property"])),
            "-1", "-1", destination_ascii(sc["elements"][0])]
    rc, lines = env.run(argv)
    a = answer(lines)
    if a is not None:
        return a
    if tool == "bacrle":
        # apps/remove-list-element/main.c at the pin registers its SimpleACK
        # and error handlers for AddListElement, so it never prints the
        # RemoveListElement result (PEER_SUPPORT.md).
        raise KnownDifference("bacrle prints no RemoveListElement result (its handlers are registered for AddListElement)")
    if any("AddListElement Acknowledged" in ln for ln in lines):
        return {"ack": True}
    raise Infra(f"{tool} exited {rc} without an answer")


def create_object(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    argv = ["bacco", str(env.device), sc["object_type"]]
    if "instance" in sc:
        argv.append(str(sc["instance"]))
    rc, lines = env.run(argv)
    return object_result(lines, "CreateObject", "bacco", rc)


def delete_object(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    # bacdo takes the object type as a number only.
    rc, lines = env.run(["bacdo", str(env.device), *obj_numbers(sc["object"])])
    return object_result(lines, "DeleteObject", "bacdo", rc)


def object_result(lines: list[str], key: str, tool: str, rc: int) -> dict[str, Any]:
    """bacco and bacdo print a JSON block; error-code success is the ACK."""
    a = answer(lines)
    if a is not None:
        return a
    text = "\n".join(lines)
    start = text.find("[")
    if start < 0:
        raise Infra(f"{tool} exited {rc} without an answer")
    try:
        res = json.loads(text[start:])[0][key]
    except (ValueError, KeyError, IndexError) as exc:
        raise Infra(f"{tool} printed no {key} result") from exc
    if res["error-code"] != "success":
        return {"error": {"class": res["error-class"], "code": res["error-code"]}}
    if key == "CreateObject":
        return {"created": f"{res['object-type']},{res['object-instance']}"}
    return {"ack": True}


def get_event_information(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    rc, lines = env.run(["bacge", str(env.device)])
    a = answer(lines)
    if a is not None:
        return a
    for ln in lines:
        m = re.match(r"^Decode of Ack returned length (-?[0-9]+)", ln)
        if m and int(m.group(1)) <= 0:
            return {"decode_failed": True}
    events = []
    for ln in lines:
        m = GE_ROW_RE.match(ln)
        if m:
            otype = OBJECT_NAMES.get(int(m.group(2)), m.group(2))
            events.append({"object": f"{otype},{m.group(3)}", "event_state": GE_STATES.get(m.group(4), m.group(4))})
    if not any("Total" in ln for ln in lines):
        raise Infra(f"bacge exited {rc} without an answer")
    return {"events": events}


def acknowledge_alarm(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    state = sc["event_state_acked"]
    if sc["time_stamp"] == "event":
        rc, lines = env.run(["bacrp", str(env.device), *obj_args(sc["object"]), "130", str(TIME_STAMP_INDEX[state])])
        if answer(lines) is not None or rc != 0 or not lines:
            raise Infra(f"Event_Time_Stamps of {sc['object']} not readable: {lines}")
        stamp = lines[-1].strip()
    else:
        date, clock = sc["time_stamp"].split("T")
        stamp = date.replace("-", "/") + "-" + clock + ".00"
    argv = ["bacackalarm", str(env.device), str(sc["process_id"]), *obj_args(sc["object"]),
            str(EVENT_STATES[state]), stamp, "interop", stamp]
    rc, lines = env.run(argv)
    return acked(lines, "AcknowledgeAlarm Acknowledged", "bacackalarm", rc)


def sent(rc: int, lines: list[str], tool: str, operation: str, marker: str | None = None) -> dict[str, Any]:
    if rc != 0 or (marker is not None and not any(marker in ln for ln in lines)):
        raise Infra(f"{tool} exited {rc}: {lines}")
    return {"sent": {"operation": operation}}


def time_synchronization(sc: dict[str, Any], env: Env, utc: bool) -> dict[str, Any]:
    argv = ["bacts"] + (["--utc"] if utc else [])
    rc, lines = env.run(argv)
    return sent(rc, lines, "bacts", "utc-time-synchronization" if utc else "time-synchronization")


def unconfirmed_private_transfer(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    argv = ["bacupt", str(env.device), str(sc["vendor_id"]), str(sc["service_number"])]
    for v in sc.get("parameters", []):
        argv += [str(TAGS[v["type"]]), value_text(v)]
    rc, lines = env.run(argv)
    return sent(rc, lines, "bacupt", "unconfirmed-private-transfer", "Sent PrivateTransfer")


def write_group(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    argv = ["bacwg", str(sc["group"]), str(sc["priority"]), "inhibit" if sc.get("inhibit") else "delay"]
    for c in sc["changes"]:
        v = c["value"]
        if v["type"] == "real":
            text = repr(float(v["value"]))
        elif v["type"] == "null":
            text = "null"
        elif v["type"] == "boolean":
            text = "true" if v["value"] else "false"
        else:
            text = str(v["value"])
        argv += [str(c["channel"]), str(c.get("overriding_priority", 0)), text]
    rc, lines = env.run(argv)
    return sent(rc, lines, "bacwg", "write-group", "WriteGroup-Request successful")


def bvlc_result(lines: list[str]) -> str | None:
    for ln in lines:
        m = BVLC_RESULT_RE.match(ln)
        if m:
            return BVLC_RESULTS.get(m.group(1), m.group(1))
    return None


# The BVLC tools address the BBMD directly and do not register: a process
# that registers prints its own Register-Foreign-Device result instead.
def read_bdt(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    host, port = env.bbmd_hostport()
    rc, lines = env.run(["bacrbdt", host, str(port)], register=False)
    r = bvlc_result(lines)
    if r is not None:
        return {"bvlc_result": r}
    if not any(ln.startswith("BBMD:") for ln in lines):
        raise Infra(f"bacrbdt exited {rc} without an answer")
    # The BBMD's own entry is named "bbmd": a scenario file cannot know its address.
    me = f"{host}:{port}"
    return {"bdt": [{"address": "bbmd" if m.group(1) == me else m.group(1), "mask": m.group(2)}
                    for m in map(BDT_RE.match, lines) if m]}


def read_fdt(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    host, port = env.bbmd_hostport()
    rc, lines = env.run(["bacrfdt", host, str(port)], register=False)
    r = bvlc_result(lines)
    if r is not None:
        return {"bvlc_result": r}
    if not any(ln.startswith("BBMD:") for ln in lines):
        raise Infra(f"bacrfdt exited {rc} without an answer")
    me = own_address(env)
    mine = [m for m in map(FDT_RE.match, lines) if m and m.group(1) == me]
    return {"fdt": {"contains_self": bool(mine), "ttl": int(mine[0].group(2)) if mine else 0}}


def write_bdt(sc: dict[str, Any], env: Env) -> dict[str, Any]:
    host, port = env.bbmd_hostport()
    entries = [f"{host}:{port}" if e == "bbmd" else e for e in sc["bdt"]]
    rc, lines = env.run(["bacwbdt", host, str(port), *entries], register=False)
    r = bvlc_result(lines)
    if r is None:
        raise Infra(f"bacwbdt exited {rc} without a BVLC-Result")
    return {"bvlc_result": r}


SERVICES: dict[str, Callable[[dict[str, Any], Env], dict[str, Any]]] = {
    "who-is": who_is,
    "who-has": who_has,
    "read-property": read_property,
    "read-property-multiple": read_property_multiple,
    "write-property": write_property,
    "write-property-multiple": write_property_multiple,
    "subscribe-cov": subscribe_cov,
    "read-range": read_range,
    "device-communication-control": device_communication_control,
    "reinitialize-device": reinitialize_device,
    "atomic-read-file": atomic_read_file,
    "atomic-write-file": atomic_write_file,
    "add-list-element": lambda sc, env: list_element(sc, env, "bacale"),
    "remove-list-element": lambda sc, env: list_element(sc, env, "bacrle"),
    "create-object": create_object,
    "delete-object": delete_object,
    "get-event-information": get_event_information,
    "acknowledge-alarm": acknowledge_alarm,
    "time-synchronization": lambda sc, env: time_synchronization(sc, env, False),
    "utc-time-synchronization": lambda sc, env: time_synchronization(sc, env, True),
    "unconfirmed-private-transfer": unconfirmed_private_transfer,
    "write-group": write_group,
    "read-bdt": read_bdt,
    "read-fdt": read_fdt,
    "write-bdt": write_bdt,
}


def compare(expect: dict[str, Any], observed: dict[str, Any]) -> bool:
    key = next(iter(expect))
    if key not in observed:
        return False
    want, got = expect[key], observed[key]
    if key == "value":
        return same_value(got, want)
    if key == "values":
        if len(got) != len(want):
            return False
        for g, w in zip(got, want):
            if g["object"] != w["object"] or str(g["property"]) != str(w["property"]):
                return False
            if "error" in w:
                if g.get("error") != w["error"]:
                    return False
            elif "value" not in g or not same_value(g["value"], w["value"]):
                return False
        return True
    if key == "error":
        if {k: got.get(k) for k in ("class", "code")} != {k: want[k] for k in ("class", "code")}:
            return False
        if "first_failed" in want:
            ff = got.get("first_failed") or {}
            if ff.get("object") != want["first_failed"]["object"] or str(ff.get("property")) != str(want["first_failed"]["property"]):
                return False
        if "first_failed_element" in want and got.get("first_failed_element") != want["first_failed_element"]:
            return False
        return True
    if key == "records":
        return len(got) == len(want) and all(
            g["timestamp"] == w["timestamp"] and same_value(g["value"], w["value"]) for g, w in zip(got, want))
    if key == "subscribed":
        return not want["notification"] or got["notification"]
    if key == "i-have":
        return sorted(got, key=json.dumps) == sorted(want, key=json.dumps)
    if key == "i-am":
        return sorted(got) == sorted(want)
    return got == want


def emit(line: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(line, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="client", description=__doc__.split("\n\n")[0])
    ap.add_argument("--target", default="", help="DUT HOST:PORT")
    ap.add_argument("--device", type=int, required=True, help="DUT device instance")
    ap.add_argument("--scenarios", required=True, help="scenario file")
    ap.add_argument("--only", default="", help="comma-separated scenario ids")
    ap.add_argument("--broadcast", default="", help="HOST:PORT discovery requests are sent to")
    ap.add_argument("--bbmd", default="", help="BBMD HOST:PORT to register with as a foreign device")
    ap.add_argument("--fd-ttl", type=int, default=60, help="foreign-device TTL in seconds (default 60)")
    args = ap.parse_args(argv)
    if not 1 <= args.fd_ttl <= 65535:
        print("client: --fd-ttl must be 1..65535", file=sys.stderr)
        return 2
    for name in ("target", "broadcast", "bbmd"):
        v = getattr(args, name)
        if v and not re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){3}:[0-9]+", v):
            print(f"client: --{name} must be IPv4:PORT", file=sys.stderr)
            return 2

    try:
        doc = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))
        scenarios = doc["scenarios"]
    except (OSError, ValueError, KeyError) as exc:
        print(f"client: cannot read scenarios: {exc}", file=sys.stderr)
        return 2
    if doc.get("requires_bbmd") and not args.bbmd:
        print(f"client: {doc.get('id')} requires --bbmd", file=sys.stderr)
        return 2
    only = {s for s in args.only.split(",") if s}

    timeout_ms = int(os.environ.get("BACNET_CLIENT_TIMEOUT_MS", "3000"))
    retries = int(os.environ.get("BACNET_CLIENT_RETRIES", "1"))
    # bacnet-stack dlenv reads these.
    os.environ["BACNET_APDU_TIMEOUT"] = str(timeout_ms)
    os.environ["BACNET_APDU_RETRIES"] = str(retries)
    env = Env(args, timeout_ms / 1000 * (retries + 2) + 10)

    emit({
        "event": "ready",
        "mode": "client",
        "adapter": ADAPTER,
        "version": os.environ.get("ADAPTER_VERSION", "dev"),
        "peer_version": os.environ.get("BACNET_STACK_VERSION", "unknown"),
        "scenarios": str(doc.get("id", "")),
    })
    summary = dict.fromkeys(OUTCOMES, 0)
    for sc in scenarios:
        if only and sc["id"] not in only:
            continue
        start = time.monotonic()
        line: dict[str, Any] = {"event": "result", "scenario": sc["id"], "service": sc["service"]}
        fn = SERVICES.get(sc["service"])
        try:
            if fn is None:
                line["outcome"] = "unsupported"
            else:
                observed = fn(sc, env)
                line["outcome"] = "pass" if compare(sc["expect"], observed) else "fail"
                line["observed"] = observed
        except KnownDifference as exc:
            line["outcome"] = "known-difference"
            line["detail"] = str(exc)
        except Infra as exc:
            line["outcome"] = "infra-error"
            line["detail"] = str(exc)
        line["durationMs"] = int((time.monotonic() - start) * 1000)
        summary[line["outcome"]] += 1
        emit(line)
    emit({"event": "done", "summary": summary})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
