#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "gaming-doctor"


def fail(reason: str) -> None:
    print(f"P03_VALIDATION=FAIL reason={reason}")
    raise SystemExit(1)


def main() -> None:
    proc = subprocess.run([str(BIN), "packaging", "--json"], capture_output=True, text=True, timeout=30, check=False)
    if proc.returncode != 0:
        fail("command_failed")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        fail("invalid_json")
    if data.get("schema_version") != 1 or data.get("phase") != "P03" or data.get("read_only") is not True:
        fail("contract_header")
    packaging = data.get("packaging", {})
    required = {
        "host_package_system", "native_steam", "flatpak_cli_present",
        "flatpak_steam_installation_count", "flatpak_steam_installations",
        "flatpak_external_library_count", "flatpak_undeclared_external_library_count",
        "host_nvidia_version", "flatpak_nvidia_gl_runtime", "flatpak_nvidia_gl32_runtime",
        "finding_count", "findings"
    }
    if not required.issubset(packaging):
        fail("missing_packaging_key")
    if packaging["flatpak_steam_installation_count"] != len(packaging["flatpak_steam_installations"]):
        fail("flatpak_count_mismatch")
    if packaging["finding_count"] != len(packaging["findings"]):
        fail("finding_count_mismatch")
    privacy = data.get("privacy", {})
    if any(privacy.get(key) is not False for key in (
        "absolute_paths_emitted", "flatpak_filesystem_paths_emitted",
        "environment_values_collected", "account_identifiers_collected", "tokens_collected"
    )):
        fail("privacy_contract")
    home = os.environ.get("HOME", "")
    if home and home != "/" and home in proc.stdout:
        fail("home_path_leak")
    print("P03_JSON=PASS")
    print("P03_READ_ONLY=PASS")
    print("P03_PRIVACY_MINIMIZATION=PASS")
    print(f"P03_NATIVE_STEAM={1 if packaging['native_steam']['present'] else 0}")
    print(f"P03_FLATPAK_STEAM={packaging['flatpak_steam_installation_count']}")
    print(f"P03_FINDINGS={packaging['finding_count']}")
    print("P03_VALIDATION=PASS")


if __name__ == "__main__":
    main()
