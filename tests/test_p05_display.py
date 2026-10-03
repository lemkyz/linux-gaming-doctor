import tempfile
import unittest
import json
import os
import subprocess
from pathlib import Path

from gaming_doctor.display import _drm_connectors, parse_kscreen_output, parse_xrandr_output


class KScreenParserTests(unittest.TestCase):
    def test_two_outputs_fractional_and_refresh(self):
        text = '''
Output: 1 eDP-1
    enabled
    connected
    Modes:  1:2560x1600@165*!  2:1920x1200@60
    Geometry: 0,0 2560x1600
    Scale: 1.25
    Rotation: 1
    Vrr: Automatic
    HDR: enabled
Output: 2 HDMI-A-1
    enabled
    connected
    Modes:  1:3840x2160@120*!  2:3840x2160@60
    Geometry: 2560,0 3840x2160
    Scale: 1
    Rotation: 1
    Vrr: Never
    HDR: disabled
'''
        out = parse_kscreen_output(text)
        self.assertEqual(2, len(out))
        self.assertEqual("eDP-1", out[0]["name"])
        self.assertEqual("2560x1600", out[0]["resolution"])
        self.assertAlmostEqual(165.0, out[0]["refresh_hz"])
        self.assertTrue(out[0]["fractional_scale"])
        self.assertEqual("enabled", out[0]["hdr"])
        self.assertEqual("3840x2160", out[1]["resolution"])
        self.assertAlmostEqual(120.0, out[1]["refresh_hz"])
        self.assertFalse(out[1]["fractional_scale"])


class XrandrParserTests(unittest.TestCase):
    def test_current_mode(self):
        text = '''eDP-1 connected primary 2560x1600+0+0
   2560x1600    165.00*+  60.00
HDMI-1 disconnected
'''
        out = parse_xrandr_output(text)
        self.assertEqual(2, len(out))
        self.assertTrue(out[0]["enabled"])
        self.assertEqual("2560x1600", out[0]["resolution"])
        self.assertAlmostEqual(165.0, out[0]["refresh_hz"])
        self.assertFalse(out[1]["connected"])


class DrmFixtureTests(unittest.TestCase):
    def test_connector_inventory_does_not_emit_edid_payload(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            conn = root / "card1-eDP-1"
            conn.mkdir(parents=True)
            (conn / "status").write_text("connected\n")
            (conn / "enabled").write_text("enabled\n")
            (conn / "modes").write_text("2560x1600\n1920x1200\n")
            (conn / "edid").write_bytes(b"SECRET-SERIAL-EDID")
            (conn / "vrr_capable").write_text("1\n")
            got = _drm_connectors(root)
            self.assertEqual(1, len(got))
            self.assertEqual("eDP-1", got[0]["name"])
            self.assertTrue(got[0]["edid_present"])
            self.assertTrue(got[0]["vrr_capable"])
            self.assertNotIn("SECRET", str(got))


class P05ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        bin_path = root / "bin" / "gaming-doctor"
        p = subprocess.run([str(bin_path), "display", "--json"], capture_output=True, text=True, check=True, timeout=40)
        cls.raw = p.stdout
        cls.data = json.loads(p.stdout)

    def test_header(self):
        self.assertEqual(1, self.data["schema_version"])
        self.assertEqual("P05", self.data["phase"])
        self.assertIs(self.data["read_only"], True)

    def test_counts(self):
        self.assertEqual(self.data["drm"]["connector_count"], len(self.data["drm"]["connectors"]))
        self.assertEqual(self.data["display"]["output_count"], len(self.data["display"]["outputs"]))
        self.assertEqual(self.data["finding_count"], len(self.data["findings"]))

    def test_privacy(self):
        home = os.environ.get("HOME", "")
        if home and home != "/":
            self.assertNotIn(home, self.raw)
        p = self.data["privacy"]
        self.assertFalse(p["absolute_paths_emitted"])
        self.assertFalse(p["environment_values_collected"])
        self.assertFalse(p["edid_payload_collected"])
        self.assertFalse(p["display_serials_collected"])


if __name__ == "__main__":
    unittest.main()
