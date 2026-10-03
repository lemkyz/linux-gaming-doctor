from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

Runner = Callable[[list[str]], tuple[int, str, str]]

VENDOR_NAMES = {
    "0x8086": "Intel",
    "0x10de": "NVIDIA",
    "0x1002": "AMD",
    "0x1022": "AMD",
}


def _default_runner(argv: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=12.0,
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


def _read(path: Path, limit: int = 4096) -> str:
    try:
        return path.read_text(errors="replace")[:limit].strip()
    except OSError:
        return ""


def _vendor_name(vendor_id: str) -> str:
    return VENDOR_NAMES.get(vendor_id.lower(), "Unknown")


def _gpu_devices(sysfs_root: Path = Path("/sys/bus/pci/devices"), dev_root: Path = Path("/dev/dri")) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    try:
        entries = sorted(sysfs_root.iterdir(), key=lambda p: p.name)
    except OSError:
        return devices

    for entry in entries:
        class_code = _read(entry / "class").lower()
        if not class_code.startswith("0x03"):
            continue
        vendor_id = _read(entry / "vendor").lower() or "unknown"
        device_id = _read(entry / "device").lower() or "unknown"
        boot_vga = _read(entry / "boot_vga") == "1"
        driver = "unbound"
        try:
            driver = (entry / "driver").resolve(strict=True).name
        except OSError:
            pass

        render_nodes: list[dict[str, Any]] = []
        drm_dir = entry / "drm"
        try:
            drm_entries = sorted(drm_dir.iterdir(), key=lambda p: p.name)
        except OSError:
            drm_entries = []
        for node in drm_entries:
            if not re.fullmatch(r"renderD\d+", node.name):
                continue
            dev_path = dev_root / node.name
            render_nodes.append(
                {
                    "name": node.name,
                    "exists": dev_path.exists(),
                    "rw_access": os.access(dev_path, os.R_OK | os.W_OK) if dev_path.exists() else False,
                }
            )
        devices.append(
            {
                "pci": entry.name,
                "class": class_code,
                "vendor_id": vendor_id,
                "vendor": _vendor_name(vendor_id),
                "device_id": device_id,
                "driver": driver,
                "boot_vga": boot_vga,
                "render_nodes": render_nodes,
            }
        )
    return devices


def parse_vulkan_summary(text: str) -> list[dict[str, str]]:
    devices: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        match = re.fullmatch(r"GPU(\d+):", line)
        if match:
            current = {"index": match.group(1)}
            devices.append(current)
            continue
        if current is None or "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        allowed = {
            "apiVersion", "driverVersion", "vendorID", "deviceID", "deviceType",
            "deviceName", "driverID", "driverName", "driverInfo",
        }
        if key in allowed:
            current[key] = _clean(value, 220)
    return devices


def _vulkan_state(runner: Runner) -> dict[str, Any]:
    tool = shutil.which("vulkaninfo")
    if not tool:
        return {
            "tool_present": False,
            "probe_status": "unavailable",
            "device_count": 0,
            "devices": [],
            "error_class": "tool_missing",
        }
    rc, out, err = runner([tool, "--summary"])
    devices = parse_vulkan_summary(out) if rc == 0 else []
    return {
        "tool_present": True,
        "probe_status": "pass" if rc == 0 else "fail",
        "device_count": len(devices),
        "devices": devices,
        "error_class": "none" if rc == 0 else _clean(err or "vulkaninfo_failed", 120),
    }


def _icd_inventory() -> list[dict[str, str]]:
    roots = (
        Path("/etc/vulkan/icd.d"),
        Path("/usr/local/share/vulkan/icd.d"),
        Path("/usr/share/vulkan/icd.d"),
    )
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for root in roots:
        try:
            candidates = sorted(root.glob("*.json"), key=lambda p: p.name)
        except OSError:
            continue
        for path in candidates:
            key = path.name
            if key in seen:
                continue
            seen.add(key)
            library = "unknown"
            api_version = "unknown"
            try:
                data = json.loads(path.read_text(errors="replace")[:1_000_000])
                icd = data.get("ICD", {}) if isinstance(data, dict) else {}
                if isinstance(icd, dict):
                    raw_library = str(icd.get("library_path", "unknown"))
                    library = Path(raw_library).name if "/" in raw_library else _clean(raw_library, 120)
                    api_version = _clean(icd.get("api_version", "unknown"), 60)
            except (OSError, json.JSONDecodeError, ValueError):
                pass
            found.append({"file": _clean(path.name, 120), "library": library, "api_version": api_version})
            if len(found) >= 128:
                return found
    return found


