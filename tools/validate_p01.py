#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "gaming-doctor"


def fail(message: str) -> None:
    print(f"P01_VALIDATION=FAIL reason={message}")
    raise SystemExit(1)


def walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


def main() -> None:
    p = subprocess.run([str(BIN), "facts", "--json"], capture_output=True, text=True, timeout=20)
    if p.returncode != 0:
        fail(f"FACTS_COMMAND_EXIT_{p.returncode}")
    try:
        data = json.loads(p.stdout)
    except Exception as exc:
        fail(f"INVALID_JSON:{exc}")

    required = {
        "schema_version", "phase", "read_only", "host", "session", "cpu", "gpus",
        "graphics", "steam", "filesystems", "audio", "input", "security", "power", "privacy"
    }
    missing = sorted(required - set(data))
    if missing:
        fail("MISSING_KEYS:" + ",".join(missing))
    if data["schema_version"] != 1 or data["phase"] != "P01" or data["read_only"] is not True:
        fail("CONTRACT_HEADER")

    privacy = data["privacy"]
    for key in ("hostname_collected", "serials_collected", "network_identifiers_collected", "user_paths_emitted"):
        if privacy.get(key) is not False:
            fail("PRIVACY_CONTRACT:" + key)

    home = os.environ.get("HOME", "")
    if home and home != "/" and home in p.stdout:
        fail("HOME_PATH_LEAK")

    forbidden = {"hostname", "username", "machine_id", "mac", "ip", "serial"}
    bad = sorted(set(walk_keys(data)) & forbidden)
    if bad:
        fail("FORBIDDEN_KEYS:" + ",".join(bad))

    print("P01_JSON=PASS")
    print("P01_READ_ONLY=PASS")
    print("P01_PRIVACY_MINIMIZATION=PASS")
    print(f"P01_GPU_FACTS={len(data['gpus'])}")
    print(f"P01_VULKAN_PROBE={data['graphics']['vulkan_probe']}")
    print("P01_VALIDATION=PASS")


if __name__ == "__main__":
    main()
