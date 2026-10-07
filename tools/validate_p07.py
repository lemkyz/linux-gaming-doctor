#!/usr/bin/env python3
import json, os, re, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BIN=ROOT/"bin"/"gaming-doctor"
p=subprocess.run([str(BIN),"audio","--json"],capture_output=True,text=True,timeout=40,check=False)
if p.returncode: raise SystemExit("P07_VALIDATION=FAIL reason=command_failed")
d=json.loads(p.stdout)
assert d["schema_version"]==1 and d["phase"]=="P07" and d["read_only"] is True
s=d["server"]
assert s["sink_count"]==len(s["sinks"])
assert s["source_count"]==len(s["sources"])
assert s["card_count"]==len(s["cards"])
assert d["finding_count"]==len(d["findings"])
for k in ("absolute_paths_emitted","raw_audio_logs_emitted","endpoint_names_emitted","device_descriptions_emitted","hardware_addresses_collected","process_command_lines_collected","environment_values_collected","tokens_collected"):
    assert d["privacy"][k] is False
home=os.environ.get("HOME","")
assert not(home and home!="/" and home in p.stdout)
assert re.search(r"(?i)(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}",p.stdout) is None
print("P07_JSON=PASS")
print("P07_READ_ONLY=PASS")
print("P07_PRIVACY_MINIMIZATION=PASS")
print("P07_SINKS="+str(s["sink_count"]))
print("P07_SOURCES="+str(s["source_count"]))
print("P07_BLUETOOTH_CARDS="+str(d["bluetooth"]["card_count"]))
print("P07_FINDINGS="+str(d["finding_count"]))
print("P07_VALIDATION=PASS")
