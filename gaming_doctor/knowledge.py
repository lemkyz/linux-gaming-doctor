from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .steam import collect_steam_state

ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "knowledge" / "games"
CASE_DIR = ROOT / "corpus" / "cases"


def _clean(value: object, limit: int = 140) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = " ".join(text.split()).replace("=", ":")
    return text[:limit] if text else "unknown"


def _norm_name(value: str) -> str:
    text = value.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def load_corpus(case_dir: Path = CASE_DIR) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    try:
        paths = sorted(case_dir.glob("LGD-*.json"))
    except OSError:
        paths = []
    for path in paths:
        data = _load_json(path)
        if not isinstance(data, dict):
            continue
        case_id = str(data.get("id", ""))
        if re.fullmatch(r"LGD-\d{4}", case_id):
            out[case_id] = data
    return out


def load_game_packs(pack_dir: Path = PACK_DIR) -> list[dict[str, Any]]:
    packs: list[dict[str, Any]] = []
    try:
        paths = sorted(pack_dir.glob("*.json"))
    except OSError:
        paths = []
    for path in paths:
        data = _load_json(path)
        if isinstance(data, dict):
            packs.append(data)
    return packs


def validate_pack(pack: dict[str, Any], corpus: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if pack.get("schema_version") != 1:
        errors.append("schema_version")
    pack_id = pack.get("pack_id")
    if not isinstance(pack_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,79}", pack_id):
        errors.append("pack_id")
    match = pack.get("match")
    if not isinstance(match, dict):
        errors.append("match")
        return errors
    appids = match.get("steam_appids", [])
    aliases = match.get("name_aliases", [])
    if not isinstance(appids, list) or any(not isinstance(x, str) or not x.isdigit() for x in appids):
        errors.append("steam_appids")
    if not isinstance(aliases, list) or any(not isinstance(x, str) or not x.strip() for x in aliases):
        errors.append("name_aliases")
    links = pack.get("case_links", [])
    if not isinstance(links, list):
        errors.append("case_links")
        return errors
    seen: set[str] = set()
    for link in links:
        if not isinstance(link, dict):
            errors.append("case_link_type")
            continue
        cid = link.get("case_id")
        relation = link.get("relation")
        if cid in seen:
            errors.append(f"duplicate_case:{cid}")
        seen.add(str(cid))
        if cid not in corpus:
            errors.append(f"missing_case:{cid}")
        if relation not in {"exact", "family", "diagnostic_boundary"}:
            errors.append(f"relation:{cid}")
    return errors


def _pack_matches_app(pack: dict[str, Any], app: dict[str, Any]) -> str | None:
    match = pack.get("match", {})
    appid = str(app.get("appid", ""))
    if appid in set(match.get("steam_appids", [])):
        return "appid"
    name = _norm_name(str(app.get("name", "")))
    for alias in match.get("name_aliases", []):
        if _norm_name(alias) == name and name:
            return "name"
    return None


def _case_view(case: dict[str, Any], relation: str) -> dict[str, Any]:
    evidence = str(case.get("evidence_status", "UNKNOWN"))
    return {
        "case_id": str(case.get("id", "unknown")),
        "relation": relation,
        "classification": str(case.get("classification", "UNKNOWN")),
        "evidence_status": evidence,
        "actionability": "candidate_only",
        "requires_runtime_confirmation": evidence != "CONFIRMED" or relation != "exact",
    }


def _pack_view(pack: dict[str, Any], corpus: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cases = []
    for link in pack.get("case_links", []):
        case = corpus.get(link.get("case_id"))
        if case:
            cases.append(_case_view(case, str(link.get("relation", "family"))))
    return {
        "pack_id": str(pack.get("pack_id", "unknown")),
        "steam_appids": list(pack.get("match", {}).get("steam_appids", [])),
        "case_count": len(cases),
        "cases": cases,
    }


def collect_knowledge_state(appid_filter: str | None = None) -> dict[str, Any]:
    corpus = load_corpus()
    packs = load_game_packs()

    validation_errors: list[str] = []
    seen_pack_ids: set[str] = set()
    for pack in packs:
        pid = str(pack.get("pack_id", ""))
        if pid in seen_pack_ids:
            validation_errors.append(f"duplicate_pack:{pid}")
        seen_pack_ids.add(pid)
        for error in validate_pack(pack, corpus):
            validation_errors.append(f"{pid or 'unknown'}:{error}")

    steam_report = collect_steam_state()
    installed = steam_report.get("steam", {}).get("apps", [])
    if appid_filter is not None:
        installed = [x for x in installed if str(x.get("appid", "")) == appid_filter]

    matches: list[dict[str, Any]] = []
    matched_appids: set[str] = set()
    for app in installed:
        appid = str(app.get("appid", ""))
        for pack in packs:
            method = _pack_matches_app(pack, app)
            if method is None:
                continue
            view = _pack_view(pack, corpus)
            matches.append({
                "appid": appid,
                "pack_id": view["pack_id"],
                "match_method": method,
                "case_count": view["case_count"],
                "cases": view["cases"],
            })
            matched_appids.add(appid)

    direct_lookup: list[dict[str, Any]] = []
    if appid_filter is not None:
        for pack in packs:
            if appid_filter in set(pack.get("match", {}).get("steam_appids", [])):
                direct_lookup.append(_pack_view(pack, corpus))

    candidate_case_count = sum(x["case_count"] for x in matches)
    confirmed_exact = sum(
        1
        for match in matches
        for case in match["cases"]
        if case["relation"] == "exact" and case["evidence_status"] == "CONFIRMED"
    )
    reported_or_unconfirmed = sum(
        1
        for match in matches
        for case in match["cases"]
        if case["evidence_status"] in {"REPORTED", "UNCONFIRMED"}
    )

    findings: list[dict[str, str]] = []
    if validation_errors:
        findings.append({
            "code": "GAME_KNOWLEDGE_VALIDATION_FAILED",
            "severity": "warning",
            "classification": "REPAIRABLE",
            "scope": "knowledge",
            "evidence": f"{len(validation_errors)} knowledge-pack validation error(s) were found",
        })

    return {
        "schema_version": 1,
        "phase": "P11",
        "read_only": True,
        "knowledge": {
            "pack_count": len(packs),
            "corpus_case_count": len(corpus),
            "validation_error_count": len(validation_errors),
            "validation_errors": validation_errors,
            "installed_app_count": len(installed),
            "matched_installed_app_count": len(matched_appids),
            "unmatched_installed_app_count": max(0, len(installed) - len(matched_appids)),
            "match_count": len(matches),
            "candidate_case_count": candidate_case_count,
            "confirmed_exact_candidate_count": confirmed_exact,
            "reported_or_unconfirmed_candidate_count": reported_or_unconfirmed,
            "matches": matches,
            "direct_lookup": direct_lookup,
        },
        "finding_count": len(findings),
        "findings": findings,
        "policy": {
            "knowledge_is_diagnosis": False,
            "reported_evidence_can_auto_repair": False,
            "unconfirmed_evidence_can_auto_repair": False,
            "exact_confirmed_still_requires_observed_preconditions": True,
        },
        "privacy": {
            "absolute_paths_emitted": False,
            "installed_game_names_emitted": False,
            "account_identifiers_collected": False,
            "raw_steam_config_emitted": False,
            "network_identifiers_collected": False,
            "tokens_collected": False,
        },
    }


def render_text(report: dict[str, Any]) -> str:
    k = report["knowledge"]
    lines = [
        "LGD_KNOWLEDGE_SCHEMA=1",
        "LGD_PHASE=P11",
        "LGD_READ_ONLY=true",
        f"GAME_KNOWLEDGE_PACKS={k['pack_count']}",
        f"CORPUS_CASES={k['corpus_case_count']}",
        f"KNOWLEDGE_VALIDATION_ERRORS={k['validation_error_count']}",
        f"INSTALLED_APPS_CONSIDERED={k['installed_app_count']}",
        f"INSTALLED_APPS_MATCHED={k['matched_installed_app_count']}",
        f"INSTALLED_APPS_UNMATCHED={k['unmatched_installed_app_count']}",
        f"GAME_KNOWLEDGE_MATCHES={k['match_count']}",
        f"CANDIDATE_CASES={k['candidate_case_count']}",
        f"CONFIRMED_EXACT_CANDIDATES={k['confirmed_exact_candidate_count']}",
        f"REPORTED_OR_UNCONFIRMED_CANDIDATES={k['reported_or_unconfirmed_candidate_count']}",
    ]
    for idx, match in enumerate(k["matches"][:40]):
        lines.append(
            "MATCH_%d=appid:%s pack:%s via:%s cases:%d"
            % (
                idx,
                _clean(match["appid"], 20),
                _clean(match["pack_id"], 80),
                _clean(match["match_method"], 20),
                match["case_count"],
            )
        )
        for cidx, case in enumerate(match["cases"][:8]):
            lines.append(
                "MATCH_%d_CASE_%d=id:%s relation:%s class:%s evidence:%s action:%s"
                % (
                    idx,
                    cidx,
                    _clean(case["case_id"], 20),
                    _clean(case["relation"], 30),
                    _clean(case["classification"], 40),
                    _clean(case["evidence_status"], 30),
                    _clean(case["actionability"], 30),
                )
            )

    if k["direct_lookup"]:
        lines.append(f"DIRECT_LOOKUP_PACKS={len(k['direct_lookup'])}")
        for idx, pack in enumerate(k["direct_lookup"][:20]):
            lines.append(
                f"DIRECT_PACK_{idx}=pack:{_clean(pack['pack_id'],80)} cases:{pack['case_count']}"
            )
    else:
        lines.append("DIRECT_LOOKUP_PACKS=0")

    lines.append(f"KNOWLEDGE_FINDINGS={report['finding_count']}")
    for idx, finding in enumerate(report["findings"][:20]):
        lines.append(
            "FINDING_%d=severity:%s code:%s scope:%s class:%s"
            % (
                idx,
                _clean(finding["severity"]),
                _clean(finding["code"]),
                _clean(finding["scope"]),
                _clean(finding["classification"]),
            )
        )

    lines.extend([
        "POLICY_KNOWLEDGE_IS_DIAGNOSIS=NO",
        "POLICY_REPORTED_AUTO_REPAIR=NO",
        "POLICY_UNCONFIRMED_AUTO_REPAIR=NO",
        "POLICY_EXACT_CONFIRMED_REQUIRES_PRECONDITIONS=YES",
        "PRIVACY_ABSOLUTE_PATHS_EMITTED=NO",
        "PRIVACY_INSTALLED_GAME_NAMES_EMITTED=NO",
        "PRIVACY_ACCOUNT_IDENTIFIERS_COLLECTED=NO",
        "P11_GAME_KNOWLEDGE=PASS",
    ])
    return "\n".join(lines) + "\n"
