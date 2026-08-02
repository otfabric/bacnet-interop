#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Load device fixture, start device_server, emit ready after UDP bind."""

from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


FIXTURE_DEFAULT = "device-baseline-v2"
FIXTURE_PATH_DEFAULT = "/fixtures/device/device-baseline-v2.json"
PORT_DEFAULT = 47808


def load_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("device fixture must be a JSON object")
    if "device_instance" not in data or "device_name" not in data:
        raise ValueError("device fixture requires device_instance and device_name")
    return data


def materialize_files(fixture: dict[str, Any], work: Path) -> list[list[str]]:
    """Write fixture File payloads under work/; return CLI args with relative paths.

    bacnet-stack bacfile-posix rejects absolute paths when
    BACNET_FILE_PATH_RESTRICTED=1 (default). device_server must run with cwd=work.
    """
    args: list[list[str]] = []
    work.mkdir(parents=True, exist_ok=True)
    for obj in fixture.get("objects") or []:
        if not isinstance(obj, dict) or obj.get("type") != "file":
            continue
        inst = int(obj.get("instance", 0))
        name = str(obj.get("object_name", f"FILE-{inst}"))
        access = str(obj.get("access_method", "stream")).strip().lower()
        rel = f"file-{inst}.bin"
        path = work / rel
        if access == "record":
            records = obj.get("records") or []
            # CRLF-delimited records for bacfile-posix fgets record access.
            text = "".join(f"{r}\r\n" for r in records)
            path.write_bytes(text.encode("utf-8"))
        else:
            b64 = obj.get("stream_data_base64")
            if not b64:
                raise ValueError(f"file:{inst} missing stream_data_base64")
            path.write_bytes(base64.b64decode(b64))
        args.append(
            [
                "--file-instance",
                str(inst),
                "--file-name",
                name,
                "--file-path",
                rel,
                "--file-access",
                "record" if access == "record" else "stream",
            ]
        )
        print(
            f"bacnet-stack materialized file:{inst} {name} -> {rel} (cwd={work}) access={access}",
            file=sys.stderr,
        )
    return args


def server_args(fixture: dict[str, Any], work: Path) -> list[str]:
    args = [
        "--instance",
        str(int(fixture["device_instance"])),
        "--name",
        str(fixture["device_name"]),
    ]
    saw_av = False
    saw_bv = False
    for obj in fixture.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        otype = obj.get("type")
        if otype == "analog-value":
            saw_av = True
            args += [
                "--av-instance",
                str(int(obj.get("instance", 1))),
                "--av-name",
                str(obj.get("object_name", "AV-1")),
                "--av-value",
                str(float(obj.get("present_value", 0.0))),
            ]
            if obj.get("description"):
                args += ["--av-description", str(obj["description"])]
        elif otype == "binary-value":
            saw_bv = True
            pv = obj.get("present_value", "inactive")
            if isinstance(pv, bool):
                pv = "active" if pv else "inactive"
            args += [
                "--bv-instance",
                str(int(obj.get("instance", 1))),
                "--bv-name",
                str(obj.get("object_name", "BV-1")),
                "--bv-value",
                str(pv),
            ]
    for group in materialize_files(fixture, work):
        args += group
    if not saw_av:
        args.append("--no-av")
    if not saw_bv:
        args.append("--no-bv")
    return args


def udp_bound(port: int) -> bool:
    port_hex = f"{port:04X}".lower()
    try:
        text = Path("/proc/net/udp").read_text(encoding="utf-8", errors="replace").lower()
    except OSError:
        return False
    return f":{port_hex}" in text


def emit_ready(version: str, fixture: str, port: int, peer_version: str) -> None:
    line = {
        "event": "ready",
        "adapter": "bacnet-stack",
        "version": version,
        "fixture": fixture,
        "address": f"0.0.0.0:{port}",
        "peer_version": peer_version,
    }
    sys.stdout.write(json.dumps(line, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    port = int(os.environ.get("BACNET_IP_PORT", PORT_DEFAULT))
    os.environ["BACNET_IP_PORT"] = str(port)
    fixture_path = Path(os.environ.get("DEVICE_FIXTURE_FILE", FIXTURE_PATH_DEFAULT))
    fixture_fallback = os.environ.get("FIXTURE", FIXTURE_DEFAULT)
    adapter_version = os.environ.get("ADAPTER_VERSION", "dev")
    peer_version = os.environ.get("BACNET_STACK_VERSION", "unknown")

    try:
        fixture = load_fixture(fixture_path)
    except Exception as exc:  # noqa: BLE001
        print(f"bacnet-stack adapter failed to load fixture: {exc}", file=sys.stderr)
        return 1

    fixture_id = str(fixture.get("fixture", fixture_fallback))
    work = Path(tempfile.mkdtemp(prefix="bacnet-interop-files-"))
    try:
        args = server_args(fixture, work)
    except Exception as exc:  # noqa: BLE001
        print(f"bacnet-stack fixture materialize failed: {exc}", file=sys.stderr)
        return 1

    proc = subprocess.Popen(
        ["device_server", *args],
        cwd=str(work),
        stdout=sys.stderr,
        stderr=sys.stderr,
    )

    def _stop(*_args: object) -> None:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    ready = False
    for _ in range(100):
        if proc.poll() is not None:
            print(f"device_server exited before binding UDP {port}", file=sys.stderr)
            return proc.returncode or 1
        if udp_bound(port):
            ready = True
            break
        time.sleep(0.05)

    if not ready:
        print(f"timed out waiting for device_server UDP bind on {port}", file=sys.stderr)
        _stop()
        proc.wait(timeout=5)
        return 1

    emit_ready(adapter_version, fixture_id, port, peer_version)
    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
