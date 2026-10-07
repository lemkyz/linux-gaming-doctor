
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from gaming_doctor.performance import (
    _cpu_freq_state,
    _memory_state,
    _thermal_state,
    parse_meminfo,
    parse_nvidia_metrics,
    parse_pressure,
)

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "gaming-doctor"


class ParserTests(unittest.TestCase):
    def test_parse_pressure(self):
        data = parse_pressure(
            "some avg10=1.23 avg60=2.34 avg300=3.45 total=100\n"
            "full avg10=0.10 avg60=0.20 avg300=0.30 total=5\n"
        )
        self.assertAlmostEqual(1.23, data["some"]["avg10"])
        self.assertEqual(100, data["some"]["total"])
        self.assertAlmostEqual(0.10, data["full"]["avg10"])

    def test_parse_meminfo(self):
        data = parse_meminfo(
            "MemTotal:       32000000 kB\n"
            "MemAvailable:   16000000 kB\n"
            "SwapTotal:       8000000 kB\n"
            "SwapFree:        6000000 kB\n"
        )
        self.assertEqual(32000000, data["MemTotal"])
        self.assertEqual(16000000, data["MemAvailable"])
        self.assertEqual(8000000, data["SwapTotal"])

    def test_parse_nvidia_metrics(self):
        rows = parse_nvidia_metrics(
            "75, 30, 82, P0, 2400, 12000, 90.5, 115, 4096, 8192\n"
        )
        self.assertEqual(1, len(rows))
        self.assertEqual(75.0, rows[0]["gpu_util_pct"])
        self.assertEqual("P0", rows[0]["pstate"])
        self.assertEqual(90.5, rows[0]["power_draw_w"])


class FixtureTests(unittest.TestCase):
    def test_cpu_freq_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p0 = root / "cpufreq" / "policy0"
            p0.mkdir(parents=True)
            (p0 / "scaling_driver").write_text("intel_pstate\n")
            (p0 / "scaling_governor").write_text("powersave\n")
            (p0 / "energy_performance_preference").write_text("balance_performance\n")
            (p0 / "scaling_cur_freq").write_text("2800000\n")
            (p0 / "scaling_min_freq").write_text("400000\n")
            (p0 / "scaling_max_freq").write_text("4800000\n")
            (root / "intel_pstate").mkdir()
            (root / "intel_pstate" / "no_turbo").write_text("0\n")
            data = _cpu_freq_state(root)
            self.assertEqual(1, data["policy_count"])
            self.assertEqual(["intel_pstate"], data["drivers"])
            self.assertEqual(["powersave"], data["governors"])
            self.assertIs(data["boost_enabled"], True)
            self.assertEqual(2800000.0, data["current_avg_khz"])

    def test_memory_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "meminfo").write_text(
                "MemTotal: 1000000 kB\nMemAvailable: 250000 kB\n"
                "SwapTotal: 100000 kB\nSwapFree: 25000 kB\n"
            )
            data = _memory_state(root)
            self.assertEqual(25.0, data["available_pct"])
            self.assertEqual(75000, data["swap_used_kib"])
            self.assertEqual(75.0, data["swap_used_pct"])

    def test_thermal_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            z0 = root / "thermal_zone0"
            z0.mkdir()
            (z0 / "type").write_text("x86_pkg_temp\n")
            (z0 / "temp").write_text("87500\n")
            data = _thermal_state(root)
            self.assertEqual(1, data["zone_count"])
            self.assertEqual(87.5, data["max_temp_c"])
            self.assertEqual("x86_pkg_temp", data["hottest_type"])


class P06ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = subprocess.run(
            [str(BIN), "performance", "--json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=40,
        )
        cls.raw = p.stdout
        cls.data = json.loads(p.stdout)

    def test_header(self):
        self.assertEqual(1, self.data["schema_version"])
        self.assertEqual("P06", self.data["phase"])
        self.assertIs(self.data["read_only"], True)

    def test_counts(self):
        self.assertEqual(self.data["finding_count"], len(self.data["findings"]))
        self.assertEqual(
            self.data["cpu"]["frequency"]["policy_count"],
            len(self.data["cpu"]["frequency"]["policies"]),
        )
        self.assertEqual(
            self.data["thermal"]["zone_count"],
            len(self.data["thermal"]["zones"]),
        )
        self.assertEqual(
            self.data["nvidia"]["device_count"],
            len(self.data["nvidia"]["devices"]),
        )

    def test_privacy(self):
        home = os.environ.get("HOME", "")
        if home and home != "/":
            self.assertNotIn(home, self.raw)
        p = self.data["privacy"]
        self.assertFalse(p["absolute_paths_emitted"])
        self.assertFalse(p["process_command_lines_collected"])
        self.assertFalse(p["environment_values_collected"])
        self.assertFalse(p["host_identifiers_collected"])
        self.assertFalse(p["hardware_serials_collected"])


if __name__ == "__main__":
    unittest.main()
