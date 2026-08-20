"""Onboarding: exactly ten questions, broad, adaptive, and not a quiz."""

from __future__ import annotations

import unittest

from helpers import LiwmTestCase

from liwm.onboarding import (
    MAX_PER_FAMILY,
    MIN_FAMILIES,
    ONBOARDING_QUESTION_COUNT,
    OnboardingSession,
)
from liwm.question_bank import by_id


class TestOnboarding(LiwmTestCase):
    def _run(self, answer_fn=None):
        session = OnboardingSession(self.store, session_id="onb")
        session.start()
        asked = []
        for _ in range(ONBOARDING_QUESTION_COUNT + 3):
            q = session.next_question()
            if q is None:
                break
            asked.append(q)
            observations = answer_fn(q) if answer_fn else []
            session.record_answer(q["id"], "answer for %s" % q["id"],
                                  observations=observations)
        session.complete(summary="a short summary")
        return session, asked

    def test_asks_exactly_ten_questions(self):
        _, asked = self._run()
        self.assertEqual(len(asked), ONBOARDING_QUESTION_COUNT)

    def test_questions_are_never_repeated(self):
        _, asked = self._run()
        ids = [q["id"] for q in asked]
        self.assertEqual(len(ids), len(set(ids)))

    def test_covers_at_least_eight_families(self):
        _, asked = self._run()
        families = {q["family"] for q in asked}
        self.assertGreaterEqual(len(families), MIN_FAMILIES)

    def test_no_family_appears_more_than_twice(self):
        _, asked = self._run()
        counts = {}
        for q in asked:
            counts[q["family"]] = counts.get(q["family"], 0) + 1
        self.assertLessEqual(max(counts.values()), MAX_PER_FAMILY)

    def test_questions_are_mostly_experiential(self):
        """They should feel like conversation, not a specification interview."""
        _, asked = self._run()
        experiential = len([q for q in asked if q["class"] == "experiential"])
        self.assertGreaterEqual(experiential, 8)

    def test_onboarding_questions_are_drawn_from_the_onboarding_set(self):
        _, asked = self._run()
        for q in asked:
            self.assertTrue(by_id(q["id"])["onboarding_ok"])

    def test_answers_enter_at_capped_self_report_strength(self):
        def answer(q):
            return [{"dimension": d, "value": "test_value"} for d in q["resolves"][:1]]

        self._run(answer_fn=answer)
        profile = self.store.load()
        onboarding_beliefs = [b for b in profile["beliefs"]
                              if "onboarding_answer" in b["source_types"]]
        self.assertTrue(onboarding_beliefs)
        for b in onboarding_beliefs:
            self.assertLessEqual(b["confidence"], 0.70,
                                 "self-report must not outrank observed behaviour")

    def test_behaviour_later_overrules_onboarding_self_report(self):
        def answer(q):
            if "interaction_profile.preferred_verbosity" in q["resolves"]:
                return [{"dimension": "interaction_profile.preferred_verbosity",
                         "value": "thorough"}]
            return []

        self._run(answer_fn=answer)
        before = self.confidence("interaction_profile.preferred_verbosity", "thorough")
        self.observe("interaction_profile.preferred_verbosity", "terse",
                     source_type="explicit_correction")
        after_terse = self.confidence("interaction_profile.preferred_verbosity", "terse")
        self.assertGreater(after_terse, before)

    def test_adaptivity_changes_the_sequence(self):
        """A decisive answer must redirect later questions, otherwise this is a
        fixed questionnaire wearing a costume."""
        _, baseline = self._run()

        self.setUp()  # fresh home

        def answer(q):
            return [{"dimension": d, "value": "settled"} for d in q["resolves"]]

        _, adapted = self._run(answer_fn=answer)
        self.assertNotEqual([q["id"] for q in baseline], [q["id"] for q in adapted])

    def test_state_reports_progress(self):
        session = OnboardingSession(self.store, session_id="onb")
        session.start()
        self.assertEqual(session.state()["status"], "in_progress")
        q = session.next_question()
        session.record_answer(q["id"], "x")
        state = session.state()
        self.assertEqual(state["answered"], 1)
        self.assertEqual(state["remaining"], ONBOARDING_QUESTION_COUNT - 1)

    def test_completion_is_recorded_with_coverage(self):
        session, _ = self._run()
        profile = self.store.load()
        self.assertEqual(profile["onboarding"]["status"], "completed")
        self.assertEqual(profile["onboarding"]["questions_asked"], ONBOARDING_QUESTION_COUNT)

    def test_user_can_correct_the_closing_summary(self):
        def answer(q):
            if "creative_profile.novelty_seeking" in q["resolves"]:
                return [{"dimension": "creative_profile.novelty_seeking", "value": "novel"}]
            return []

        session, _ = self._run(answer_fn=answer)
        session.correct("creative_profile.novelty_seeking", "familiar",
                        reason="that's not right")
        self.assertGreater(self.confidence("creative_profile.novelty_seeking", "familiar"),
                           self.confidence("creative_profile.novelty_seeking", "novel"))

    def test_onboarding_never_stores_a_sensitive_attribute(self):
        session = OnboardingSession(self.store, session_id="onb")
        session.start()
        q = session.next_question()
        with self.assertRaises(ValueError):
            session.record_answer(q["id"], "x", observations=[
                {"dimension": "religion", "value": "something"}
            ])
        self.assertFalse([b for b in self.store.load()["beliefs"]
                          if "religion" in b["dimension"]])

    def test_answer_must_match_an_asked_unanswered_question(self):
        session = OnboardingSession(self.store, session_id="onb")
        session.start()
        with self.assertRaises(ValueError):
            session.record_answer("does-not-exist", "x")
        q = session.next_question()
        session.record_answer(q["id"], "x")
        with self.assertRaises(ValueError):
            session.record_answer(q["id"], "again")



class TestOfferedFlag(LiwmTestCase):
    """Declining onboarding must be remembered, or the agent nags forever."""

    def test_declining_is_distinguishable_from_never_being_asked(self):
        from liwm.config import ConfigStore
        from liwm.context import build_runtime_context

        ctx = build_runtime_context(self.store, domain="software", task="a task")
        self.assertEqual(ctx["onboarding_status"], "not_started")
        self.assertFalse(ctx["onboarding_already_offered"])

        ConfigStore(self.home).set("onboarding_offered", True)
        ctx = build_runtime_context(self.store, domain="software", task="a task")
        self.assertEqual(ctx["onboarding_status"], "not_started",
                         "declining is not the same as completing")
        self.assertTrue(ctx["onboarding_already_offered"])



if __name__ == "__main__":
    unittest.main()
