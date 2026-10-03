import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from gaming_doctor.steam import _tool_aliases, parse_vdf, collect_steam_state

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "gaming-doctor"


class VDFTests(unittest.TestCase):
    def test_parser_handles_nested_keyvalues_and_comments(self):
        data = parse_vdf('''
        // comment
        "root" { "name" "hello world" "child" { "x" "1" } }
        ''')
        self.assertEqual("hello world", data["root"]["name"])
        self.assertEqual("1", data["root"]["child"]["x"])

    def test_proton_aliases(self):
        self.assertIn("proton_experimental", _tool_aliases("Proton - Experimental", []))
        self.assertIn("proton_10", _tool_aliases("Proton 10.0", []))
        self.assertIn("GE-Proton10-20", _tool_aliases("GE-Proton10-20", ["GE-Proton10-20"]))


class FixtureDiscoveryTests(unittest.TestCase):
    def _fixture(self, base: Path, selected: str = "proton_experimental", add_tool: bool = True) -> Path:
        root = base / "Steam"
        (root / "steamapps/common/Devil May Cry 5").mkdir(parents=True)
        (root / "steamapps/compatdata/601150/pfx/drive_c").mkdir(parents=True)
        (root / "steamapps/compatdata/601150/pfx/system.reg").write_text("REGEDIT4\n")
        (root / "config").mkdir(parents=True)
        (root / "steamapps/libraryfolders.vdf").write_text(
            f'"libraryfolders" {{ "0" {{ "path" "{root}" }} }}\n'
        )
        (root / "steamapps/appmanifest_601150.acf").write_text('''
        "AppState"
        {
          "appid" "601150"
          "name" "Devil May Cry 5"
          "StateFlags" "4"
          "installdir" "Devil May Cry 5"
          "buildid" "123"
        }
        ''')
        (root / "config/config.vdf").write_text(f'''
        "InstallConfigStore" {{ "Software" {{ "Valve" {{ "Steam" {{
          "CompatToolMapping" {{ "601150" {{ "name" "{selected}" }} }}
        }} }} }} }}
        ''')
        if add_tool:
            tool = root / "steamapps/common/Proton - Experimental"
            tool.mkdir(parents=True)
            (tool / "version").write_text("proton-experimental-test\n")
            (tool / "compatibilitytool.vdf").write_text('''
            "compatibilitytools" { "proton_experimental" { "install_path" "." } }
            ''')
        return root

    def test_discovers_game_tool_and_healthy_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._fixture(Path(td))
            r = collect_steam_state([("native", root)])
            s = r["steam"]
            self.assertEqual(1, s["installation_count"])
            self.assertEqual(1, s["library_count"])
            self.assertEqual(1, s["app_count"])
            self.assertEqual("601150", s["apps"][0]["appid"])
            self.assertEqual("healthy", s["apps"][0]["prefix"]["status"])
            self.assertEqual("proton_experimental", s["apps"][0]["compat_tool"])
            codes = {f["code"] for f in s["findings"]}
            self.assertNotIn("SELECTED_COMPAT_TOOL_NOT_DISCOVERED", codes)

    def test_missing_selected_tool_is_evidence_backed_finding(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._fixture(Path(td), selected="proton_999", add_tool=False)
            r = collect_steam_state([("native", root)])
            matches = [f for f in r["steam"]["findings"] if f["code"] == "SELECTED_COMPAT_TOOL_NOT_DISCOVERED"]
            self.assertEqual(1, len(matches))
            self.assertEqual("601150", matches[0]["appid"])

    def test_incomplete_existing_prefix_is_distinguished_from_absent_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._fixture(Path(td))
            (root / "steamapps/compatdata/601150/pfx/system.reg").unlink()
            r = collect_steam_state([("native", root)])
            self.assertEqual("incomplete", r["steam"]["apps"][0]["prefix"]["status"])
            self.assertIn("PREFIX_INCOMPLETE", {f["code"] for f in r["steam"]["findings"]})


class P02ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = subprocess.run([str(BIN), "steam", "--json"], capture_output=True, text=True, check=True, timeout=30)
        cls.raw = p.stdout
        cls.data = json.loads(p.stdout)

    def test_contract_header(self):
        self.assertEqual(1, self.data["schema_version"])
        self.assertEqual("P02", self.data["phase"])
        self.assertIs(self.data["read_only"], True)

    def test_counts_match_arrays(self):
        s = self.data["steam"]
        self.assertEqual(s["library_count"], len(s["libraries"]))
        self.assertEqual(s["app_count"], len(s["apps"]))
        self.assertEqual(s["compat_tool_count"], len(s["compat_tools"]))
        self.assertEqual(s["finding_count"], len(s["findings"]))

    def test_no_home_path_leak(self):
        home = os.environ.get("HOME", "")
        if home and home != "/":
            self.assertNotIn(home, self.raw)


if __name__ == "__main__":
    unittest.main()
