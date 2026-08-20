"""Behavioural tests for LOW, MEDIUM, HIGH, AUTO and OFF.

The requirement is not "different numbers" but *different reasoning*.  These
tests assert the contract that makes the modes meaningfully distinct, and the
property that matters most for the framework's honesty: AUTO must get quieter as
the profile matures, never louder.
"""

from __future__ import annotations

import unittest

from helpers import LiwmTestCase

from liwm.fatigue import estimate_fatigue, profile_maturity
from liwm.modes import MODE_PROFILES, Signals, mode_profile, question_budget, resolve_auto
from liwm.questions import QuestionPlanner


class TestModeContracts(unittest.TestCase):
    def test_question_budgets_increase_with_mode(self):
        budgets = [MODE_PROFILES[m]["max_questions"] for m in ("off", "low", "medium", "high")]
        self.assertEqual(budgets, sorted(budgets))
        self.assertEqual(budgets[0], 0)

    def test_utility_thresholds_decrease_with_mode(self):
        thresholds = [MODE_PROFILES[m]["min_utility"] for m in ("low", "medium", "high")]
        self.assertEqual(thresholds, sorted(thresholds, reverse=True))

    def test_experiential_ratio_increases_with_mode(self):
        ratios = [MODE_PROFILES[m]["experiential_ratio"] for m in ("low", "medium", "high")]
        self.assertEqual(ratios, sorted(ratios))
        self.assertAlmostEqual(ratios[0], 0.30)
        self.assertAlmostEqual(ratios[1], 0.50)
        self.assertAlmostEqual(ratios[2], 0.80)

    def test_high_asks_one_at_a_time(self):
        self.assertTrue(MODE_PROFILES["high"]["one_at_a_time"])
        self.assertFalse(MODE_PROFILES["low"]["one_at_a_time"])

    def test_off_disables_profile_use_and_learning(self):
        off = mode_profile("off")
        self.assertFalse(off["use_profile"])
        self.assertFalse(off["record_evidence"])
        self.assertEqual(off["max_questions"], 0)

    def test_auto_must_be_resolved_before_use(self):
        with self.assertRaises(ValueError):
            mode_profile("auto")


class TestModeBehaviour(LiwmTestCase):
    def _plan(self, mode, **kwargs):
        contract = mode_profile(mode)
        planner = QuestionPlanner(contract, resolved={})
        return planner.plan(misunderstanding_risk=0.6, **kwargs)

    def test_modes_are_behaviourally_distinguishable(self):
        low, medium, high = (self._plan(m) for m in ("low", "medium", "high"))
        self.assertLess(len(low), len(medium))
        self.assertLess(len(medium), len(high))

        def share(plan):
            return len([p for p in plan if p["class"] == "experiential"]) / len(plan)

        self.assertLess(share(low), share(medium))
        self.assertLess(share(medium), share(high))

    def test_off_mode_asks_nothing(self):
        self.assertEqual(self._plan("off"), [])

    def test_high_mode_reaches_for_counterfactuals(self):
        styles = {p["style"] for p in self._plan("high")}
        self.assertTrue(styles & {"counterfactual", "scenario", "anti_example"})

    def test_low_mode_leans_technical(self):
        plan = self._plan("low")
        technical = len([p for p in plan if p["class"] == "technical"])
        self.assertGreaterEqual(technical, len(plan) / 2)

    def test_planner_returns_nothing_when_everything_is_known(self):
        resolved = {
            d["dimension"]: {"value": "x", "confidence": 0.97}
            for d in __import__("liwm.taxonomy", fromlist=["DIMENSIONS"]).DIMENSIONS
        }
        planner = QuestionPlanner(mode_profile("medium"), resolved=resolved)
        self.assertEqual(planner.plan(misunderstanding_risk=0.5), [],
                         "a confident profile must convert into silence, not questions")


