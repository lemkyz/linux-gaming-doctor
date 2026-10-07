from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from .steam import _discover_roots, _library_paths, _parse_manifest

Runner = Callable[[list[str]], tuple[int, str, str]]

WINDOWS_SHARED_FS = {"ntfs", "ntfs3", "fuseblk", "exfat", "vfat"}
NATIVE_LINUX_FS = {"btrfs", "ext2", "ext3", "ext4", "xfs", "f2fs", "bcachefs"}
NETWORK_FS = {"nfs", "nfs4", "cifs", "smb3", "sshfs", "9p"}
MEMORY_FS = {"tmpfs", "ramfs"}


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


def filesystem_kind(fstype: str) -> str:
    fs = (fstype or "unknown").lower()
    if fs in WINDOWS_SHARED_FS:
        return "windows_shared"
    if fs in NATIVE_LINUX_FS:
        return "native_linux"
    if fs in NETWORK_FS or fs.startswith("fuse.sshfs"):
        return "network"
    if fs in MEMORY_FS:
        return "memory"
    return "unknown"


def parse_mount_line(text: str) -> dict[str, Any]:
    line = (text or "").strip().splitlines()
    if not line:
        return {
            "fstype": "unknown",
            "kind": "unknown",
            "read_only": None,
            "noexec": None,
            "nodev": None,
            "nosuid": None,
            "discard": None,
            "compressed": None,
        }
    parts = line[0].split(None, 1)
    fstype = parts[0].lower() if parts else "unknown"
    options = set((parts[1] if len(parts) > 1 else "").split(",")) - {""}
    return {
        "fstype": _clean(fstype, 40).lower(),
        "kind": filesystem_kind(fstype),
        "read_only": True if "ro" in options else False if "rw" in options else None,
        "noexec": True if "noexec" in options else False if options else None,
        "nodev": True if "nodev" in options else False if options else None,
        "nosuid": True if "nosuid" in options else False if options else None,
        "discard": True if any(x == "discard" or x.startswith("discard=") for x in options) else False if options else None,
        "compressed": True if any(x.startswith("compress") for x in options) else False if options else None,
    }


def _mount_fact(path: Path, runner: Runner) -> dict[str, Any]:
    tool = shutil.which("findmnt")
    if not tool:
        return parse_mount_line("")
    rc, out, _ = runner([tool, "-n", "-o", "FSTYPE,OPTIONS", "-T", str(path)])
    return parse_mount_line(out if rc == 0 else "")


def _space_fact(path: Path) -> dict[str, Any]:
    try:
        st = os.statvfs(path)
    except OSError:
        return {
            "available": False,
            "total_bytes": 0,
            "free_bytes": 0,
            "free_pct": None,
            "inode_total": 0,
            "inode_free": 0,
            "inode_free_pct": None,
        }
    total = int(st.f_blocks * st.f_frsize)
    free = int(st.f_bavail * st.f_frsize)
    inode_total = int(st.f_files)
    inode_free = int(st.f_favail)
    return {
        "available": True,
        "total_bytes": total,
        "free_bytes": free,
        "free_pct": round((free / total) * 100.0, 3) if total else None,
        "inode_total": inode_total,
        "inode_free": inode_free,
        "inode_free_pct": round((inode_free / inode_total) * 100.0, 3) if inode_total else None,
    }


def _same_device(a: Path, b: Path) -> bool | None:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return None


def _host_target(name: str, path: Path, runner: Runner) -> dict[str, Any]:
    return {
        "id": name,
        "mount": _mount_fact(path, runner),
        "space": _space_fact(path),
    }


def _library_metrics(path: Path, runner: Runner, library_id: str) -> dict[str, Any]:
    steamapps = path / "steamapps"
    compatdata = steamapps / "compatdata"
    mount = _mount_fact(path, runner)
    space = _space_fact(path)
    compat_mount = _mount_fact(compatdata if compatdata.exists() else steamapps if steamapps.exists() else path, runner)

    app_count = 0
    max_install_path_chars = 0
    max_install_component_chars = 0
    manifests_unreadable = 0
    try:
        manifests = sorted(steamapps.glob("appmanifest_*.acf"))
    except OSError:
        manifests = []
    for manifest_path in manifests:
        manifest = _parse_manifest(manifest_path)
        if manifest is None:
            manifests_unreadable += 1
            continue
        app_count += 1
        installdir = str(manifest.get("installdir", ""))
        install_path = steamapps / "common" / installdir
        max_install_path_chars = max(max_install_path_chars, len(str(install_path)))
        max_install_component_chars = max(max_install_component_chars, len(installdir))

    return {
        "id": library_id,
        "exists": path.exists(),
        "steamapps_present": steamapps.is_dir(),
        "compatdata_present": compatdata.is_dir(),
        "mount": mount,
        "compatdata_mount": compat_mount,
        "compatdata_same_device_as_library": _same_device(path, compatdata) if compatdata.exists() else None,
        "space": space,
        "app_count": app_count,
        "unreadable_manifest_count": manifests_unreadable,
        "max_install_path_chars": max_install_path_chars,
        "max_install_component_chars": max_install_component_chars,
    }


