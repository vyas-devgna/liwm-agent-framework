"""Token accounting: the estimator has to be honest about being an estimator."""

import pathlib
import unittest

import helpers  # noqa: F401  -- puts src/ on sys.path

from liwm.budget import (ESTIMATOR_ERROR, account, count_tokens, estimate_tokens,
                         exact_tokens, tokenizer_available)


class TestEstimator(unittest.TestCase):
    def test_empty_is_free(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertEqual(estimate_tokens(None), 0)

    def test_any_content_costs_at_least_one(self):
        self.assertGreaterEqual(estimate_tokens("a"), 1)

    def test_monotonic_in_content(self):
        short = estimate_tokens("the user prefers terse output")
        longer = estimate_tokens("the user prefers terse output" * 4)
        self.assertGreater(longer, short)

    def test_identifier_boundaries_are_charged_for(self):
        """BPE cannot merge across an underscore, and neither may the estimate."""
        self.assertGreater(estimate_tokens("interaction_profile_preferred_verbosity"),
                           estimate_tokens("interactionprofilepreferredverbosity"))

    def test_stays_inside_its_published_bounds_on_real_payloads(self):
        """The constants in ESTIMATOR_ERROR are a claim; this is the check.

        Skipped when no exact tokenizer is importable -- LIWM does not depend
        on one, so this guard runs in the environments that install the dev
        extra and is simply absent elsewhere.
        """
        if not tokenizer_available():
            self.skipTest("no exact tokenizer available")
        root = pathlib.Path(__file__).resolve().parent.parent
        payloads = [root / "README.md", root / "ARCHITECTURE.md",
                    root / "schemas" / "intent-graph.schema.json",
                    root / "src" / "liwm" / "context.py",
                    root / "adapters" / "blocks" / "standalone.md"]
        for path in payloads:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            actual = exact_tokens(text)
            error = (estimate_tokens(text) - actual) / actual
            with self.subTest(payload=path.name):
                self.assertGreaterEqual(error, ESTIMATOR_ERROR["low"])
                self.assertLessEqual(error, ESTIMATOR_ERROR["high"])

    def test_error_bounds_are_published(self):
        for key in ("mean", "low", "high", "samples", "reference"):
            self.assertIn(key, ESTIMATOR_ERROR)
        self.assertLess(ESTIMATOR_ERROR["low"], 0)
        self.assertGreater(ESTIMATOR_ERROR["high"], 0)


class TestCounting(unittest.TestCase):
    def test_method_is_always_reported(self):
        _, method = count_tokens("hello world")
        self.assertIn(method, ("exact", "estimated"))

    def test_estimate_path_is_forced_when_asked(self):
        tokens, method = count_tokens("hello world", prefer_exact=False)
        self.assertEqual(method, "estimated")
        self.assertGreater(tokens, 0)

    def test_exact_is_none_without_a_tokenizer(self):
        if tokenizer_available():
            self.assertIsInstance(exact_tokens("hello"), int)
        else:
            self.assertIsNone(exact_tokens("hello"))

    def test_account_reports_parts_and_method(self):
        result = account({"a": "one two three", "b": "four five"}, prefer_exact=False)
        self.assertEqual(set(result["parts"]), {"a", "b"})
        self.assertEqual(result["total_tokens"],
                         sum(row["tokens"] for row in result["parts"].values()))
        self.assertEqual(result["method"], "estimated")
        self.assertIn("error_bounds", result)

    def test_estimated_accounts_always_carry_their_error(self):
        """A number without its error bars is a number with no claim attached."""
        result = account({"x": "some text"}, prefer_exact=False)
        self.assertIn("error_bounds", result)


if __name__ == "__main__":
    unittest.main()
