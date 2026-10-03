#!/usr/bin/env python3
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "corpus" / "cases"
INDEX = ROOT / "corpus" / "index.json"

ALLOWED_CLASS = {"REPAIRABLE", "WORKAROUND", "UPSTREAM_BUG", "UNSUPPORTED_POLICY", "UNKNOWN"}
ALLOWED_EVIDENCE = {"CONFIRMED", "REPORTED", "UNCONFIRMED"}
ALLOWED_MUTATION = {"NONE", "TEMPORARY_ONLY", "REVERSIBLE"}
ID_RE = re.compile(r"^LGD-(\d{4})$")


def fail(msg: str) -> None:
    print(f"P00_VALIDATION=FAIL: {msg}")
    raise SystemExit(1)


def main() -> None:
    files = sorted(CASES.glob("LGD-*.json"))
    if len(files) != 100:
        fail(f"expected 100 cases, found {len(files)}")

    ids = set()
    for i, path in enumerate(files, 1):
        try:
            obj = json.loads(path.read_text())
        except Exception as e:
            fail(f"{path.name}: invalid JSON: {e}")

        required = {"id", "title", "category", "symptom", "classification", "evidence_status", "probes", "mutation_policy", "verification", "rollback"}
        missing = sorted(required - obj.keys())
        if missing:
            fail(f"{path.name}: missing {missing}")

        m = ID_RE.match(obj["id"])
        if not m:
            fail(f"{path.name}: invalid id {obj['id']!r}")
        if int(m.group(1)) != i:
            fail(f"{path.name}: expected sequential id LGD-{i:04d}")
        if obj["id"] in ids:
            fail(f"duplicate id {obj['id']}")
        ids.add(obj["id"])

        if obj["classification"] not in ALLOWED_CLASS:
            fail(f"{obj['id']}: invalid classification")
        if obj["evidence_status"] not in ALLOWED_EVIDENCE:
            fail(f"{obj['id']}: invalid evidence_status")
        if obj["mutation_policy"] not in ALLOWED_MUTATION:
            fail(f"{obj['id']}: invalid mutation_policy")
        if not isinstance(obj["probes"], list) or not obj["probes"]:
            fail(f"{obj['id']}: at least one probe required")
        if not isinstance(obj["verification"], list) or not obj["verification"]:
            fail(f"{obj['id']}: verification required")
        if obj["mutation_policy"] != "NONE" and not obj["rollback"]:
            fail(f"{obj['id']}: mutation requires rollback")
        if obj["evidence_status"] == "UNCONFIRMED" and obj["classification"] == "REPAIRABLE":
            fail(f"{obj['id']}: unconfirmed case cannot be directly repairable")

    index = json.loads(INDEX.read_text())
    if index.get("case_count") != 100:
        fail("corpus/index.json case_count must be 100")
    if index.get("status") != "P00_FROZEN":
        fail("corpus/index.json status must be P00_FROZEN")

    print("P00_CORPUS_COUNT=100")
    print("P00_IDS=PASS")
    print("P00_CLASSIFICATIONS=PASS")
    print("P00_MUTATION_ROLLBACK_INVARIANT=PASS")
    print("P00_EVIDENCE_GATING=PASS")
    print("P00_VALIDATION=PASS")


if __name__ == "__main__":
    main()
