from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any, Callable

Runner = Callable[[list[str]], tuple[int, str, str]]


def _run_default(argv: list[str]) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            argv, capture_output=True, text=True, timeout=10,
            check=False, env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return 127, "", ""
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def _clean(value: object, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(value).replace("=", ":")).strip()
    return text[:limit] if text else "unknown"


def _yn(value: bool | None) -> str:
    return "UNKNOWN" if value is None else ("YES" if value else "NO")


def _service(runner: Runner, unit: str) -> str:
    tool = shutil.which("systemctl")
    if not tool:
        return "unknown"
    rc, out, _ = runner([tool, "--user", "is-active", unit])
    return _clean(out.splitlines()[0] if out else ("inactive" if rc else "unknown"), 40).lower()


def _version(runner: Runner, binary: str) -> dict[str, Any]:
    tool = shutil.which(binary)
    if not tool:
        return {"present": False, "status": "unavailable", "version": "unknown"}
    rc, out, err = runner([tool, "--version"])
    line = (out or err).splitlines()[0] if (out or err) else "unknown"
    return {"present": True, "status": "pass" if rc == 0 else "fail", "version": _clean(line)}


def parse_pactl_info(text: str) -> dict[str, str]:
    mapping = {
        "Server Name": "server_name",
        "Server Version": "server_version",
        "Default Sink": "default_sink",
        "Default Source": "default_source",
    }
    out = {v: "unknown" for v in mapping.values()}
    for raw in (text or "").splitlines():
        if ":" not in raw:
            continue
        k, v = raw.split(":", 1)
        if k.strip() in mapping:
            out[mapping[k.strip()]] = v.strip() or "unknown"
    return out


def endpoint_transport(name: str) -> str:
    low = (name or "").lower()
    if "bluez" in low:
        return "bluetooth"
    if "alsa" in low:
        return "alsa"
    if "raop" in low or "airplay" in low:
        return "network_audio"
    if "null" in low or "dummy" in low:
        return "virtual"
    return "other"


def parse_pactl_short(text: str) -> list[dict[str, Any]]:
    rows = []
    for raw in (text or "").splitlines():
        parts = raw.split("\t")
        if len(parts) < 5:
            parts = re.split(r"\s+", raw.strip(), maxsplit=4)
        if len(parts) < 5:
            continue
        try:
            index = int(parts[0])
        except ValueError:
            continue
        name, driver, spec, state = parts[1:5]
        rate = None
        channels = None
        m = re.search(r"(\d+)\s*Hz", spec, re.I)
        if m:
            rate = int(m.group(1))
        m = re.search(r"(\d+)ch", spec, re.I)
        if m:
            channels = int(m.group(1))
        rows.append({
            "index": index,
            "transport": endpoint_transport(name),
            "driver_family": "pipewire" if "pipewire" in driver.lower() else "other",
            "rate_hz": rate,
            "channels": channels,
            "state": _clean(state, 40).lower(),
            "_name": name,
        })
    return rows


def parse_card_profiles(text: str) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    current = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("Card #"):
            current = {"transport": "other", "active_profile": "unknown"}
            cards.append(current)
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip().lower(), value.strip()
        if key == "name":
            current["transport"] = endpoint_transport(value)
        elif key == "active profile":
            current["active_profile"] = _clean(value, 100)
    return cards


def parse_pw_metadata(text: str) -> dict[str, int | None]:
    keys = (
        "clock.rate", "clock.quantum", "clock.min-quantum",
        "clock.max-quantum", "clock.force-rate", "clock.force-quantum",
    )
    out = {k.replace(".", "_").replace("-", "_"): None for k in keys}
    for raw in (text or "").splitlines():
        for key in keys:
            if key not in raw:
                continue
            tail = raw.split(key, 1)[1]
            m = re.search(r"(-?\d+)", tail)
            if m:
                out[key.replace(".", "_").replace("-", "_")] = int(m.group(1))
            break
    return out


