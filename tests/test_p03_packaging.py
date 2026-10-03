import json
import os
import subprocess
import unittest
from pathlib import Path

from gaming_doctor.packaging import (
    _nvidia_runtime_ids,
    _path_allowed_by_flatpak,
    parse_flatpak_permissions,
)

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "gaming-doctor"


class PermissionParserTests(unittest.TestCase):
    def test_parses_flatpak_context_without_emitting_values(self):
        p = parse_flatpak_permissions('''
[Context]
shared=network;ipc;
sockets=x11;wayland;pulseaudio;
devices=all;
filesystems=home;/run/udev:ro;/mnt/Games:rw;
[Environment]
FOO=secret-value
BAR=another-secret
''')
        self.assertTrue(p["shared_network"])
        self.assertTrue(p["socket_wayland"])
        self.assertTrue(p["socket_pulseaudio"])
        self.assertTrue(p["device_all"])
        self.assertTrue(p["filesystem_home"])
        self.assertTrue(p["filesystem_run_udev"])
        self.assertEqual(1, p["filesystem_external_absolute_count"])
        self.assertEqual(["BAR", "FOO"], p["environment_override_names"])
        self.assertNotIn("secret-value", json.dumps(p))

    def test_external_path_permission_matching(self):
        home = Path("/home/tester")
        self.assertTrue(_path_allowed_by_flatpak(Path("/mnt/Games/Steam"), ["/mnt/Games:rw"], home))
        self.assertFalse(_path_allowed_by_flatpak(Path("/games/Steam"), ["/mnt/Games:rw"], home))
        self.assertTrue(_path_allowed_by_flatpak(Path("/home/tester/Games"), ["home"], home))

    def test_nvidia_extension_id(self):
        gl, gl32 = _nvidia_runtime_ids("615.71.09")
        self.assertEqual("org.freedesktop.Platform.GL.nvidia-615-71-09", gl)
        self.assertEqual("org.freedesktop.Platform.GL32.nvidia-615-71-09", gl32)


class P03ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = subprocess.run([str(BIN), "packaging", "--json"], capture_output=True, text=True, check=True, timeout=30)
        cls.raw = p.stdout
        cls.data = json.loads(p.stdout)

    def test_header(self):
        self.assertEqual(1, self.data["schema_version"])
        self.assertEqual("P03", self.data["phase"])
        self.assertIs(self.data["read_only"], True)

    def test_counts(self):
        p = self.data["packaging"]
        self.assertEqual(p["flatpak_steam_installation_count"], len(p["flatpak_steam_installations"]))
        self.assertEqual(p["finding_count"], len(p["findings"]))

    def test_privacy(self):
        home = os.environ.get("HOME", "")
        if home and home != "/":
            self.assertNotIn(home, self.raw)
        self.assertNotIn("_filesystem_tokens", self.raw)
        self.assertFalse(self.data["privacy"]["absolute_paths_emitted"])


if __name__ == "__main__":
    unittest.main()