class TestAutoResolution(LiwmTestCase):
    def test_high_uncertainty_and_irreversibility_selects_high(self):
        contract = resolve_auto(Signals(
            intent_uncertainty=0.9, novelty=0.8, consequence=0.85, reversibility=0.15,
            specification_completeness=0.1, project_stage="inception",
        ))
        self.assertEqual(contract["mode"], "high")

    def test_clear_reversible_task_selects_low(self):
        contract = resolve_auto(Signals(
            intent_uncertainty=0.15, novelty=0.1, consequence=0.2, reversibility=0.95,
            specification_completeness=0.9, project_stage="build",
        ))
        self.assertEqual(contract["mode"], "low")

    def test_middle_ground_selects_medium(self):
        contract = resolve_auto(Signals(
            intent_uncertainty=0.55, novelty=0.45, consequence=0.5, reversibility=0.6,
            specification_completeness=0.45, project_stage="design",
        ))
        self.assertEqual(contract["mode"], "medium")

    def test_a_mature_profile_reduces_investigation(self):
        """Requirement §43: understanding must convert into fewer questions."""
        base = dict(intent_uncertainty=0.7, novelty=0.5, consequence=0.6,
                    reversibility=0.5, specification_completeness=0.4,
                    project_stage="design")
        naive = resolve_auto(Signals(profile_maturity=0.0, **base))
        mature = resolve_auto(Signals(profile_maturity=0.9, **base))
        self.assertLess(mature["investigation_need"], naive["investigation_need"])
        self.assertLessEqual(mature["max_questions"], naive["max_questions"])

    def test_fatigue_suppresses_questioning(self):
        base = dict(intent_uncertainty=0.8, novelty=0.6, consequence=0.6,
                    reversibility=0.5, specification_completeness=0.3,
                    project_stage="design")
        fresh = resolve_auto(Signals(fatigue=0.0, **base))
        tired = resolve_auto(Signals(fatigue=0.95, **base))
        self.assertLess(tired["investigation_need"], fresh["investigation_need"])
        self.assertLess(tired["max_questions"], fresh["max_questions"])

    def test_stated_dislike_of_questions_caps_the_budget(self):
        self.assertLessEqual(
            question_budget("high", Signals(question_preference="minimal")), 1)

    def test_irreversibility_raises_investigation_even_when_specified(self):
        spec = dict(intent_uncertainty=0.4, novelty=0.2, specification_completeness=0.8,
                    project_stage="build")
        safe = resolve_auto(Signals(consequence=0.2, reversibility=0.95, **spec))
        risky = resolve_auto(Signals(consequence=0.95, reversibility=0.05, **spec))
        self.assertGreater(risky["investigation_need"], safe["investigation_need"])

    def test_rationale_is_legible(self):
        contract = resolve_auto(Signals(intent_uncertainty=0.9, project_stage="inception"))
        self.assertIn("investigation need", contract["rationale"])
        self.assertIn("driven by", contract["rationale"])


class TestFatigue(LiwmTestCase):
    def test_ignored_questions_raise_fatigue_fastest(self):
        volume_only = estimate_fatigue(asked=3)
        with_ignores = estimate_fatigue(asked=3, ignored=2)
        self.assertGreater(with_ignores, volume_only)

    def test_maturity_does_not_saturate_on_one_belief(self):
        self.observe("interaction_profile.preferred_verbosity", "terse")
        self.assertLess(profile_maturity(self.store.load()), 0.2,
                        "knowing one thing well is not knowing a person")

    def test_maturity_grows_with_breadth(self):
        low = profile_maturity(self.store.load())
        dims = [
            "interaction_profile.preferred_verbosity",
            "interaction_profile.autonomy_preference",
            "interaction_profile.explanation_depth",
            "decision_style.option_breadth",
            "creative_profile.simplicity_vs_richness",
            "working_style.planning_preference",
            "reasoning_profile.novelty_preference",
            "interaction_profile.challenge_level",
        ]
        for i, dim in enumerate(dims):
            self.observe(dim, "value_%d" % i)
        self.assertGreater(profile_maturity(self.store.load()), low)
        self.assertLess(profile_maturity(self.store.load()), 1.0)


if __name__ == "__main__":
    unittest.main()
