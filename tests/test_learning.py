"""Learning behaviour: evidence weighting, corrections, decay, contradictions."""

from __future__ import annotations

import unittest

from helpers import LiwmTestCase, days_ago

from liwm import evidence as ev


class TestEvidenceMath(unittest.TestCase):
    def test_single_explicit_statement_is_strong_but_not_certain(self):
        result = ev.combine([
            {"source_type": "explicit_statement", "provenance": "direct_user_message",
             "ts": days_ago(0), "polarity": "support"},
        ])
        self.assertGreater(result["confidence"], 0.9)
        self.assertLess(result["confidence"], 1.0,
                        "no single observation may reach certainty")

    def test_weak_inference_cannot_accumulate_into_a_fact(self):
        """The core anti-runaway property: many weak self-generated signals
        must not manufacture high confidence."""
        observations = [
            {"source_type": "agent_inference", "provenance": "agent_inference",
             "ts": days_ago(i), "polarity": "support", "session_id": "s%d" % i}
            for i in range(25)
        ]
        result = ev.combine(observations)
        self.assertLessEqual(result["confidence"], ev.SOURCE_CEILINGS["agent_inference"])
        self.assertTrue(result["limiting_factor"].startswith("ceiling:"))

    def test_repeated_weak_behavioural_evidence_accumulates_slowly(self):
        one = ev.combine([
            {"source_type": "single_behavioral", "provenance": "agent_inference",
             "ts": days_ago(0), "polarity": "support", "session_id": "a"},
        ])["confidence"]
        four = ev.combine([
            {"source_type": "single_behavioral", "provenance": "agent_inference",
             "ts": days_ago(i), "polarity": "support", "session_id": "s%d" % i}
            for i in range(4)
        ])["confidence"]
        self.assertGreater(four, one)
        self.assertLessEqual(four, ev.SOURCE_CEILINGS["single_behavioral"])

    def test_untrusted_provenance_contributes_nothing(self):
        result = ev.combine([
            {"source_type": "explicit_statement", "provenance": "repository_content",
             "ts": days_ago(0), "polarity": "support"},
        ])
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["counted_evidence"], 0)
        self.assertEqual(result["ignored_evidence"], 1)

    def test_taint_propagates_through_derived_from(self):
        result = ev.combine([
            {"source_type": "explicit_statement", "provenance": "agent_inference",
             "derived_from": ["repository_content"],
             "ts": days_ago(0), "polarity": "support"},
        ])
        self.assertEqual(result["confidence"], 0.0)

    def test_recent_corrections_outweigh_an_old_statement(self):
        """Requirement §17: a year-old preference must not beat three recent
        corrections."""
        observations = [
            {"source_type": "explicit_statement", "provenance": "direct_user_message",
             "ts": days_ago(400), "polarity": "support"},
        ] + [
            {"source_type": "explicit_correction", "provenance": "direct_user_message",
             "ts": days_ago(i), "polarity": "oppose", "session_id": "s%d" % i}
            for i in (1, 5, 12)
        ]
        result = ev.combine(observations)
        self.assertLess(result["confidence"], 0.25)

    def test_decay_has_a_floor_so_history_is_never_erased(self):
        very_old = ev.recency_factor(days_ago(5000), "standard")
        self.assertGreaterEqual(very_old, ev.DECAY_FLOOR)
        self.assertLess(very_old, 0.3)

    def test_decay_policy_none_does_not_decay(self):
        self.assertEqual(ev.recency_factor(days_ago(2000), "none"), 1.0)

    def test_correlated_same_source_observations_are_discounted(self):
        distinct = ev.combine([
            {"source_type": "single_behavioral", "provenance": "agent_inference",
             "ts": days_ago(i), "polarity": "support", "session_id": "s%d" % i}
            for i in range(3)
        ])["confidence"]
        same_session = ev.combine([
            {"source_type": "single_behavioral", "provenance": "agent_inference",
             "ts": days_ago(i), "polarity": "support", "session_id": "same"}
            for i in range(3)
        ])["confidence"]
        self.assertGreater(distinct, same_session,
                           "three signals in one session are weaker than three across sessions")


