#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "gaming-doctor"

def fail(reason: str) -> None:
    print(f"P06_VALIDATION=FAIL reason={reason}")
    raise SystemExit(1)

def main() -> None:
    proc = subprocess.run([str(BIN), "performance", "--json"], capture_output=True, text=True, timeout=40, check=False)
    if proc.returncode != 0:
        fail("command_failed")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        fail("invalid_json")
    if data.get("schema_version") != 1 or data.get("phase") != "P06" or data.get("read_only") is not True:
        fail("contract_header")
    freq = data.get("cpu", {}).get("frequency", {})
    thermal = data.get("thermal", {})
    nvidia = data.get("nvidia", {})
    if freq.get("policy_count") != len(freq.get("policies", [])):
        fail("cpufreq_count_mismatch")
    if thermal.get("zone_count") != len(thermal.get("zones", [])):
        fail("thermal_count_mismatch")
    if nvidia.get("device_count") != len(nvidia.get("devices", [])):
        fail("nvidia_count_mismatch")
    if data.get("finding_count") != len(data.get("findings", [])):
        fail("finding_count_mismatch")
    privacy = data.get("privacy", {})
    for key in (
        "absolute_paths_emitted",
        "process_command_lines_collected",
        "environment_values_collected",
        "host_identifiers_collected",
        "hardware_serials_collected",
        "network_identifiers_collected",
        "tokens_collected",
    ):
        if privacy.get(key) is not False:
            fail("privacy_contract:" + key)
    home = os.environ.get("HOME", "")
    if home and home != "/" and home in proc.stdout:
        fail("home_path_leak")
    print("P06_JSON=PASS")
    print("P06_READ_ONLY=PASS")
    print("P06_PRIVACY_MINIMIZATION=PASS")
    print(f"P06_CPUFREQ_POLICIES={freq.get('policy_count', 0)}")
    print(f"P06_THERMAL_ZONES={thermal.get('zone_count', 0)}")
    print(f"P06_NVIDIA_PERF_DEVICES={nvidia.get('device_count', 0)}")
    print(f"P06_FINDINGS={data.get('finding_count', 0)}")
    print("P06_VALIDATION=PASS")

if __name__ == "__main__":
    main()
