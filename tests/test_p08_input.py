import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from gaming_doctor.input import (
    _device_scope_batteries,
    parse_proc_input_devices,
    parse_udev_properties,
)

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "gaming-doctor"


class InputParserTests(unittest.TestCase):
    def test_proc_parser_classifies_gamepad(self):
        text = """
I: Bus=0003 Vendor=045e Product=0b13 Version=0515
N: Name="Example Controller"
H: Handlers=event12 js0

I: Bus=0011 Vendor=0001 Product=0001 Version=ab41
N: Name="Keyboard"
H: Handlers=sysrq kbd event3
"""
        devices = parse_proc_input_devices(text)
        self.assertEqual(2, len(devices))
        self.assertIn("gamepad", devices[0]["classes"])
        self.assertEqual(["event12"], devices[0]["event_nodes"])
        self.assertIn("keyboard", devices[1]["classes"])

    def test_udev_parser_drops_raw_name_and_serial(self):
        data = parse_udev_properties(
            "ID_INPUT=1\nID_INPUT_JOYSTICK=1\nID_BUS=bluetooth\n"
            "ID_VENDOR_ID=054c\nID_MODEL_ID=0ce6\n"
            "ID_SERIAL=SHOULD_NOT_SURVIVE\nNAME=PRIVATE_NAME\n"
        )
        self.assertEqual(["gamepad"], data["classes"])
        self.assertEqual("bluetooth", data["bus"])
        self.assertEqual("054c", data["vendor_id"])
        self.assertNotIn("serial", data)
        self.assertNotIn("name", data)

    def test_device_scope_battery_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bat = root / "controller-battery"
            bat.mkdir()
            (bat / "type").write_text("Battery\n")
            (bat / "scope").write_text("Device\n")
            (bat / "capacity").write_text("42\n")
            (bat / "status").write_text("Discharging\n")
            rows = _device_scope_batteries(root)
            self.assertEqual(1, len(rows))
            self.assertEqual(42, rows[0]["capacity_pct"])
            self.assertEqual("Discharging", rows[0]["status"])


class P08ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = subprocess.run(
            [str(BIN), "input", "--json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=40,
        )
        cls.raw = p.stdout
        cls.data = json.loads(p.stdout)

    def test_header(self):
        self.assertEqual(1, self.data["schema_version"])
        self.assertEqual("P08", self.data["phase"])
        self.assertIs(self.data["read_only"], True)

    def test_counts(self):
        e = self.data["events"]
        self.assertEqual(e["count"], len(e["devices"]))
        self.assertEqual(self.data["hidraw"]["count"], len(self.data["hidraw"]["nodes"]))
        self.assertEqual(
            self.data["device_scope_batteries"]["count"],
            len(self.data["device_scope_batteries"]["batteries"]),
        )
        self.assertEqual(self.data["finding_count"], len(self.data["findings"]))

    def test_privacy(self):
        home = os.environ.get("HOME", "")
        if home and home != "/":
            self.assertNotIn(home, self.raw)
        p = self.data["privacy"]
        for key in (
            "absolute_paths_emitted",
            "device_names_emitted",
            "physical_paths_emitted",
            "hardware_serials_collected",
            "hardware_addresses_collected",
            "process_command_lines_collected",
            "environment_values_collected",
            "tokens_collected",
        ):
            self.assertFalse(p[key])


if __name__ == "__main__":
    unittest.main()
