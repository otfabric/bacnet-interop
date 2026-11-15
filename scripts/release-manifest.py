#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Write the manifest.json of a release (the Release workflow, job merge).

    scripts/release-manifest.py [<manifest.json>]

Reads, from the environment: TAG, ADAPTERS_JSON (the adapters the prepare job
detected: name, file, image, kind, pin_grep, pin_fixed) and the digest of
each merged multi-arch image (STACK_DIGEST, BACP_DIGEST, ...; DIGEST_ENV
below). Every adapter of adapters/inventory.yaml must be among the detected
adapters and have a digest: otherwise nothing is written and the exit status
is 1, so the release stops before it is created.
"""

import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Adapter name -> the environment variable with its digest.
DIGEST_ENV = {
    "bacnet-stack": "STACK_DIGEST",
    "bacpypes3": "BACP_DIGEST",
    "bacpypes": "BACPYPES_LEGACY_DIGEST",
    "bacnet4j": "B4J_DIGEST",
    "worldiety": "WORLD_DIGEST",
    "sysiobacnet": "SYSIO_DIGEST",
    "cbsigma": "CBSIGMA_DIGEST",
    "ulbios": "ULBIOS_DIGEST",
    "bacnet-js": "BACNETJS_DIGEST",
    "bip-router": "BIP_DIGEST",
    "bacnet-stack-router": "STACK_ROUTER_DIGEST",
}
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def inventory_ids(root=ROOT):
    """The ids of adapters/inventory.yaml, in its order."""
    text = (root / "adapters" / "inventory.yaml").read_text(encoding="utf-8")
    return re.findall(r"^  - id: ([a-z0-9-]+)\s*$", text, re.M)


def pin_for(adapter, root=ROOT):
    fixed = adapter.get("pin_fixed") or ""
    if fixed:
        return fixed
    grep_pat = adapter.get("pin_grep") or ""
    path = adapter.get("file") or ""
    if not grep_pat or not path:
        return None
    p = root / path
    if not p.is_file():
        return None
    cre = re.compile(grep_pat)
    for line in p.read_text(encoding="utf-8").splitlines():
        if cre.search(line) and "=" in line:
            return line.split("=", 1)[1].strip() or None
    return None


def manifest(tag, adapters, env, root=ROOT):
    """(manifest, errors). A manifest is only valid when errors is empty."""
    errors = []
    peers, topology = {}, {}
    for adapter in adapters:
        name = adapter["name"]
        digest = env.get(DIGEST_ENV.get(name, ""), "")
        if not DIGEST.fullmatch(digest):
            errors.append(f"{name}: no image digest ({DIGEST_ENV.get(name, 'no digest variable')}={digest!r})")
        entry = {"pin": pin_for(adapter, root), "image": adapter["image"], "digest": digest}
        if adapter.get("kind") == "topology":
            topology[name] = entry
        else:
            # Every peer is an implementation independent of the libraries under test.
            entry["independent"] = True
            peers[name] = entry
    for name in inventory_ids(root):
        if name not in peers and name not in topology:
            errors.append(f"{name}: in adapters/inventory.yaml, but no image was built for it")
    doc = {
        "version": tag,
        "fixture_schema": "fixtures/schema/fixture.schema.json",
        "peers": peers,
        "topology": topology,
    }
    return doc, errors


def main(argv):
    out = argv[0] if argv else "manifest.json"
    adapters = json.loads(os.environ.get("ADAPTERS_JSON") or "[]")
    doc, errors = manifest(os.environ["TAG"], adapters, os.environ)
    for error in errors:
        print(f"::error::manifest.json: {error}", file=sys.stderr)
    if errors:
        return 1
    with open(out, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    with open(out, encoding="utf-8") as f:
        print(f.read())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
