from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable

Runner = Callable[[list[str]], tuple[int, str, str]]

HEROIC_FLATPAK = "com.heroicgameslauncher.hgl"
LUTRIS_FLATPAK = "net.lutris.Lutris"


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


def _clean(value: object, limit: int = 120) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = " ".join(text.split()).replace("=", ":")
    return text[:limit] if text else "unknown"


def _path_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip().strip('"').strip("'")
    if not value or "\x00" in value:
        return None
    return value


def _flatpak_scope(runner: Runner, app_id: str) -> dict[str, Any]:
    tool = shutil.which("flatpak")
    if not tool:
        return {"cli_present": False, "user": False, "system": False}
    user_rc, _, _ = runner([tool, "info", "--user", app_id])
    system_rc, _, _ = runner([tool, "info", "--system", app_id])
    return {"cli_present": True, "user": user_rc == 0, "system": system_rc == 0}


def _binary_state(candidates: Iterable[str]) -> dict[str, Any]:
    for name in candidates:
        path = shutil.which(name)
        if path:
            return {"present": True, "binary": name}
    return {"present": False, "binary": "none"}


def _read_json(path: Path, limit: int = 8_000_000) -> Any:
    try:
        if path.stat().st_size > limit:
            return None
        return json.loads(path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _first_string(record: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    lower = {str(k).lower(): v for k, v in record.items()}
    for key in keys:
        value = lower.get(key.lower())
        s = _path_string(value)
        if s:
            return s
    return None


def parse_heroic_records(value: Any) -> list[dict[str, str]]:
    install_keys = (
        "install_path", "installpath", "installlocation", "install_location",
        "path", "installpathstring",
    )
    prefix_keys = ("wineprefix", "wine_prefix", "prefix", "prefixpath", "prefix_path")
    exe_keys = ("executable", "exe", "launchexecutable", "executablepath", "executable_path")
    runner_keys = ("wineversion", "wine_version", "runner", "runnername", "runner_name")

    out: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for record in _walk_dicts(value):
        install = _first_string(record, install_keys)
        prefix = _first_string(record, prefix_keys)
        exe = _first_string(record, exe_keys)
        runner = _first_string(record, runner_keys)
        if not any((install, prefix, exe, runner)):
            continue

        # Require at least one path-like field or a runner plus another field.
        pathish = any(
            x and ("/" in x or "\\" in x or x.startswith("~"))
            for x in (install, prefix, exe)
        )
        if not pathish and not (runner and any((install, prefix, exe))):
            continue

        item = {
            "install": install or "",
            "prefix": prefix or "",
            "executable": exe or "",
            "runner": runner or "",
        }
        key = (item["install"], item["prefix"], item["executable"], item["runner"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def parse_lutris_yaml(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    stack: list[tuple[int, str]] = []

    for raw in (text or "").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()

        if not value:
            stack.append((indent, key))
            continue

        path = ".".join([x[1] for x in stack] + [key])
        value = value.strip('"').strip("'")
        if path in {
            "game.exe", "game.prefix", "game.working_dir",
            "runner", "wine.version", "game.arch", "game.args",
        }:
            result[path] = value
    return result


def executable_kind(path: Path) -> str:
    try:
        with path.open("rb") as fh:
            head = fh.read(4)
    except OSError:
        return "unavailable"
    if head.startswith(b"\x7fELF"):
        return "elf"
    if head[:2] == b"MZ":
        return "pe"
    return "other"


def _absolute_existing(value: str) -> tuple[bool | None, Path | None]:
    s = _path_string(value)
    if not s:
        return None, None
    expanded = Path(os.path.expanduser(s))
    if not expanded.is_absolute():
        return None, None
    return expanded.exists(), expanded


def _runner_token(value: str) -> str:
    if not value:
        return "unknown"
    token = Path(value).name if ("/" in value or "\\" in value) else value
    token = token.lower()
    token = re.sub(r"[^a-z0-9._+-]+", "-", token)
    return _clean(token, 80)


def _compat_runner(token: str) -> bool:
    low = (token or "").lower()
    return any(x in low for x in ("wine", "proton", "umu", "caffe", "lutris-ge", "ge-proton"))


def _resolve_executable(install: str, executable: str) -> tuple[bool | None, Path | None]:
    e = _path_string(executable)
    if not e:
        return None, None
    exe = Path(os.path.expanduser(e))
    if exe.is_absolute():
        return exe.exists(), exe
    i = _path_string(install)
    if not i:
        return None, None
    base = Path(os.path.expanduser(i))
    if not base.is_absolute():
        return None, None
    candidate = base / exe
    return candidate.exists(), candidate


def _heroic_roots(home: Path) -> list[Path]:
    return [
        home / ".config/heroic",
        home / ".var/app/com.heroicgameslauncher.hgl/config/heroic",
    ]


def _bounded_installed_json(root: Path) -> list[Path]:
    out: list[Path] = []
    if not root.is_dir():
        return out
    root_depth = len(root.parts)
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            if len(current.parts) - root_depth >= 6:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d not in {"Cache", "GPUCache", "Code Cache", "node_modules"}][:64]
            for name in filenames:
                if name.lower() == "installed.json":
                    out.append(current / name)
                    if len(out) >= 64:
                        return out
    except OSError:
        pass
    return out


def _heroic_logs(root: Path) -> dict[str, int]:
    total = 0
    count = 0
    largest = 0
    if not root.is_dir():
        return {"file_count": 0, "total_bytes": 0, "largest_bytes": 0}
    root_depth = len(root.parts)
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            depth = len(current.parts) - root_depth
            if depth >= 6:
                dirnames[:] = []
            # Only descend broadly until a logs/log directory; cache trees are irrelevant.
            dirnames[:] = [d for d in dirnames if d not in {"Cache", "GPUCache", "Code Cache", "node_modules"}][:64]
            if "log" not in current.name.lower():
                continue
            for name in filenames[:512]:
                path = current / name
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                count += 1
                total += size
                largest = max(largest, size)
                if count >= 4096:
                    return {"file_count": count, "total_bytes": total, "largest_bytes": largest}
    except OSError:
        pass
    return {"file_count": count, "total_bytes": total, "largest_bytes": largest}


def _collect_heroic(runner: Runner, home: Path) -> dict[str, Any]:
    flatpak = _flatpak_scope(runner, HEROIC_FLATPAK)
    binary = _binary_state(("heroic", "heroic-games-launcher"))
    roots = [p for p in _heroic_roots(home) if p.exists()]
    manifest_count = 0
    parse_failures = 0
    records: list[dict[str, Any]] = []
    logs = {"file_count": 0, "total_bytes": 0, "largest_bytes": 0}

    for root in roots:
        log_state = _heroic_logs(root)
        logs["file_count"] += log_state["file_count"]
        logs["total_bytes"] += log_state["total_bytes"]
        logs["largest_bytes"] = max(logs["largest_bytes"], log_state["largest_bytes"])

        for manifest in _bounded_installed_json(root):
            manifest_count += 1
            data = _read_json(manifest)
            if data is None:
                parse_failures += 1
                continue
            for raw in parse_heroic_records(data):
                install_exists, _ = _absolute_existing(raw["install"])
                prefix_exists, _ = _absolute_existing(raw["prefix"])
                exe_exists, exe_path = _resolve_executable(raw["install"], raw["executable"])
                kind = executable_kind(exe_path) if exe_exists is True and exe_path is not None else "unavailable"
                records.append({
                    "install_configured": bool(raw["install"]),
                    "install_exists": install_exists,
                    "prefix_configured": bool(raw["prefix"]),
                    "prefix_exists": prefix_exists,
                    "executable_configured": bool(raw["executable"]),
                    "executable_exists": exe_exists,
                    "executable_kind": kind,
                    "runner": _runner_token(raw["runner"]),
                })

    return {
        "present": binary["present"] or flatpak["user"] or flatpak["system"] or bool(roots),
        "binary": binary,
        "flatpak": flatpak,
        "config_root_count": len(roots),
        "installed_manifest_count": manifest_count,
        "manifest_parse_failures": parse_failures,
        "record_count": len(records),
        "records": records,
        "logs": logs,
    }


def _lutris_config_roots(home: Path) -> list[Path]:
    return [
        home / ".config/lutris/games",
        home / ".var/app/net.lutris.Lutris/config/lutris/games",
    ]


def _collect_lutris(runner: Runner, home: Path) -> dict[str, Any]:
    flatpak = _flatpak_scope(runner, LUTRIS_FLATPAK)
    binary = _binary_state(("lutris",))
    roots = [p for p in _lutris_config_roots(home) if p.is_dir()]
    configs: list[dict[str, Any]] = []
    parse_failures = 0

    for root in roots:
        try:
            files = sorted(list(root.glob("*.yml")) + list(root.glob("*.yaml")))[:2048]
        except OSError:
            files = []
        for path in files:
            try:
                text = path.read_text(errors="replace")[:2_000_000]
            except OSError:
                parse_failures += 1
                continue
            parsed = parse_lutris_yaml(text)
            runner_token = _runner_token(parsed.get("runner", ""))
            prefix = parsed.get("game.prefix", "")
            exe = parsed.get("game.exe", "")
            prefix_exists, prefix_path = _absolute_existing(prefix)
            exe_exists, exe_path = _absolute_existing(exe)
            if exe_exists is None and exe and prefix_path is not None:
                candidate = prefix_path / exe
                exe_exists = candidate.exists()
                exe_path = candidate
            kind = executable_kind(exe_path) if exe_exists is True and exe_path is not None else "unavailable"
            configs.append({
                "runner": runner_token,
                "prefix_configured": bool(prefix),
                "prefix_exists": prefix_exists,
                "executable_configured": bool(exe),
                "executable_exists": exe_exists,
                "executable_kind": kind,
                "wine_version": _runner_token(parsed.get("wine.version", "")),
            })

    return {
        "present": binary["present"] or flatpak["user"] or flatpak["system"] or bool(roots),
        "binary": binary,
        "flatpak": flatpak,
        "config_root_count": len(roots),
        "config_count": len(configs),
        "config_parse_failures": parse_failures,
        "configs": configs,
    }


def _tool_state(runner: Runner, name: str, version_args: list[str] | None = None) -> dict[str, Any]:
    path = shutil.which(name)
    if not path:
        return {"present": False, "version_status": "unavailable", "version": "unknown"}
    args = version_args or ["--version"]
    rc, out, err = runner([path, *args])
    first = (out or err).splitlines()[0] if (out or err) else "unknown"
    return {
        "present": True,
        "version_status": "pass" if rc == 0 else "fail",
        "version": _clean(first, 100),
    }


def collect_launcher_state(runner: Runner | None = None) -> dict[str, Any]:
    run = runner or _default_runner
    home = Path(os.environ.get("HOME", "/"))
    heroic = _collect_heroic(run, home)
    lutris = _collect_lutris(run, home)
    tools = {
        "umu_run": _tool_state(run, "umu-run"),
        "wine": _tool_state(run, "wine"),
        "winetricks": _tool_state(run, "winetricks"),
        "protontricks": _tool_state(run, "protontricks"),
    }
    findings: list[dict[str, str]] = []

    for idx, record in enumerate(heroic["records"]):
        scope = f"heroic_record_{idx}"
        if record["install_configured"] and record["install_exists"] is False:
            findings.append({
                "code": "HEROIC_INSTALL_PATH_MISSING",
                "severity": "warning",
                "classification": "REPAIRABLE",
                "scope": scope,
                "evidence": "Heroic metadata contains an absolute install path that does not exist",
            })
        if record["prefix_configured"] and record["prefix_exists"] is False:
            findings.append({
                "code": "HEROIC_PREFIX_PATH_MISSING",
                "severity": "warning",
                "classification": "REPAIRABLE",
                "scope": scope,
                "evidence": "Heroic metadata contains an absolute prefix path that does not exist",
            })
        if record["executable_configured"] and record["executable_exists"] is False:
            findings.append({
                "code": "HEROIC_EXECUTABLE_MISSING",
                "severity": "warning",
                "classification": "REPAIRABLE",
                "scope": scope,
                "evidence": "Heroic metadata resolves an executable path that does not exist",
            })
        if record["executable_kind"] == "elf" and _compat_runner(record["runner"]):
            findings.append({
                "code": "HEROIC_NATIVE_ELF_WITH_COMPAT_RUNNER",
                "severity": "warning",
                "classification": "REPAIRABLE",
                "scope": scope,
                "evidence": "Heroic metadata resolves an ELF executable while a Wine/Proton/UMU-like runner token is configured",
            })

    if heroic["logs"]["largest_bytes"] >= 512 * 1024 * 1024 or heroic["logs"]["total_bytes"] >= 1024 * 1024 * 1024:
        findings.append({
            "code": "HEROIC_LOG_STORAGE_EXCESSIVE",
            "severity": "warning",
            "classification": "REPAIRABLE",
            "scope": "heroic_logs",
            "evidence": "Heroic log storage exceeds 1 GiB total or contains a log at least 512 MiB",
        })

    for idx, cfg in enumerate(lutris["configs"]):
        scope = f"lutris_config_{idx}"
        if cfg["prefix_configured"] and cfg["prefix_exists"] is False:
            findings.append({
                "code": "LUTRIS_PREFIX_PATH_MISSING",
                "severity": "warning",
                "classification": "REPAIRABLE",
                "scope": scope,
                "evidence": "Lutris config contains an absolute prefix path that does not exist",
            })
        if cfg["executable_configured"] and cfg["executable_exists"] is False:
            findings.append({
                "code": "LUTRIS_EXECUTABLE_MISSING",
                "severity": "warning",
                "classification": "REPAIRABLE",
                "scope": scope,
                "evidence": "Lutris config resolves an executable path that does not exist",
            })
        if cfg["executable_kind"] == "elf" and _compat_runner(cfg["runner"]):
            findings.append({
                "code": "LUTRIS_NATIVE_ELF_WITH_COMPAT_RUNNER",
                "severity": "warning",
                "classification": "REPAIRABLE",
                "scope": scope,
                "evidence": "Lutris config resolves an ELF executable while a Wine/Proton/UMU-like runner is selected",
            })

    findings.sort(key=lambda x: ({"error": 0, "warning": 1, "info": 2}.get(x["severity"], 9), x["code"], x["scope"]))

    return {
        "schema_version": 1,
        "phase": "P10",
        "read_only": True,
        "heroic": heroic,
        "lutris": lutris,
        "tools": tools,
        "finding_count": len(findings),
        "findings": findings,
        "privacy": {
            "absolute_paths_emitted": False,
            "game_titles_emitted": False,
            "account_identifiers_collected": False,
            "launcher_tokens_collected": False,
            "raw_config_emitted": False,
            "raw_logs_emitted": False,
            "environment_values_collected": False,
            "network_identifiers_collected": False,
        },
    }


def _yn(value: bool | None) -> str:
    if value is None:
        return "UNKNOWN"
    return "YES" if value else "NO"


def render_text(report: dict[str, Any]) -> str:
    h = report["heroic"]
    l = report["lutris"]
    t = report["tools"]
    lines = [
        "LGD_LAUNCHER_SCHEMA=1",
        "LGD_PHASE=P10",
        "LGD_READ_ONLY=true",
        f"HEROIC_PRESENT={_yn(h['present'])}",
        f"HEROIC_NATIVE_BINARY={_yn(h['binary']['present'])}",
        f"HEROIC_FLATPAK_USER={_yn(h['flatpak']['user'])}",
        f"HEROIC_FLATPAK_SYSTEM={_yn(h['flatpak']['system'])}",
        f"HEROIC_CONFIG_ROOTS={h['config_root_count']}",
        f"HEROIC_INSTALLED_MANIFESTS={h['installed_manifest_count']}",
        f"HEROIC_MANIFEST_PARSE_FAILURES={h['manifest_parse_failures']}",
        f"HEROIC_RECORDS={h['record_count']}",
        f"HEROIC_LOG_FILES={h['logs']['file_count']}",
        f"HEROIC_LOG_TOTAL_MIB={h['logs']['total_bytes'] / (1024**2):.3f}",
        f"HEROIC_LOG_LARGEST_MIB={h['logs']['largest_bytes'] / (1024**2):.3f}",
    ]
    for idx, record in enumerate(h["records"][:24]):
        lines.append(
            "HEROIC_RECORD_%d=install_configured:%s install_exists:%s prefix_configured:%s prefix_exists:%s executable_configured:%s executable_exists:%s executable_kind:%s runner:%s"
            % (
                idx,
                _yn(record["install_configured"]),
                _yn(record["install_exists"]),
                _yn(record["prefix_configured"]),
                _yn(record["prefix_exists"]),
                _yn(record["executable_configured"]),
                _yn(record["executable_exists"]),
                _clean(record["executable_kind"], 20),
                _clean(record["runner"], 80),
            )
        )

    lines.extend([
        f"LUTRIS_PRESENT={_yn(l['present'])}",
        f"LUTRIS_NATIVE_BINARY={_yn(l['binary']['present'])}",
        f"LUTRIS_FLATPAK_USER={_yn(l['flatpak']['user'])}",
        f"LUTRIS_FLATPAK_SYSTEM={_yn(l['flatpak']['system'])}",
        f"LUTRIS_CONFIG_ROOTS={l['config_root_count']}",
        f"LUTRIS_CONFIGS={l['config_count']}",
        f"LUTRIS_CONFIG_PARSE_FAILURES={l['config_parse_failures']}",
    ])
    for idx, cfg in enumerate(l["configs"][:24]):
        lines.append(
            "LUTRIS_CONFIG_%d=runner:%s wine_version:%s prefix_configured:%s prefix_exists:%s executable_configured:%s executable_exists:%s executable_kind:%s"
            % (
                idx,
                _clean(cfg["runner"], 80),
                _clean(cfg["wine_version"], 80),
                _yn(cfg["prefix_configured"]),
                _yn(cfg["prefix_exists"]),
                _yn(cfg["executable_configured"]),
                _yn(cfg["executable_exists"]),
                _clean(cfg["executable_kind"], 20),
            )
        )

    for label, key in (
        ("UMU_RUN", "umu_run"),
        ("WINE", "wine"),
        ("WINETRICKS", "winetricks"),
        ("PROTONTRICKS", "protontricks"),
    ):
        tool = t[key]
        lines.extend([
            f"{label}={_yn(tool['present'])}",
            f"{label}_VERSION_STATUS={_clean(tool['version_status']).upper()}",
            f"{label}_VERSION={_clean(tool['version'], 100)}",
        ])

    lines.append(f"LAUNCHER_FINDINGS={report['finding_count']}")
    for idx, finding in enumerate(report["findings"][:32]):
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
        "PRIVACY_GAME_TITLES_EMITTED=NO",
        "PRIVACY_ACCOUNT_IDENTIFIERS_COLLECTED=NO",
        "PRIVACY_RAW_CONFIG_EMITTED=NO",
        "PRIVACY_RAW_LOGS_EMITTED=NO",
        "P10_LAUNCHERS=PASS",
    ])
    return "\n".join(lines) + "\n"
