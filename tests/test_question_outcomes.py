"""Sparse question outcomes use heuristics until local evidence is sufficient."""

from helpers import LiwmTestCase

from liwm.question_outcomes import MIN_SAMPLES, QuestionOutcomeStore


class TestQuestionOutcomes(LiwmTestCase):
    def test_empirical_estimate_waits_for_minimum_samples(self):
        outcomes = QuestionOutcomeStore(self.store)
        for index in range(MIN_SAMPLES - 1):
            self.store.events.record(
                "question_asked", "agent_inference",
                payload={"question_id": "q%d" % index},
            )
            outcomes.record("q%d" % index, "verbosity", ["interaction_profile.pace"],
                            0.8, 0.4, 0.4, domain="software")
        self.assertFalse(outcomes.effectiveness(
            "verbosity", "interaction_profile.pace", "software")["empirical"])
        self.store.events.record(
            "question_asked", "agent_inference", payload={"question_id": "q-final"}
        )
        outcomes.record("q-final", "verbosity", ["interaction_profile.pace"],
                        0.8, 0.4, 0.3, changed_decision=True, domain="software")
        estimate = outcomes.effectiveness(
            "verbosity", "interaction_profile.pace", "software"
        )
        self.assertTrue(estimate["empirical"])
        self.assertEqual(estimate["level"], "family_dimension_domain")
