#!/usr/bin/env python3
"""Validate bacnet-interop fixture manifest and per-fixture metadata."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SCHEMA = ROOT / "fixtures" / "schema" / "fixture.schema.json"
MANIFEST_SCHEMA = ROOT / "fixtures" / "schema" / "manifest.schema.json"
DEVICE_SCHEMA = ROOT / "fixtures" / "schema" / "device.schema.json"
MANIFEST = ROOT / "fixtures" / "manifest.json"
HEX_RE = re.compile(r"^[0-9a-f]*$")


def load_json(path: Path) -> object:
    with path.open() as f:
        return json.load(f)


def try_import_validator():
    try:
        from jsonschema import Draft202012Validator  # type: ignore

        return Draft202012Validator
    except ImportError:
        return None


def under_fixtures(rel: str) -> bool:
    p = PurePosixPath(rel)
    return p.parts[:1] == ("fixtures",) and ".." not in p.parts


def resolved_under_fixtures(rel: str) -> bool:
    """True when rel resolves to a path inside ROOT/fixtures (no .. escapes)."""
    try:
        target = (ROOT / rel).resolve()
        base = (ROOT / "fixtures").resolve()
        return target == base or base in target.parents
    except OSError:
        return False


def main() -> int:
    errors: list[str] = []
    Validator = try_import_validator()
    if Validator is None:
        print(
            "ERROR: jsonschema is required (see requirements-dev.txt).",
            file=sys.stderr,
        )
        return 1

    for path in (FIXTURE_SCHEMA, MANIFEST_SCHEMA, DEVICE_SCHEMA, MANIFEST):
        if not path.is_file():
            errors.append(f"missing {path.relative_to(ROOT)}")
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    try:
        fixture_schema = load_json(FIXTURE_SCHEMA)
        manifest_schema = load_json(MANIFEST_SCHEMA)
        device_schema = load_json(DEVICE_SCHEMA)
        manifest = load_json(MANIFEST)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON: {exc}", file=sys.stderr)
        return 1

    for err in sorted(Validator(manifest_schema).iter_errors(manifest), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "(root)"
        errors.append(f"manifest {loc}: {err.message}")

    if not isinstance(manifest, dict):
        print("ERROR: manifest must be an object", file=sys.stderr)
        return 1

    fixtures = manifest.get("fixtures")
    if not isinstance(fixtures, list):
        print("ERROR: manifest.fixtures must be an array", file=sys.stderr)
        return 1

    fixture_validator = Validator(fixture_schema)
    ids: set[str] = set()
    paths: set[str] = set()

    for i, entry in enumerate(fixtures):
        if not isinstance(entry, dict):
            errors.append(f"fixtures[{i}] must be an object")
            continue
        fid = entry.get("id")
        rel = entry.get("path")
        if not isinstance(fid, str) or not isinstance(rel, str):
            continue
        if fid in ids:
            errors.append(f"duplicate fixture id: {fid}")
        ids.add(fid)
        if rel in paths:
            errors.append(f"duplicate fixture path: {rel}")
        paths.add(rel)
        if not under_fixtures(rel):
            errors.append(f"fixtures[{i}] path escapes fixtures/: {rel}")
            continue
        full = ROOT / rel
        if not full.is_file():
            errors.append(f"missing file for fixtures[{i}]: {rel}")
            continue
        try:
            meta = load_json(full)
        except json.JSONDecodeError as exc:
            errors.append(f"{rel}: invalid JSON: {exc}")
            continue
        if not isinstance(meta, dict):
            errors.append(f"{rel}: must be a JSON object")
            continue
        for err in sorted(fixture_validator.iter_errors(meta), key=lambda e: list(e.path)):
            loc = "/".join(str(p) for p in err.path) or "(root)"
            errors.append(f"{rel} {loc}: {err.message}")
        if meta.get("id") != fid:
            errors.append(f"{rel}: metadata id {meta.get('id')!r} != manifest id {fid!r}")
        hx = meta.get("input_hex")
        if isinstance(hx, str) and (len(hx) % 2 or not HEX_RE.fullmatch(hx.lower()) or hx != hx.lower()):
            # Allow uppercase in schema pattern, but prefer lowercase; enforce even length always.
            if len(hx) % 2 or not re.fullmatch(r"^[0-9a-fA-F]*$", hx):
                errors.append(f"{rel}: input_hex must be even-length hex")
        sem = meta.get("semantic_file")
        if isinstance(sem, str):
            if not resolved_under_fixtures(sem):
                errors.append(f"{rel}: semantic_file must resolve under fixtures/: {sem}")
            elif not (ROOT / sem).is_file():
                errors.append(f"{rel}: missing semantic_file {sem}")
        expect = meta.get("expect") or {}
        if isinstance(expect, dict):
            if expect.get("original_bytes_equal") and not meta.get("input_hex"):
                errors.append(f"{rel}: original_bytes_equal requires input_hex")
            if expect.get("semantic_decode_equal"):
                if not meta.get("semantic_file") and not meta.get("operation"):
                    errors.append(
                        f"{rel}: semantic_decode_equal requires operation+expected "
                        "or semantic_file"
                    )
                if meta.get("operation") and "expected" not in meta and "expected_error" not in meta:
                    errors.append(f"{rel}: operation requires expected or expected_error")
        lic = meta.get("license") or {}
        if isinstance(lic, dict) and lic.get("status") == "vendor-restricted":
            errors.append(f"{rel}: vendor-restricted fixtures must not be public")

    device_validator = Validator(device_schema)
    for device_path in sorted((ROOT / "fixtures" / "device").glob("*.json")):
        rel = str(device_path.relative_to(ROOT)).replace("\\", "/")
        try:
            device_meta = load_json(device_path)
        except json.JSONDecodeError as exc:
            errors.append(f"{rel}: invalid JSON: {exc}")
            continue
        for err in sorted(device_validator.iter_errors(device_meta), key=lambda e: list(e.path)):
            loc = "/".join(str(p) for p in err.path) or "(root)"
            errors.append(f"{rel} {loc}: {err.message}")

    if fixtures:
        for meta_path in ROOT.glob("fixtures/**/*.json"):
            rel = str(meta_path.relative_to(ROOT)).replace("\\", "/")
            if rel.endswith("manifest.json") or "/schema/" in rel:
                continue
            # Live adapter device models (not codec goldens).
            if "/device/" in rel:
                continue
            if meta_path.name.endswith(".semantic.json"):
                continue
            if rel not in paths:
                errors.append(f"unlisted fixture metadata: {rel}")

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    print(
        f"manifest schema: OK (schemaVersion={manifest.get('schemaVersion')!r}, "
        f"fixtures={len(fixtures)})"
    )
    print("validate-fixtures: passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
