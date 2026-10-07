#!/usr/bin/env python3
import json, os, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BIN=ROOT/"bin"/"gaming-doctor"

p=subprocess.run([str(BIN),"storage","--json"],capture_output=True,text=True,timeout=40,check=False)
if p.returncode:
    raise SystemExit("P09_VALIDATION=FAIL reason=command_failed")
d=json.loads(p.stdout)
assert d["schema_version"]==1 and d["phase"]=="P09" and d["read_only"] is True
s=d["steam_storage"]
assert s["library_count"]==len(s["libraries"])
assert d["finding_count"]==len(d["findings"])
for k in (
    "absolute_paths_emitted","mount_sources_emitted","mount_targets_emitted",
    "usernames_collected","volume_labels_collected","filesystem_uuids_collected",
    "device_serials_collected","network_identifiers_collected","tokens_collected"
):
    assert d["privacy"][k] is False
home=os.environ.get("HOME","")
assert not(home and home!="/" and home in p.stdout)
print("P09_JSON=PASS")
print("P09_READ_ONLY=PASS")
print("P09_PRIVACY_MINIMIZATION=PASS")
print("P09_STEAM_LIBRARIES="+str(s["library_count"]))
print("P09_WINDOWS_SHARED_LIBRARIES="+str(s["windows_shared_library_count"]))
print("P09_READ_ONLY_LIBRARIES="+str(s["read_only_library_count"]))
print("P09_NOEXEC_LIBRARIES="+str(s["noexec_library_count"]))
print("P09_FINDINGS="+str(d["finding_count"]))
print("P09_VALIDATION=PASS")
