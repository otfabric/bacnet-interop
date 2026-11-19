#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests of the inventory check of scripts/validate-fixtures.py (adapters/inventory.yaml
against schemas/capabilities-v1.schema.json)."""

import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("validate_fixtures", os.path.join(HERE, "validate-fixtures.py"))
vf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vf)
Validator = vf.try_import_validator()


def inventory():
    with open(vf.INVENTORY, encoding="utf-8") as f:
        return f.read()


class Loader(unittest.TestCase):
    def test_the_inventory(self):
        doc = vf.load_inventory(inventory())
        self.assertEqual(doc["schema_version"], "1")
        self.assertEqual(len(doc["adapters"]), 11)
        stack = doc["adapters"][0]
        self.assertEqual(stack["id"], "bacnet-stack")
        self.assertEqual(stack["capabilities"]["read_property"], "native")
        self.assertEqual(doc["fixtures_single_adapter"], {"device-baseline-v9": ["bacnet-stack"]})

    def test_scalars(self):
        doc = vf.load_inventory('a: "1"\nb: 1\nc: x-y  # note\nd: [p, "q r"]\ne:\nf: "a # b"\r\n')
        self.assertEqual(doc, {"a": "1", "b": 1, "c": "x-y", "d": ["p", "q r"], "e": None, "f": "a # b"})

    def test_what_it_does_not_parse_is_refused(self):
        for text in (
            "a:\n\tb: c\n",            # tab
            "a: b\na: c\n",            # duplicate key
            "a: 'b'\n",                # single-quoted scalar
            "a: {b: c}\n",             # flow mapping
            "a: b: c\n",               # a colon in a plain scalar
            "a: yes\n",                # YAML 1.1 and 1.2 disagree
            "a:\n    b: c\n  d: e\n",  # indentation that matches no parent
            "a: |\n  text\n",          # block scalar
            "  a: b\n",                # document not at column 0
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                vf.load_inventory(text)


@unittest.skipIf(Validator is None, "jsonschema is not installed (requirements-dev.txt)")
class Schema(unittest.TestCase):
    def test_the_inventory_is_valid(self):
        self.assertEqual(vf.validate_inventory(Validator), [])

    def test_an_unknown_cell_value_fails(self):
        text = inventory().replace("      read_property: native\n", "      read_property: nativ\n", 1)
        errors = vf.validate_inventory(Validator, text)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("adapters/0/capabilities/read_property", errors[0])

    def test_a_client_cell_cannot_be_topology_aid(self):
        text = inventory().replace("      who_is_i_am: native  # bacwi\n", "      who_is_i_am: topology-aid  # bacwi\n", 1)
        errors = vf.validate_inventory(Validator, text)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("adapters/0/client_capabilities/who_is_i_am", errors[0])

    def test_an_unknown_role_or_key_fails(self):
        for old, new in (("    role: peer-oracle\n", "    role: oracle\n"),
                         ("    upstream_version: \"1.6.1\"\n", "    upstream_versoin: \"1.6.1\"\n"),
                         ('schema_version: "1"\n', "schema_version: 1\n")):
            with self.subTest(new=new):
                self.assertTrue(vf.validate_inventory(Validator, inventory().replace(old, new, 1)))

    def test_an_unparsable_inventory_fails(self):
        errors = vf.validate_inventory(Validator, inventory() + "\tbroken: line\n")
        self.assertEqual(len(errors), 1)
        self.assertIn("tab in indentation", errors[0])


if __name__ == "__main__":
    unittest.main()
