import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from gaming_doctor.gpu import (
    _gpu_devices,
    parse_nvidia_smi,
    parse_vulkan_summary,
    rpm_vulkan_requirements,
)

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "gaming-doctor"


class VulkanParserTests(unittest.TestCase):
    def test_parses_two_gpu_summary(self):
        text = '''
Devices:
========
GPU0:
    apiVersion         = 1.4.313
    driverVersion      = 0.0.1
    vendorID           = 0x8086
    deviceID           = 0x7d51
    deviceType         = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU
    deviceName         = Intel(R) Graphics
    driverName         = Intel open-source Mesa driver
GPU1:
    apiVersion         = 1.4.313
    driverVersion      = 615.71.09
    vendorID           = 0x10de
    deviceID           = 0x2d19
    deviceType         = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
    deviceName         = NVIDIA GeForce RTX 5060 Laptop GPU
    driverName         = NVIDIA
'''
        devices = parse_vulkan_summary(text)
        self.assertEqual(2, len(devices))
        self.assertEqual("0x8086", devices[0]["vendorID"])
        self.assertEqual("NVIDIA GeForce RTX 5060 Laptop GPU", devices[1]["deviceName"])

    def test_rpm_requirements_cover_hybrid_intel_nvidia(self):
        req = rpm_vulkan_requirements({"Intel", "NVIDIA"})
        self.assertIn("vulkan-loader.i686", req)
        self.assertIn("mesa-vulkan-drivers.i686", req)
        self.assertIn("xorg-x11-drv-nvidia-libs.i686", req)
        self.assertEqual(len(req), len(set(req)))

    def test_nvidia_smi_parser(self):
        rows = parse_nvidia_smi("NVIDIA GeForce RTX 5060 Laptop GPU, 615.71.09, P8\n")
        self.assertEqual(1, len(rows))
        self.assertEqual("615.71.09", rows[0]["driver_version"])
        self.assertEqual("P8", rows[0]["pstate"])


class SysfsFixtureTests(unittest.TestCase):
    def test_discovers_bound_gpu_without_leaking_real_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sysfs = root / "sys"
            dev = root / "dev"
            gpu = sysfs / "0000:01:00.0"
            gpu.mkdir(parents=True)
            (gpu / "class").write_text("0x030000\n")
            (gpu / "vendor").write_text("0x10de\n")
            (gpu / "device").write_text("0x2d19\n")
            (gpu / "boot_vga").write_text("0\n")
            driver_target = root / "drivers" / "nvidia"
            driver_target.mkdir(parents=True)
            (gpu / "driver").symlink_to(driver_target)
            (gpu / "drm").mkdir()
            (gpu / "drm" / "renderD129").mkdir()
            dev.mkdir(parents=True)
            (dev / "renderD129").write_text("")
            devices = _gpu_devices(sysfs, dev)
            self.assertEqual(1, len(devices))
            self.assertEqual("NVIDIA", devices[0]["vendor"])
            self.assertEqual("nvidia", devices[0]["driver"])
            self.assertEqual("renderD129", devices[0]["render_nodes"][0]["name"])


class P04ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = subprocess.run([str(BIN), "gpu", "--json"], capture_output=True, text=True, check=True, timeout=40)
        cls.raw = p.stdout
        cls.data = json.loads(p.stdout)

    def test_header(self):
        self.assertEqual(1, self.data["schema_version"])
        self.assertEqual("P04", self.data["phase"])
        self.assertIs(self.data["read_only"], True)

    def test_counts(self):
        self.assertEqual(self.data["gpu"]["device_count"], len(self.data["gpu"]["devices"]))
        self.assertEqual(self.data["vulkan"]["device_count"], len(self.data["vulkan"]["devices"]))
        self.assertEqual(self.data["vulkan"]["icd_count"], len(self.data["vulkan"]["icds"]))
        self.assertEqual(self.data["finding_count"], len(self.data["findings"]))

    def test_privacy(self):
        home = os.environ.get("HOME", "")
        if home and home != "/":
            self.assertNotIn(home, self.raw)
        self.assertFalse(self.data["privacy"]["absolute_paths_emitted"])
        for icd in self.data["vulkan"]["icds"]:
            self.assertNotIn("/", icd["file"])
            self.assertNotIn("/", icd["library"])


if __name__ == "__main__":
    unittest.main()
