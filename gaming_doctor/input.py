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


def _read(path: Path, limit: int = 262144) -> str:
    try:
        return path.read_text(errors="replace")[:limit].strip()
    except OSError:
        return ""


def _clean(value: object, limit: int = 120) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = text.replace("=", ":")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] if text else "unknown"


def parse_proc_input_devices(text: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", text or ""):
        if not block.strip():
            continue
        identity = {"bus": "unknown", "vendor_id": "unknown", "product_id": "unknown", "version": "unknown"}
        handlers: list[str] = []
        for raw in block.splitlines():
            line = raw.strip()
            if line.startswith("I:"):
                for key, value in re.findall(r"(Bus|Vendor|Product|Version)=([0-9A-Fa-f]+)", line):
                    mapped = {"Bus": "bus", "Vendor": "vendor_id", "Product": "product_id", "Version": "version"}[key]
                    identity[mapped] = value.lower()
            elif line.startswith("H:") and "Handlers=" in line:
                handlers = line.split("Handlers=", 1)[1].split()
        if not handlers:
            continue
        event_nodes = [x for x in handlers if re.fullmatch(r"event\d+", x)]
        js_nodes = [x for x in handlers if re.fullmatch(r"js\d+", x)]
        classes: list[str] = []
        if js_nodes:
            classes.append("gamepad")
        if any(x == "kbd" for x in handlers):
            classes.append("keyboard")
        if any(x.startswith("mouse") for x in handlers):
            classes.append("mouse")
        if not classes:
            classes.append("other")
        devices.append({
            **identity,
            "event_nodes": event_nodes,
            "js_nodes": js_nodes,
            "classes": sorted(set(classes)),
        })
    return devices


def parse_udev_properties(text: str) -> dict[str, Any]:
    props: dict[str, str] = {}
    for raw in (text or "").splitlines():
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        props[key.strip()] = value.strip()
    classes: list[str] = []
    mapping = {
        "ID_INPUT_JOYSTICK": "gamepad",
        "ID_INPUT_GAMEPAD": "gamepad",
        "ID_INPUT_KEY": "keyboard",
        "ID_INPUT_KEYBOARD": "keyboard",
        "ID_INPUT_MOUSE": "mouse",
        "ID_INPUT_TOUCHPAD": "touchpad",
        "ID_INPUT_TOUCHSCREEN": "touchscreen",
    }
    for key, cls in mapping.items():
        if props.get(key) == "1":
            classes.append(cls)
    return {
        "classes": sorted(set(classes)),
        "bus": _clean(props.get("ID_BUS", "unknown"), 40).lower(),
        "vendor_id": _clean(props.get("ID_VENDOR_ID", "unknown"), 16).lower(),
        "model_id": _clean(props.get("ID_MODEL_ID", "unknown"), 16).lower(),
    }


def _udev_for_event(runner: Runner, event_name: str) -> dict[str, Any]:
    tool = shutil.which("udevadm")
    if not tool:
        return {"status": "unavailable", "classes": [], "bus": "unknown", "vendor_id": "unknown", "model_id": "unknown"}
    rc, out, _ = runner([tool, "info", "--query=property", f"--name=/dev/input/{event_name}"])
    if rc != 0:
        return {"status": "fail", "classes": [], "bus": "unknown", "vendor_id": "unknown", "model_id": "unknown"}
    parsed = parse_udev_properties(out)
    return {"status": "pass", **parsed}


def _node_access(path: Path) -> dict[str, Any]:
    return {
        "exists": path.exists(),
        "readable": os.access(path, os.R_OK) if path.exists() else False,
        "writable": os.access(path, os.W_OK) if path.exists() else False,
        "rw": os.access(path, os.R_OK | os.W_OK) if path.exists() else False,
    }


def _event_inventory(
    runner: Runner,
    proc_path: Path = Path("/proc/bus/input/devices"),
    dev_input: Path = Path("/dev/input"),
) -> list[dict[str, Any]]:
    proc_devices = parse_proc_input_devices(_read(proc_path))
    by_event: dict[str, dict[str, Any]] = {}
    for dev in proc_devices:
        for event in dev["event_nodes"]:
            by_event[event] = dev

    names: set[str] = set(by_event)
    try:
        names.update(p.name for p in dev_input.glob("event*") if re.fullmatch(r"event\d+", p.name))
    except OSError:
        pass

    out: list[dict[str, Any]] = []
    for event in sorted(names, key=lambda x: int(x.removeprefix("event")) if x.removeprefix("event").isdigit() else 999999):
        proc = by_event.get(event, {})
        udev = _udev_for_event(runner, event)
        classes = sorted(set(proc.get("classes", [])) | set(udev.get("classes", [])))
        if not classes:
            classes = ["other"]
        vendor = udev.get("vendor_id", "unknown")
        model = udev.get("model_id", "unknown")
        if vendor == "unknown":
            vendor = proc.get("vendor_id", "unknown")
        if model == "unknown":
            model = proc.get("product_id", "unknown")
        access = _node_access(dev_input / event)
        out.append({
            "event": event,
            "classes": classes,
            "bus": udev.get("bus", "unknown"),
            "vendor_id": _clean(vendor, 16),
            "model_id": _clean(model, 16),
            "exists": access["exists"],
            "readable": access["readable"],
            "writable": access["writable"],
            "rw": access["rw"],
            "udev_status": udev.get("status", "unavailable"),
        })
    return out


def _hidraw_state(root: Path = Path("/dev")) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    try:
        entries = sorted(root.glob("hidraw*"), key=lambda p: p.name)
    except OSError:
        entries = []
    for path in entries[:256]:
        if not re.fullmatch(r"hidraw\d+", path.name):
            continue
        access = _node_access(path)
        nodes.append({
            "node": path.name,
            "readable": access["readable"],
            "writable": access["writable"],
            "rw": access["rw"],
        })
    return {
        "count": len(nodes),
        "readable_count": sum(1 for x in nodes if x["readable"]),
        "rw_count": sum(1 for x in nodes if x["rw"]),
        "nodes": nodes,
    }


def _uinput_state(path: Path = Path("/dev/uinput")) -> dict[str, Any]:
    access = _node_access(path)
    module_loaded = Path("/sys/module/uinput").exists()
    return {
        "exists": access["exists"],
        "readable": access["readable"],
        "writable": access["writable"],
        "rw": access["rw"],
        "module_loaded": module_loaded,
    }


def _steam_rules_state() -> dict[str, Any]:
    roots = (
        Path("/usr/lib/udev/rules.d"),
        Path("/usr/local/lib/udev/rules.d"),
        Path("/etc/udev/rules.d"),
    )
    names: set[str] = set()
    for root in roots:
        try:
            for path in root.glob("*steam*.rules"):
                if path.is_file():
                    names.add(path.name)
        except OSError:
            continue
    return {
        "present": bool(names),
        "file_count": len(names),
        "files": sorted(_clean(x, 100) for x in names)[:32],
    }


def _udev_database_state(path: Path = Path("/run/udev/data")) -> dict[str, Any]:
    return {
        "exists": path.exists(),
        "readable": os.access(path, os.R_OK | os.X_OK) if path.exists() else False,
    }


def _device_scope_batteries(root: Path = Path("/sys/class/power_supply")) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError:
        return out
    for entry in entries:
        if _read(entry / "type", 64) != "Battery":
            continue
        if _read(entry / "scope", 64).lower() != "device":
            continue
        cap = _read(entry / "capacity", 64)
        try:
            capacity = int(cap)
        except ValueError:
            capacity = None
        out.append({
            "capacity_pct": capacity,
            "status": _clean(_read(entry / "status", 64) or "unknown", 40),
        })
    return out


def collect_input_state(runner: Runner | None = None) -> dict[str, Any]:
    run = runner or _default_runner
    events = _event_inventory(run)
    hidraw = _hidraw_state()
    uinput = _uinput_state()
    steam_rules = _steam_rules_state()
    udev_db = _udev_database_state()
    device_batteries = _device_scope_batteries()

    gamepads = [x for x in events if "gamepad" in x["classes"]]
    keyboards = [x for x in events if "keyboard" in x["classes"]]
    mice = [x for x in events if "mouse" in x["classes"]]
    bluetooth_gamepads = [x for x in gamepads if x["bus"] == "bluetooth"]
    findings: list[dict[str, str]] = []

    for event in gamepads:
        if event["exists"] and not event["readable"]:
            findings.append({
                "code": "GAMEPAD_EVENT_ACCESS_DENIED",
                "severity": "warning",
                "classification": "REPAIRABLE",
                "scope": event["event"],
                "evidence": "A discovered gamepad event node is not readable by the current user",
            })

    if gamepads and not uinput["exists"]:
        findings.append({
            "code": "UINPUT_DEVICE_MISSING",
            "severity": "info",
            "classification": "UNKNOWN",
            "scope": "uinput",
            "evidence": "A gamepad is present but /dev/uinput is missing; Steam Input virtual-device features may be limited",
        })
    elif gamepads and uinput["exists"] and not uinput["rw"]:
        findings.append({
            "code": "UINPUT_ACCESS_DENIED",
            "severity": "warning",
            "classification": "REPAIRABLE",
            "scope": "uinput",
            "evidence": "A gamepad is present but the current user lacks read/write access to /dev/uinput",
        })

    if gamepads and not steam_rules["present"]:
        findings.append({
            "code": "STEAM_INPUT_UDEV_RULES_NOT_FOUND",
            "severity": "info",
            "classification": "UNKNOWN",
            "scope": "udev",
            "evidence": "Gamepad input exists but no Steam-named udev rules file was discovered in standard host rule directories",
        })

    if gamepads and hidraw["count"] and hidraw["readable_count"] == 0:
        findings.append({
            "code": "HIDRAW_ACCESS_GAP_WITH_GAMEPAD",
            "severity": "info",
            "classification": "UNKNOWN",
            "scope": "hidraw",
            "evidence": "Gamepad input exists and hidraw devices exist, but none are readable by the current user",
        })

    if not udev_db["exists"] or not udev_db["readable"]:
        findings.append({
            "code": "UDEV_DATABASE_NOT_READABLE",
            "severity": "info",
            "classification": "UNKNOWN",
            "scope": "udev",
            "evidence": "/run/udev/data is unavailable to this process; sandboxed launcher input discovery can differ from the host",
        })

    for idx, battery in enumerate(device_batteries):
        cap = battery["capacity_pct"]
        if isinstance(cap, int) and cap <= 5:
            findings.append({
                "code": "DEVICE_SCOPE_BATTERY_CRITICAL",
                "severity": "info",
                "classification": "WORKAROUND",
                "scope": f"device_battery_{idx}",
                "evidence": f"A device-scope battery reports {cap}% capacity",
            })

    findings.sort(key=lambda x: ({"error": 0, "warning": 1, "info": 2}.get(x["severity"], 9), x["code"], x["scope"]))

    return {
        "schema_version": 1,
        "phase": "P08",
        "read_only": True,
        "events": {
            "count": len(events),
            "readable_count": sum(1 for x in events if x["readable"]),
            "rw_count": sum(1 for x in events if x["rw"]),
            "gamepad_count": len(gamepads),
            "keyboard_count": len(keyboards),
            "mouse_count": len(mice),
            "bluetooth_gamepad_count": len(bluetooth_gamepads),
            "devices": events,
        },
        "hidraw": hidraw,
        "uinput": uinput,
        "udev": {
            "tool_present": bool(shutil.which("udevadm")),
            "database": udev_db,
            "steam_input_rules": steam_rules,
        },
        "device_scope_batteries": {
            "count": len(device_batteries),
            "batteries": device_batteries,
        },
        "finding_count": len(findings),
        "findings": findings,
        "privacy": {
            "absolute_paths_emitted": False,
            "device_names_emitted": False,
            "physical_paths_emitted": False,
            "hardware_serials_collected": False,
            "hardware_addresses_collected": False,
            "process_command_lines_collected": False,
            "environment_values_collected": False,
            "tokens_collected": False,
        },
    }


def _yn(value: bool | None) -> str:
    if value is None:
        return "UNKNOWN"
    return "YES" if value else "NO"


def render_text(report: dict[str, Any]) -> str:
    e = report["events"]
    h = report["hidraw"]
    u = report["uinput"]
    ud = report["udev"]
    b = report["device_scope_batteries"]
    lines = [
        "LGD_INPUT_SCHEMA=1",
        "LGD_PHASE=P08",
        "LGD_READ_ONLY=true",
        f"INPUT_EVENTS={e['count']}",
        f"INPUT_EVENTS_READABLE={e['readable_count']}",
        f"INPUT_EVENTS_RW={e['rw_count']}",
        f"GAMEPADS={e['gamepad_count']}",
        f"KEYBOARDS={e['keyboard_count']}",
        f"MICE={e['mouse_count']}",
        f"BLUETOOTH_GAMEPADS={e['bluetooth_gamepad_count']}",
    ]
    for idx, dev in enumerate(e["devices"][:32]):
        lines.append(
            "INPUT_%d=event:%s classes:%s bus:%s vendor:%s model:%s exists:%s readable:%s writable:%s udev:%s"
            % (
                idx,
                _clean(dev["event"], 30),
                ",".join(_clean(x, 30) for x in dev["classes"]),
                _clean(dev["bus"], 40),
                _clean(dev["vendor_id"], 16),
                _clean(dev["model_id"], 16),
                _yn(dev["exists"]),
                _yn(dev["readable"]),
                _yn(dev["writable"]),
                _clean(dev["udev_status"], 30).upper(),
            )
        )
    lines.extend([
        f"HIDRAW_NODES={h['count']}",
        f"HIDRAW_READABLE={h['readable_count']}",
        f"HIDRAW_RW={h['rw_count']}",
        f"UINPUT_EXISTS={_yn(u['exists'])}",
        f"UINPUT_RW={_yn(u['rw'])}",
        f"UINPUT_MODULE_LOADED={_yn(u['module_loaded'])}",
        f"UDEVADM={_yn(ud['tool_present'])}",
        f"UDEV_DATABASE_EXISTS={_yn(ud['database']['exists'])}",
        f"UDEV_DATABASE_READABLE={_yn(ud['database']['readable'])}",
        f"STEAM_INPUT_RULES={_yn(ud['steam_input_rules']['present'])}",
        f"STEAM_INPUT_RULE_FILES={ud['steam_input_rules']['file_count']}",
        f"DEVICE_SCOPE_BATTERIES={b['count']}",
    ])
    for idx, bat in enumerate(b["batteries"][:16]):
        lines.append(
            f"DEVICE_BATTERY_{idx}=capacity:{bat['capacity_pct'] if bat['capacity_pct'] is not None else 'unknown'} status:{_clean(bat['status'], 40)}"
        )
    lines.append(f"INPUT_FINDINGS={report['finding_count']}")
    for idx, finding in enumerate(report["findings"][:24]):
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
        "PRIVACY_ABSOLUTE_PATHS_EMITTED=NO",
        "PRIVACY_DEVICE_NAMES_EMITTED=NO",
        "PRIVACY_PHYSICAL_PATHS_EMITTED=NO",
        "PRIVACY_HARDWARE_SERIALS_COLLECTED=NO",
        "PRIVACY_HARDWARE_ADDRESSES_COLLECTED=NO",
        "P08_INPUT=PASS",
    ])
    return "\n".join(lines) + "\n"
