"""The retrieval suite, and the properties that keep it able to fail."""

from __future__ import annotations

import unittest

import helpers  # noqa: F401  -- puts src/ on sys.path

from liwm.evaluation.retrieval import load_suite, run_retrieval, split_of, wilson_interval


class TestSuiteIntegrity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.suite = load_suite()

    def test_every_taxonomy_dimension_is_covered(self):
        from liwm.taxonomy import DIMENSION_INDEX
        covered = {case["requires"] for case in self.suite["cases"]}
        self.assertEqual(set(DIMENSION_INDEX) - covered, set())

    def test_no_case_names_its_own_dimension(self):
        """A case containing its answer would measure string matching."""
        for case in self.suite["cases"]:
            leaf = case["requires"].rsplit(".", 1)[-1]
            words = leaf.split("_")
            with self.subTest(case=case["id"]):
                self.assertFalse(all(word in case["task"].lower() for word in words),
                                 "%s leaks into %r" % (leaf, case["task"]))

    def test_split_depends_only_on_the_case_id(self):
        self.assertEqual(split_of("a#0"), split_of("a#0"))
        self.assertIn(split_of("anything#3"), ("dev", "holdout"))

    def test_both_splits_are_populated(self):
        splits = {case["split"] for case in self.suite["cases"]}
        self.assertEqual(splits, {"dev", "holdout"})

    def test_the_suite_records_its_own_hash(self):
        self.assertEqual(len(self.suite["content_sha256"]), 64)


class TestWilson(unittest.TestCase):
    def test_stays_inside_the_unit_interval_at_the_extremes(self):
        """The reason this is not a normal approximation."""
        for successes, total in ((0, 20), (20, 20), (1, 3)):
            low, high = wilson_interval(successes, total)
            self.assertGreaterEqual(low, 0.0)
            self.assertLessEqual(high, 1.0)

    def test_brackets_the_estimate(self):
        low, high = wilson_interval(30, 60)
        self.assertLess(low, 0.5)
        self.assertGreater(high, 0.5)

    def test_no_samples_is_not_an_answer(self):
        self.assertEqual(wilson_interval(0, 0), (None, None))


class TestIntentBeatsConfidence(unittest.TestCase):
    """The campaign's headline claim, as a gate rather than a sentence.

    Run on the development split: the holdout exists to be read once, and a
    test that asserts against it every CI run has turned it into a dev set.
    """

    @classmethod
    def setUpClass(cls):
        suite = load_suite()
        cls.base = run_retrieval(suite, splits=("dev",), use_intent=False)
        cls.intent = run_retrieval(suite, splits=("dev",), use_intent=True)

    def test_intent_recall_is_substantially_higher(self):
        self.assertGreater(self.intent["splits"]["dev"]["recall"],
                           self.base["splits"]["dev"]["recall"] + 0.20)

    def test_it_is_not_bought_with_tokens(self):
        """Recall from projecting more is not a retrieval result."""
        self.assertLess(self.intent["splits"]["dev"]["mean_tokens"],
                        self.base["splits"]["dev"]["mean_tokens"] * 1.15)

    def test_the_baseline_is_genuinely_weak_here(self):
        """If confidence ranking ever scores well, the suite stopped being hard."""
        self.assertLess(self.base["splits"]["dev"]["recall"], 0.45)

    def test_no_case_regresses_relative_to_the_baseline(self):
        """The holdout showed 10 fixed and 0 broken; hold that shape on dev."""
        base = {row["id"]: row["found"] for row in self.base["rows"]}
        intent = {row["id"]: row["found"] for row in self.intent["rows"]}
        broken = [k for k in base if base[k] and not intent[k]]
        self.assertEqual(broken, [])

    def test_the_manifest_says_no_model_ran(self):
        self.assertFalse(self.intent["manifest"]["model_in_the_loop"])


if __name__ == "__main__":
    unittest.main()
