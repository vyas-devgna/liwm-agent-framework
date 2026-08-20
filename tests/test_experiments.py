"""A candidate earns human evidence without being sprung on anyone.

The gate demanded observed outcomes from a candidate that never ran, so the
strictest rule in the framework was also the one nothing could pass. These
tests cover the loop that closes it, and the consent that bounds it.
"""

from __future__ import annotations

from helpers import LiwmTestCase
from liwm.config import ConfigStore
from liwm.experiments import MAX_CANARY_EXPOSURE, ExperimentStore
from liwm.selfimprove import GUARDED_METRICS, CandidateRule, SelfImprovementStore


class _Consenting(LiwmTestCase):
    def _consent(self):
        config = ConfigStore(self.home)
        settings = config.load()
        settings["learning"]["experiments_enabled"] = True
        config.save(settings)


class ConsentBoundsExperiments(_Consenting):
    def test_enrolling_without_consent_is_refused(self):
        with self.assertRaises(ValueError) as caught:
            ExperimentStore(self.home).enroll("cand_a", "canary", store=self.store)
        self.assertIn("experiments are off", str(caught.exception))

    def test_consent_is_off_by_default(self):
        config = ConfigStore(self.home).load()
        self.assertFalse(config["learning"]["experiments_enabled"])

    def test_user_facing_exposure_is_capped(self):
        self._consent()
        with self.assertRaises(ValueError):
            ExperimentStore(self.home).enroll("cand_a", "canary", store=self.store,
                                              exposure=0.9)
        row = ExperimentStore(self.home).enroll(
            "cand_a", "canary", store=self.store, exposure=MAX_CANARY_EXPOSURE)
        self.assertEqual(row["exposure"], MAX_CANARY_EXPOSURE)


class AssignmentIsCommittedBeforeTheOutput(_Consenting):
    def setUp(self):
        super().setUp()
        self._consent()
        self.experiments = ExperimentStore(self.home)

    def test_shadow_never_reports_user_exposure(self):
        self.experiments.enroll("cand_a", "shadow", store=self.store)
        assignments = [self.experiments.assign("cand_a", "task-%d" % i, store=self.store)
                       for i in range(20)]
        self.assertTrue(all(row["condition"] == "candidate" for row in assignments))
        self.assertTrue(all(row["exposure"] == "shadow" for row in assignments))
        self.assertEqual(self.experiments.exposure_for(self.store, "cand_a"), set())

    def test_the_same_unit_always_lands_in_the_same_arm(self):
        self.experiments.enroll("cand_a", "canary", store=self.store, exposure=0.2,
                                seed="fixed")
        first = self.experiments.assign("cand_a", "task-7")
        second = self.experiments.assign("cand_a", "task-7")
        self.assertEqual(first["draw"], second["draw"])
        self.assertEqual(first["exposure"], second["exposure"])

    def test_canary_exposes_roughly_the_registered_fraction(self):
        self.experiments.enroll("cand_a", "canary", store=self.store, exposure=0.2,
                                seed="fixed")
        exposed = sum(self.experiments.assign("cand_a", "task-%d" % i)["exposure"]
                      == "user_facing" for i in range(400))
        self.assertGreater(exposed, 400 * 0.1)
        self.assertLess(exposed, 400 * 0.3)

    def test_an_unenrolled_candidate_cannot_be_assigned(self):
        with self.assertRaises(KeyError):
            self.experiments.assign("cand_missing", "task-1")

    def test_stopping_ends_assignment(self):
        self.experiments.enroll("cand_a", "shadow", store=self.store)
        self.assertTrue(self.experiments.stop("cand_a", store=self.store))
        with self.assertRaises(KeyError):
            self.experiments.assign("cand_a", "task-1")


