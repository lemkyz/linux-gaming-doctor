#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "gaming-doctor"


def fail(message: str) -> None:
    print(f"P02_VALIDATION=FAIL reason={message}")
    raise SystemExit(1)


def main() -> None:
    p = subprocess.run([str(BIN), "steam", "--json"], capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        fail(f"STEAM_COMMAND_EXIT_{p.returncode}")
    try:
        data = json.loads(p.stdout)
    except Exception as exc:
        fail(f"INVALID_JSON:{exc}")

    if data.get("schema_version") != 1 or data.get("phase") != "P02" or data.get("read_only") is not True:
        fail("CONTRACT_HEADER")
    steam = data.get("steam")
    if not isinstance(steam, dict):
        fail("STEAM_OBJECT")
    for key in (
        "installation_count", "installations", "library_count", "libraries", "app_count", "apps",
        "compat_tool_count", "compat_tools", "compatdata_count", "orphan_compatdata_count",
        "default_compat_tools", "shared_windows_filesystem_library_count", "finding_count", "findings"
    ):
        if key not in steam:
            fail("MISSING_STEAM_KEY:" + key)
    if steam["app_count"] != len(steam["apps"]):
        fail("APP_COUNT_MISMATCH")
    if steam["library_count"] != len(steam["libraries"]):
        fail("LIBRARY_COUNT_MISMATCH")
    if steam["compat_tool_count"] != len(steam["compat_tools"]):
        fail("TOOL_COUNT_MISMATCH")
    if steam["finding_count"] != len(steam["findings"]):
        fail("FINDING_COUNT_MISMATCH")
    appids = [a.get("appid") for a in steam["apps"]]
    if any(not isinstance(a, str) or not a.isdigit() for a in appids):
        fail("INVALID_APPID")

    privacy = data.get("privacy", {})
    for key in ("absolute_paths_emitted", "account_identifiers_collected", "tokens_collected", "network_identifiers_collected"):
        if privacy.get(key) is not False:
            fail("PRIVACY_CONTRACT:" + key)
    home = os.environ.get("HOME", "")
    if home and home != "/" and home in p.stdout:
        fail("HOME_PATH_LEAK")

    print("P02_JSON=PASS")
    print("P02_READ_ONLY=PASS")
    print("P02_PRIVACY_MINIMIZATION=PASS")
    print(f"P02_STEAM_INSTALLATIONS={steam['installation_count']}")
    print(f"P02_LIBRARIES={steam['library_count']}")
    print(f"P02_APPS={steam['app_count']}")
    print(f"P02_PROTON_TOOLS={steam['compat_tool_count']}")
    print(f"P02_FINDINGS={steam['finding_count']}")
    print("P02_VALIDATION=PASS")


if __name__ == "__main__":
    main()
