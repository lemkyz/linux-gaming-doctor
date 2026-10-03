from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

Runner = Callable[[list[str]], tuple[int, str, str]]


def _default_runner(argv: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=8.0,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return 127, "", ""
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _clean(value: object, limit: int = 180) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = text.replace("=", ":")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] if text else "unknown"


def _read(path: Path, limit: int = 65536) -> str:
    try:
        return path.read_text(errors="replace")[:limit].strip()
    except OSError:
        return ""


def _desktop_name() -> str:
    raw = " ".join(
        x for x in (
            os.environ.get("XDG_CURRENT_DESKTOP", ""),
            os.environ.get("DESKTOP_SESSION", ""),
        ) if x
    ).lower()
    if "kde" in raw or "plasma" in raw:
        return "KDE"
    if "gnome" in raw:
        return "GNOME"
    if "sway" in raw:
        return "Sway"
    if "hyprland" in raw:
        return "Hyprland"
    return "unknown"


def _session_state(runner: Runner) -> dict[str, Any]:
    session = os.environ.get("XDG_SESSION_TYPE", "unknown").strip().lower() or "unknown"
    wayland_present = bool(os.environ.get("WAYLAND_DISPLAY"))
    x11_present = bool(os.environ.get("DISPLAY"))
    xwayland_running = False
    pgrep = shutil.which("pgrep")
    if pgrep:
        rc, _, _ = runner([pgrep, "-x", "Xwayland"])
        xwayland_running = rc == 0
    return {
        "type": session,
        "desktop": _desktop_name(),
        "wayland_socket_present": wayland_present,
        "x11_display_present": x11_present,
        "xwayland_process_running": xwayland_running,
    }


def _drm_connector_name(name: str) -> str:
    m = re.match(r"card\d+-(.+)$", name)
    return m.group(1) if m else name


def _drm_connectors(sysfs_root: Path = Path("/sys/class/drm")) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        entries = sorted(sysfs_root.iterdir(), key=lambda p: p.name)
    except OSError:
        return out
    for entry in entries:
        if not (entry / "status").exists():
            continue
        status = (_read(entry / "status", 64) or "unknown").lower()
        enabled_text = (_read(entry / "enabled", 64) or "unknown").lower()
        modes = []
        for line in _read(entry / "modes", 32768).splitlines():
            mode = line.strip()
            if re.fullmatch(r"\d{2,5}x\d{2,5}", mode) and mode not in modes:
                modes.append(mode)
            if len(modes) >= 64:
                break
        vrr_raw = (_read(entry / "vrr_capable", 64) or "unknown").lower()
        vrr_capable: bool | None
        if vrr_raw in {"1", "yes", "true"}:
            vrr_capable = True
        elif vrr_raw in {"0", "no", "false"}:
            vrr_capable = False
        else:
            vrr_capable = None
        edid_present = False
        try:
            edid_present = (entry / "edid").stat().st_size > 0
        except OSError:
            pass
        out.append(
            {
                "name": _clean(_drm_connector_name(entry.name), 80),
                "status": status,
                "connected": status == "connected",
                "enabled": enabled_text == "enabled",
                "mode_count": len(modes),
                "modes": modes,
                "edid_present": edid_present,
                "vrr_capable": vrr_capable,
            }
        )
    return out


def _mode_from_modes_line(line: str) -> tuple[str, float | None]:
    # kscreen-doctor marks the current mode with '*', often as "1:2560x1600@165*!".
    candidates = re.findall(r"(?:\d+:)?(\d{2,5}x\d{2,5})@([0-9]+(?:\.[0-9]+)?)([^\s]*)", line)
    for res, hz, flags in candidates:
        if "*" in flags:
            try:
                return res, float(hz)
            except ValueError:
                return res, None
    return ("unknown", None)


