#!/usr/bin/env python3
import json, os, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BIN=ROOT/"bin"/"gaming-doctor"

p=subprocess.run([str(BIN),"launchers","--json"],capture_output=True,text=True,timeout=50,check=False)
if p.returncode:
    raise SystemExit("P10_VALIDATION=FAIL reason=command_failed")
d=json.loads(p.stdout)
assert d["schema_version"]==1 and d["phase"]=="P10" and d["read_only"] is True
assert d["heroic"]["record_count"]==len(d["heroic"]["records"])
assert d["lutris"]["config_count"]==len(d["lutris"]["configs"])
assert d["finding_count"]==len(d["findings"])
for k in (
    "absolute_paths_emitted","game_titles_emitted","account_identifiers_collected",
    "launcher_tokens_collected","raw_config_emitted","raw_logs_emitted",
    "environment_values_collected","network_identifiers_collected"
):
    assert d["privacy"][k] is False
home=os.environ.get("HOME","")
assert not(home and home!="/" and home in p.stdout)
print("P10_JSON=PASS")
print("P10_READ_ONLY=PASS")
print("P10_PRIVACY_MINIMIZATION=PASS")
print("P10_HEROIC_PRESENT="+("YES" if d["heroic"]["present"] else "NO"))
print("P10_HEROIC_RECORDS="+str(d["heroic"]["record_count"]))
print("P10_LUTRIS_PRESENT="+("YES" if d["lutris"]["present"] else "NO"))
print("P10_LUTRIS_CONFIGS="+str(d["lutris"]["config_count"]))
print("P10_FINDINGS="+str(d["finding_count"]))
print("P10_VALIDATION=PASS")