def _space_findings(scope: str, space: dict[str, Any]) -> list[dict[str, str]]:
    if not space["available"]:
        return []
    findings: list[dict[str, str]] = []
    free = int(space["free_bytes"])
    free_pct = space["free_pct"]
    gib = 1024 ** 3
    if free < 2 * gib or (isinstance(free_pct, (int, float)) and free_pct < 2.0):
        findings.append({
            "code": "FILESYSTEM_FREE_SPACE_CRITICAL",
            "severity": "warning",
            "classification": "REPAIRABLE",
            "scope": scope,
            "evidence": "Filesystem has less than 2 GiB available or less than 2% free space",
        })
    elif free < 10 * gib or (isinstance(free_pct, (int, float)) and free_pct < 5.0):
        findings.append({
            "code": "FILESYSTEM_FREE_SPACE_LOW",
            "severity": "info",
            "classification": "WORKAROUND",
            "scope": scope,
            "evidence": "Filesystem has less than 10 GiB available or less than 5% free space",
        })
    inode_total = int(space["inode_total"])
    inode_free = int(space["inode_free"])
    inode_pct = space["inode_free_pct"]
    if inode_total > 0 and (inode_free < 1024 or (isinstance(inode_pct, (int, float)) and inode_pct < 1.0)):
        findings.append({
            "code": "FILESYSTEM_INODES_CRITICALLY_LOW",
            "severity": "warning",
            "classification": "REPAIRABLE",
            "scope": scope,
            "evidence": "Filesystem inode availability is below 1024 entries or below 1%",
        })
    return findings


def collect_storage_state(runner: Runner | None = None) -> dict[str, Any]:
    run = runner or _default_runner
    home = Path(os.environ.get("HOME", "/"))
    host = {
        "root": _host_target("root", Path("/"), run),
        "home": _host_target("home", home, run),
        "root_home_same_device": _same_device(Path("/"), home),
    }

    libraries: list[dict[str, Any]] = []
    seen: set[str] = set()
    library_index = 0
    for steam_root in _discover_roots():
        for path in _library_paths(steam_root.path):
            try:
                key = str(path.resolve(strict=False))
            except OSError:
                key = str(path)
            if key in seen:
                continue
            seen.add(key)
            libraries.append(_library_metrics(path, run, f"library_{library_index}"))
            library_index += 1

    findings: list[dict[str, str]] = []
    findings.extend(_space_findings("home", host["home"]["space"]))

    for lib in libraries:
        scope = lib["id"]
        mount = lib["mount"]
        compat_mount = lib["compatdata_mount"]

        findings.extend(_space_findings(scope, lib["space"]))

        if mount["read_only"] is True:
            findings.append({
                "code": "STEAM_LIBRARY_READ_ONLY",
                "severity": "warning",
                "classification": "REPAIRABLE",
                "scope": scope,
                "evidence": "Steam library mount is read-only",
            })
        if mount["noexec"] is True:
            findings.append({
                "code": "STEAM_LIBRARY_NOEXEC",
                "severity": "warning",
                "classification": "REPAIRABLE",
                "scope": scope,
                "evidence": "Steam library mount has noexec; native runtimes and helper executables can fail",
            })
        if mount["kind"] == "windows_shared":
            findings.append({
                "code": "STEAM_LIBRARY_WINDOWS_SHARED_FILESYSTEM",
                "severity": "info",
                "classification": "WORKAROUND",
                "scope": scope,
                "evidence": f"Steam library filesystem is {mount['fstype']}; Proton prefix semantics require extra scrutiny",
            })
        if lib["compatdata_present"] and compat_mount["kind"] == "windows_shared":
            findings.append({
                "code": "COMPATDATA_WINDOWS_SHARED_FILESYSTEM",
                "severity": "warning",
                "classification": "WORKAROUND",
                "scope": scope,
                "evidence": f"Existing compatdata resolves to a {compat_mount['fstype']} filesystem",
            })
        if lib["max_install_path_chars"] >= 240:
            findings.append({
                "code": "HOST_INSTALL_PATH_VERY_LONG",
                "severity": "info",
                "classification": "UNKNOWN",
                "scope": scope,
                "evidence": f"At least one host install path is {lib['max_install_path_chars']} characters; application-specific path assumptions require differential verification",
            })
        if lib["max_install_component_chars"] >= 240:
            findings.append({
                "code": "INSTALL_DIRECTORY_COMPONENT_VERY_LONG",
                "severity": "warning",
                "classification": "REPAIRABLE",
                "scope": scope,
                "evidence": f"An install directory component is {lib['max_install_component_chars']} characters long",
            })

    findings.sort(key=lambda x: ({"error": 0, "warning": 1, "info": 2}.get(x["severity"], 9), x["code"], x["scope"]))

    return {
        "schema_version": 1,
        "phase": "P09",
        "read_only": True,
        "host_filesystems": host,
        "steam_storage": {
            "library_count": len(libraries),
            "libraries": libraries,
            "windows_shared_library_count": sum(1 for x in libraries if x["mount"]["kind"] == "windows_shared"),
            "read_only_library_count": sum(1 for x in libraries if x["mount"]["read_only"] is True),
            "noexec_library_count": sum(1 for x in libraries if x["mount"]["noexec"] is True),
        },
        "finding_count": len(findings),
        "findings": findings,
        "privacy": {
            "absolute_paths_emitted": False,
            "mount_sources_emitted": False,
            "mount_targets_emitted": False,
            "usernames_collected": False,
            "volume_labels_collected": False,
            "filesystem_uuids_collected": False,
            "device_serials_collected": False,
            "network_identifiers_collected": False,
            "tokens_collected": False,
        },
    }


