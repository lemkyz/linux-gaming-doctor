import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from gaming_doctor.facts import _gpu_vendor, _parse_os_release, render_text

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "gaming-doctor"


class P01UnitTests(unittest.TestCase):
    def test_os_release_parser(self):
        got = _parse_os_release('ID=fedora\nVERSION_ID=44\nPRETTY_NAME="Fedora Linux 44"\n')
        self.assertEqual("fedora", got["ID"])
        self.assertEqual("44", got["VERSION_ID"])
        self.assertEqual("Fedora Linux 44", got["PRETTY_NAME"])

    def test_gpu_vendor_mapping(self):
        self.assertEqual("NVIDIA", _gpu_vendor("0x10de"))
        self.assertEqual("AMD", _gpu_vendor("0x1002"))
        self.assertEqual("Intel", _gpu_vendor("0x8086"))
        self.assertEqual("Unknown", _gpu_vendor("0xffff"))

    def test_text_contract(self):
        sample = {
            "host": {"os_id": "fedora", "os_version_id": "44", "os_pretty_name": "Fedora Linux 44", "kernel": "x", "arch": "x86_64"},
            "session": {"type": "wayland", "desktop": "KDE"},
            "gpus": [],
            "graphics": {"nvidia_module_version": "none", "vulkan_tool_available": False, "vulkan_probe": "UNAVAILABLE", "vulkan_icds": []},
            "steam": {"native": True, "flatpak_user": False, "flatpak_system": False},
            "filesystems": {"root": {"fstype": "btrfs"}, "home": {"fstype": "btrfs"}},
            "audio": {"pipewire_service": "active", "wireplumber_service": "active"},
            "input": {"event_devices": 2, "readable_event_devices": 0},
            "security": {"secure_boot": "enabled", "selinux": "Enforcing"},
            "power": {"profile": "balanced", "ac_state": "online", "battery_status": "Charging"},
        }
        text = render_text(sample)
        self.assertIn("LGD_READ_ONLY=true", text)
        self.assertIn("P01_FACTS=PASS", text)


class P01ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([str(BIN), "facts", "--json"], check=True, capture_output=True, text=True, timeout=20)
        cls.raw = result.stdout
        cls.data = json.loads(result.stdout)

    def test_identity(self):
        self.assertEqual(1, self.data["schema_version"])
        self.assertEqual("P01", self.data["phase"])
        self.assertIs(self.data["read_only"], True)

    def test_required_subsystems(self):
        for key in ("host", "session", "cpu", "gpus", "graphics", "steam", "filesystems", "audio", "input", "security", "power", "privacy"):
            self.assertIn(key, self.data)

    def test_privacy_contract(self):
        p = self.data["privacy"]
        self.assertIs(p["hostname_collected"], False)
        self.assertIs(p["serials_collected"], False)
        self.assertIs(p["network_identifiers_collected"], False)
        self.assertIs(p["user_paths_emitted"], False)
        home = os.environ.get("HOME", "")
        if home and home != "/":
            self.assertNotIn(home, self.raw)


if __name__ == "__main__":
    unittest.main()
