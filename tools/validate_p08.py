#!/usr/bin/env python3
import json, os, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BIN=ROOT/"bin"/"gaming-doctor"

p=subprocess.run([str(BIN),"input","--json"],capture_output=True,text=True,timeout=40,check=False)
if p.returncode:
    raise SystemExit("P08_VALIDATION=FAIL reason=command_failed")
d=json.loads(p.stdout)
assert d["schema_version"]==1 and d["phase"]=="P08" and d["read_only"] is True
assert d["events"]["count"]==len(d["events"]["devices"])
assert d["hidraw"]["count"]==len(d["hidraw"]["nodes"])
assert d["device_scope_batteries"]["count"]==len(d["device_scope_batteries"]["batteries"])
assert d["finding_count"]==len(d["findings"])
for k in (
    "absolute_paths_emitted","device_names_emitted","physical_paths_emitted",
    "hardware_serials_collected","hardware_addresses_collected",
    "process_command_lines_collected","environment_values_collected","tokens_collected"
):
    assert d["privacy"][k] is False
home=os.environ.get("HOME","")
assert not(home and home!="/" and home in p.stdout)
print("P08_JSON=PASS")
print("P08_READ_ONLY=PASS")
print("P08_PRIVACY_MINIMIZATION=PASS")
print("P08_INPUT_EVENTS="+str(d["events"]["count"]))
print("P08_GAMEPADS="+str(d["events"]["gamepad_count"]))
print("P08_HIDRAW="+str(d["hidraw"]["count"]))
print("P08_FINDINGS="+str(d["finding_count"]))
print("P08_VALIDATION=PASS")