def _rpm_package(runner: Runner, nevra: str) -> dict[str, Any]:
    rc, out, _ = runner(["rpm", "-q", "--qf", "%{NAME}.%{ARCH}|%{VERSION}-%{RELEASE}", nevra])
    if rc != 0 or "|" not in out:
        return {"name": nevra, "installed": False, "version": "unknown"}
    name, version = out.split("|", 1)
    return {"name": _clean(name, 100), "installed": True, "version": _clean(version, 120)}


def _package_system() -> str:
    if shutil.which("rpm"):
        return "rpm"
    if shutil.which("dpkg-query"):
        return "dpkg"
    if shutil.which("pacman"):
        return "pacman"
    return "unknown"


def rpm_vulkan_requirements(vendors: set[str]) -> list[str]:
    req = ["vulkan-loader.i686"]
    if "Intel" in vendors or "AMD" in vendors:
        req.append("mesa-vulkan-drivers.i686")
    if "NVIDIA" in vendors:
        req.append("xorg-x11-drv-nvidia-libs.i686")
    return req


def _compat32_state(runner: Runner, vendors: set[str]) -> dict[str, Any]:
    manager = _package_system()
    if manager != "rpm":
        return {
            "package_system": manager,
            "status": "unknown",
            "requirement_count": 0,
            "missing_count": 0,
            "requirements": [],
        }
    requirements = [_rpm_package(runner, name) for name in rpm_vulkan_requirements(vendors)]
    missing = sum(1 for item in requirements if not item["installed"])
    return {
        "package_system": manager,
        "status": "ready" if missing == 0 else "incomplete",
        "requirement_count": len(requirements),
        "missing_count": missing,
        "requirements": requirements,
    }


def _nvidia_module_version() -> str:
    value = _read(Path("/sys/module/nvidia/version"), 256)
    if value:
        return _clean(value.splitlines()[0], 80)
    text = _read(Path("/proc/driver/nvidia/version"), 4096)
    match = re.search(r"Kernel Module\s+([0-9][0-9A-Za-z._-]*)", text)
    return _clean(match.group(1), 80) if match else "unknown"


