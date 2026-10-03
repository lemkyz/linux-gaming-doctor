from __future__ import annotations

import argparse
import json

from . import __version__
from .facts import collect_facts, render_text as render_facts_text
from .steam import collect_steam_state, render_text as render_steam_text
from .packaging import collect_packaging_state, render_text as render_packaging_text


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gaming-doctor",
        description="Evidence-driven Linux gaming diagnostics. P03 remains read-only.",
    )
    p.add_argument("--version", action="version", version=f"gaming-doctor {__version__} (P03)")
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
    p.error("unsupported command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
