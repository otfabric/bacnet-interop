#!/usr/bin/env python3
"""Validate bacnet-interop fixture manifest and per-fixture metadata, the
client-mode scenario files and adapters/inventory.yaml (capabilities)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SCHEMA = ROOT / "fixtures" / "schema" / "fixture.schema.json"
MANIFEST_SCHEMA = ROOT / "fixtures" / "schema" / "manifest.schema.json"
DEVICE_SCHEMA = ROOT / "fixtures" / "schema" / "device.schema.json"
SCENARIOS_SCHEMA = ROOT / "fixtures" / "schema" / "client-scenarios.schema.json"
RESULT_LINE_SCHEMA = ROOT / "schemas" / "client-result-line-v1.schema.json"
CAPABILITIES_SCHEMA = ROOT / "schemas" / "capabilities-v1.schema.json"
INVENTORY = ROOT / "adapters" / "inventory.yaml"
MANIFEST = ROOT / "fixtures" / "manifest.json"
HEX_RE = re.compile(r"^[0-9a-f]*$")

# The YAML subset of adapters/inventory.yaml: block mappings and sequences
# indented by spaces, double-quoted and plain scalars, flow sequences of
# scalars ([a, b]) and comments. Anything else is refused, not guessed.
KEY_RE = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*):(?:\s+(.*))?$")
PLAIN_RE = re.compile(r"^[A-Za-z0-9_./+-][^#:]*$")
FLOW_ITEM_RE = re.compile(r'^(?:[A-Za-z0-9_./+-]+|"[^",\\]*")$')
INT_RE = re.compile(r"^[-+]?[0-9]+$")
FLOAT_RE = re.compile(r"^[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?$")
AMBIGUOUS = {"yes", "no", "on", "off", "y", "n"}


def strip_comment(line: str) -> str:
    """line without its comment (a # at the start or after a space, outside quotes)."""
    quoted = False
    for i, ch in enumerate(line):
        if ch == '"' and (i == 0 or line[i - 1] != "\\"):
            quoted = not quoted
        elif ch == "#" and not quoted and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def yaml_scalar(text: str, where: str) -> object:
    if text.startswith('"'):
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            value = None
        if not isinstance(value, str):
            raise ValueError(f"{where}: not a double-quoted string: {text}")
        return value
    if text.startswith("["):
        if not text.endswith("]"):
            raise ValueError(f"{where}: unterminated flow sequence: {text}")
        inner = text[1:-1].strip()
        items = [s.strip() for s in inner.split(",")] if inner else []
        for item in items:
            if not FLOW_ITEM_RE.fullmatch(item):
                raise ValueError(f"{where}: unsupported flow sequence item: {item!r}")
        return [yaml_scalar(item, where) for item in items]
    if not PLAIN_RE.fullmatch(text) or text.lower() in AMBIGUOUS:
        raise ValueError(f"{where}: unsupported scalar: {text}")
    if text in ("null", "Null", "NULL", "~"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if INT_RE.fullmatch(text):
        return int(text)
    if FLOAT_RE.fullmatch(text):
        return float(text)
    return text


def load_inventory(text: str, name: str = "adapters/inventory.yaml") -> object:
    """Parse the YAML subset of adapters/inventory.yaml; ValueError on anything else."""
    lines = []
    for no, raw in enumerate(text.replace("\r\n", "\n").split("\n"), 1):
        body = strip_comment(raw)
        if not body.strip():
            continue
        stripped = body.lstrip(" ")
        if stripped.startswith("\t") or "\t" in body[: len(body) - len(stripped)]:
            raise ValueError(f"{name}:{no}: tab in indentation")
        lines.append((no, len(body) - len(stripped), stripped))
    if not lines:
        raise ValueError(f"{name}: empty")

    def item(body: str) -> bool:
        return body == "-" or body.startswith("- ")

    def block(i: int, indent: int) -> tuple[object, int]:
        return sequence(i, indent) if item(lines[i][2]) else mapping(i, indent)

    def value_after(i: int, indent: int, rest: str | None, where: str) -> tuple[object, int]:
        """The value of a key or item on line i, whose content is rest."""
        if rest:
            return yaml_scalar(rest, where), i + 1
        if i + 1 < len(lines) and (lines[i + 1][1] > indent or (lines[i + 1][1] == indent and item(lines[i + 1][2]))):
            return block(i + 1, lines[i + 1][1])
        return None, i + 1

    def mapping(i: int, indent: int) -> tuple[object, int]:
        result: dict[str, object] = {}
        while i < len(lines) and lines[i][1] == indent and not item(lines[i][2]):
            no, _, body = lines[i]
            m = KEY_RE.fullmatch(body)
            if not m:
                raise ValueError(f"{name}:{no}: not a key: value line: {body}")
            key = m.group(1)
            if key in result:
                raise ValueError(f"{name}:{no}: duplicate key {key}")
            result[key], i = value_after(i, indent, m.group(2), f"{name}:{no}")
        if i < len(lines) and lines[i][1] > indent:
            raise ValueError(f"{name}:{lines[i][0]}: unexpected indentation")
        return result, i

    def sequence(i: int, indent: int) -> tuple[object, int]:
        result: list[object] = []
        while i < len(lines) and lines[i][1] == indent and item(lines[i][2]):
            no, _, body = lines[i]
            rest = body[1:].lstrip(" ")
            if KEY_RE.fullmatch(rest):
                # "- key: value" starts a mapping at the column of the key.
                lines[i] = (no, indent + len(body) - len(rest), rest)
                value, i = mapping(i, lines[i][1])
            else:
                value, i = value_after(i, indent, rest, f"{name}:{no}")
            result.append(value)
        if i < len(lines) and lines[i][1] > indent:
            raise ValueError(f"{name}:{lines[i][0]}: unexpected indentation")
        return result, i

    if lines[0][1] != 0:
        raise ValueError(f"{name}:{lines[0][0]}: the document must start at column 0")
    doc, i = block(0, 0)
    if i < len(lines):
        raise ValueError(f"{name}:{lines[i][0]}: unexpected line: {lines[i][2]}")
    return doc


def validate_inventory(Validator, text: str | None = None) -> list[str]:
    """adapters/inventory.yaml against schemas/capabilities-v1.schema.json."""
    rel = str(INVENTORY.relative_to(ROOT))
    try:
        schema = load_json(CAPABILITIES_SCHEMA)
        Validator.check_schema(schema)
    except Exception as exc:  # noqa: BLE001
        return [f"capabilities schema: {exc}"]
    try:
        doc = load_inventory(INVENTORY.read_text(encoding="utf-8") if text is None else text, rel)
    except (OSError, ValueError) as exc:
        return [str(exc)]
    errors = []
    for err in sorted(Validator(schema).iter_errors(doc), key=lambda e: [str(p) for p in e.path]):
        loc = "/".join(str(p) for p in err.path) or "(root)"
        errors.append(f"{rel} {loc}: {err.message}")
    return errors


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


def validate_scenarios(Validator) -> list[str]:
    """Client-mode scenario files (docs/CLIENT_DRIVER_CONTRACT.md)."""
    errors: list[str] = []
    try:
        scenario_schema = load_json(SCENARIOS_SCHEMA)
        Validator.check_schema(scenario_schema)
        Validator.check_schema(load_json(RESULT_LINE_SCHEMA))
    except Exception as exc:  # noqa: BLE001
        return [f"client schemas: {exc}"]
    validator = Validator(scenario_schema)
    for path in sorted((ROOT / "fixtures" / "scenarios").glob("*.json")):
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        try:
            doc = load_json(path)
        except json.JSONDecodeError as exc:
            errors.append(f"{rel}: invalid JSON: {exc}")
            continue
        for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
            loc = "/".join(str(p) for p in err.path) or "(root)"
            errors.append(f"{rel} {loc}: {err.message}")
        if not isinstance(doc, dict):
            continue
        if doc.get("id") != path.stem:
            errors.append(f"{rel}: id {doc.get('id')!r} != file name {path.stem!r}")
        req = doc.get("requires_fixture")
        if isinstance(req, str) and not (ROOT / "fixtures" / "device" / f"{req}.json").is_file():
            errors.append(f"{rel}: requires_fixture {req} has no fixtures/device/{req}.json")
        seen: set[str] = set()
        for sc in doc.get("scenarios") or []:
            sid = sc.get("id") if isinstance(sc, dict) else None
            if sid in seen:
                errors.append(f"{rel}: duplicate scenario id {sid}")
            seen.add(sid)
    return errors


def main() -> int:
    errors: list[str] = []
    Validator = try_import_validator()
    if Validator is None:
        print(
            "ERROR: jsonschema is required (see requirements-dev.txt).",
            file=sys.stderr,
        )
        return 1

    for path in (FIXTURE_SCHEMA, MANIFEST_SCHEMA, DEVICE_SCHEMA, SCENARIOS_SCHEMA, RESULT_LINE_SCHEMA,
                 CAPABILITIES_SCHEMA, INVENTORY, MANIFEST):
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
            if expect.get("original_bytes_equal") and "input_hex" not in meta:
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

    errors.extend(validate_scenarios(Validator))
    errors.extend(validate_inventory(Validator))

    if fixtures:
        for meta_path in ROOT.glob("fixtures/**/*.json"):
            rel = str(meta_path.relative_to(ROOT)).replace("\\", "/")
            if rel.endswith("manifest.json") or "/schema/" in rel:
                continue
            # Live adapter / topology models (not codec goldens).
            if "/device/" in rel or "/topology/" in rel or "/bbmd/" in rel or "/scenarios/" in rel:
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
