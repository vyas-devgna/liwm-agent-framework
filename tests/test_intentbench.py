from __future__ import annotations

import unittest

from helpers import LiwmTestCase

from liwm.evaluation.intentbench import load_suite, run_intentbench


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


class MechanismSuiteTests(LiwmTestCase):
    """The mechanism suite must exercise LIWM, and must be able to fail."""

    def _run(self, adapter):
        from liwm.evaluation.intentbench import load_suite, run_intentbench
        return run_intentbench(load_suite(suite="mechanism"), adapter=adapter)

    def test_real_liwm_passes_every_mechanism_case(self):
        result = self._run("liwm")
        failures = [row["case_id"] for row in result["results"] if not row["correct"]]
        self.assertEqual(failures, [])
        self.assertEqual(result["metrics"]["top1_accuracy"], 1.0)

    def test_the_suite_is_not_trivially_passable(self):
        # A benchmark every adapter passes measures nothing. The fixed-choice
        # baseline has to do badly, or the cases are not discriminating.
        baseline = self._run("static-first")
        self.assertLess(baseline["metrics"]["top1_accuracy"], 0.5)
        self.assertGreater(baseline["metrics"]["mean_log_loss"],
                           self._run("liwm")["metrics"]["mean_log_loss"])

    def test_every_mechanism_family_is_covered(self):
        result = self._run("liwm")
        self.assertEqual(set(result["by_task"]), {
            "scope_contamination", "poisoning_resistance", "selective_forget",
            "cross_domain_transfer", "preference_prediction",
        })

    def test_no_candidate_view_names_its_own_answer(self):
        from liwm.evaluation.intentbench import load_suite, participant_view
        for case in load_suite(suite="mechanism")["cases"]:
            view = participant_view(case)
            self.assertNotIn("hidden_ground_truth", view)
            self.assertNotIn("observed_choice", view)
            self.assertNotIn("candidate_scores", view["exposed_to_liwm"])

    def test_the_manifest_says_what_the_number_means(self):
        manifest = self._run("liwm")["manifest"]
        self.assertEqual(manifest["adapter"], "liwm")
        self.assertFalse(manifest["hidden_labels_exposed"])
        self.assertIn("no human involved", manifest["evidence_label"])
        self.assertIn("top1_accuracy", manifest["metric_definitions"])

    def test_no_evidence_produces_no_opinion(self):
        result = self._run("liwm")
        uniform = [row for row in result["results"] if row["scored_as"] == "uniformity"]
        self.assertTrue(uniform)
        for row in uniform:
            self.assertLessEqual(row["max_deviation_from_uniform"], 0.02)
            self.assertAlmostEqual(row["log_loss"], 0.6931, places=3)

    def test_the_suite_runs_deterministically(self):
        first, second = self._run("liwm"), self._run("liwm")
        self.assertEqual([row["target_probability"] for row in first["results"]],
                         [row["target_probability"] for row in second["results"]])


class HumanDataLeakageChecks(unittest.TestCase):
    """A human case that exposes its own answer is a fabrication, not a bug."""

    def _suite(self, exposed, candidates=None):
        return {
            "suite_id": "human-test", "dataset_kind": "human_anonymised",
            "cases": [{
                "case_id": "leaky", "task_type": "preference_prediction",
                "exposed_to_liwm": exposed,
                "candidate_outputs": candidates or [{"id": "terse"}, {"id": "detailed"}],
                "hidden_ground_truth": {"preferred_candidate": "terse"},
                "observed_choice": "terse",
            }],
        }

    def _load(self, suite):
        import json
        import tempfile
        from pathlib import Path
        from liwm.evaluation.intentbench import load_suite
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "suite.json"
            path.write_text(json.dumps(suite), encoding="utf-8")
            return load_suite(path)

    def test_an_answer_in_the_participant_view_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self._load(self._suite({"candidate_scores": {"terse": 0.9}}))
        self.assertIn("exposes its own answer", str(caught.exception))

    def test_an_answer_in_candidate_metadata_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            self._load(self._suite(
                {}, [{"id": "terse"},
                     {"id": "detailed", "note": "the participant picked terse"}]))
        self.assertIn("leaks its answer", str(caught.exception))

    def test_a_clean_human_case_loads(self):
        suite = self._load(self._suite({"setup": []},
                                       [{"id": "terse"}, {"id": "detailed"}]))
        self.assertEqual(len(suite["cases"]), 1)

    def test_the_synthetic_smoke_suite_is_exempt_and_labelled(self):
        # It is circular on purpose. The exemption is why it must never claim
        # to be anything but a runner check.
        suite = load_suite(suite="smoke")
        self.assertEqual(suite["dataset_kind"], "synthetic")
        result = run_intentbench(suite)
        self.assertEqual(result["result_label"], "synthetic_scorer_contract_smoke")