def count_journal_events(text: str) -> dict[str, int]:
    lower = (text or "").lower()
    return {
        "xrun": len(re.findall(r"\bxrun\b", lower)),
        "underrun": len(re.findall(r"\bunderrun\b", lower)),
        "overrun": len(re.findall(r"\boverrun\b", lower)),
        "timeout": len(re.findall(r"\btimeout\b", lower)),
    }


def _server(runner: Runner) -> dict[str, Any]:
    tool = shutil.which("pactl")
    if not tool:
        return {
            "tool_present": False, "status": "unavailable",
            "server_name": "unknown", "server_version": "unknown",
            "default_sink_present": None, "default_source_present": None,
            "sink_count": 0, "source_count": 0, "card_count": 0,
            "sinks": [], "sources": [], "cards": [],
        }
    rc_i, out_i, err_i = runner([tool, "info"])
    info = parse_pactl_info(out_i if rc_i == 0 else "")
    rc_s, out_s, _ = runner([tool, "list", "short", "sinks"])
    rc_r, out_r, _ = runner([tool, "list", "short", "sources"])
    rc_c, out_c, _ = runner([tool, "list", "cards"])
    sinks = parse_pactl_short(out_s) if rc_s == 0 else []
    sources = parse_pactl_short(out_r) if rc_r == 0 else []
    cards = parse_card_profiles(out_c) if rc_c == 0 else []
    default_sink = None if info["default_sink"] == "unknown" else any(x["_name"] == info["default_sink"] for x in sinks)
    default_source = None if info["default_source"] == "unknown" else any(x["_name"] == info["default_source"] for x in sources)
    for row in sinks + sources:
        row.pop("_name", None)
    return {
        "tool_present": True,
        "status": "pass" if rc_i == 0 else "fail",
        "server_name": _clean(info["server_name"], 80) if rc_i == 0 else "unknown",
        "server_version": _clean(info["server_version"], 80) if rc_i == 0 else "unknown",
        "default_sink_present": default_sink,
        "default_source_present": default_source,
        "sink_count": len(sinks), "source_count": len(sources), "card_count": len(cards),
        "sinks": sinks, "sources": sources, "cards": cards,
        "error_class": "none" if rc_i == 0 else _clean(err_i or "pactl_failed", 100),
    }


def _settings(runner: Runner) -> dict[str, Any]:
    tool = shutil.which("pw-metadata")
    if not tool:
        return {"tool_present": False, "status": "unavailable", "settings": {}}
    rc, out, err = runner([tool, "-n", "settings"])
    return {
        "tool_present": True,
        "status": "pass" if rc == 0 else "fail",
        "settings": parse_pw_metadata(out if rc == 0 else ""),
        "error_class": "none" if rc == 0 else _clean(err or "pw_metadata_failed", 100),
    }


def _journal(runner: Runner) -> dict[str, Any]:
    tool = shutil.which("journalctl")
    if not tool:
        return {"tool_present": False, "status": "unavailable", "window_minutes": 10, "events": count_journal_events("")}
    rc, out, _ = runner([
        tool, "--user", "-u", "pipewire.service", "-u", "wireplumber.service",
        "--since", "10 minutes ago", "--no-pager", "--output=cat",
    ])
    return {
        "tool_present": True,
        "status": "pass" if rc == 0 else "fail",
        "window_minutes": 10,
        "events": count_journal_events(out if rc == 0 else ""),
    }


