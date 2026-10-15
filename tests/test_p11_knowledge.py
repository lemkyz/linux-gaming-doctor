import json
import os
import tempfile
import unittest
from pathlib import Path

from gaming_doctor.knowledge import (
    _pack_matches_app,
    load_corpus,
    load_game_packs,
    validate_pack,
)

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "gaming-doctor"


class KnowledgeUnitTests(unittest.TestCase):
    def test_exact_appid_match(self):
        pack = {
            "match": {
                "steam_appids": ["381210"],
                "name_aliases": ["Dead by Daylight"],
            }
        }
        self.assertEqual(
            "appid",
            _pack_matches_app(pack, {"appid": "381210", "name": "Anything"}),
        )

    def test_exact_normalized_name_match(self):
        pack = {
            "match": {
                "steam_appids": [],
                "name_aliases": ["Resident Evil 4"],
            }
        }
        self.assertEqual(
            "name",
            _pack_matches_app(pack, {"appid": "1", "name": "Resident Evil 4"}),
        )

    def test_pack_references_real_corpus(self):
        corpus = load_corpus()
        packs = load_game_packs()
        self.assertGreaterEqual(len(packs), 9)
        self.assertEqual(100, len(corpus))
        for pack in packs:
            self.assertEqual([], validate_pack(pack, corpus))

    def test_unconfirmed_or_reported_never_becomes_auto_repair(self):
        import subprocess
        p = subprocess.run(
            [str(BIN), "knowledge", "--json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=50,
        )
        data = json.loads(p.stdout)
        self.assertIs(data["policy"]["reported_evidence_can_auto_repair"], False)
        self.assertIs(data["policy"]["unconfirmed_evidence_can_auto_repair"], False)
        for match in data["knowledge"]["matches"]:
            for case in match["cases"]:
                self.assertEqual("candidate_only", case["actionability"])


class P11ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess
        p = subprocess.run(
            [str(BIN), "knowledge", "--json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=50,
        )
        cls.raw = p.stdout
        cls.data = json.loads(p.stdout)

    def test_header(self):
        self.assertEqual(1, self.data["schema_version"])
        self.assertEqual("P11", self.data["phase"])
        self.assertIs(self.data["read_only"], True)

    def test_validation_clean(self):
        k = self.data["knowledge"]
        self.assertEqual(0, k["validation_error_count"])
        self.assertEqual([], k["validation_errors"])

    def test_policy(self):
        p = self.data["policy"]
        self.assertIs(p["knowledge_is_diagnosis"], False)
        self.assertIs(p["reported_evidence_can_auto_repair"], False)
        self.assertIs(p["unconfirmed_evidence_can_auto_repair"], False)
        self.assertIs(p["exact_confirmed_still_requires_observed_preconditions"], True)

    def test_privacy(self):
        home = os.environ.get("HOME", "")
        if home and home != "/":
            self.assertNotIn(home, self.raw)
        p = self.data["privacy"]
        self.assertFalse(p["absolute_paths_emitted"])
        self.assertFalse(p["installed_game_names_emitted"])
        self.assertFalse(p["account_identifiers_collected"])


if __name__ == "__main__":
    unittest.main()
