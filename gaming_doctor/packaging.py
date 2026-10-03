from __future__ import annotations

import configparser
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .steam import parse_vdf

Runner = Callable[[list[str]], tuple[int, str, str]]


def _default_runner(argv: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=8.0, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return 127, "", ""
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _clean(value: object, limit: int = 160) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = text.replace("=", ":")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] if text else "unknown"


def _split_semicolon(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def _strip_flatpak_mode(token: str) -> str:
    # Flatpak filesystem tokens may carry :ro, :rw or :create suffixes.
    for suffix in (":ro", ":rw", ":create"):
        if token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def parse_flatpak_permissions(text: str) -> dict[str, Any]:
    parser = configparser.RawConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read_string(text or "")
    except (configparser.Error, ValueError):
        return {
            "shared_network": False,
            "shared_ipc": False,
            "socket_x11": False,
            "socket_wayland": False,
            "socket_pulseaudio": False,
            "socket_fallback_x11": False,
            "device_all": False,
            "device_dri": False,
            "filesystem_host": False,
            "filesystem_home": False,
            "filesystem_run_udev": False,
            "filesystem_external_absolute_count": 0,
            "filesystem_token_count": 0,
            "environment_override_count": 0,
            "environment_override_names": [],
            "_filesystem_tokens": [],
        }

    def get(section: str, key: str) -> list[str]:
        if not parser.has_section(section):
            return []
        try:
            return _split_semicolon(parser.get(section, key, fallback=""))
        except (configparser.Error, ValueError):
            return []

    shared = set(get("Context", "shared"))
    sockets = set(get("Context", "sockets"))
    devices = set(get("Context", "devices"))
    fs_raw = get("Context", "filesystems")
    fs_tokens = [_strip_flatpak_mode(x) for x in fs_raw]
    env_names: list[str] = []
    if parser.has_section("Environment"):
        env_names = sorted(_clean(k, 80) for k, _ in parser.items("Environment"))

    def fs_has(prefix: str) -> bool:
        return any(token == prefix or token.startswith(prefix + "/") for token in fs_tokens)

    external_absolute = [
        token for token in fs_tokens
        if token.startswith("/") and not token.startswith("/run/udev")
    ]
    return {
        "shared_network": "network" in shared,
        "shared_ipc": "ipc" in shared,
        "socket_x11": "x11" in sockets,
        "socket_wayland": "wayland" in sockets,
        "socket_pulseaudio": "pulseaudio" in sockets,
        "socket_fallback_x11": "fallback-x11" in sockets,
        "device_all": "all" in devices,
        "device_dri": "dri" in devices,
        "filesystem_host": "host" in fs_tokens or "host-os" in fs_tokens,
        "filesystem_home": "home" in fs_tokens,
        "filesystem_run_udev": fs_has("/run/udev") or fs_has("/run/udev/data"),
        "filesystem_external_absolute_count": len(external_absolute),
        "filesystem_token_count": len(fs_tokens),
        "environment_override_count": len(env_names),
        "environment_override_names": env_names,
        # Internal-only raw category input. collect_packaging_state removes it before output.
        "_filesystem_tokens": fs_tokens,
    }


def _path_allowed_by_flatpak(path: Path, fs_tokens: list[str], home: Path) -> bool:
    try:
        resolved = path.resolve(strict=False)
    except OSError:
        resolved = path
    text = str(resolved)
    home_text = str(home)

    normalized = [_strip_flatpak_mode(token) for token in fs_tokens]
    if "host" in normalized:
        return True
    if "home" in normalized and (text == home_text or text.startswith(home_text.rstrip("/") + "/")):
        return True

    # Flatpak app-private HOME is inherently visible to the app.
    app_home = home / ".var/app/com.valvesoftware.Steam"
    app_home_text = str(app_home)
    if text == app_home_text or text.startswith(app_home_text.rstrip("/") + "/"):
        return True

    for token in normalized:
        if not token.startswith("/"):
            continue
        prefix = token.rstrip("/") or "/"
        if text == prefix or text.startswith(prefix + "/"):
            return True
    return False


def _nvidia_runtime_ids(version: str) -> tuple[str, str]:
    normalized = re.sub(r"[^0-9]+", "-", version.strip()).strip("-")
    if not normalized:
        return "", ""
    return (
        f"org.freedesktop.Platform.GL.nvidia-{normalized}",
        f"org.freedesktop.Platform.GL32.nvidia-{normalized}",
    )


def _host_nvidia_version() -> str:
    for path in (Path("/sys/module/nvidia/version"), Path("/proc/driver/nvidia/version")):
        try:
            text = path.read_text(errors="replace")[:4096]
        except OSError:
            continue
        if path.name == "version":
            value = text.strip().splitlines()[0] if text.strip() else ""
            if value:
                return _clean(value, 80)
        match = re.search(r"Kernel Module\s+([0-9][0-9A-Za-z._-]*)", text)
        if match:
            return _clean(match.group(1), 80)
    return "unknown"


def _package_system() -> str:
    if shutil.which("rpm"):
        return "rpm"
    if shutil.which("dpkg-query"):
        return "dpkg"
    if shutil.which("pacman"):
        return "pacman"
    return "unknown"


def _native_steam(runner: Runner) -> dict[str, Any]:
    executable = shutil.which("steam")
    package_system = _package_system()
    result: dict[str, Any] = {
        "present": bool(executable),
        "launcher_on_path": bool(executable),
        "package_system": package_system,
        "package_owned": False,
        "package_name": "unknown",
        "package_version": "unknown",
        "package_arch": "unknown",
    }
    if not executable:
        return result

    if package_system == "rpm":
        rc, out, _ = runner(["rpm", "-qf", "--qf", "%{NAME}|%{VERSION}-%{RELEASE}|%{ARCH}", executable])
        if rc == 0 and "|" in out:
            parts = out.split("|", 2)
            if len(parts) == 3:
                result.update(
                    package_owned=True,
                    package_name=_clean(parts[0], 80),
                    package_version=_clean(parts[1], 120),
                    package_arch=_clean(parts[2], 40),
                )
    elif package_system == "dpkg":
        rc, out, _ = runner(["dpkg-query", "-S", executable])
        if rc == 0 and ":" in out:
            package = out.split(":", 1)[0].strip()
            rc2, ver, _ = runner(["dpkg-query", "-W", "-f=${Version}|${Architecture}", package])
            parts = ver.split("|", 1) if rc2 == 0 else []
            result.update(
                package_owned=True,
                package_name=_clean(package, 80),
                package_version=_clean(parts[0], 120) if parts else "unknown",
                package_arch=_clean(parts[1], 40) if len(parts) == 2 else "unknown",
            )
    elif package_system == "pacman":
        rc, out, _ = runner(["pacman", "-Qo", executable])
        match = re.search(r" is owned by ([^ ]+) ([^ ]+)", out) if rc == 0 else None
        if match:
            result.update(
                package_owned=True,
                package_name=_clean(match.group(1), 80),
                package_version=_clean(match.group(2), 120),
                package_arch="unknown",
            )
    return result


def _flatpak_list(runner: Runner, scope: str, kind: str) -> list[dict[str, str]]:
    flag = "--user" if scope == "user" else "--system"
    type_flag = "--app" if kind == "app" else "--runtime"
    rc, out, _ = runner(["flatpak", "list", flag, type_flag, "--columns=application,branch,runtime"])
    if rc != 0 or not out:
        return []
    rows: list[dict[str, str]] = []
    for line in out.splitlines():
        cols = line.split("\t")
        if not cols or not cols[0].strip():
            continue
        rows.append(
            {
                "application": _clean(cols[0], 160),
                "branch": _clean(cols[1], 60) if len(cols) > 1 else "unknown",
                "runtime": _clean(cols[2], 180) if len(cols) > 2 else "unknown",
            }
        )
    return rows


def _flatpak_permissions(runner: Runner, scope: str) -> dict[str, Any]:
    flag = "--user" if scope == "user" else "--system"
    rc, out, _ = runner(["flatpak", "info", flag, "--show-permissions", "com.valvesoftware.Steam"])
    return parse_flatpak_permissions(out if rc == 0 else "")


def _flatpak_library_paths(home: Path) -> list[Path]:
    roots = [
        home / ".var/app/com.valvesoftware.Steam/.local/share/Steam",
        home / ".var/app/com.valvesoftware.Steam/data/Steam",
    ]
    paths: list[Path] = []
    for root in roots:
        vdf = root / "steamapps/libraryfolders.vdf"
        try:
            text = vdf.read_text(errors="replace")[:4_000_000]
        except OSError:
            continue
        parsed = parse_vdf(text)
        node = parsed.get("libraryfolders", {}) if isinstance(parsed, dict) else {}
        if not isinstance(node, dict):
            continue
        for key, entry in node.items():
            if not str(key).isdigit():
                continue
            value = entry.get("path", "") if isinstance(entry, dict) else entry
            if not isinstance(value, str) or not value.strip():
                continue
            paths.append(Path(value.replace("\\\\", "\\")))
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def collect_packaging_state(runner: Runner | None = None) -> dict[str, Any]:
    run = runner or _default_runner
    home = Path(os.environ.get("HOME", "/"))
    native = _native_steam(run)
    flatpak_cli = shutil.which("flatpak") is not None
    host_nvidia = _host_nvidia_version()
    findings: list[dict[str, Any]] = []

    flatpak_installations: list[dict[str, Any]] = []
    runtime_ids: set[str] = set()
    for scope in ("user", "system"):
        apps = _flatpak_list(run, scope, "app") if flatpak_cli else []
        runtimes = _flatpak_list(run, scope, "runtime") if flatpak_cli else []
        runtime_ids.update(row["application"] for row in runtimes)
        steam_rows = [row for row in apps if row["application"] == "com.valvesoftware.Steam"]
        for row in steam_rows:
            permissions = _flatpak_permissions(run, scope)
            fs_tokens = list(permissions.pop("_filesystem_tokens", []))
            flatpak_installations.append(
                {
                    "scope": scope,
                    "branch": row["branch"],
                    "runtime": row["runtime"],
                    "permissions": permissions,
                    "_filesystem_tokens": fs_tokens,
                }
            )

    if native["present"] and flatpak_installations:
        findings.append(
            {
                "code": "MULTIPLE_STEAM_PACKAGING_MODELS",
                "severity": "info",
                "classification": "WORKAROUND",
                "scope": "steam",
                "evidence": "Native and Flatpak Steam are both installed; runtime, library and permission state can diverge between them",
            }
        )

    if native["present"] and not native["package_owned"]:
        findings.append(
            {
                "code": "NATIVE_STEAM_PACKAGE_OWNER_UNKNOWN",
                "severity": "info",
                "classification": "UNKNOWN",
                "scope": "native",
                "evidence": "Steam is on PATH but the detected package manager did not identify an owning package",
            }
        )

    external_library_count = 0
    declared_external_library_count = 0
    undeclared_external_library_count = 0
    flatpak_libraries = _flatpak_library_paths(home) if flatpak_installations else []
    # Apply the union of visible filesystem declarations across installed Steam Flatpaks.
    all_fs_tokens: list[str] = []
    for item in flatpak_installations:
        all_fs_tokens.extend(item.get("_filesystem_tokens", []))
    for path in flatpak_libraries:
        app_home = home / ".var/app/com.valvesoftware.Steam"
        try:
            inside_app_home = path.resolve(strict=False).is_relative_to(app_home.resolve(strict=False))
        except (AttributeError, OSError):
            p = str(path)
            a = str(app_home)
            inside_app_home = p == a or p.startswith(a.rstrip("/") + "/")
        if inside_app_home:
            continue
        external_library_count += 1
        if _path_allowed_by_flatpak(path, all_fs_tokens, home):
            declared_external_library_count += 1
        else:
            undeclared_external_library_count += 1

    if undeclared_external_library_count:
        findings.append(
            {
                "code": "FLATPAK_STEAM_LIBRARY_PERMISSION_GAP",
                "severity": "warning",
                "classification": "REPAIRABLE",
                "scope": "flatpak",
                "evidence": f"{undeclared_external_library_count} configured external Steam library path(s) are not covered by discovered Flatpak filesystem declarations",
            }
        )

    nvidia_gl = "unknown"
    nvidia_gl32 = "unknown"
    if flatpak_installations and host_nvidia != "unknown":
        gl_id, gl32_id = _nvidia_runtime_ids(host_nvidia)
        nvidia_gl = "present" if gl_id in runtime_ids else "missing"
        nvidia_gl32 = "present" if gl32_id in runtime_ids else "missing"
        if nvidia_gl == "missing" or nvidia_gl32 == "missing":
            findings.append(
                {
                    "code": "FLATPAK_NVIDIA_RUNTIME_MISMATCH",
                    "severity": "warning",
                    "classification": "REPAIRABLE",
                    "scope": "flatpak",
                    "evidence": "Steam Flatpak is installed but a host-driver-matched NVIDIA GL/GL32 runtime extension was not discovered",
                }
            )

    # Strip internal raw permission tokens before returning the privacy-preserving report.
    for item in flatpak_installations:
        item.pop("_filesystem_tokens", None)

    findings.sort(key=lambda x: (x["severity"], x["code"]))
    user_count = sum(1 for x in flatpak_installations if x["scope"] == "user")
    system_count = sum(1 for x in flatpak_installations if x["scope"] == "system")
    return {
        "schema_version": 1,
        "phase": "P03",
        "read_only": True,
        "packaging": {
            "host_package_system": _package_system(),
            "native_steam": native,
            "flatpak_cli_present": flatpak_cli,
            "flatpak_steam_installation_count": len(flatpak_installations),
            "flatpak_steam_user_count": user_count,
            "flatpak_steam_system_count": system_count,
            "flatpak_steam_installations": flatpak_installations,
            "flatpak_runtime_count": len(runtime_ids),
            "flatpak_external_library_count": external_library_count,
            "flatpak_declared_external_library_count": declared_external_library_count,
            "flatpak_undeclared_external_library_count": undeclared_external_library_count,
            "host_nvidia_version": host_nvidia,
            "flatpak_nvidia_gl_runtime": nvidia_gl,
            "flatpak_nvidia_gl32_runtime": nvidia_gl32,
            "finding_count": len(findings),
            "findings": findings,
        },
        "privacy": {
            "absolute_paths_emitted": False,
            "flatpak_filesystem_paths_emitted": False,
            "environment_values_collected": False,
            "account_identifiers_collected": False,
            "tokens_collected": False,
        },
    }


def _yn(value: bool) -> str:
    return "YES" if value else "NO"


def render_text(report: dict[str, Any]) -> str:
    p = report["packaging"]
    native = p["native_steam"]
    lines = [
        "LGD_PACKAGING_SCHEMA=1",
        "LGD_PHASE=P03",
        "LGD_READ_ONLY=true",
        f"HOST_PACKAGE_SYSTEM={_clean(p['host_package_system'])}",
        f"STEAM_NATIVE_PRESENT={_yn(native['present'])}",
        f"STEAM_NATIVE_PACKAGE_MANAGER={_clean(native['package_system'])}",
        f"STEAM_NATIVE_PACKAGE_OWNED={_yn(native['package_owned'])}",
        f"STEAM_NATIVE_PACKAGE={_clean(native['package_name'])}",
        f"STEAM_NATIVE_VERSION={_clean(native['package_version'])}",
        f"STEAM_NATIVE_ARCH={_clean(native['package_arch'])}",
        f"FLATPAK_CLI={_yn(p['flatpak_cli_present'])}",
        f"FLATPAK_STEAM_INSTALLATIONS={p['flatpak_steam_installation_count']}",
        f"FLATPAK_STEAM_USER={p['flatpak_steam_user_count']}",
        f"FLATPAK_STEAM_SYSTEM={p['flatpak_steam_system_count']}",
        f"FLATPAK_RUNTIMES={p['flatpak_runtime_count']}",
        f"FLATPAK_EXTERNAL_LIBRARIES={p['flatpak_external_library_count']}",
        f"FLATPAK_UNDECLARED_EXTERNAL_LIBRARIES={p['flatpak_undeclared_external_library_count']}",
        f"HOST_NVIDIA_VERSION={_clean(p['host_nvidia_version'])}",
        f"FLATPAK_NVIDIA_GL={_clean(p['flatpak_nvidia_gl_runtime'])}",
        f"FLATPAK_NVIDIA_GL32={_clean(p['flatpak_nvidia_gl32_runtime'])}",
    ]
    for idx, item in enumerate(p["flatpak_steam_installations"][:4]):
        perm = item["permissions"]
        lines.append(
            "FLATPAK_STEAM_%d=scope:%s branch:%s runtime:%s network:%s wayland:%s x11:%s audio:%s device_all:%s udev:%s fs_host:%s fs_home:%s external_fs:%d"
            % (
                idx,
                _clean(item["scope"]),
                _clean(item["branch"]),
                _clean(item["runtime"]),
                _yn(perm["shared_network"]),
                _yn(perm["socket_wayland"]),
                _yn(perm["socket_x11"] or perm["socket_fallback_x11"]),
                _yn(perm["socket_pulseaudio"]),
                _yn(perm["device_all"]),
                _yn(perm["filesystem_run_udev"]),
                _yn(perm["filesystem_host"]),
                _yn(perm["filesystem_home"]),
                perm["filesystem_external_absolute_count"],
            )
        )
    lines.append(f"PACKAGING_FINDINGS={p['finding_count']}")
    for idx, finding in enumerate(p["findings"][:12]):
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
            "PRIVACY_FLATPAK_FILESYSTEM_PATHS_EMITTED=NO",
            "PRIVACY_ENVIRONMENT_VALUES_COLLECTED=NO",
            "P03_PACKAGING=PASS",
        ]
    )
    return "\n".join(lines) + "\n"
