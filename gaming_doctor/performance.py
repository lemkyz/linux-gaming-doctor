
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


def _clean(value: object, limit: int = 160) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = text.replace("=", ":")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] if text else "unknown"


def _to_float(value: str | object) -> float | None:
    text = str(value).strip()
    if not text or text.lower() in {"n/a", "na", "unknown", "[not supported]", "not supported"}:
        return None
    match = re.search(r"-?[0-9]+(?:\.[0-9]+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def parse_meminfo(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for raw in (text or "").splitlines():
        if ":" not in raw:
            continue
        key, value = raw.split(":", 1)
        match = re.search(r"([0-9]+)", value)
        if match:
            out[key.strip()] = int(match.group(1))
    return out


def _memory_state(proc_root: Path = Path("/proc")) -> dict[str, Any]:
    data = parse_meminfo(_read(proc_root / "meminfo"))
    total = int(data.get("MemTotal", 0))
    available = int(data.get("MemAvailable", data.get("MemFree", 0)))
    swap_total = int(data.get("SwapTotal", 0))
    swap_free = int(data.get("SwapFree", 0))
    swap_used = max(0, swap_total - swap_free)
    return {
        "total_kib": total,
        "available_kib": available,
        "available_pct": round((available / total) * 100.0, 3) if total else None,
        "swap_total_kib": swap_total,
        "swap_used_kib": swap_used,
        "swap_used_pct": round((swap_used / swap_total) * 100.0, 3) if swap_total else 0.0,
    }


def _load_state(proc_root: Path = Path("/proc")) -> dict[str, float | None]:
    text = _read(proc_root / "loadavg", 256)
    parts = text.split()
    values: list[float | None] = []
    for raw in parts[:3]:
        try:
            values.append(float(raw))
        except ValueError:
            values.append(None)
    while len(values) < 3:
        values.append(None)
    return {"load_1m": values[0], "load_5m": values[1], "load_15m": values[2]}


def parse_pressure(text: str) -> dict[str, dict[str, float | int]]:
    out: dict[str, dict[str, float | int]] = {}
    for raw in (text or "").splitlines():
        parts = raw.split()
        if not parts:
            continue
        kind = parts[0]
        if kind not in {"some", "full"}:
            continue
        row: dict[str, float | int] = {}
        for item in parts[1:]:
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            try:
                row[key] = int(value) if key == "total" else float(value)
            except ValueError:
                continue
        out[kind] = row
    return out


def _pressure_state(proc_root: Path = Path("/proc")) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in ("cpu", "memory", "io"):
        path = proc_root / "pressure" / name
        text = _read(path, 8192)
        result[name] = {
            "available": bool(text),
            "some": {},
            "full": {},
        }
        if text:
            parsed = parse_pressure(text)
            result[name]["some"] = parsed.get("some", {})
            result[name]["full"] = parsed.get("full", {})
    return result


def _read_int(path: Path) -> int | None:
    text = _read(path, 128)
    try:
        return int(text)
    except ValueError:
        return None


def _cpu_freq_state(sys_root: Path = Path("/sys/devices/system/cpu")) -> dict[str, Any]:
    cpufreq_root = sys_root / "cpufreq"
    policies: list[dict[str, Any]] = []
    try:
        entries = sorted(cpufreq_root.glob("policy*"), key=lambda p: p.name)
    except OSError:
        entries = []
    for policy in entries[:256]:
        cur = _read_int(policy / "scaling_cur_freq")
        minf = _read_int(policy / "scaling_min_freq")
        maxf = _read_int(policy / "scaling_max_freq")
        policies.append(
            {
                "name": _clean(policy.name, 40),
                "driver": _clean(_read(policy / "scaling_driver", 128) or "unknown", 80),
                "governor": _clean(_read(policy / "scaling_governor", 128) or "unknown", 80),
                "epp": _clean(_read(policy / "energy_performance_preference", 128) or "unknown", 80),
                "current_khz": cur,
                "min_khz": minf,
                "max_khz": maxf,
            }
        )
    currents = [p["current_khz"] for p in policies if isinstance(p["current_khz"], int)]
    mins = [p["min_khz"] for p in policies if isinstance(p["min_khz"], int)]
    maxes = [p["max_khz"] for p in policies if isinstance(p["max_khz"], int)]
    drivers = sorted({str(p["driver"]) for p in policies if p["driver"] != "unknown"})
    governors = sorted({str(p["governor"]) for p in policies if p["governor"] != "unknown"})
    epps = sorted({str(p["epp"]) for p in policies if p["epp"] != "unknown"})

    boost: bool | None = None
    boost_text = _read(cpufreq_root / "boost", 16)
    if boost_text in {"0", "1"}:
        boost = boost_text == "1"
    else:
        no_turbo = _read(sys_root / "intel_pstate" / "no_turbo", 16)
        if no_turbo in {"0", "1"}:
            boost = no_turbo == "0"

    def avg_khz(values: list[int]) -> float | None:
        return round(sum(values) / len(values), 3) if values else None

    return {
        "policy_count": len(policies),
        "policies": policies,
        "drivers": drivers,
        "governors": governors,
        "energy_performance_preferences": epps,
        "boost_enabled": boost,
        "current_avg_khz": avg_khz(currents),
        "min_avg_khz": avg_khz(mins),
        "max_avg_khz": avg_khz(maxes),
    }


def _thermal_state(root: Path = Path("/sys/class/thermal")) -> dict[str, Any]:
    zones: list[dict[str, Any]] = []
    try:
        entries = sorted(root.glob("thermal_zone*"), key=lambda p: p.name)
    except OSError:
        entries = []
    for zone in entries[:128]:
        raw = _read_int(zone / "temp")
        if raw is None:
            continue
        # Linux thermal zones are normally millidegrees C; tolerate direct-C fixtures.
        temp_c = raw / 1000.0 if abs(raw) > 1000 else float(raw)
        if temp_c < -50 or temp_c > 250:
            continue
        zones.append(
            {
                "type": _clean(_read(zone / "type", 256) or "unknown", 100),
                "temp_c": round(temp_c, 3),
            }
        )
    hottest = max(zones, key=lambda x: x["temp_c"], default=None)
    return {
        "zone_count": len(zones),
        "zones": zones,
        "max_temp_c": hottest["temp_c"] if hottest else None,
        "hottest_type": hottest["type"] if hottest else "unknown",
    }


def parse_nvidia_metrics(text: str) -> list[dict[str, Any]]:
    fields = [
        "gpu_util_pct",
        "memory_util_pct",
        "temp_c",
        "pstate",
        "graphics_clock_mhz",
        "memory_clock_mhz",
        "power_draw_w",
        "power_limit_w",
        "memory_used_mib",
        "memory_total_mib",
    ]
    numeric = set(fields) - {"pstate"}
    rows: list[dict[str, Any]] = []
    for raw in (text or "").splitlines():
        if not raw.strip():
            continue
        parts = [x.strip() for x in raw.split(",")]
        if len(parts) != len(fields):
            continue
        row: dict[str, Any] = {}
        for key, value in zip(fields, parts):
            row[key] = _to_float(value) if key in numeric else _clean(value, 40)
        rows.append(row)
    return rows


def _nvidia_state(runner: Runner) -> dict[str, Any]:
    tool = shutil.which("nvidia-smi")
    if not tool:
        return {"tool_present": False, "status": "unavailable", "device_count": 0, "devices": []}
    query = ",".join([
        "utilization.gpu",
        "utilization.memory",
        "temperature.gpu",
        "pstate",
        "clocks.current.graphics",
        "clocks.current.memory",
        "power.draw",
        "power.limit",
        "memory.used",
        "memory.total",
    ])
    rc, out, err = runner([tool, f"--query-gpu={query}", "--format=csv,noheader,nounits"])
    devices = parse_nvidia_metrics(out) if rc == 0 else []
    return {
        "tool_present": True,
        "status": "pass" if rc == 0 else "fail",
        "device_count": len(devices),
        "devices": devices,
        "error_class": "none" if rc == 0 else _clean(err or "nvidia_smi_failed", 120),
    }


def _version_probe(runner: Runner, commands: list[tuple[str, list[str]]]) -> dict[str, Any]:
    for binary, args in commands:
        path = shutil.which(binary)
        if not path:
            continue
        rc, out, err = runner([path, *args])
        text = out or err
        first = text.splitlines()[0] if text else "unknown"
        return {
            "present": True,
            "status": "pass" if rc == 0 else "fail",
            "version": _clean(first, 120),
        }
    return {"present": False, "status": "unavailable", "version": "unknown"}


def _tools_state(runner: Runner) -> dict[str, Any]:
    return {
        "gamemode": {
            "runner_present": bool(shutil.which("gamemoderun")),
            "daemon_binary_present": bool(shutil.which("gamemoded")),
        },
        "mangohud": _version_probe(runner, [("mangohud", ["--version"])]),
    }


def _power_state(runner: Runner, root: Path = Path("/sys/class/power_supply")) -> dict[str, Any]:
    profile = "unavailable"
    tool = shutil.which("powerprofilesctl")
    if tool:
        rc, out, _ = runner([tool, "get"])
        profile = _clean(out, 80) if rc == 0 and out else "unknown"
    ac_state = "unknown"
    battery_statuses: list[str] = []
    try:
        entries = list(root.iterdir())
    except OSError:
        entries = []
    for dev in entries:
        typ = _read(dev / "type", 64)
        if typ in {"Mains", "USB", "USB_C"}:
            online = _read(dev / "online", 16)
            if online == "1":
                ac_state = "online"
            elif online == "0" and ac_state != "online":
                ac_state = "offline"
        elif typ == "Battery":
            status = _clean(_read(dev / "status", 64) or "unknown", 40)
            if status not in battery_statuses:
                battery_statuses.append(status)
    return {
        "profile": profile,
        "ac_state": ac_state,
        "battery_statuses": battery_statuses,
    }


def _psi_avg10(pressure: dict[str, Any], resource: str, kind: str = "some") -> float | None:
    row = pressure.get(resource, {}).get(kind, {})
    value = row.get("avg10") if isinstance(row, dict) else None
    return float(value) if isinstance(value, (int, float)) else None


def collect_performance_state(
    runner: Runner | None = None,
    proc_root: Path = Path("/proc"),
    cpu_sys_root: Path = Path("/sys/devices/system/cpu"),
    thermal_root: Path = Path("/sys/class/thermal"),
    power_root: Path = Path("/sys/class/power_supply"),
) -> dict[str, Any]:
    run = runner or _default_runner
    cpu = _cpu_freq_state(cpu_sys_root)
    load = _load_state(proc_root)
    memory = _memory_state(proc_root)
    pressure = _pressure_state(proc_root)
    thermal = _thermal_state(thermal_root)
    nvidia = _nvidia_state(run)
    tools = _tools_state(run)
    power = _power_state(run, power_root)
    findings: list[dict[str, str]] = []

    avail_pct = memory["available_pct"]
    if isinstance(avail_pct, (int, float)) and avail_pct < 3.0 and memory["available_kib"] < 524288:
        findings.append({
            "code": "MEMORY_AVAILABLE_CRITICALLY_LOW",
            "severity": "warning",
            "classification": "UNKNOWN",
            "scope": "memory",
            "evidence": "Available memory is below both 3% and 512 MiB in this snapshot",
        })

    if memory["swap_total_kib"] > 0 and memory["swap_used_pct"] >= 80.0:
        findings.append({
            "code": "SWAP_HEAVILY_USED_SNAPSHOT",
            "severity": "info",
            "classification": "UNKNOWN",
            "scope": "memory",
            "evidence": "At least 80% of configured swap is in use in this snapshot",
        })

    cpu_psi = _psi_avg10(pressure, "cpu", "some")
    if cpu_psi is not None and cpu_psi >= 70.0:
        findings.append({
            "code": "CPU_PRESSURE_HIGH_SNAPSHOT",
            "severity": "warning",
            "classification": "UNKNOWN",
            "scope": "cpu",
            "evidence": f"CPU PSI some avg10 is {cpu_psi:.2f}; sustained correlation with game frametime is required before attribution",
        })

    memory_full = _psi_avg10(pressure, "memory", "full")
    if memory_full is not None and memory_full >= 5.0:
        findings.append({
            "code": "MEMORY_STALL_PRESSURE_ACTIVE",
            "severity": "warning",
            "classification": "UNKNOWN",
            "scope": "memory",
            "evidence": f"Memory PSI full avg10 is {memory_full:.2f}; this snapshot alone does not prove a game bottleneck",
        })

    if isinstance(thermal["max_temp_c"], (int, float)) and thermal["max_temp_c"] >= 100.0:
        findings.append({
            "code": "THERMAL_ZONE_EXTREME_SNAPSHOT",
            "severity": "warning",
            "classification": "UNKNOWN",
            "scope": str(thermal["hottest_type"]),
            "evidence": f"A thermal zone reports {thermal['max_temp_c']:.1f} C; hardware-specific throttling evidence is still required",
        })

    if nvidia["status"] == "fail":
        findings.append({
            "code": "NVIDIA_PERFORMANCE_TELEMETRY_UNAVAILABLE",
            "severity": "info",
            "classification": "UNKNOWN",
            "scope": "nvidia",
            "evidence": "nvidia-smi is installed but the read-only performance query failed",
        })
    for idx, device in enumerate(nvidia["devices"]):
        temp = device.get("temp_c")
        if isinstance(temp, (int, float)) and temp >= 90.0:
            findings.append({
                "code": "NVIDIA_GPU_TEMPERATURE_HIGH_SNAPSHOT",
                "severity": "warning",
                "classification": "UNKNOWN",
                "scope": f"nvidia_gpu_{idx}",
                "evidence": f"NVIDIA GPU temperature is {temp:.1f} C in this snapshot; throttling must be confirmed separately",
            })

    if power["ac_state"] == "offline" and any(x.lower() == "discharging" for x in power["battery_statuses"]):
        findings.append({
            "code": "RUNNING_ON_BATTERY",
            "severity": "info",
            "classification": "WORKAROUND",
            "scope": "power",
            "evidence": "AC power is offline and a battery reports Discharging; laptop gaming performance may be power-limited",
        })

    if len(cpu["governors"]) > 1:
        findings.append({
            "code": "CPU_GOVERNOR_MIXED",
            "severity": "info",
            "classification": "UNKNOWN",
            "scope": "cpu",
            "evidence": "More than one CPU frequency governor is active across policies; heterogeneous systems can make this valid",
        })

    findings.sort(key=lambda x: ({"error": 0, "warning": 1, "info": 2}.get(x["severity"], 9), x["code"], x["scope"]))
    return {
        "schema_version": 1,
        "phase": "P06",
        "read_only": True,
        "cpu": {
            "logical_cpus": os.cpu_count() or 0,
            "frequency": cpu,
            "load": load,
        },
        "memory": memory,
        "pressure": pressure,
        "thermal": thermal,
        "nvidia": nvidia,
        "power": power,
        "tools": tools,
        "finding_count": len(findings),
        "findings": findings,
        "privacy": {
            "absolute_paths_emitted": False,
            "process_command_lines_collected": False,
            "environment_values_collected": False,
            "host_identifiers_collected": False,
            "hardware_serials_collected": False,
            "network_identifiers_collected": False,
            "tokens_collected": False,
        },
    }


def _fmt(value: object, digits: int = 3) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return _clean(value)


def _yn(value: bool | None) -> str:
    if value is None:
        return "UNKNOWN"
    return "YES" if value else "NO"


def render_text(report: dict[str, Any]) -> str:
    cpu = report["cpu"]
    freq = cpu["frequency"]
    mem = report["memory"]
    pressure = report["pressure"]
    thermal = report["thermal"]
    nvidia = report["nvidia"]
    power = report["power"]
    tools = report["tools"]
    lines = [
        "LGD_PERFORMANCE_SCHEMA=1",
        "LGD_PHASE=P06",
        "LGD_READ_ONLY=true",
        f"CPU_LOGICAL={cpu['logical_cpus']}",
        f"CPUFREQ_POLICIES={freq['policy_count']}",
        "CPUFREQ_DRIVERS=" + (",".join(_clean(x, 80) for x in freq["drivers"]) or "unknown"),
        "CPUFREQ_GOVERNORS=" + (",".join(_clean(x, 80) for x in freq["governors"]) or "unknown"),
        "CPU_EPP=" + (",".join(_clean(x, 80) for x in freq["energy_performance_preferences"]) or "unknown"),
        f"CPU_BOOST_ENABLED={_yn(freq['boost_enabled'])}",
        f"CPU_FREQ_CURRENT_AVG_MHZ={_fmt(freq['current_avg_khz'] / 1000.0 if freq['current_avg_khz'] is not None else None)}",
        f"CPU_FREQ_MIN_AVG_MHZ={_fmt(freq['min_avg_khz'] / 1000.0 if freq['min_avg_khz'] is not None else None)}",
        f"CPU_FREQ_MAX_AVG_MHZ={_fmt(freq['max_avg_khz'] / 1000.0 if freq['max_avg_khz'] is not None else None)}",
        f"LOAD_1M={_fmt(cpu['load']['load_1m'])}",
        f"LOAD_5M={_fmt(cpu['load']['load_5m'])}",
        f"LOAD_15M={_fmt(cpu['load']['load_15m'])}",
        f"MEMORY_TOTAL_MIB={_fmt(mem['total_kib'] / 1024.0 if mem['total_kib'] else 0.0)}",
        f"MEMORY_AVAILABLE_MIB={_fmt(mem['available_kib'] / 1024.0 if mem['available_kib'] else 0.0)}",
        f"MEMORY_AVAILABLE_PCT={_fmt(mem['available_pct'])}",
        f"SWAP_TOTAL_MIB={_fmt(mem['swap_total_kib'] / 1024.0 if mem['swap_total_kib'] else 0.0)}",
        f"SWAP_USED_MIB={_fmt(mem['swap_used_kib'] / 1024.0 if mem['swap_used_kib'] else 0.0)}",
        f"SWAP_USED_PCT={_fmt(mem['swap_used_pct'])}",
        f"PRESSURE_CPU_SOME_AVG10={_fmt(_psi_avg10(pressure, 'cpu', 'some'))}",
        f"PRESSURE_MEMORY_SOME_AVG10={_fmt(_psi_avg10(pressure, 'memory', 'some'))}",
        f"PRESSURE_MEMORY_FULL_AVG10={_fmt(_psi_avg10(pressure, 'memory', 'full'))}",
        f"PRESSURE_IO_SOME_AVG10={_fmt(_psi_avg10(pressure, 'io', 'some'))}",
        f"PRESSURE_IO_FULL_AVG10={_fmt(_psi_avg10(pressure, 'io', 'full'))}",
        f"THERMAL_ZONES={thermal['zone_count']}",
        f"THERMAL_MAX_C={_fmt(thermal['max_temp_c'])}",
        f"THERMAL_HOTTEST_TYPE={_clean(thermal['hottest_type'])}",
        f"POWER_PROFILE={_clean(power['profile'])}",
        f"AC_STATE={_clean(power['ac_state'])}",
        "BATTERY_STATUS=" + (",".join(_clean(x, 40) for x in power["battery_statuses"]) or "none"),
        f"NVIDIA_SMI_PERF={_clean(nvidia['status']).upper()}",
        f"NVIDIA_PERF_DEVICES={nvidia['device_count']}",
    ]
    for idx, dev in enumerate(nvidia["devices"][:8]):
        lines.append(
            "NVIDIA_PERF_%d=gpu_util:%s mem_util:%s temp_c:%s pstate:%s gfx_mhz:%s mem_mhz:%s power_w:%s power_limit_w:%s vram_used_mib:%s vram_total_mib:%s"
            % (
                idx,
                _fmt(dev.get("gpu_util_pct")),
                _fmt(dev.get("memory_util_pct")),
                _fmt(dev.get("temp_c")),
                _clean(dev.get("pstate", "unknown")),
                _fmt(dev.get("graphics_clock_mhz")),
                _fmt(dev.get("memory_clock_mhz")),
                _fmt(dev.get("power_draw_w")),
                _fmt(dev.get("power_limit_w")),
                _fmt(dev.get("memory_used_mib")),
                _fmt(dev.get("memory_total_mib")),
            )
        )
    lines.extend([
        f"GAMEMODE_RUNNER={_yn(tools['gamemode']['runner_present'])}",
        f"GAMEMODE_DAEMON_BINARY={_yn(tools['gamemode']['daemon_binary_present'])}",
        f"MANGOHUD={_yn(tools['mangohud']['present'])}",
        f"MANGOHUD_VERSION_STATUS={_clean(tools['mangohud']['status']).upper()}",
        f"MANGOHUD_VERSION={_clean(tools['mangohud']['version'])}",
        f"PERFORMANCE_FINDINGS={report['finding_count']}",
    ])
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
        "PRIVACY_ABSOLUTE_PATHS_EMITTED=NO",
        "PRIVACY_PROCESS_COMMAND_LINES_COLLECTED=NO",
        "PRIVACY_ENVIRONMENT_VALUES_COLLECTED=NO",
        "PRIVACY_HOST_IDENTIFIERS_COLLECTED=NO",
        "PRIVACY_HARDWARE_SERIALS_COLLECTED=NO",
        "P06_PERFORMANCE=PASS",
    ])
    return "\n".join(lines) + "\n"