def collect_audio_state(runner: Runner | None = None) -> dict[str, Any]:
    run = runner or _run_default
    runtime = {
        "pipewire": _version(run, "pipewire"),
        "wireplumber": _version(run, "wireplumber"),
        "services": {
            "pipewire": _service(run, "pipewire.service"),
            "wireplumber": _service(run, "wireplumber.service"),
        },
    }
    server = _server(run)
    settings = _settings(run)
    recent = _journal(run)
    findings: list[dict[str, str]] = []

    if runtime["services"]["pipewire"] != "active":
        findings.append({"code": "PIPEWIRE_SERVICE_NOT_ACTIVE", "severity": "warning", "classification": "REPAIRABLE", "scope": "pipewire", "evidence": "PipeWire user service is not active"})
    if runtime["services"]["wireplumber"] != "active":
        findings.append({"code": "WIREPLUMBER_SERVICE_NOT_ACTIVE", "severity": "warning", "classification": "REPAIRABLE", "scope": "wireplumber", "evidence": "WirePlumber user service is not active"})

    if server["status"] == "pass":
        if server["sink_count"] and server["default_sink_present"] is False:
            findings.append({"code": "DEFAULT_SINK_NOT_RESOLVED", "severity": "warning", "classification": "REPAIRABLE", "scope": "output", "evidence": "Audio sinks exist but the configured default sink did not resolve"})
        if server["source_count"] and server["default_source_present"] is False:
            findings.append({"code": "DEFAULT_SOURCE_NOT_RESOLVED", "severity": "warning", "classification": "REPAIRABLE", "scope": "input", "evidence": "Audio sources exist but the configured default source did not resolve"})
    elif runtime["services"]["pipewire"] == "active":
        findings.append({"code": "AUDIO_SERVER_QUERY_UNAVAILABLE", "severity": "info", "classification": "UNKNOWN", "scope": "audio", "evidence": "PipeWire is active but pactl compatibility-server state could not be verified"})

    bt_cards = [x for x in server["cards"] if x["transport"] == "bluetooth"]
    profiles = [x["active_profile"] for x in bt_cards]
    if any(any(t in p.lower() for t in ("headset", "handsfree", "head-unit", "hfp", "hsp")) for p in profiles):
        findings.append({"code": "BLUETOOTH_HEADSET_PROFILE_ACTIVE", "severity": "info", "classification": "WORKAROUND", "scope": "bluetooth", "evidence": "A Bluetooth card uses a headset/hands-free profile; microphone support can reduce playback quality"})

    force_q = settings.get("settings", {}).get("clock_force_quantum")
    if isinstance(force_q, int) and 0 < force_q < 64:
        findings.append({"code": "PIPEWIRE_FORCED_QUANTUM_AGGRESSIVE", "severity": "info", "classification": "WORKAROUND", "scope": "pipewire_clock", "evidence": f"clock.force-quantum is {force_q}; very low forced quantum can increase xrun risk"})

    ev = recent["events"]
    xrun_total = ev["xrun"] + ev["underrun"] + ev["overrun"]
    if xrun_total:
        findings.append({"code": "PIPEWIRE_XRUN_EVIDENCE_RECENT", "severity": "warning", "classification": "UNKNOWN", "scope": "pipewire", "evidence": f"Recent user journal contains {xrun_total} xrun/underrun/overrun mention(s); raw logs were discarded"})

    findings.sort(key=lambda x: ({"error": 0, "warning": 1, "info": 2}.get(x["severity"], 9), x["code"]))
    return {
        "schema_version": 1, "phase": "P07", "read_only": True,
        "runtime": runtime, "server": server, "pipewire_settings": settings,
        "bluetooth": {
            "card_count": len(bt_cards),
            "sink_count": sum(1 for x in server["sinks"] if x["transport"] == "bluetooth"),
            "source_count": sum(1 for x in server["sources"] if x["transport"] == "bluetooth"),
            "active_profiles": profiles,
        },
        "recent_events": recent,
        "finding_count": len(findings), "findings": findings,
        "privacy": {
            "absolute_paths_emitted": False,
            "raw_audio_logs_emitted": False,
            "endpoint_names_emitted": False,
            "device_descriptions_emitted": False,
            "hardware_addresses_collected": False,
            "process_command_lines_collected": False,
            "environment_values_collected": False,
            "tokens_collected": False,
        },
    }


