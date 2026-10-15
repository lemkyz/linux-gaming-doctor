#!/usr/bin/env python3
import json, os, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BIN=ROOT/"bin"/"gaming-doctor"

p=subprocess.run([str(BIN),"knowledge","--json"],capture_output=True,text=True,timeout=50,check=False)
if p.returncode:
    raise SystemExit("P11_VALIDATION=FAIL reason=command_failed")
d=json.loads(p.stdout)
assert d["schema_version"]==1 and d["phase"]=="P11" and d["read_only"] is True
k=d["knowledge"]
assert k["validation_error_count"]==0
assert k["validation_errors"]==[]
assert k["pack_count"]>=9
assert k["corpus_case_count"]==100
assert d["finding_count"]==len(d["findings"])
policy=d["policy"]
assert policy["knowledge_is_diagnosis"] is False
assert policy["reported_evidence_can_auto_repair"] is False
assert policy["unconfirmed_evidence_can_auto_repair"] is False
assert policy["exact_confirmed_still_requires_observed_preconditions"] is True
for match in k["matches"]:
    for case in match["cases"]:
        assert case["actionability"]=="candidate_only"
privacy=d["privacy"]
for key in (
    "absolute_paths_emitted","installed_game_names_emitted",
    "account_identifiers_collected","raw_steam_config_emitted",
    "network_identifiers_collected","tokens_collected"
):
    assert privacy[key] is False
home=os.environ.get("HOME","")
assert not(home and home!="/" and home in p.stdout)
print("P11_JSON=PASS")
print("P11_READ_ONLY=PASS")
print("P11_PRIVACY_MINIMIZATION=PASS")
print("P11_PACKS="+str(k["pack_count"]))
print("P11_CORPUS_CASES="+str(k["corpus_case_count"]))
print("P11_INSTALLED_APPS="+str(k["installed_app_count"]))
print("P11_MATCHED_APPS="+str(k["matched_installed_app_count"]))
print("P11_CANDIDATE_CASES="+str(k["candidate_case_count"]))
print("P11_FINDINGS="+str(d["finding_count"]))
print("P11_VALIDATION=PASS")
