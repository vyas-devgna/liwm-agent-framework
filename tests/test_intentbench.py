from __future__ import annotations

import unittest

import helpers  # noqa: F401 - adds src/ to sys.path

from liwm.evaluation.intentbench import load_suite, run_intentbench  # noqa: E402


class TestIntentBench(unittest.TestCase):
    def test_hidden_labels_never_reach_adapter(self):
        seen = []

        def inspecting_adapter(view):
            seen.append(view)
            self.assertNotIn("hidden_ground_truth", view)
            self.assertNotIn("observed_choice", view)
            ids = [row["id"] for row in view["candidate_outputs"]]
            return {"probabilities": {candidate_id: 1 for candidate_id in ids}}

        run_intentbench(load_suite(), inspecting_adapter)
        self.assertTrue(seen)

    def test_synthetic_smoke_is_deterministic_and_explicitly_labelled(self):
        first = run_intentbench(load_suite())
        second = run_intentbench(load_suite())
        self.assertEqual(first, second)
        self.assertEqual(first["result_label"], "synthetic_scorer_contract_smoke")
        self.assertEqual(first["metrics"]["top1_accuracy"], 1.0)
        self.assertIn("poisoning_resistance", first["by_task"])
        self.assertIn("scope_contamination", first["by_task"])

    def test_unknown_candidate_is_rejected(self):
        def bad_adapter(_view):
            return {"probabilities": {"hidden-answer": 1}}

        with self.assertRaises(ValueError):
            run_intentbench(load_suite(), bad_adapter)

    def test_non_finite_adapter_scores_are_rejected(self):
        with self.assertRaises(ValueError):
            run_intentbench(load_suite(), lambda view: {
                "probabilities": {row["id"]: float("nan") for row in view["candidate_outputs"]}
            })


if __name__ == "__main__":
    unittest.main()