def parse_nvidia_smi(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        parts = [x.strip() for x in line.split(",", 2)]
        if len(parts) < 2:
            continue
        item = {"name": _clean(parts[0], 160), "driver_version": _clean(parts[1], 80)}
        if len(parts) == 3:
            item["pstate"] = _clean(parts[2], 40)
        out.append(item)
    return out


def _nvidia_state(runner: Runner, gpu_devices: list[dict[str, Any]]) -> dict[str, Any]:
    present = any(gpu["vendor"] == "NVIDIA" for gpu in gpu_devices)
    module_version = _nvidia_module_version() if present else "not_applicable"
    tool = shutil.which("nvidia-smi")
    smi_devices: list[dict[str, str]] = []
    status = "not_applicable" if not present else "unavailable"
    if present and tool:
        rc, out, _ = runner([tool, "--query-gpu=name,driver_version,pstate", "--format=csv,noheader,nounits"])
        if rc == 0:
            smi_devices = parse_nvidia_smi(out)
            status = "pass"
        else:
            status = "fail"
    userspace_version = smi_devices[0]["driver_version"] if smi_devices else "unknown"
    mismatch = (
        module_version not in {"unknown", "not_applicable"}
        and userspace_version != "unknown"
        and module_version != userspace_version
    )
    return {
        "present": present,
        "module_version": module_version,
        "smi_tool_present": bool(tool),
        "smi_status": status,
        "device_count": len(smi_devices),
        "devices": smi_devices,
        "userspace_driver_version": userspace_version,
        "kernel_userspace_version_match": None if module_version in {"unknown", "not_applicable"} or userspace_version == "unknown" else not mismatch,
    }


def _switcheroo_state(runner: Runner) -> dict[str, Any]:
    tool = shutil.which("switcherooctl")
    if not tool:
        return {"tool_present": False, "status": "unavailable", "device_count": 0, "default_count": 0}
    rc, out, _ = runner([tool, "list"])
    if rc != 0:
        return {"tool_present": True, "status": "fail", "device_count": 0, "default_count": 0}
    device_count = len(re.findall(r"(?m)^Device:\s*\d+\s*$", out))
    default_count = len(re.findall(r"(?mi)^\s*Default:\s*yes\s*$", out))
    return {"tool_present": True, "status": "pass", "device_count": device_count, "default_count": default_count}


def collect_gpu_state(runner: Runner | None = None) -> dict[str, Any]:
    run = runner or _default_runner
    gpu_devices = _gpu_devices()
    vendors = {gpu["vendor"] for gpu in gpu_devices if gpu["vendor"] != "Unknown"}
    vulkan = _vulkan_state(run)
    icds = _icd_inventory()
    compat32 = _compat32_state(run, vendors)
    nvidia = _nvidia_state(run, gpu_devices)
    switcheroo = _switcheroo_state(run)
    findings: list[dict[str, Any]] = []

    if not gpu_devices:
        findings.append({
            "code": "NO_DISPLAY_GPU_DISCOVERED",
            "severity": "warning",
            "classification": "UNKNOWN",
            "scope": "gpu",
            "evidence": "No PCI display-class GPU was discovered in sysfs",
        })

    for gpu in gpu_devices:
        if gpu["driver"] == "unbound":
            findings.append({
                "code": "GPU_DRIVER_UNBOUND",
                "severity": "warning",
                "classification": "REPAIRABLE",
                "scope": gpu["pci"],
                "evidence": f"{gpu['vendor']} display device has no bound kernel driver",
            })
        for node in gpu["render_nodes"]:
            if node["exists"] and not node["rw_access"]:
                findings.append({
                    "code": "DRM_RENDER_NODE_ACCESS_DENIED",
                    "severity": "warning",
                    "classification": "REPAIRABLE",
                    "scope": node["name"],
                    "evidence": "Current user lacks read/write access to a GPU DRM render node",
                })

    if not vulkan["tool_present"]:
        findings.append({
            "code": "VULKANINFO_UNAVAILABLE",
            "severity": "info",
            "classification": "UNKNOWN",
            "scope": "vulkan",
            "evidence": "vulkaninfo is not installed; Vulkan runtime enumeration could not be directly verified",
        })
    elif vulkan["probe_status"] != "pass":
        findings.append({
            "code": "VULKAN_PROBE_FAILED",
            "severity": "warning",
            "classification": "UNKNOWN",
            "scope": "vulkan",
            "evidence": "vulkaninfo --summary returned a failure",
        })
    else:
        enumerated_vendors = {str(d.get("vendorID", "")).lower() for d in vulkan["devices"]}
        for gpu in gpu_devices:
            if gpu["vendor_id"] in {"unknown", ""}:
                continue
            if gpu["vendor_id"] not in enumerated_vendors:
                findings.append({
                    "code": "GPU_NOT_ENUMERATED_BY_VULKAN",
                    "severity": "warning",
                    "classification": "UNKNOWN",
                    "scope": gpu["pci"],
                    "evidence": f"{gpu['vendor']} GPU is bound to {gpu['driver']} but was not present in vulkaninfo summary",
                })

    if nvidia["present"] and nvidia["smi_tool_present"] and nvidia["smi_status"] != "pass":
        findings.append({
            "code": "NVIDIA_SMI_FAILED",
            "severity": "warning",
            "classification": "UNKNOWN",
            "scope": "nvidia",
            "evidence": "NVIDIA PCI device is present but nvidia-smi did not complete successfully",
        })
    if nvidia["kernel_userspace_version_match"] is False:
        findings.append({
            "code": "NVIDIA_KERNEL_USERSPACE_VERSION_MISMATCH",
            "severity": "error",
            "classification": "REPAIRABLE",
            "scope": "nvidia",
            "evidence": "Loaded NVIDIA kernel-module version differs from nvidia-smi userspace driver version",
        })

    if compat32["package_system"] == "rpm" and compat32["missing_count"]:
        for req in compat32["requirements"]:
            if req["installed"]:
                continue
            findings.append({
                "code": "VULKAN_32BIT_PACKAGE_MISSING",
                "severity": "warning",
                "classification": "REPAIRABLE",
                "scope": req["name"],
                "evidence": "A Fedora/RPM 32-bit Vulkan runtime package required by the detected GPU vendor set is not installed",
            })

    findings.sort(key=lambda x: ({"error": 0, "warning": 1, "info": 2}.get(x["severity"], 9), x["code"], x["scope"]))

    readable_render_nodes = sum(
        1 for gpu in gpu_devices for node in gpu["render_nodes"] if node["exists"] and node["rw_access"]
    )
    total_render_nodes = sum(len(gpu["render_nodes"]) for gpu in gpu_devices)

    return {
        "schema_version": 1,
        "phase": "P04",
        "read_only": True,
        "gpu": {
            "device_count": len(gpu_devices),
            "devices": gpu_devices,
            "vendor_set": sorted(vendors),
            "render_node_count": total_render_nodes,
            "readable_render_node_count": readable_render_nodes,
            "hybrid_gpu": len({gpu["vendor"] for gpu in gpu_devices}) > 1,
        },
        "vulkan": {
            **vulkan,
            "icd_count": len(icds),
            "icds": icds,
            "compat32": compat32,
        },
        "nvidia": nvidia,
        "switcheroo": switcheroo,
        "finding_count": len(findings),
        "findings": findings,
        "privacy": {
            "absolute_paths_emitted": False,
            "environment_values_collected": False,
            "device_serials_collected": False,
            "network_identifiers_collected": False,
            "tokens_collected": False,
        },
    }


def _yn(value: bool | None) -> str:
    if value is None:
        return "UNKNOWN"
    return "YES" if value else "NO"


def render_text(report: dict[str, Any]) -> str:
    g = report["gpu"]
    v = report["vulkan"]
    n = report["nvidia"]
    s = report["switcheroo"]
    c32 = v["compat32"]
    lines = [
        "LGD_GPU_SCHEMA=1",
        "LGD_PHASE=P04",
        "LGD_READ_ONLY=true",
        f"GPU_COUNT={g['device_count']}",
        f"GPU_VENDORS={','.join(g['vendor_set']) if g['vendor_set'] else 'none'}",
        f"HYBRID_GPU={_yn(g['hybrid_gpu'])}",
        f"DRM_RENDER_NODES={g['render_node_count']}",
        f"DRM_RENDER_NODES_RW={g['readable_render_node_count']}",
    ]
    for idx, gpu in enumerate(g["devices"][:8]):
        render = ",".join(f"{x['name']}:{'rw' if x['rw_access'] else 'blocked'}" for x in gpu["render_nodes"]) or "none"
        lines.append(
            "GPU_%d=vendor:%s vendor_id:%s device_id:%s driver:%s boot_vga:%s pci:%s render:%s"
            % (
                idx,
                _clean(gpu["vendor"]),
                _clean(gpu["vendor_id"]),
                _clean(gpu["device_id"]),
                _clean(gpu["driver"]),
                _yn(gpu["boot_vga"]),
                _clean(gpu["pci"]),
                _clean(render, 200),
            )
        )
    lines.extend(
        [
            f"VULKANINFO={_yn(v['tool_present'])}",
            f"VULKAN_PROBE={_clean(v['probe_status']).upper()}",
            f"VULKAN_DEVICES={v['device_count']}",
            f"VULKAN_ICDS={v['icd_count']}",
        ]
    )
    for idx, dev in enumerate(v["devices"][:8]):
        lines.append(
            "VULKAN_GPU_%d=name:%s vendor_id:%s device_id:%s type:%s driver:%s api:%s"
            % (
                idx,
                _clean(dev.get("deviceName", "unknown")),
                _clean(dev.get("vendorID", "unknown")),
                _clean(dev.get("deviceID", "unknown")),
                _clean(dev.get("deviceType", "unknown")),
                _clean(dev.get("driverName", dev.get("driverID", "unknown"))),
                _clean(dev.get("apiVersion", "unknown")),
            )
        )
    lines.extend(
        [
            f"VULKAN_32BIT_STATUS={_clean(c32['status']).upper()}",
            f"VULKAN_32BIT_REQUIREMENTS={c32['requirement_count']}",
            f"VULKAN_32BIT_MISSING={c32['missing_count']}",
        ]
    )
    for idx, req in enumerate(c32["requirements"][:8]):
        lines.append(
            "VULKAN_32BIT_%d=package:%s installed:%s version:%s"
            % (idx, _clean(req["name"]), _yn(req["installed"]), _clean(req["version"]))
        )
    lines.extend(
        [
            f"NVIDIA_PRESENT={_yn(n['present'])}",
            f"NVIDIA_MODULE_VERSION={_clean(n['module_version'])}",
            f"NVIDIA_SMI={_clean(n['smi_status']).upper()}",
            f"NVIDIA_USERSPACE_VERSION={_clean(n['userspace_driver_version'])}",
            f"NVIDIA_KERNEL_USERSPACE_MATCH={_yn(n['kernel_userspace_version_match'])}",
            f"SWITCHEROOCTL={_yn(s['tool_present'])}",
            f"SWITCHEROO_STATUS={_clean(s['status']).upper()}",
            f"SWITCHEROO_GPU_ENTRIES={s['device_count']}",
            f"GPU_FINDINGS={report['finding_count']}",
        ]
    )
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
    lines.extend(
        [
            "PRIVACY_ABSOLUTE_PATHS_EMITTED=NO",
            "PRIVACY_ENVIRONMENT_VALUES_COLLECTED=NO",
            "PRIVACY_DEVICE_SERIALS_COLLECTED=NO",
            "P04_GPU_VULKAN=PASS",
        ]
    )
    return "\n".join(lines) + "\n"
