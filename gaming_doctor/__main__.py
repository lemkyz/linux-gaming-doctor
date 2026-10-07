from __future__ import annotations

import argparse
import json

from . import __version__
from .facts import collect_facts, render_text as render_facts_text
from .steam import collect_steam_state, render_text as render_steam_text
from .packaging import collect_packaging_state, render_text as render_packaging_text
from .gpu import collect_gpu_state, render_text as render_gpu_text
from .display import collect_display_state, render_text as render_display_text
from .performance import collect_performance_state, render_text as render_performance_text
from .audio import collect_audio_state, render_text as render_audio_text


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gaming-doctor",
        description="Evidence-driven Linux gaming diagnostics. P07 remains read-only.",
    )
    p.add_argument("--version", action="version", version=f"gaming-doctor {__version__} (P07)")
    sub = p.add_subparsers(dest="command")

    facts = sub.add_parser("facts", help="Collect the read-only system gaming baseline")
    facts.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    steam = sub.add_parser("steam", help="Inspect Steam libraries, Proton tools and prefixes")
    steam.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    packaging = sub.add_parser(
        "packaging",
        help="Inspect native/Flatpak Steam packaging and sandbox boundaries",
    )
    packaging.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    gpu = sub.add_parser(
        "gpu",
        help="Inspect GPU binding, Vulkan enumeration, ICDs and 32-bit runtime readiness",
    )
    gpu.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    display = sub.add_parser(
        "display",
        help="Inspect Wayland/X11, compositor outputs, DRM connectors, scaling, refresh, HDR/VRR and Gamescope",
    )
    display.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    performance = sub.add_parser(
        "performance",
        help="Inspect CPU frequency policy, pressure, memory, thermal, power and GPU performance telemetry",
    )
    performance.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    audio = sub.add_parser(
        "audio",
        help="Inspect PipeWire/WirePlumber, endpoints, Bluetooth profiles, clock settings and recent xrun evidence",
    )
    audio.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return p


def main() -> int:
    p = parser()
    args = p.parse_args()
    if args.command is None:
        p.print_help()
        return 0
    if args.command == "facts":
        report = collect_facts()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if args.json else render_facts_text(report), end="\n" if args.json else "")
        return 0
    if args.command == "steam":
        report = collect_steam_state()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if args.json else render_steam_text(report), end="\n" if args.json else "")
        return 0
    if args.command == "packaging":
        report = collect_packaging_state()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if args.json else render_packaging_text(report), end="\n" if args.json else "")
        return 0
    if args.command == "gpu":
        report = collect_gpu_state()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if args.json else render_gpu_text(report), end="\n" if args.json else "")
        return 0
    if args.command == "display":
        report = collect_display_state()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if args.json else render_display_text(report), end="\n" if args.json else "")
        return 0
    if args.command == "performance":
        report = collect_performance_state()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if args.json else render_performance_text(report), end="\n" if args.json else "")
        return 0
    if args.command == "audio":
        report = collect_audio_state()
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) if args.json else render_audio_text(report), end="\n" if args.json else "")
        return 0
    p.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
