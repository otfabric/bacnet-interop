#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests of scripts/release-manifest.py (the manifest.json of a release)."""

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("release_manifest", os.path.join(HERE, "release-manifest.py"))
rm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rm)

TOPOLOGY = {"bip-router", "bacnet-stack-router"}


def adapters(skip=()):
    """The adapters the prepare job detects when every Dockerfile exists."""
    return [{"name": n, "file": f"adapters/{n}/Dockerfile", "image": f"ghcr.io/otfabric/bacnet-interop-{n}",
             "kind": "topology" if n in TOPOLOGY else "peer", "pin_grep": "", "pin_fixed": ""}
            for n in rm.inventory_ids() if n not in skip]


def env(**override):
    e = {var: "sha256:" + format(i, "064x") for i, var in enumerate(rm.DIGEST_ENV.values(), 1)}
    e.update(override)
    return e


class Manifest(unittest.TestCase):
    def test_every_inventory_adapter_has_a_digest_variable(self):
        self.assertEqual(sorted(rm.inventory_ids()), sorted(rm.DIGEST_ENV))

    def test_every_adapter_with_a_digest(self):
        doc, errors = rm.manifest("v1.2.3", adapters(), env())
        self.assertEqual(errors, [])
        self.assertEqual(sorted(doc["peers"]) + sorted(doc["topology"]),
                         sorted(set(rm.inventory_ids()) - TOPOLOGY) + sorted(TOPOLOGY))
        for entry in doc["peers"].values():
            self.assertTrue(entry["independent"])
            self.assertRegex(entry["digest"], r"^sha256:[0-9a-f]{64}$")
        for entry in doc["topology"].values():
            self.assertNotIn("independent", entry)

    def test_an_adapter_without_an_image_is_refused(self):
        _, errors = rm.manifest("v1.2.3", adapters(skip={"bacnet4j"}), env())
        self.assertEqual(errors, ["bacnet4j: in adapters/inventory.yaml, but no image was built for it"])

    def test_an_adapter_without_a_digest_is_refused(self):
        for digest in ("", "sha256:", "sha256:" + "0" * 63):
            _, errors = rm.manifest("v1.2.3", adapters(), env(BIP_DIGEST=digest))
            self.assertEqual(len(errors), 1, digest)
            self.assertTrue(errors[0].startswith("bip-router: no image digest"), errors)

    def test_nothing_is_written_when_refused(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "manifest.json")
            e = env(TAG="v1.2.3", ADAPTERS_JSON=json.dumps(adapters(skip={"worldiety"})))
            with mock.patch.dict(os.environ, e, clear=True), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(rm.main([out]), 1)
            self.assertFalse(os.path.exists(out))
            e = env(TAG="v1.2.3", ADAPTERS_JSON=json.dumps(adapters()))
            with mock.patch.dict(os.environ, e, clear=True), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(rm.main([out]), 0)
            with open(out, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["version"], "v1.2.3")


if __name__ == "__main__":
    unittest.main()