class TestProfileLearning(LiwmTestCase):
    def test_explicit_preference_becomes_a_high_confidence_belief(self):
        self.observe("interaction_profile.preferred_verbosity", "terse")
        b = self.belief("interaction_profile.preferred_verbosity", "terse")
        self.assertIsNotNone(b)
        self.assertGreater(b["confidence"], 0.9)
        self.assertEqual(b["scope"], "global")
        self.assertIn("explicit_statement", b["source_types"])

    def test_correction_overrides_an_earlier_weak_inference(self):
        self.observe("interaction_profile.preferred_verbosity", "thorough",
                     source_type="agent_inference", provenance="agent_inference")
        self.assertLessEqual(self.confidence("interaction_profile.preferred_verbosity",
                                             "thorough"), 0.30)
        self.observe("interaction_profile.preferred_verbosity", "terse",
                     source_type="explicit_correction")
        self.assertGreater(self.confidence("interaction_profile.preferred_verbosity", "terse"),
                           self.confidence("interaction_profile.preferred_verbosity", "thorough"))

    def test_conflicting_values_surface_as_a_contradiction(self):
        self.observe("creative_profile.simplicity_vs_richness", "minimal")
        self.observe("creative_profile.simplicity_vs_richness", "feature_rich")
        profile = self.store.load()
        dims = [c["dimension"] for c in profile["contradictions"]]
        self.assertIn("creative_profile.simplicity_vs_richness", dims)
        conflict = next(c for c in profile["contradictions"]
                        if c["dimension"] == "creative_profile.simplicity_vs_richness")
        self.assertEqual(conflict["type"], "same_scope_conflict")

    def test_user_rejection_zeroes_confidence_and_sticks(self):
        self.observe("reasoning_profile.novelty_preference", "novel",
                     source_type="single_behavioral", provenance="agent_inference")
        self.store.reject("reasoning_profile.novelty_preference", value="novel",
                          reason="not true about me", inference_source="single_behavioral")
        b = self.belief("reasoning_profile.novelty_preference", "novel")
        self.assertEqual(b["confidence"], 0.0)
        self.assertTrue(b["rejected_by_user"])

        # A weak signal must not resurrect it.
        self.observe("reasoning_profile.novelty_preference", "novel",
                     source_type="single_behavioral", provenance="agent_inference")
        b = self.belief("reasoning_profile.novelty_preference", "novel")
        self.assertEqual(b["confidence"], 0.0,
                         "weak evidence must not relearn a rejected conclusion")

    def test_rejected_belief_can_be_revived_by_a_direct_statement(self):
        self.observe("reasoning_profile.novelty_preference", "novel",
                     source_type="single_behavioral", provenance="agent_inference")
        self.store.reject("reasoning_profile.novelty_preference", value="novel")
        self.observe("reasoning_profile.novelty_preference", "novel",
                     source_type="explicit_statement", provenance="direct_user_message")
        b = self.belief("reasoning_profile.novelty_preference", "novel")
        self.assertGreater(b["confidence"], 0.5,
                           "the user themselves can always overrule a rejection")

    def test_forget_removes_effect_but_keeps_history(self):
        self.observe("working_style.documentation_appetite", "minimal")
        before_events = self.store.events.count()
        self.store.forget(dimension="working_style.documentation_appetite")
        self.assertIsNone(self.belief("working_style.documentation_appetite"))
        self.assertGreater(self.store.events.count(), before_events,
                           "forget writes a tombstone rather than deleting evidence")

    def test_forget_allows_fresh_direct_evidence_after_tombstone(self):
        self.observe("working_style.documentation_appetite", "minimal")
        self.store.forget(dimension="working_style.documentation_appetite")
        self.observe("working_style.documentation_appetite", "thorough")
        self.assertIsNone(self.belief("working_style.documentation_appetite", "minimal"))
        self.assertGreater(
            self.confidence("working_style.documentation_appetite", "thorough"), 0.9
        )

    def test_rejection_is_scoped(self):
        dimension = "creative_profile.novelty_seeking"
        self.observe(dimension, "novel", scope="project", scope_key="alpha",
                     project_id="alpha", domain="software")
        self.observe(dimension, "novel", scope="project", scope_key="beta",
                     project_id="beta", domain="software")
        self.store.reject(dimension, value="novel", scope="project", scope_key="alpha")
        alpha = self.belief(dimension, "novel", scope="project", scope_key="alpha")
        beta = self.belief(dimension, "novel", scope="project", scope_key="beta")
        self.assertEqual(alpha["confidence"], 0.0)
        self.assertGreater(beta["confidence"], 0.9)

    def test_fold_is_deterministic(self):
        self.observe("interaction_profile.pace", "fast")
        self.observe("decision_style.speed", "decisive")
        a = self.store.fold()["materialized_from"]["fold_hash"]
        b = self.store.fold()["materialized_from"]["fold_hash"]
        self.assertEqual(a, b)

    def test_profile_is_fully_reconstructible_from_events(self):
        self.observe("interaction_profile.preferred_verbosity", "terse")
        self.observe("decision_style.option_breadth", "one_recommendation")
        original = self.store.load()
        self.store.path.unlink()
        rebuilt = self.store.rebuild(reason="test-reconstruction")
        self.assertEqual(
            {(b["dimension"], str(b["value"]), b["confidence"]) for b in original["beliefs"]},
            {(b["dimension"], str(b["value"]), b["confidence"]) for b in rebuilt["beliefs"]},
        )

    def test_uncertainties_are_reported_for_thin_evidence(self):
        self.observe("reasoning_profile.tradeoff_style", "satisfice",
                     source_type="agent_inference", provenance="agent_inference")
        profile = self.store.load()
        dims = [u["dimension"] for u in profile["uncertainties"]]
        self.assertIn("reasoning_profile.tradeoff_style", dims)


if __name__ == "__main__":
    unittest.main()
