#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""BACpypes3 device server for bacnet-interop.

Loads device-baseline-v1 JSON, binds BACnet/IP, emits a single JSON Lines ready
event on stdout once the application is live, then serves until SIGTERM/SIGINT.
Diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import sys
from pathlib import Path
from typing import Any, Optional

from bacpypes3.app import Application
from bacpypes3.argparse import SimpleArgumentParser
from bacpypes3.basetypes import Segmentation
from bacpypes3.local.analog import AnalogValueObjectCmd
from bacpypes3.local.binary import BinaryValueObjectCmd


FIXTURE_DEFAULT = "device-baseline-v1"
FIXTURE_PATH_DEFAULT = "/fixtures/device/device-baseline-v1.json"
PORT_DEFAULT = 47808


def load_device_fixture(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("device fixture must be a JSON object")
    if "device_instance" not in data or "device_name" not in data:
        raise ValueError("device fixture requires device_instance and device_name")
    return data


def primary_ipv4() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        host = s.getsockname()[0]
        s.close()
        return host
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def resolve_numeric_address(address: str, *, with_prefix: bool = False) -> str:
    """Resolve host:<port> to a numeric IP[:/prefix]:port for BBMD.

    BACpypes3 HostNPort.address raises NotImplementedError for name-based hosts.
    BBMD local distribution also needs a broadcast-capable address (CIDR form).
    """
    host, sep, port = address.rpartition(":")
    if not sep:
        host, port = address, str(PORT_DEFAULT)
    # Strip an existing prefix length from the host part.
    prefix = ""
    if "/" in host:
        host, prefix = host.split("/", 1)
        prefix = "/" + prefix
    if host in ("", "host", "0.0.0.0", "::"):
        host = primary_ipv4()
    elif any(c.isalpha() for c in host):
        host = socket.gethostbyname(host)
    if with_prefix and not prefix:
        # Docker user-defined bridges are typically /16; /24 is a safe fallback
        # for local BBMD broadcast calculation.
        prefix = "/16"
    return f"{host}{prefix}:{port}"


def emit_ready(
    adapter: str,
    version: str,
    fixture: str,
    port: int,
    peer_version: str,
) -> None:
    line = {
        "event": "ready",
        "adapter": adapter,
        "version": version,
        "fixture": fixture,
        "address": f"0.0.0.0:{port}",
        "peer_version": peer_version,
    }
    sys.stdout.write(json.dumps(line, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def build_app(
    fixture: dict[str, Any],
    address: str,
    max_apdu: Optional[int] = None,
    bbmd: bool = False,
    network: Optional[int] = None,
) -> Application:
    name = str(fixture["device_name"])
    instance = int(fixture["device_instance"])
    parser = SimpleArgumentParser()
    argv = [
        "--name",
        name,
        "--instance",
        str(instance),
        "--address",
        address,
        "--vendoridentifier",
        "999",
    ]
    if network is not None and network > 0:
        argv += ["--network", str(network)]
    if bbmd:
        # Enable BBMD and accept FD registrations. Include this device in the
        # BDT so Distribute-Broadcast-To-Network has a local distribution entry.
        # Bind + BDT must be numeric CIDR so BACpypes3 can compute a broadcast.
        address = resolve_numeric_address(address, with_prefix=True)
        argv[argv.index("--address") + 1] = address
        argv += ["--bbmd", address]
        print(f"bacpypes3 BBMD address/BDT={address}", file=sys.stderr, flush=True)
    args = parser.parse_args(argv)
    logging.getLogger().handlers.clear()
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

    app = Application.from_args(args)

    # Optional small MaxAPDU for segmented-response interop (default keeps BACpypes3's 1024).
    if max_apdu is not None and max_apdu > 0:
        device = getattr(app, "device_object", None) or getattr(app, "deviceObject", None)
        if device is None:
            # Application exposes the device object via objectIdentifier lookup.
            try:
                device = app.get_object_id(("device", instance))
            except Exception:  # noqa: BLE001
                device = None
        if device is None:
            raise RuntimeError("unable to locate device object to set maxApduLengthAccepted")
        device.maxApduLengthAccepted = int(max_apdu)
        # Keep segmentation enabled so oversized ComplexACKs can be segmented.
        if getattr(device, "segmentationSupported", None) is not None:
            device.segmentationSupported = Segmentation.segmentedBoth
        print(f"bacpypes3 maxApduLengthAccepted={max_apdu}", file=sys.stderr, flush=True)

    for obj in fixture.get("objects") or []:
        if not isinstance(obj, dict):
            continue
        otype = obj.get("type")
        oinst = int(obj.get("instance", 0))
        oname = str(obj.get("object_name", otype))
        if otype == "device":
            continue
        if otype == "analog-value":
            # Commandable AV supports WriteProperty present-value (+ priority).
            app.add_object(
                AnalogValueObjectCmd(
                    objectIdentifier=("analog-value", oinst),
                    objectName=oname,
                    presentValue=float(obj.get("present_value", 0.0)),
                    covIncrement=0.1,
                    description=str(obj.get("description", f"{fixture.get('fixture', 'device')} analog value")),
                )
            )
        elif otype == "binary-value":
            app.add_object(
                BinaryValueObjectCmd(
                    objectIdentifier=("binary-value", oinst),
                    objectName=oname,
                    presentValue=str(obj.get("present_value", "inactive")),
                    description=str(obj.get("description", f"{fixture.get('fixture', 'device')} binary value")),
                )
            )
        else:
            print(f"skipping unsupported object type {otype!r}", file=sys.stderr)
    return app


async def _serve(
    fixture: dict[str, Any],
    address: str,
    ready_args: dict[str, Any],
    max_apdu: Optional[int],
    bbmd: bool,
    network: Optional[int],
) -> None:
    app = build_app(fixture, address, max_apdu=max_apdu, bbmd=bbmd, network=network)
    # Application is bound; announce readiness only after that completes.
    emit_ready(**ready_args)
    mode = "bbmd" if bbmd else "normal"
    print(f"bacpypes3 listening address={address} mode={mode}", file=sys.stderr, flush=True)

    stop = asyncio.get_running_loop().create_future()

    def _stop() -> None:
        if not stop.done():
            stop.set_result(None)

    loop = asyncio.get_running_loop()
    for sig in ("SIGINT", "SIGTERM"):
        try:
            import signal

            loop.add_signal_handler(getattr(signal, sig), _stop)
        except (NotImplementedError, RuntimeError, AttributeError):
            pass

    await stop
    if hasattr(app, "close"):
        close = getattr(app, "close")
        result = close()
        if asyncio.iscoroutine(result):
            await result


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="bacnet-interop BACpypes3 device server")
    p.add_argument("--port", type=int, default=int(os.environ.get("BACNET_IP_PORT", PORT_DEFAULT)))
    p.add_argument(
        "--fixture-file",
        default=os.environ.get("DEVICE_FIXTURE_FILE", FIXTURE_PATH_DEFAULT),
    )
    p.add_argument(
        "--fixture",
        default=os.environ.get("FIXTURE", FIXTURE_DEFAULT),
    )
    p.add_argument(
        "--address",
        default=os.environ.get("BACNET_DEVICE_ADDRESS", ""),
        help="BACpypes3 address (default: host:<port>)",
    )
    p.add_argument(
        "--max-apdu",
        type=int,
        default=int(os.environ.get("BACNET_MAX_APDU", "0")),
        help="Override device maxApduLengthAccepted (0 = BACpypes3 default). Use small values for segmented-response tests.",
    )
    p.add_argument(
        "--bbmd",
        action="store_true",
        default=os.environ.get("BACNET_BBMD", "").lower() in ("1", "true", "yes"),
        help="Run as BBMD accepting foreign-device registrations (BDT includes this device).",
    )
    p.add_argument(
        "--network",
        type=int,
        default=int(os.environ.get("BACNET_NETWORK", "0")),
        help="Optional BACnet network number for the local port (0 = unset).",
    )
    args = p.parse_args(argv)

    version = os.environ.get("ADAPTER_VERSION", "dev")
    peer_version = os.environ.get("BACPYPES3_VERSION", "unknown")
    address = args.address.strip() or f"host:{args.port}"

    try:
        fixture = load_device_fixture(args.fixture_file)
    except Exception as exc:  # noqa: BLE001
        print(f"bacpypes3 adapter failed to load fixture: {exc}", file=sys.stderr)
        return 1

    fixture_id = str(fixture.get("fixture", args.fixture))
    ready_args = {
        "adapter": "bacpypes3",
        "version": version,
        "fixture": fixture_id,
        "port": args.port,
        "peer_version": peer_version,
    }

    max_apdu = args.max_apdu if args.max_apdu > 0 else None
    network = args.network if args.network > 0 else None
    try:
        asyncio.run(_serve(fixture, address, ready_args, max_apdu, args.bbmd, network))
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # noqa: BLE001
        print(f"bacpypes3 adapter failed to start: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