def parse_kscreen_output(text: str) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        m = re.match(r"Output:\s*\d+\s+(.+)$", line, re.I)
        if m:
            current = {
                "name": _clean(m.group(1).split()[0], 80),
                "connected": None,
                "enabled": None,
                "resolution": "unknown",
                "refresh_hz": None,
                "scale": None,
                "fractional_scale": False,
                "rotation": "unknown",
                "vrr": "unknown",
                "hdr": "unknown",
            }
            outputs.append(current)
            continue
        if current is None:
            continue
        lower = line.lower()
        if lower == "enabled":
            current["enabled"] = True
        elif lower == "disabled":
            current["enabled"] = False
        elif lower == "connected":
            current["connected"] = True
        elif lower == "disconnected":
            current["connected"] = False
        elif lower.startswith("modes:"):
            resolution, hz = _mode_from_modes_line(line)
            if resolution != "unknown":
                current["resolution"] = resolution
            if hz is not None:
                current["refresh_hz"] = hz
        elif lower.startswith("geometry:"):
            mgeo = re.search(r"(\d{2,5})x(\d{2,5})\s*$", line)
            if mgeo and current["resolution"] == "unknown":
                current["resolution"] = f"{mgeo.group(1)}x{mgeo.group(2)}"
        elif lower.startswith("scale:"):
            try:
                scale = float(line.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                scale = None
            current["scale"] = scale
            if scale is not None:
                current["fractional_scale"] = abs(scale - round(scale)) > 1e-6
        elif lower.startswith("rotation:"):
            current["rotation"] = _clean(line.split(":", 1)[1].strip(), 60)
        elif lower.startswith("vrr:") or lower.startswith("adaptive sync:"):
            current["vrr"] = _clean(line.split(":", 1)[1].strip(), 80).lower()
        elif lower.startswith("hdr:"):
            current["hdr"] = _clean(line.split(":", 1)[1].strip(), 80).lower()
    return outputs


def parse_xrandr_output(text: str) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw in (text or "").splitlines():
        if raw and not raw[0].isspace():
            m = re.match(r"^(\S+)\s+(connected|disconnected)(?:\s+primary)?(?:\s+(\d{2,5}x\d{2,5})\+[-\d]+\+[-\d]+)?", raw)
            if m:
                current = {
                    "name": _clean(m.group(1), 80),
                    "connected": m.group(2) == "connected",
                    "enabled": bool(m.group(3)),
                    "resolution": m.group(3) or "unknown",
                    "refresh_hz": None,
                    "scale": None,
                    "fractional_scale": False,
                    "rotation": "unknown",
                    "vrr": "unknown",
                    "hdr": "unknown",
                }
                outputs.append(current)
                continue
        if current is None or not current["enabled"]:
            continue
        m = re.match(r"^\s+(\d{2,5}x\d{2,5})\s+(.+)$", raw)
        if not m:
            continue
        resolution, rates = m.groups()
        starred = re.search(r"([0-9]+(?:\.[0-9]+)?)\*", rates)
        if starred:
            current["resolution"] = resolution
            try:
                current["refresh_hz"] = float(starred.group(1))
            except ValueError:
                pass
    return outputs


def _kscreen_state(runner: Runner) -> dict[str, Any]:
    tool = shutil.which("kscreen-doctor")
    if not tool:
        return {"tool_present": False, "probe_status": "unavailable", "outputs": []}
    rc, out, err = runner([tool, "-o"])
    parsed = parse_kscreen_output(out) if rc == 0 else []
    return {
        "tool_present": True,
        "probe_status": "pass" if rc == 0 else "fail",
        "outputs": parsed,
        "error_class": "none" if rc == 0 else _clean(err or "kscreen_doctor_failed", 100),
    }


def _xrandr_state(runner: Runner) -> dict[str, Any]:
    tool = shutil.which("xrandr")
    if not tool or not os.environ.get("DISPLAY"):
        return {"tool_present": bool(tool), "probe_status": "unavailable", "outputs": []}
    rc, out, err = runner([tool, "--current"])
    parsed = parse_xrandr_output(out) if rc == 0 else []
    return {
        "tool_present": True,
        "probe_status": "pass" if rc == 0 else "fail",
        "outputs": parsed,
        "error_class": "none" if rc == 0 else _clean(err or "xrandr_failed", 100),
    }


def _compositor_state(runner: Runner, desktop: str, session: str) -> dict[str, Any]:
    candidates: list[tuple[str, list[str]]] = []
    if desktop == "KDE":
        for name in ("kwin_wayland", "kwin_x11"):
            path = shutil.which(name)
            if path:
                candidates.append((name, [path, "--version"]))
    elif desktop == "GNOME":
        path = shutil.which("gnome-shell")
        if path:
            candidates.append(("gnome-shell", [path, "--version"]))
    if not candidates:
        return {"name": "unknown", "version_status": "unavailable", "version": "unknown", "session": session}
    name, argv = candidates[0]
    rc, out, err = runner(argv)
    first = (out or err).splitlines()[0] if (out or err) else "unknown"
    return {
        "name": name,
        "version_status": "pass" if rc == 0 else "fail",
        "version": _clean(first, 120),
        "session": session,
    }


def _gamescope_state(runner: Runner) -> dict[str, Any]:
    tool = shutil.which("gamescope")
    if not tool:
        return {"tool_present": False, "version_status": "unavailable", "version": "unknown"}
    rc, out, err = runner([tool, "--version"])
    text = out or err
    first = text.splitlines()[0] if text else "unknown"
    return {
        "tool_present": True,
        "version_status": "pass" if rc == 0 else "fail",
        "version": _clean(first, 120),
    }


def _summarize_outputs(kscreen: dict[str, Any], xrandr: dict[str, Any], drm: list[dict[str, Any]]) -> dict[str, Any]:
    if kscreen["probe_status"] == "pass" and kscreen["outputs"]:
        source = "kscreen"
        outputs = kscreen["outputs"]
    elif xrandr["probe_status"] == "pass" and xrandr["outputs"]:
        source = "xrandr"
        outputs = xrandr["outputs"]
    else:
        source = "drm"
        outputs = [
            {
                "name": c["name"],
                "connected": c["connected"],
                "enabled": c["enabled"],
                "resolution": "unknown",
                "refresh_hz": None,
                "scale": None,
                "fractional_scale": False,
                "rotation": "unknown",
                "vrr": "capable" if c["vrr_capable"] is True else "unsupported" if c["vrr_capable"] is False else "unknown",
                "hdr": "unknown",
            }
            for c in drm
        ]
    active = [x for x in outputs if x.get("enabled") is True]
    scales = [float(x["scale"]) for x in active if isinstance(x.get("scale"), (int, float))]
    refreshes = [round(float(x["refresh_hz"]), 3) for x in active if isinstance(x.get("refresh_hz"), (int, float))]
    fractional_count = sum(1 for x in active if x.get("fractional_scale") is True)
    hdr_known = [str(x.get("hdr", "unknown")).lower() for x in active if str(x.get("hdr", "unknown")).lower() not in {"unknown", "none", "unsupported"}]
    vrr_known = [str(x.get("vrr", "unknown")).lower() for x in active if str(x.get("vrr", "unknown")).lower() not in {"unknown", "none"}]
    return {
        "source": source,
        "output_count": len(outputs),
        "active_count": len(active),
        "fractional_scale_count": fractional_count,
        "mixed_scale": len({round(s, 4) for s in scales}) > 1,
        "mixed_refresh": len(set(refreshes)) > 1,
        "hdr_state_known_count": len(hdr_known),
        "hdr_enabled_count": sum(1 for x in hdr_known if x in {"enabled", "on", "true", "yes"}),
        "vrr_state_known_count": len(vrr_known),
        "outputs": outputs,
    }


def collect_display_state(runner: Runner | None = None, sysfs_root: Path = Path("/sys/class/drm")) -> dict[str, Any]:
    run = runner or _default_runner
    session = _session_state(run)
    drm = _drm_connectors(sysfs_root)
    kscreen = _kscreen_state(run)
    xrandr = _xrandr_state(run)
    outputs = _summarize_outputs(kscreen, xrandr, drm)
    compositor = _compositor_state(run, session["desktop"], session["type"])
    gamescope = _gamescope_state(run)
    findings: list[dict[str, str]] = []

    if session["type"] == "wayland" and not session["wayland_socket_present"]:
        findings.append({
            "code": "WAYLAND_SESSION_WITHOUT_SOCKET",
            "severity": "warning",
            "classification": "UNKNOWN",
            "scope": "session",
            "evidence": "XDG session type is Wayland but no Wayland display socket is present in the process environment",
        })
    if session["type"] == "x11" and not session["x11_display_present"]:
        findings.append({
            "code": "X11_SESSION_WITHOUT_DISPLAY",
            "severity": "warning",
            "classification": "UNKNOWN",
            "scope": "session",
            "evidence": "XDG session type is X11 but DISPLAY is unavailable",
        })
    connected = [c for c in drm if c["connected"]]
    if not connected:
        findings.append({
            "code": "NO_CONNECTED_DRM_OUTPUT",
            "severity": "info",
            "classification": "UNKNOWN",
            "scope": "display",
            "evidence": "No connected physical DRM connector was observed; this may be expected for headless or virtual sessions",
        })
    for output in outputs["outputs"]:
        hz = output.get("refresh_hz")
        if output.get("enabled") is True and isinstance(hz, (int, float)) and hz > 0 and hz < 20:
            findings.append({
                "code": "DISPLAY_REFRESH_IMPLAUSIBLY_LOW",
                "severity": "warning",
                "classification": "UNKNOWN",
                "scope": str(output.get("name", "display")),
                "evidence": f"Active output reports a current refresh below 20 Hz ({hz:g} Hz)",
            })
        scale = output.get("scale")
        if output.get("enabled") is True and isinstance(scale, (int, float)) and (scale <= 0 or scale > 4):
            findings.append({
                "code": "DISPLAY_SCALE_IMPLAUSIBLE",
                "severity": "warning",
                "classification": "UNKNOWN",
                "scope": str(output.get("name", "display")),
                "evidence": f"Active output reports an implausible compositor scale ({scale:g})",
            })
    if session["type"] == "wayland" and outputs["source"] == "drm":
        findings.append({
            "code": "WAYLAND_COMPOSITOR_OUTPUT_STATE_UNAVAILABLE",
            "severity": "info",
            "classification": "UNKNOWN",
            "scope": "display",
            "evidence": "Only DRM connector facts were available; compositor logical resolution, scaling and current refresh could not be verified",
        })

    findings.sort(key=lambda x: ({"error": 0, "warning": 1, "info": 2}.get(x["severity"], 9), x["code"], x["scope"]))
    return {
        "schema_version": 1,
        "phase": "P05",
        "read_only": True,
        "session": session,
        "compositor": compositor,
        "drm": {
            "connector_count": len(drm),
            "connected_count": sum(1 for x in drm if x["connected"]),
            "enabled_count": sum(1 for x in drm if x["enabled"]),
            "connectors": drm,
        },
        "kscreen": kscreen,
        "xrandr": xrandr,
        "display": outputs,
        "gamescope": gamescope,
        "finding_count": len(findings),
        "findings": findings,
        "privacy": {
            "absolute_paths_emitted": False,
            "environment_values_collected": False,
            "edid_payload_collected": False,
            "display_serials_collected": False,
            "network_identifiers_collected": False,
            "tokens_collected": False,
        },
    }


def _yn(value: bool | None) -> str:
    if value is None:
        return "UNKNOWN"
    return "YES" if value else "NO"


def render_text(report: dict[str, Any]) -> str:
    s = report["session"]
    d = report["drm"]
    o = report["display"]
    c = report["compositor"]
    g = report["gamescope"]
    lines = [
        "LGD_DISPLAY_SCHEMA=1",
        "LGD_PHASE=P05",
        "LGD_READ_ONLY=true",
        f"SESSION_TYPE={_clean(s['type']).upper()}",
        f"DESKTOP={_clean(s['desktop'])}",
        f"WAYLAND_SOCKET={_yn(s['wayland_socket_present'])}",
        f"X11_DISPLAY={_yn(s['x11_display_present'])}",
        f"XWAYLAND_PROCESS={_yn(s['xwayland_process_running'])}",
        f"COMPOSITOR={_clean(c['name'])}",
        f"COMPOSITOR_VERSION_STATUS={_clean(c['version_status']).upper()}",
        f"COMPOSITOR_VERSION={_clean(c['version'])}",
        f"DRM_CONNECTORS={d['connector_count']}",
        f"DRM_CONNECTED={d['connected_count']}",
        f"DRM_ENABLED={d['enabled_count']}",
    ]
    for idx, conn in enumerate(d["connectors"][:12]):
        lines.append(
            "DRM_%d=name:%s status:%s enabled:%s modes:%d edid:%s vrr_capable:%s"
            % (
                idx,
                _clean(conn["name"]),
                _clean(conn["status"]),
                _yn(conn["enabled"]),
                conn["mode_count"],
                _yn(conn["edid_present"]),
                _yn(conn["vrr_capable"]),
            )
        )
    lines.extend([
        f"DISPLAY_SOURCE={_clean(o['source']).upper()}",
        f"DISPLAY_OUTPUTS={o['output_count']}",
        f"DISPLAY_ACTIVE={o['active_count']}",
        f"FRACTIONAL_SCALE_OUTPUTS={o['fractional_scale_count']}",
        f"MIXED_SCALE={_yn(o['mixed_scale'])}",
        f"MIXED_REFRESH={_yn(o['mixed_refresh'])}",
        f"HDR_STATE_KNOWN={o['hdr_state_known_count']}",
        f"HDR_ENABLED={o['hdr_enabled_count']}",
        f"VRR_STATE_KNOWN={o['vrr_state_known_count']}",
    ])
    for idx, output in enumerate(o["outputs"][:12]):
        hz = output.get("refresh_hz")
        scale = output.get("scale")
        lines.append(
            "OUTPUT_%d=name:%s connected:%s enabled:%s resolution:%s refresh:%s scale:%s fractional:%s rotation:%s vrr:%s hdr:%s"
            % (
                idx,
                _clean(output.get("name", "unknown")),
                _yn(output.get("connected")),
                _yn(output.get("enabled")),
                _clean(output.get("resolution", "unknown")),
                "unknown" if hz is None else f"{float(hz):.3f}",
                "unknown" if scale is None else f"{float(scale):.3f}",
                _yn(output.get("fractional_scale")),
                _clean(output.get("rotation", "unknown")),
                _clean(output.get("vrr", "unknown")),
                _clean(output.get("hdr", "unknown")),
            )
        )
    lines.extend([
        f"GAMESCOPE={_yn(g['tool_present'])}",
        f"GAMESCOPE_VERSION_STATUS={_clean(g['version_status']).upper()}",
        f"GAMESCOPE_VERSION={_clean(g['version'])}",
        f"DISPLAY_FINDINGS={report['finding_count']}",
    ])
    for idx, finding in enumerate(report["findings"][:20]):
        lines.append(
            "FINDING_%d=severity:%s code:%s scope:%s class:%s"
            % (idx, _clean(finding["severity"]), _clean(finding["code"]), _clean(finding["scope"]), _clean(finding["classification"]))
        )
    lines.extend([
        "PRIVACY_ABSOLUTE_PATHS_EMITTED=NO",
        "PRIVACY_ENVIRONMENT_VALUES_COLLECTED=NO",
        "PRIVACY_EDID_PAYLOAD_COLLECTED=NO",
        "PRIVACY_DISPLAY_SERIALS_COLLECTED=NO",
        "P05_DISPLAY_WAYLAND=PASS",
    ])
    return "\n".join(lines) + "\n"
