from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace").strip()
    except (OSError, UnicodeError):
        return ""


def _run(argv: list[str], timeout: float = 5.0) -> tuple[bool, str]:
    try:
        p = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    text = p.stdout.strip() or p.stderr.strip()
    return p.returncode == 0, text


def _parse_os_release(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        value = value.replace(r'\"', '"').replace(r"\\", "\\")
        out[key.strip()] = value
    return out


def _cpu_model() -> str:
    text = _read_text(Path("/proc/cpuinfo"))
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key.strip() in {"model name", "Hardware", "Processor"} and value.strip():
            return value.strip()
    return platform.processor() or "unknown"


def _memory_kib() -> int:
    text = _read_text(Path("/proc/meminfo"))
    for line in text.splitlines():
        if line.startswith("MemTotal:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(parts[1])
                except ValueError:
                    pass
    return 0


def _gpu_vendor(vendor_id: str) -> str:
    return {
        "0x10de": "NVIDIA",
        "0x1002": "AMD",
        "0x1022": "AMD",
        "0x8086": "Intel",
        "0x1af4": "Virtio",
    }.get(vendor_id.lower(), "Unknown")


def _gpu_class(class_id: str) -> str:
    value = class_id.lower()
    if value.startswith("0x0300"):
        return "display"
    if value.startswith("0x0302"):
        return "3d_controller"
    return "other"


def _driver_name(device: Path) -> str:
    try:
        return (device / "driver").resolve(strict=True).name
    except OSError:
        return "none"


def _collect_gpus() -> list[dict[str, str]]:
    root = Path("/sys/bus/pci/devices")
    out: list[dict[str, str]] = []
    try:
        entries = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError:
        return out

    for dev in entries:
        class_id = _read_text(dev / "class")
        if not (class_id.lower().startswith("0x0300") or class_id.lower().startswith("0x0302")):
            continue
        vendor_id = _read_text(dev / "vendor")
        out.append(
            {
                "pci": dev.name,
                "vendor_id": vendor_id or "unknown",
                "vendor": _gpu_vendor(vendor_id),
                "device_id": _read_text(dev / "device") or "unknown",
                "class": _gpu_class(class_id),
                "driver": _driver_name(dev),
            }
        )
    return out


def _collect_vulkan_icds() -> list[str]:
    roots = [
        Path("/etc/vulkan/icd.d"),
        Path("/usr/local/share/vulkan/icd.d"),
        Path("/usr/share/vulkan/icd.d"),
    ]
    home = os.environ.get("HOME")
    if home:
        roots.append(Path(home) / ".local/share/vulkan/icd.d")
    names: set[str] = set()
    for root in roots:
        try:
            for entry in root.iterdir():
                if entry.is_file() and entry.suffix == ".json":
                    names.add(entry.name)
        except OSError:
            continue
    return sorted(names)


def _vulkan_probe() -> tuple[bool, str]:
    if shutil.which("vulkaninfo") is None:
        return False, "UNAVAILABLE"
    try:
        p = subprocess.run(
            ["vulkaninfo", "--summary"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return True, "TIMEOUT"
    except OSError:
        return True, "FAIL"
    return True, "PASS" if p.returncode == 0 else "FAIL"


def _detect_steam() -> dict[str, bool]:
    home = Path(os.environ.get("HOME", "/"))
    return {
        "native": any(
            p.exists()
            for p in (
                home / ".steam/steam",
                home / ".local/share/Steam",
                home / ".local/share/steam",
            )
        ),
        "flatpak_user": (home / ".var/app/com.valvesoftware.Steam").exists(),
        "flatpak_system": Path("/var/lib/flatpak/app/com.valvesoftware.Steam").exists(),
    }


def _mount_fact(path: Path) -> dict[str, str]:
    if shutil.which("findmnt") is None:
        return {"fstype": "unknown", "options": "unknown"}
    ok, text = _run(["findmnt", "-n", "-o", "FSTYPE,OPTIONS", "-T", str(path)])
    if not ok or not text:
        return {"fstype": "unknown", "options": "unknown"}
    parts = text.split(None, 1)
    return {
        "fstype": parts[0] if parts else "unknown",
        "options": parts[1] if len(parts) > 1 else "unknown",
    }


def _version_line(command: str, *args: str) -> str:
    if shutil.which(command) is None:
        return "unavailable"
    _, text = _run([command, *args])
    return text.splitlines()[0].strip() if text else "unknown"


def _user_service_state(name: str) -> str:
    if shutil.which("systemctl") is None:
        return "unknown"
    _, text = _run(["systemctl", "--user", "is-active", name], timeout=3)
    return text.splitlines()[0].strip() if text else "unknown"


def _collect_input() -> dict[str, Any]:
    root = Path("/dev/input")
    events: list[Path] = []
    try:
        events = sorted(p for p in root.iterdir() if p.name.startswith("event"))
    except OSError:
        pass

    names: list[str] = []
    for line in _read_text(Path("/proc/bus/input/devices")).splitlines():
        if line.startswith("N: Name="):
            name = line.removeprefix("N: Name=").strip().strip('"')
            if name and name not in names:
                names.append(name)
        if len(names) >= 32:
            break

    return {
        "event_devices": len(events),
        "readable_event_devices": sum(1 for p in events if os.access(p, os.R_OK)),
        "names": names,
    }


def _secure_boot_state() -> str:
    if shutil.which("mokutil") is not None:
        _, text = _run(["mokutil", "--sb-state"])
        low = text.lower()
        if "secureboot enabled" in low or "secure boot enabled" in low:
            return "enabled"
        if "secureboot disabled" in low or "secure boot disabled" in low:
            return "disabled"
    return "unknown" if Path("/sys/firmware/efi").exists() else "not_efi_or_unavailable"


def _selinux_state() -> str:
    if shutil.which("getenforce") is not None:
        _, text = _run(["getenforce"])
        return text or "unknown"
    return "present_unknown" if Path("/sys/fs/selinux").exists() else "unavailable"


def _power_profile() -> str:
    if shutil.which("powerprofilesctl") is None:
        return "unavailable"
    _, text = _run(["powerprofilesctl", "get"])
    return text or "unknown"


def _power_supply_states() -> tuple[str, str]:
    root = Path("/sys/class/power_supply")
    ac = "unknown"
    battery = "none"
    try:
        entries = list(root.iterdir())
    except OSError:
        return ac, battery

    for dev in entries:
        typ = _read_text(dev / "type")
        if typ in {"Mains", "USB", "USB_C"}:
            online = _read_text(dev / "online")
            if online == "1":
                ac = "online"
            elif online == "0" and ac != "online":
                ac = "offline"
        elif typ == "Battery":
            battery = _read_text(dev / "status") or "unknown"
    return ac, battery


def collect_facts() -> dict[str, Any]:
    osr = _parse_os_release(_read_text(Path("/etc/os-release")))
    vulkan_tool, vulkan_status = _vulkan_probe()
    home = Path(os.environ.get("HOME", "/"))
    ac_state, battery_status = _power_supply_states()

    return {
        "schema_version": 1,
        "phase": "P01",
        "read_only": True,
        "host": {
            "os_id": osr.get("ID", "unknown"),
            "os_version_id": osr.get("VERSION_ID", "unknown"),
            "os_pretty_name": osr.get("PRETTY_NAME", "unknown"),
            "os_variant_id": osr.get("VARIANT_ID", "unknown"),
            "kernel": platform.release() or "unknown",
            "arch": platform.machine() or "unknown",
        },
        "session": {
            "type": os.environ.get("XDG_SESSION_TYPE", "unknown"),
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP", "unknown"),
            "wayland_display": bool(os.environ.get("WAYLAND_DISPLAY")),
            "x11_display": bool(os.environ.get("DISPLAY")),
        },
        "cpu": {
            "model": _cpu_model(),
            "logical_cpus": os.cpu_count() or 0,
            "memory_kib": _memory_kib(),
        },
        "gpus": _collect_gpus(),
        "graphics": {
            "nvidia_module_version": _read_text(Path("/sys/module/nvidia/version")) or "none",
            "vulkan_icds": _collect_vulkan_icds(),
            "vulkan_tool_available": vulkan_tool,
            "vulkan_probe": vulkan_status,
        },
        "steam": _detect_steam(),
        "filesystems": {
            "root": _mount_fact(Path("/")),
            "home": _mount_fact(home),
        },
        "audio": {
            "pipewire_version": _version_line("pipewire", "--version"),
            "wireplumber_version": _version_line("wireplumber", "--version"),
            "pipewire_service": _user_service_state("pipewire.service"),
            "wireplumber_service": _user_service_state("wireplumber.service"),
        },
        "input": _collect_input(),
        "security": {
            "secure_boot": _secure_boot_state(),
            "selinux": _selinux_state(),
        },
        "power": {
            "profile": _power_profile(),
            "ac_state": ac_state,
            "battery_status": battery_status,
        },
        "privacy": {
            "hostname_collected": False,
            "serials_collected": False,
            "network_identifiers_collected": False,
            "user_paths_emitted": False,
        },
    }


def _yn(value: bool) -> str:
    return "YES" if value else "NO"


def render_text(r: dict[str, Any]) -> str:
    lines = [
        "LGD_FACTS_SCHEMA=1",
        "LGD_PHASE=P01",
        "LGD_READ_ONLY=true",
        f"OS_ID={r['host']['os_id']}",
        f"OS_VERSION={r['host']['os_version_id']}",
        f"OS_PRETTY={r['host']['os_pretty_name']}",
        f"KERNEL={r['host']['kernel']}",
        f"ARCH={r['host']['arch']}",
        f"SESSION={r['session']['type']}",
        f"DESKTOP={r['session']['desktop']}",
        f"GPU_COUNT={len(r['gpus'])}",
    ]
    for i, gpu in enumerate(r["gpus"]):
        lines.append(
            f"GPU_{i}={gpu['vendor']} vendor_id={gpu['vendor_id']} "
            f"device_id={gpu['device_id']} driver={gpu['driver']} "
            f"class={gpu['class']} pci={gpu['pci']}"
        )
    lines += [
        f"NVIDIA_MODULE={r['graphics']['nvidia_module_version']}",
        f"VULKAN_TOOL={_yn(r['graphics']['vulkan_tool_available'])}",
        f"VULKAN_PROBE={r['graphics']['vulkan_probe']}",
        f"VULKAN_ICDS={len(r['graphics']['vulkan_icds'])}",
        f"STEAM_NATIVE={_yn(r['steam']['native'])}",
        f"STEAM_FLATPAK_USER={_yn(r['steam']['flatpak_user'])}",
        f"STEAM_FLATPAK_SYSTEM={_yn(r['steam']['flatpak_system'])}",
        f"ROOT_FS={r['filesystems']['root']['fstype']}",
        f"HOME_FS={r['filesystems']['home']['fstype']}",
        f"PIPEWIRE_SERVICE={r['audio']['pipewire_service']}",
        f"WIREPLUMBER_SERVICE={r['audio']['wireplumber_service']}",
        f"INPUT_EVENT_DEVICES={r['input']['event_devices']}",
        f"INPUT_READABLE_EVENT_DEVICES={r['input']['readable_event_devices']}",
        f"SECURE_BOOT={r['security']['secure_boot']}",
        f"SELINUX={r['security']['selinux']}",
        f"POWER_PROFILE={r['power']['profile']}",
        f"AC_STATE={r['power']['ac_state']}",
        f"BATTERY_STATUS={r['power']['battery_status']}",
        "PRIVACY_HOSTNAME_COLLECTED=NO",
        "PRIVACY_SERIALS_COLLECTED=NO",
        "PRIVACY_NETWORK_IDENTIFIERS_COLLECTED=NO",
        "PRIVACY_USER_PATHS_EMITTED=NO",
        "P01_FACTS=PASS",
    ]
    return "\n".join(lines) + "\n"
