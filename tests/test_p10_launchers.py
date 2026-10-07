import json
import os
import tempfile
import unittest
from pathlib import Path

from gaming_doctor.launchers import (
    executable_kind,
    parse_heroic_records,
    parse_lutris_yaml,
)

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "gaming-doctor"


class LauncherParserTests(unittest.TestCase):
    def test_heroic_record_parser(self):
        data = {
            "game": {
                "install_path": "/games/Test",
                "winePrefix": "/prefixes/Test",
                "executable": "Game.exe",
                "wineVersion": "Proton-GE",
                "title": "PRIVATE TITLE",
                "accountId": "PRIVATE ACCOUNT",
            }
        }
        rows = parse_heroic_records(data)
        self.assertEqual(1, len(rows))
        self.assertEqual("/games/Test", rows[0]["install"])
        self.assertEqual("/prefixes/Test", rows[0]["prefix"])
        self.assertEqual("Game.exe", rows[0]["executable"])
        self.assertEqual("Proton-GE", rows[0]["runner"])
        self.assertNotIn("PRIVATE TITLE", str(rows))
        self.assertNotIn("PRIVATE ACCOUNT", str(rows))

    def test_lutris_yaml_parser(self):
        data = parse_lutris_yaml(
            "runner: wine\n"
            "game:\n"
            "  exe: /games/foo/Game.exe\n"
            "  prefix: /prefix/foo\n"
            "wine:\n"
            "  version: wine-ge-8-26\n"
            "system:\n"
            "  env:\n"
            "    SECRET_TOKEN: abc\n"
        )
        self.assertEqual("wine", data["runner"])
        self.assertEqual("/games/foo/Game.exe", data["game.exe"])
        self.assertEqual("/prefix/foo", data["game.prefix"])
        self.assertEqual("wine-ge-8-26", data["wine.version"])
        self.assertNotIn("SECRET_TOKEN", data)

    def test_executable_magic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            elf = root / "native"
            pe = root / "windows.exe"
            elf.write_bytes(b"\x7fELF" + b"x" * 8)
            pe.write_bytes(b"MZ" + b"x" * 8)
            self.assertEqual("elf", executable_kind(elf))
            self.assertEqual("pe", executable_kind(pe))


class P10ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess
        p = subprocess.run(
            [str(BIN), "launchers", "--json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=50,
        )
        cls.raw = p.stdout
        cls.data = json.loads(p.stdout)

    def test_header(self):
        self.assertEqual(1, self.data["schema_version"])
        self.assertEqual("P10", self.data["phase"])
        self.assertIs(self.data["read_only"], True)

    def test_counts(self):
        h = self.data["heroic"]
        l = self.data["lutris"]
        self.assertEqual(h["record_count"], len(h["records"]))
        self.assertEqual(l["config_count"], len(l["configs"]))
        self.assertEqual(self.data["finding_count"], len(self.data["findings"]))

    def test_privacy(self):
        home = os.environ.get("HOME", "")
        if home and home != "/":
            self.assertNotIn(home, self.raw)
        p = self.data["privacy"]
        for key in (
            "absolute_paths_emitted",
            "game_titles_emitted",
            "account_identifiers_collected",
            "launcher_tokens_collected",
            "raw_config_emitted",
            "raw_logs_emitted",
            "environment_values_collected",
            "network_identifiers_collected",
        ):
            self.assertFalse(p[key])


if __name__ == "__main__":
    unittest.main()
