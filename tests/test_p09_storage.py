import json
import os
import tempfile
import unittest
from pathlib import Path

from gaming_doctor.storage import (
    _same_device,
    _space_fact,
    filesystem_kind,
    parse_mount_line,
)


class StorageParserTests(unittest.TestCase):
    def test_filesystem_classification(self):
        self.assertEqual("native_linux", filesystem_kind("btrfs"))
        self.assertEqual("native_linux", filesystem_kind("ext4"))
        self.assertEqual("windows_shared", filesystem_kind("ntfs3"))
        self.assertEqual("windows_shared", filesystem_kind("exfat"))
        self.assertEqual("network", filesystem_kind("nfs4"))
        self.assertEqual("memory", filesystem_kind("tmpfs"))

    def test_mount_flags_are_reduced_to_booleans(self):
        d = parse_mount_line("btrfs rw,noexec,nodev,compress=zstd:1,subvol=/home")
        self.assertEqual("btrfs", d["fstype"])
        self.assertEqual("native_linux", d["kind"])
        self.assertIs(d["read_only"], False)
        self.assertIs(d["noexec"], True)
        self.assertIs(d["nodev"], True)
        self.assertIs(d["compressed"], True)
        self.assertNotIn("options", d)

    def test_empty_mount_is_unknown(self):
        d = parse_mount_line("")
        self.assertEqual("unknown", d["fstype"])
        self.assertIsNone(d["read_only"])
        self.assertIsNone(d["noexec"])


class StorageFixtureTests(unittest.TestCase):
    def test_space_fact_and_same_device(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            child = root / "child"
            child.mkdir()
            s = _space_fact(root)
            self.assertTrue(s["available"])
            self.assertGreater(s["total_bytes"], 0)
            self.assertGreaterEqual(s["free_bytes"], 0)
            self.assertIs(_same_device(root, child), True)


class P09ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess
        root = Path(__file__).resolve().parents[1]
        p = subprocess.run(
            [str(root / "bin" / "gaming-doctor"), "storage", "--json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=40,
        )
        cls.raw = p.stdout
        cls.data = json.loads(p.stdout)

    def test_header(self):
        self.assertEqual(1, self.data["schema_version"])
        self.assertEqual("P09", self.data["phase"])
        self.assertIs(self.data["read_only"], True)

    def test_counts(self):
        s = self.data["steam_storage"]
        self.assertEqual(s["library_count"], len(s["libraries"]))
        self.assertEqual(self.data["finding_count"], len(self.data["findings"]))

    def test_privacy(self):
        home = os.environ.get("HOME", "")
        if home and home != "/":
            self.assertNotIn(home, self.raw)
        p = self.data["privacy"]
        for key in (
            "absolute_paths_emitted",
            "mount_sources_emitted",
            "mount_targets_emitted",
            "usernames_collected",
            "volume_labels_collected",
            "filesystem_uuids_collected",
            "device_serials_collected",
            "network_identifiers_collected",
            "tokens_collected",
        ):
            self.assertFalse(p[key])


if __name__ == "__main__":
    unittest.main()