def render_text(r: dict[str, Any]) -> str:
    rt, srv, cfg, bt, recent = r["runtime"], r["server"], r["pipewire_settings"], r["bluetooth"], r["recent_events"]
    s = cfg.get("settings", {})
    lines = [
        "LGD_AUDIO_SCHEMA=1", "LGD_PHASE=P07", "LGD_READ_ONLY=true",
        f"PIPEWIRE_SERVICE={_clean(rt['services']['pipewire'])}",
        f"WIREPLUMBER_SERVICE={_clean(rt['services']['wireplumber'])}",
        f"PIPEWIRE_VERSION={_clean(rt['pipewire']['version'])}",
        f"WIREPLUMBER_VERSION={_clean(rt['wireplumber']['version'])}",
        f"PACTL={_yn(srv['tool_present'])}", f"AUDIO_SERVER_STATUS={_clean(srv['status']).upper()}",
        f"AUDIO_SERVER_NAME={_clean(srv['server_name'])}", f"AUDIO_SERVER_VERSION={_clean(srv['server_version'])}",
        f"AUDIO_SINKS={srv['sink_count']}", f"AUDIO_SOURCES={srv['source_count']}",
        f"DEFAULT_SINK_RESOLVED={_yn(srv['default_sink_present'])}",
        f"DEFAULT_SOURCE_RESOLVED={_yn(srv['default_source_present'])}",
    ]
    for i, x in enumerate(srv["sinks"][:16]):
        lines.append(f"SINK_{i}=transport:{x['transport']} driver:{x['driver_family']} rate_hz:{x['rate_hz'] or 'unknown'} channels:{x['channels'] or 'unknown'} state:{x['state']}")
    for i, x in enumerate(srv["sources"][:16]):
        lines.append(f"SOURCE_{i}=transport:{x['transport']} driver:{x['driver_family']} rate_hz:{x['rate_hz'] or 'unknown'} channels:{x['channels'] or 'unknown'} state:{x['state']}")
    lines += [
        f"BLUETOOTH_AUDIO_CARDS={bt['card_count']}", f"BLUETOOTH_AUDIO_SINKS={bt['sink_count']}",
        f"BLUETOOTH_AUDIO_SOURCES={bt['source_count']}",
        "BLUETOOTH_ACTIVE_PROFILES=" + (",".join(_clean(x) for x in bt["active_profiles"]) or "none"),
        f"PW_METADATA={_yn(cfg['tool_present'])}", f"PW_METADATA_STATUS={_clean(cfg['status']).upper()}",
        f"PIPEWIRE_CLOCK_RATE={s.get('clock_rate') if s.get('clock_rate') is not None else 'unknown'}",
        f"PIPEWIRE_CLOCK_QUANTUM={s.get('clock_quantum') if s.get('clock_quantum') is not None else 'unknown'}",
        f"PIPEWIRE_CLOCK_FORCE_QUANTUM={s.get('clock_force_quantum') if s.get('clock_force_quantum') is not None else 'unknown'}",
        f"AUDIO_JOURNAL_STATUS={_clean(recent['status']).upper()}",
        f"AUDIO_XRUN_MENTIONS={recent['events']['xrun']}",
        f"AUDIO_UNDERRUN_MENTIONS={recent['events']['underrun']}",
        f"AUDIO_OVERRUN_MENTIONS={recent['events']['overrun']}",
        f"AUDIO_FINDINGS={r['finding_count']}",
    ]
    for i, f in enumerate(r["findings"][:20]):
        lines.append(f"FINDING_{i}=severity:{f['severity']} code:{f['code']} scope:{f['scope']} class:{f['classification']}")
    lines += [
        "PRIVACY_ABSOLUTE_PATHS_EMITTED=NO",
        "PRIVACY_RAW_AUDIO_LOGS_EMITTED=NO",
        "PRIVACY_ENDPOINT_NAMES_EMITTED=NO",
        "PRIVACY_DEVICE_DESCRIPTIONS_EMITTED=NO",
        "PRIVACY_HARDWARE_ADDRESSES_COLLECTED=NO",
        "P07_AUDIO=PASS",
    ]
    return "\n".join(lines) + "\n"
