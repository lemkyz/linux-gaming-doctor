import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "corpus" / "cases"

class CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = [json.loads(p.read_text()) for p in sorted(CASES.glob("LGD-*.json"))]

    def test_exactly_100_cases(self):
        self.assertEqual(100, len(self.cases))

    def test_ids_unique_and_sequential(self):
        ids = [c["id"] for c in self.cases]
        self.assertEqual(100, len(set(ids)))
        self.assertEqual([f"LGD-{i:04d}" for i in range(1, 101)], ids)

    def test_every_case_has_probe_and_verification(self):
        for case in self.cases:
            self.assertTrue(case["probes"], case["id"])
            self.assertTrue(case["verification"], case["id"])

    def test_mutations_always_have_rollback(self):
        for case in self.cases:
            if case["mutation_policy"] != "NONE":
                self.assertTrue(case["rollback"], case["id"])

    def test_unconfirmed_never_directly_repairable(self):
        for case in self.cases:
            if case["evidence_status"] == "UNCONFIRMED":
                self.assertNotEqual("REPAIRABLE", case["classification"], case["id"])

    def test_unknown_exists(self):
        self.assertTrue(any(c["classification"] == "UNKNOWN" for c in self.cases))

    def test_unsupported_policy_exists(self):
        self.assertTrue(any(c["classification"] == "UNSUPPORTED_POLICY" for c in self.cases))

if __name__ == "__main__":
    unittest.main()
