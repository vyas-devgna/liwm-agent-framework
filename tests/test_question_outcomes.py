"""Question effectiveness is shrunk toward a prior, never switched on."""

from helpers import LiwmTestCase

from liwm.question_outcomes import (
    HEURISTIC_PRIOR, PLANNER_BOUNDS, QuestionOutcomeStore, planner_factor,
)


class TestQuestionOutcomes(LiwmTestCase):
    def setUp(self):
        super().setUp()
        self.outcomes = QuestionOutcomeStore(self.store)

    def _record(self, index, post=0.4, session=None, **kwargs):
        self.store.events.record(
            "question_asked", "agent_inference",
            payload={"question_id": "q%d" % index}, session_id=session,
        )
        return self.outcomes.record(
            "q%d" % index, "verbosity", ["interaction_profile.pace"],
            0.8, 0.4, post, domain="software", session_id=session, **kwargs)

    def _estimate(self):
        return self.outcomes.effectiveness(
            "verbosity", "interaction_profile.pace", "software")

    def test_no_history_is_the_prior_and_a_neutral_planner_factor(self):
        estimate = self._estimate()
        self.assertEqual(estimate["estimate"], HEURISTIC_PRIOR)
        self.assertEqual(estimate["level"], "prior")
        self.assertFalse(estimate["empirical"])
        self.assertEqual(estimate["planner_factor"], 1.0)

    def test_the_estimate_moves_smoothly_and_never_jumps_at_a_threshold(self):
        seen = [self._estimate()["estimate"]]
        steps = []
        for index in range(20):
            self._record(index, post=0.1, session="s%d" % index)
            estimate = self._estimate()["estimate"]
            steps.append(abs(estimate - seen[-1]))
            seen.append(estimate)
        # Monotone toward the evidence, with no single sample worth more than a
        # tenth of the range -- the old rule moved from "ignored" to "in full
        # control" between the fourth observation and the fifth.
        self.assertGreater(seen[-1], seen[0])
        self.assertLess(max(steps), 0.10)
        self.assertLess(steps[4], steps[0] + 0.02)

    def test_evidence_pulls_the_estimate_but_the_prior_still_shows_at_n_equals_one(self):
        self._record(0, post=0.0, changed_decision=True, session="s0")
        estimate = self._estimate()
        self.assertGreater(estimate["estimate"], HEURISTIC_PRIOR)
        self.assertLess(estimate["estimate"], 0.55)
        self.assertGreater(estimate["shrinkage"], 0.9)
        self.assertEqual(estimate["samples"], 1)

    def test_the_planner_factor_is_bounded_at_both_ends(self):
        low, high = PLANNER_BOUNDS
        self.assertEqual(planner_factor(0.0), low)
        self.assertEqual(planner_factor(1.0), high)
        self.assertEqual(planner_factor(HEURISTIC_PRIOR), 1.0)

        for index in range(30):
            self._record(index, post=0.0, changed_decision=True,
                         later_correction_signal=True, session="s%d" % index)
        self.assertLessEqual(self._estimate()["planner_factor"], high)

    def test_same_session_outcomes_are_worth_less_than_separate_ones(self):
        for index in range(6):
            self._record(index, post=0.0, session="one-session")
        clustered = self._estimate()["effective_sample_size"]

        other = QuestionOutcomeStore(self.store)
        self.setUp()
        self.outcomes = other = QuestionOutcomeStore(self.store)
        for index in range(6):
            self._record(index, post=0.0, session="s%d" % index)
        spread = self._estimate()["effective_sample_size"]

        self.assertLess(clustered, spread)

    def test_an_agent_estimate_carries_less_weight_than_the_user_saying_so(self):
        self._record(0, post=0.0, session="s0")
        agent_only = self._estimate()["effective_sample_size"]

        self.setUp()
        self.outcomes = QuestionOutcomeStore(self.store)
        self._record(0, post=0.0, session="s0", explicit_user_usefulness=True)
        stated = self._estimate()

        self.assertGreater(stated["effective_sample_size"], agent_only)
        self.assertEqual(stated["evaluator_mix"], {"explicit_user_usefulness": 1})

    def test_answer_evidence_is_resolved_not_merely_stored(self):
        evidence, _ = self.observe("interaction_profile.pace", "fast")
        event = self._record(0, session="s0",
                             answer_evidence=[evidence["event_id"], "evt_deadbeef"])
        payload = event["payload"]
        self.assertEqual(payload["answer_evidence"], [evidence["event_id"]])
        self.assertEqual(payload["unresolved_evidence"], ["evt_deadbeef"])
        self.assertEqual(payload["evaluator_type"], "user_evidence")

    def test_claiming_user_evidence_without_any_is_refused(self):
        with self.assertRaises(ValueError):
            self._record(0, session="s0", evaluator_type="user_evidence")

    def test_the_gain_field_says_it_is_an_estimate(self):
        event = self._record(0, session="s0")
        self.assertIn("estimated_uncertainty_reduction", event["payload"])
        self.assertNotIn("observed_information_gain", event["payload"])

    def test_zero_two_rows_are_read_under_their_old_name_as_agent_estimates(self):
        self.store.events.record(
            "question_asked", "agent_inference", payload={"question_id": "legacy"})
        self.store.events.record(
            "question_answered", "agent_inference",
            payload={"question_id": "legacy", "family": "verbosity",
                     "dimensions": ["interaction_profile.pace"],
                     "observed_information_gain": 0.4})
        rows = self.outcomes.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["estimated_uncertainty_reduction"], 0.4)
        self.assertEqual(rows[0]["evaluator_type"], "agent_estimate")
