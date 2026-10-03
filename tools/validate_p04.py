#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "gaming-doctor"


def fail(reason: str) -> None:
    print(f"P04_VALIDATION=FAIL reason={reason}")
    raise SystemExit(1)


def main() -> None:
    proc = subprocess.run([str(BIN), "gpu", "--json"], capture_output=True, text=True, timeout=40, check=False)
    if proc.returncode != 0:
        fail("command_failed")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        fail("invalid_json")
    if data.get("schema_version") != 1 or data.get("phase") != "P04" or data.get("read_only") is not True:
        fail("contract_header")
    gpu = data.get("gpu", {})
    vulkan = data.get("vulkan", {})
    if gpu.get("device_count") != len(gpu.get("devices", [])):
        fail("gpu_count_mismatch")
    if vulkan.get("device_count") != len(vulkan.get("devices", [])):
        fail("vulkan_count_mismatch")
    if vulkan.get("icd_count") != len(vulkan.get("icds", [])):
        fail("icd_count_mismatch")
    if data.get("finding_count") != len(data.get("findings", [])):
        fail("finding_count_mismatch")
    c32 = vulkan.get("compat32", {})
    if c32.get("requirement_count") != len(c32.get("requirements", [])):
        fail("compat32_count_mismatch")
    if c32.get("missing_count") != sum(1 for x in c32.get("requirements", []) if not x.get("installed")):
        fail("compat32_missing_mismatch")
    privacy = data.get("privacy", {})
    if any(privacy.get(key) is not False for key in (
        "absolute_paths_emitted", "environment_values_collected", "device_serials_collected",
        "network_identifiers_collected", "tokens_collected"
    )):
        fail("privacy_contract")
    home = os.environ.get("HOME", "")
    if home and home != "/" and home in proc.stdout:
        fail("home_path_leak")
    for icd in vulkan.get("icds", []):
        if "/" in str(icd.get("file", "")) or "/" in str(icd.get("library", "")):
            fail("icd_absolute_path_leak")
    print("P04_JSON=PASS")
    print("P04_READ_ONLY=PASS")
    print("P04_PRIVACY_MINIMIZATION=PASS")
    print(f"P04_GPU_DEVICES={gpu.get('device_count', 0)}")
    print(f"P04_VULKAN_DEVICES={vulkan.get('device_count', 0)}")
    print(f"P04_VULKAN_32BIT_MISSING={c32.get('missing_count', 0)}")
    print(f"P04_FINDINGS={data.get('finding_count', 0)}")
    print("P04_VALIDATION=PASS")


if __name__ == "__main__":
    main()