def _yn(value: bool | None) -> str:
    if value is None:
        return "UNKNOWN"
    return "YES" if value else "NO"


def _mib(value: int) -> str:
    return f"{value / (1024 ** 2):.3f}"


def _pct(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.3f}"


def render_text(report: dict[str, Any]) -> str:
    host = report["host_filesystems"]
    steam = report["steam_storage"]
    lines = [
        "LGD_STORAGE_SCHEMA=1",
        "LGD_PHASE=P09",
        "LGD_READ_ONLY=true",
    ]
    for key in ("root", "home"):
        item = host[key]
        m = item["mount"]
        s = item["space"]
        lines.extend([
            f"{key.upper()}_FS={_clean(m['fstype'], 40)}",
            f"{key.upper()}_FS_KIND={_clean(m['kind'], 40)}",
            f"{key.upper()}_READ_ONLY={_yn(m['read_only'])}",
            f"{key.upper()}_NOEXEC={_yn(m['noexec'])}",
            f"{key.upper()}_FREE_MIB={_mib(s['free_bytes']) if s['available'] else 'unknown'}",
            f"{key.upper()}_FREE_PCT={_pct(s['free_pct'])}",
            f"{key.upper()}_INODE_FREE_PCT={_pct(s['inode_free_pct'])}",
        ])
    lines.append(f"ROOT_HOME_SAME_DEVICE={_yn(host['root_home_same_device'])}")
    lines.extend([
        f"STEAM_STORAGE_LIBRARIES={steam['library_count']}",
        f"STEAM_WINDOWS_SHARED_LIBRARIES={steam['windows_shared_library_count']}",
        f"STEAM_READ_ONLY_LIBRARIES={steam['read_only_library_count']}",
        f"STEAM_NOEXEC_LIBRARIES={steam['noexec_library_count']}",
    ])

    for idx, lib in enumerate(steam["libraries"][:24]):
        m = lib["mount"]
        cm = lib["compatdata_mount"]
        s = lib["space"]
        lines.append(
            "LIBRARY_%d=id:%s fs:%s kind:%s ro:%s noexec:%s free_mib:%s free_pct:%s apps:%d compatdata:%s compat_fs:%s compat_same_device:%s max_path_chars:%d max_component_chars:%d"
            % (
                idx,
                _clean(lib["id"], 40),
                _clean(m["fstype"], 40),
                _clean(m["kind"], 40),
                _yn(m["read_only"]),
                _yn(m["noexec"]),
                _mib(s["free_bytes"]) if s["available"] else "unknown",
                _pct(s["free_pct"]),
                lib["app_count"],
                _yn(lib["compatdata_present"]),
                _clean(cm["fstype"], 40),
                _yn(lib["compatdata_same_device_as_library"]),
                lib["max_install_path_chars"],
                lib["max_install_component_chars"],
            )
        )

    lines.append(f"STORAGE_FINDINGS={report['finding_count']}")
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
        "PRIVACY_MOUNT_SOURCES_EMITTED=NO",
        "PRIVACY_MOUNT_TARGETS_EMITTED=NO",
        "PRIVACY_VOLUME_LABELS_COLLECTED=NO",
        "PRIVACY_FILESYSTEM_UUIDS_COLLECTED=NO",
        "PRIVACY_DEVICE_SERIALS_COLLECTED=NO",
        "P09_STORAGE=PASS",
    ])
    return "\n".join(lines) + "\n"
