"""The gate's errors are asymmetric, and the benchmark has to keep saying so."""

from __future__ import annotations

import unittest

import helpers  # noqa: F401  -- puts src/ on sys.path

from liwm.evaluation.gatebench import load_suite, run_gatebench


class TestGateBench(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_gatebench()
        cls.overall = cls.result["overall"]

    def test_no_request_that_needed_memory_was_sent_without_it(self):
        """The expensive error. A wrong skip is silent; a wrong retrieve is not."""
        self.assertEqual(self.overall["false_skips"], 0,
                         self.overall["failing"])

    def test_the_corpus_covers_the_hard_family(self):
        """Requests that parse like lookups but turn on local state."""
        families = {case["family"] for case in load_suite()["cases"]}
        self.assertIn("generic_looking_but_situated", families)
        self.assertIn("project_relative", families)

    def test_the_gate_still_skips_something(self):
        """A gate that always retrieves passes the false-skip test and is useless."""
        self.assertGreater(sum(1 for row in self.result["rows"]
                               if not row["predicted"]), 5)

    def test_loss_prices_a_skip_above_a_retrieve(self):
        weights = self.result["manifest"]["loss_weights"]
        self.assertGreater(weights["false_skip_weight"],
                           weights["false_retrieve_weight"])

    def test_rates_are_reported_with_intervals(self):
        low, high = self.overall["false_skip_rate_ci95"]
        self.assertIsNotNone(low)
        self.assertGreaterEqual(high, self.overall["false_skip_rate"])

    def test_the_manifest_says_no_model_ran(self):
        self.assertFalse(self.result["manifest"]["model_in_the_loop"])


if __name__ == "__main__":
    unittest.main()