class ShadowEvidenceCannotPromote(_Consenting):
    def setUp(self):
        super().setUp()
        self._consent()
        self.si = SelfImprovementStore(self.home)
        self.experiments = ExperimentStore(self.home)

    def _candidate(self):
        candidate = self.si.propose(CandidateRule.create(
            "Ask less about pace", "reduce pace questions", surface="behaviour"))
        self.si.attach_replay(candidate["id"], {
            "episodes": 20, "distinct_sessions": 5, "primary_delta": 0.10,
            "guarded_deltas": {metric: 0.0 for metric in GUARDED_METRICS},
        })
        self.si.attach_benchmark(candidate["id"], {
            "passed": True, "candidate_id": candidate["id"],
            "evaluator_type": "benchmark_ground_truth"})
        self.si.attach_adversarial(candidate["id"], {
            "passed": True, "failures": [], "candidate_id": candidate["id"],
            "suite_id": "liwm-adversarial-v1"})
        return self.si.read(candidate["id"])

    def _resolve(self, candidate_id, unit, session):
        from liwm.prediction import make_prediction, record_prediction, resolve_prediction
        prediction = make_prediction(0.7, 0.6, candidate_id=candidate_id, unit=unit)
        record_prediction(self.store, prediction, session_id=session)
        feedback = self.store.events.record(
            "feedback", "direct_user_message", session_id=session,
            payload={"acceptance": 0.9, "prediction_id": prediction["id"]})
        resolve_prediction(self.store, prediction["id"], session_id=session,
                           evaluator_type="observed_human_outcome",
                           evidence_event_id=feedback["event_id"])

    def test_six_shadow_outcomes_do_not_satisfy_the_gate(self):
        candidate = self._candidate()
        self.experiments.enroll(candidate["id"], "shadow", store=self.store)
        for index in range(6):
            unit = "task-%d" % index
            self.experiments.assign(candidate["id"], unit, store=self.store,
                                    session_id="s%d" % index)
            self._resolve(candidate["id"], unit, "s%d" % index)

        verdict = self.si.evaluate_gate(candidate, store=self.store)
        self.assertFalse(verdict["passed"])
        self.assertTrue(any("candidate produced the work" in reason
                            for reason in verdict["reasons"]), verdict["reasons"])
        self.assertEqual(verdict["user_facing_units"], 0)

    def test_outcomes_from_a_canary_the_user_saw_do_satisfy_it(self):
        candidate = self._candidate()
        self.experiments.enroll(candidate["id"], "canary", store=self.store,
                                exposure=MAX_CANARY_EXPOSURE, seed="fixed")
        recorded, unit = 0, 0
        while recorded < 6:
            unit += 1
            assignment = self.experiments.assign(
                candidate["id"], "task-%d" % unit, store=self.store,
                session_id="s%d" % recorded)
            if assignment["exposure"] != "user_facing":
                continue
            self._resolve(candidate["id"], assignment["unit"], "s%d" % recorded)
            recorded += 1

        verdict = self.si.evaluate_gate(candidate, store=self.store)
        self.assertTrue(verdict["passed"], verdict["reasons"])
        self.assertEqual(verdict["resolved_outcomes"], 6)
        self.assertGreaterEqual(verdict["user_facing_units"], 6)


class AbIsNotACanaryWithADifferentName(_Consenting):
    def setUp(self):
        super().setUp()
        self._consent()
        self.experiments = ExperimentStore(self.home)

    def test_the_two_user_facing_modes_have_different_designs(self):
        canary = self.experiments.enroll("cand_a", "canary", store=self.store)
        ab = self.experiments.enroll("cand_b", "ab", store=self.store)
        self.assertEqual(canary["exposure"], 0.10)
        self.assertEqual(ab["exposure"], 0.50)

    def test_a_canary_cannot_be_ramped_to_a_trial(self):
        with self.assertRaises(ValueError):
            self.experiments.enroll("cand_a", "canary", store=self.store, exposure=0.5)

    def test_an_ab_arm_is_roughly_balanced(self):
        self.experiments.enroll("cand_b", "ab", store=self.store, seed="fixed")
        exposed = sum(self.experiments.assign("cand_b", "task-%d" % i)["exposure"]
                      == "user_facing" for i in range(400))
        self.assertGreater(exposed, 160)
        self.assertLess(exposed, 240)
