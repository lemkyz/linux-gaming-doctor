#!/usr/bin/env python3
import json, os, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BIN=ROOT/"bin"/"gaming-doctor"
p=subprocess.run([str(BIN),"display","--json"],capture_output=True,text=True,timeout=40,check=False)
if p.returncode: raise SystemExit("P05_VALIDATION=FAIL reason=command_failed")
d=json.loads(p.stdout)
assert d["schema_version"]==1 and d["phase"]=="P05" and d["read_only"] is True
assert d["drm"]["connector_count"]==len(d["drm"]["connectors"])
assert d["display"]["output_count"]==len(d["display"]["outputs"])
assert d["finding_count"]==len(d["findings"])
for k in ("absolute_paths_emitted","environment_values_collected","edid_payload_collected","display_serials_collected"):
    assert d["privacy"][k] is False
home=os.environ.get("HOME","")
assert not(home and home!="/" and home in p.stdout)
print("P05_JSON=PASS")
print("P05_READ_ONLY=PASS")
print("P05_PRIVACY_MINIMIZATION=PASS")
print("P05_DRM_CONNECTORS="+str(d["drm"]["connector_count"]))
print("P05_DISPLAY_OUTPUTS="+str(d["display"]["output_count"]))
print("P05_DISPLAY_SOURCE="+str(d["display"]["source"]).upper())
print("P05_FINDINGS="+str(d["finding_count"]))
print("P05_VALIDATION=PASS")
