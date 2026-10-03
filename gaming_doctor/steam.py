from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class SteamRoot:
    kind: str
    path: Path


def _read_text(path: Path, limit: int = 4_000_000) -> str:
    try:
        with path.open("r", errors="replace") as fh:
            return fh.read(limit)
    except (OSError, UnicodeError):
        return ""


def _safe(value: object, limit: int = 180) -> str:
    text = str(value)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = text.replace("=", ":")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] if text else "unknown"


def _run(argv: list[str], timeout: float = 4.0) -> tuple[bool, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return p.returncode == 0, (p.stdout.strip() or p.stderr.strip())


def _vdf_tokens(text: str) -> list[str]:
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if c in "{}":
            out.append(c)
            i += 1
            continue
        if c == '"':
            i += 1
            buf: list[str] = []
            while i < n:
                c = text[i]
                if c == '"':
                    i += 1
                    break
                if c == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    if nxt in {'"', "\\"}:
                        buf.append(nxt)
                        i += 2
                        continue
                buf.append(c)
                i += 1
            out.append("".join(buf))
            continue
        start = i
        while i < n and not text[i].isspace() and text[i] not in "{}":
            i += 1
        if i > start:
            out.append(text[start:i])
    return out


def parse_vdf(text: str) -> dict[str, Any]:
    tokens = _vdf_tokens(text)
    pos = 0

    def parse_object(stop_on_brace: bool = False) -> dict[str, Any]:
        nonlocal pos
        obj: dict[str, Any] = {}
        while pos < len(tokens):
            tok = tokens[pos]
            if tok == "}":
                if stop_on_brace:
                    pos += 1
                    return obj
                pos += 1
                continue
            if tok == "{":
                pos += 1
                continue
            key = tok
            pos += 1
            if pos >= len(tokens):
                obj[key] = ""
                break
            if tokens[pos] == "{":
                pos += 1
                obj[key] = parse_object(True)
            else:
                obj[key] = tokens[pos]
                pos += 1
        return obj

    return parse_object(False)


def _find_dict_by_key(value: Any, wanted: str) -> dict[str, Any] | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() == wanted.lower() and isinstance(child, dict):
                return child
            found = _find_dict_by_key(child, wanted)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_dict_by_key(child, wanted)
            if found is not None:
                return found
    return None


def _discover_roots() -> list[SteamRoot]:
    home = Path(os.environ.get("HOME", "/"))
    candidates = [
        ("native", home / ".local/share/Steam"),
        ("native", home / ".steam/steam"),
        ("native", home / ".local/share/steam"),
        ("flatpak", home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"),
        ("flatpak", home / ".var/app/com.valvesoftware.Steam/data/Steam"),
    ]
    seen: set[str] = set()
    out: list[SteamRoot] = []
    for kind, path in candidates:
        if not path.exists():
            continue
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(SteamRoot(kind=kind, path=path))
    return out


def _mount_fact(path: Path) -> dict[str, Any]:
    if shutil.which("findmnt") is None:
        return {"fstype": "unknown", "options": [], "shared_windows_fs": False}
    ok, text = _run(["findmnt", "-n", "-o", "FSTYPE,OPTIONS", "-T", str(path)])
    if not ok or not text:
        return {"fstype": "unknown", "options": [], "shared_windows_fs": False}
    parts = text.split(None, 1)
    fstype = parts[0].lower() if parts else "unknown"
    options = sorted(set((parts[1] if len(parts) > 1 else "").split(",")) - {""})
    windows = fstype in {"ntfs", "ntfs3", "fuseblk", "exfat", "vfat"}
    return {"fstype": fstype, "options": options, "shared_windows_fs": windows}


def _library_paths(root: Path) -> list[Path]:
    libs: list[Path] = [root]
    data = parse_vdf(_read_text(root / "steamapps/libraryfolders.vdf"))
    folders = _find_dict_by_key(data, "libraryfolders")
    if not folders:
        folders = data.get("libraryfolders") if isinstance(data.get("libraryfolders"), dict) else None
    if isinstance(folders, dict):
        for key, value in folders.items():
            if not str(key).isdigit() or not isinstance(value, dict):
                continue
            raw = value.get("path")
            if isinstance(raw, str) and raw:
                libs.append(Path(raw))
    dedup: list[Path] = []
    seen: set[str] = set()
    for lib in libs:
        try:
            key = str(lib.resolve())
        except OSError:
            key = str(lib)
        if key not in seen:
            seen.add(key)
            dedup.append(lib)
    return dedup


def _compat_mapping(root: Path) -> tuple[str, dict[str, str]]:
    config = parse_vdf(_read_text(root / "config/config.vdf"))
    mapping = _find_dict_by_key(config, "CompatToolMapping") or {}
    default = "auto"
    apps: dict[str, str] = {}
    for appid, value in mapping.items():
        if not isinstance(value, dict):
            continue
        name = value.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        if str(appid) == "0":
            default = name.strip()
        elif str(appid).isdigit():
            apps[str(appid)] = name.strip()
    return default, apps


def _tool_aliases(name: str, tokens: Iterable[str]) -> list[str]:
    aliases = {name}
    aliases.update(t for t in tokens if t)
    low = name.lower()
    if "experimental" in low and "proton" in low:
        aliases.add("proton_experimental")
    if "hotfix" in low and "proton" in low:
        aliases.add("proton_hotfix")
    m = re.search(r"proton\s*[- ]?([0-9]+)(?:\.[0-9]+)?", low)
    if m:
        aliases.add(f"proton_{m.group(1)}")
    return sorted(aliases)


def _extract_compat_tokens(path: Path) -> list[str]:
    data = parse_vdf(_read_text(path / "compatibilitytool.vdf"))
    node = _find_dict_by_key(data, "compatibilitytools")
    if not isinstance(node, dict):
        return []
    return [str(k) for k, v in node.items() if isinstance(v, dict)]


def _tool_version(path: Path) -> str:
    for filename in ("version", "proton", "CURRENT"):  # first useful metadata only
        p = path / filename
        if not p.is_file():
            continue
        text = _read_text(p, 2048).splitlines()
        if text:
            return _safe(text[0], 120)
    return "unknown"


def _collect_tools(root: Path, libraries: list[Path]) -> list[dict[str, Any]]:
    candidates: list[tuple[str, Path]] = []
    for base in [root / "compatibilitytools.d"]:
        try:
            for child in base.iterdir():
                if child.is_dir():
                    candidates.append(("custom", child))
        except OSError:
            pass
    for lib in libraries:
        common = lib / "steamapps/common"
        try:
            for child in common.iterdir():
                if child.is_dir() and child.name.lower().startswith("proton"):
                    candidates.append(("official", child))
        except OSError:
            pass

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kind, path in candidates:
        try:
            key = str(path.resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        tokens = _extract_compat_tokens(path)
        out.append(
            {
                "name": path.name,
                "kind": kind,
                "version": _tool_version(path),
                "aliases": _tool_aliases(path.name, tokens),
            }
        )
    return sorted(out, key=lambda x: (x["kind"], x["name"].lower()))


def _parse_manifest(path: Path) -> dict[str, str] | None:
    data = parse_vdf(_read_text(path))
    app = _find_dict_by_key(data, "AppState")
    if not isinstance(app, dict):
        return None
    appid = str(app.get("appid", "")).strip()
    if not appid.isdigit():
        return None
    return {
        "appid": appid,
        "name": str(app.get("name", "Unknown game")),
        "installdir": str(app.get("installdir", "")),
        "state_flags": str(app.get("StateFlags", app.get("stateflags", "unknown"))),
        "buildid": str(app.get("buildid", "unknown")),
    }


def _prefix_health(compat: Path) -> dict[str, Any]:
    if not compat.exists():
        return {"present": False, "pfx_present": False, "status": "absent"}
    pfx = compat / "pfx"
    if not pfx.exists():
        return {"present": True, "pfx_present": False, "status": "not_initialized"}
    drive_c = pfx / "drive_c"
    system_reg = pfx / "system.reg"
    user_reg = pfx / "user.reg"
    if drive_c.exists() and system_reg.exists():
        return {
            "present": True,
            "pfx_present": True,
            "status": "healthy",
            "drive_c": True,
            "system_reg": True,
            "user_reg": user_reg.exists(),
        }
    return {
        "present": True,
        "pfx_present": True,
        "status": "incomplete",
        "drive_c": drive_c.exists(),
        "system_reg": system_reg.exists(),
        "user_reg": user_reg.exists(),
    }


def _is_protonish(name: str) -> bool:
    low = name.lower()
    return "proton" in low or "wine" in low or low.startswith("ge-") or low.startswith("ge_")


def collect_steam_state(roots: list[tuple[str, Path]] | None = None) -> dict[str, Any]:
    root_objs = [SteamRoot(k, Path(p)) for k, p in roots] if roots is not None else _discover_roots()
    installations: list[dict[str, Any]] = []
    libraries_out: list[dict[str, Any]] = []
    apps_out: list[dict[str, Any]] = []
    tools_out: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    compatdata_ids: set[str] = set()
    manifest_ids: set[str] = set()
    installed_aliases: set[str] = set()
    default_tools: list[str] = []
    library_number = 0

    for root_index, steam_root in enumerate(root_objs):
        root = steam_root.path
        installation_id = f"steam_{root_index}"
        steamapps_present = (root / "steamapps").is_dir()
        config_present = (root / "config").is_dir()
        installations.append(
            {
                "id": installation_id,
                "kind": steam_root.kind,
                "steamapps_present": steamapps_present,
                "config_present": config_present,
                "healthy_layout": steamapps_present and config_present,
            }
        )
        if not steamapps_present:
            findings.append(
                {
                    "code": "STEAM_LAYOUT_INCOMPLETE",
                    "severity": "warning",
                    "classification": "REPAIRABLE",
                    "scope": installation_id,
                    "evidence": "Steam root exists but steamapps directory is missing",
                }
            )
            continue

        default_tool, app_mapping = _compat_mapping(root)
        default_tools.append(default_tool)
        libraries = _library_paths(root)
        tools = _collect_tools(root, libraries)
        for tool in tools:
            tagged = dict(tool)
            tagged["installation_id"] = installation_id
            tools_out.append(tagged)
            installed_aliases.update(a.lower() for a in tool["aliases"])

        for lib in libraries:
            library_id = f"library_{library_number}"
            library_number += 1
            exists = lib.exists()
            mount = _mount_fact(lib) if exists else {"fstype": "unknown", "options": [], "shared_windows_fs": False}
            manifests: list[Path] = []
            try:
                manifests = sorted((lib / "steamapps").glob("appmanifest_*.acf"))
            except OSError:
                pass
            lib_app_count = 0
            malformed = 0
            for manifest_path in manifests:
                manifest = _parse_manifest(manifest_path)
                if manifest is None:
                    malformed += 1
                    findings.append(
                        {
                            "code": "APP_MANIFEST_UNREADABLE",
                            "severity": "warning",
                            "classification": "REPAIRABLE",
                            "scope": library_id,
                            "evidence": "An appmanifest could not be parsed",
                        }
                    )
                    continue
                appid = manifest["appid"]
                if appid in manifest_ids:
                    findings.append(
                        {
                            "code": "DUPLICATE_APP_MANIFEST",
                            "severity": "warning",
                            "classification": "REPAIRABLE",
                            "scope": library_id,
                            "appid": appid,
                            "evidence": "The same AppID is represented by more than one discovered manifest",
                        }
                    )
                manifest_ids.add(appid)
                lib_app_count += 1
                explicit = app_mapping.get(appid)
                if explicit:
                    effective = explicit
                    tool_source = "app_override"
                elif default_tool != "auto":
                    effective = default_tool
                    tool_source = "global_default"
                else:
                    effective = "auto"
                    tool_source = "steam_auto"

                install_present = bool(manifest["installdir"]) and (lib / "steamapps/common" / manifest["installdir"]).exists()
                prefix = _prefix_health(lib / "steamapps/compatdata" / appid)
                if prefix["present"]:
                    compatdata_ids.add(appid)
                app_entry = {
                    "appid": appid,
                    "name": _safe(manifest["name"], 160),
                    "library_id": library_id,
                    "state_flags": _safe(manifest["state_flags"], 40),
                    "buildid": _safe(manifest["buildid"], 60),
                    "install_dir_present": install_present,
                    "compat_tool": effective,
                    "compat_tool_source": tool_source,
                    "prefix": prefix,
                }
                apps_out.append(app_entry)
                if not install_present:
                    findings.append(
                        {
                            "code": "INSTALL_DIRECTORY_MISSING",
                            "severity": "warning",
                            "classification": "REPAIRABLE",
                            "scope": library_id,
                            "appid": appid,
                            "evidence": "App manifest exists but its install directory is absent",
                        }
                    )
                if prefix.get("status") == "incomplete":
                    findings.append(
                        {
                            "code": "PREFIX_INCOMPLETE",
                            "severity": "warning",
                            "classification": "REPAIRABLE",
                            "scope": library_id,
                            "appid": appid,
                            "evidence": "A Proton pfx directory exists without the minimum Wine prefix structure",
                        }
                    )
                if effective != "auto" and _is_protonish(effective) and effective.lower() not in installed_aliases:
                    findings.append(
                        {
                            "code": "SELECTED_COMPAT_TOOL_NOT_DISCOVERED",
                            "severity": "warning",
                            "classification": "REPAIRABLE",
                            "scope": library_id,
                            "appid": appid,
                            "evidence": f"Selected compatibility tool token '{_safe(effective, 80)}' was not found in discovered tools",
                        }
                    )

            compat_root = lib / "steamapps/compatdata"
            try:
                for child in compat_root.iterdir():
                    if child.is_dir() and child.name.isdigit():
                        compatdata_ids.add(child.name)
            except OSError:
                pass

            if mount["shared_windows_fs"]:
                findings.append(
                    {
                        "code": "WINDOWS_SHARED_FILESYSTEM_LIBRARY",
                        "severity": "info",
                        "classification": "WORKAROUND",
                        "scope": library_id,
                        "evidence": f"Steam library filesystem is {mount['fstype']}; Proton prefixes on Windows-shared filesystems need extra scrutiny",
                    }
                )

            libraries_out.append(
                {
                    "id": library_id,
                    "installation_id": installation_id,
                    "exists": exists,
                    "filesystem": mount,
                    "app_count": lib_app_count,
                    "malformed_manifest_count": malformed,
                }
            )

    orphan_compatdata = sorted(compatdata_ids - manifest_ids, key=lambda x: int(x))
    if orphan_compatdata:
        findings.append(
            {
                "code": "STALE_COMPATDATA_PRESENT",
                "severity": "info",
                "classification": "WORKAROUND",
                "scope": "steam",
                "evidence": f"{len(orphan_compatdata)} compatdata directories have no currently discovered app manifest",
            }
        )

    # Stable order and dedup of tools from symlinked roots/libraries.
    tool_seen: set[tuple[str, str, tuple[str, ...]]] = set()
    unique_tools: list[dict[str, Any]] = []
    for tool in tools_out:
        key = (tool["kind"], tool["name"], tuple(tool["aliases"]))
        if key in tool_seen:
            continue
        tool_seen.add(key)
        unique_tools.append(tool)

    apps_out.sort(key=lambda x: int(x["appid"]))
    findings.sort(key=lambda x: (x["severity"], x["code"], x.get("appid", "")))
    shared_fs_count = sum(1 for lib in libraries_out if lib["filesystem"]["shared_windows_fs"])

    return {
        "schema_version": 1,
        "phase": "P02",
        "read_only": True,
        "steam": {
            "installation_count": len(installations),
            "installations": installations,
            "library_count": len(libraries_out),
            "libraries": libraries_out,
            "app_count": len(apps_out),
            "apps": apps_out,
            "compat_tool_count": len(unique_tools),
            "compat_tools": unique_tools,
            "compatdata_count": len(compatdata_ids),
            "orphan_compatdata_count": len(orphan_compatdata),
            "default_compat_tools": sorted(set(default_tools)) if default_tools else [],
            "shared_windows_filesystem_library_count": shared_fs_count,
            "finding_count": len(findings),
            "findings": findings,
        },
        "privacy": {
            "absolute_paths_emitted": False,
            "account_identifiers_collected": False,
            "tokens_collected": False,
            "network_identifiers_collected": False,
        },
    }


def render_text(report: dict[str, Any]) -> str:
    steam = report["steam"]
    findings = steam["findings"]
    missing_tools = sum(1 for f in findings if f["code"] == "SELECTED_COMPAT_TOOL_NOT_DISCOVERED")
    incomplete_prefixes = sum(1 for f in findings if f["code"] == "PREFIX_INCOMPLETE")
    missing_installs = sum(1 for f in findings if f["code"] == "INSTALL_DIRECTORY_MISSING")
    lines = [
        "LGD_STEAM_SCHEMA=1",
        "LGD_PHASE=P02",
        "LGD_READ_ONLY=true",
        f"STEAM_INSTALLATIONS={steam['installation_count']}",
        f"STEAM_LIBRARIES={steam['library_count']}",
        f"STEAM_APPS={steam['app_count']}",
        f"PROTON_TOOLS={steam['compat_tool_count']}",
        f"COMPATDATA_DIRS={steam['compatdata_count']}",
        f"ORPHAN_COMPATDATA={steam['orphan_compatdata_count']}",
        f"WINDOWS_SHARED_LIBRARIES={steam['shared_windows_filesystem_library_count']}",
        f"SELECTED_TOOL_MISSING={missing_tools}",
        f"INCOMPLETE_PREFIXES={incomplete_prefixes}",
        f"MISSING_INSTALL_DIRS={missing_installs}",
        f"STEAM_FINDINGS={steam['finding_count']}",
        "DEFAULT_COMPAT_TOOLS=" + (",".join(_safe(x, 80) for x in steam["default_compat_tools"]) or "auto"),
    ]
    for index, tool in enumerate(steam["compat_tools"][:20]):
        lines.append(
            f"PROTON_TOOL_{index}=name:{_safe(tool['name'])} kind:{tool['kind']} version:{_safe(tool['version'], 100)}"
        )
    lines.append(f"PROTON_TOOL_SAMPLE_COUNT={min(20, steam['compat_tool_count'])}")
    for index, app in enumerate(steam["apps"][:30]):
        lines.append(
            f"APP_{index}=appid:{app['appid']} name:{_safe(app['name'])} "
            f"tool:{_safe(app['compat_tool'], 80)} prefix:{app['prefix']['status']} "
            f"install:{'present' if app['install_dir_present'] else 'missing'}"
        )
    lines.append(f"APP_SAMPLE_COUNT={min(30, steam['app_count'])}")
    if steam["app_count"] > 30:
        lines.append(f"APP_SAMPLE_MORE={steam['app_count'] - 30}")
    for index, finding in enumerate(findings[:30]):
        scope = finding.get("appid", finding.get("scope", "steam"))
        lines.append(
            f"FINDING_{index}=severity:{finding['severity']} code:{finding['code']} "
            f"scope:{_safe(scope, 80)} class:{finding['classification']}"
        )
    lines += [
        f"FINDING_SAMPLE_COUNT={min(30, len(findings))}",
        "PRIVACY_ABSOLUTE_PATHS_EMITTED=NO",
        "PRIVACY_ACCOUNT_IDENTIFIERS_COLLECTED=NO",
        "PRIVACY_TOKENS_COLLECTED=NO",
        "P02_STEAM_PROTON=PASS",
    ]
    return "\n".join(lines) + "\n"
