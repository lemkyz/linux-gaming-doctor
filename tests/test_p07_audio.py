import json
import os
import re
import subprocess
import unittest
from pathlib import Path

from gaming_doctor.audio import (
    count_journal_events,
    endpoint_transport,
    parse_card_profiles,
    parse_pactl_info,
    parse_pactl_short,
    parse_pw_metadata,
)

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "gaming-doctor"


class AudioParserTests(unittest.TestCase):
    def test_pactl_info(self):
        d = parse_pactl_info(
            "Server Name: PulseAudio (on PipeWire 1.4.9)\n"
            "Server Version: 15.0.0\n"
            "Default Sink: bluez_output.XX\n"
            "Default Source: alsa_input.pci\n"
        )
        self.assertIn("PipeWire", d["server_name"])
        self.assertEqual("bluez_output.XX", d["default_sink"])

    def test_short_endpoint_parser(self):
        rows = parse_pactl_short(
            "42\tbluez_output.AA_BB_CC_DD_EE_FF.1\tPipeWire\ts32le 2ch 48000Hz\tRUNNING\n"
        )
        self.assertEqual(1, len(rows))
        self.assertEqual("bluetooth", rows[0]["transport"])
        self.assertEqual(48000, rows[0]["rate_hz"])
        self.assertEqual(2, rows[0]["channels"])

    def test_transport_classification(self):
        self.assertEqual("bluetooth", endpoint_transport("bluez_input.AA"))
        self.assertEqual("alsa", endpoint_transport("alsa_output.pci"))
        self.assertEqual("virtual", endpoint_transport("auto_null"))

    def test_card_profiles(self):
        cards = parse_card_profiles(
            "Card #1\n\tName: bluez_card.AA_BB\n\tActive Profile: headset-head-unit-msbc\n"
            "Card #2\n\tName: alsa_card.pci\n\tActive Profile: output:analog-stereo\n"
        )
        self.assertEqual(2, len(cards))
        self.assertEqual("bluetooth", cards[0]["transport"])
        self.assertEqual("headset-head-unit-msbc", cards[0]["active_profile"])
        self.assertEqual("alsa", cards[1]["transport"])

    def test_pw_metadata(self):
        d = parse_pw_metadata(
            "update: id:0 key:'clock.rate' value:'48000' type:''\n"
            "update: id:0 key:'clock.force-quantum' value:'32' type:''\n"
        )
        self.assertEqual(48000, d["clock_rate"])
        self.assertEqual(32, d["clock_force_quantum"])

    def test_journal_counts(self):
        d = count_journal_events("xrun\nunderrun\nOVERRUN\n")
        self.assertEqual(1, d["xrun"])
        self.assertEqual(1, d["underrun"])
        self.assertEqual(1, d["overrun"])


class P07ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = subprocess.run(
            [str(BIN), "audio", "--json"],
            capture_output=True, text=True, check=True, timeout=40,
        )
        cls.raw = p.stdout
        cls.data = json.loads(p.stdout)

    def test_header(self):
        self.assertEqual(1, self.data["schema_version"])
        self.assertEqual("P07", self.data["phase"])
        self.assertIs(self.data["read_only"], True)

    def test_counts(self):
        s = self.data["server"]
        self.assertEqual(s["sink_count"], len(s["sinks"]))
        self.assertEqual(s["source_count"], len(s["sources"]))
        self.assertEqual(s["card_count"], len(s["cards"]))
        self.assertEqual(self.data["finding_count"], len(self.data["findings"]))

    def test_privacy(self):
        home = os.environ.get("HOME", "")
        if home and home != "/":
            self.assertNotIn(home, self.raw)
        p = self.data["privacy"]
        for key in (
            "absolute_paths_emitted", "raw_audio_logs_emitted",
            "endpoint_names_emitted", "device_descriptions_emitted",
            "hardware_addresses_collected", "process_command_lines_collected",
            "environment_values_collected", "tokens_collected",
        ):
            self.assertFalse(p[key])
        self.assertIsNone(re.search(r"(?i)(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}", self.raw))


if __name__ == "__main__":
    unittest.main()
