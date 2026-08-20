"""One conformance suite for every projection derived from the event log.

`docs/STATE_INVALIDATION.md` names the layers and what each user control does
to each one. This file is that document as executable assertions, so a new
projection cannot be added that quietly ignores a rejection, a tombstone, a
rollback or a reset -- which is exactly how the intent graph came to keep
serving a preference the user had deleted.
"""

from __future__ import annotations

from helpers import LiwmTestCase
from liwm.compaction import compact
from liwm.intent_graph import IntentGraphStore
from liwm.metrics import compute_metrics
from liwm.question_outcomes import QuestionOutcomeStore
from liwm.study import export_study, set_study_enabled

V = "interaction_profile.preferred_verbosity"


class _Populated(LiwmTestCase):
    """A home with something in every layer that derives from the log."""

    def setUp(self):
        super().setUp()
        self.graph = IntentGraphStore(self.home)
        self.evidence, _ = self.observe(V, "detailed", session_id="s1")
        _, self.node = self.graph.add_node(
            "preference", "Detailed answers", "direct_user_message", 0.9,
            evidence_refs=[self.evidence["event_id"]], session_id="s1")
        self.kept, _ = self.observe("preferences.language", "python", session_id="s1")

        self.store.events.record("question_asked", "agent_inference", session_id="s1",
                                 payload={"question_id": "q1"})
        QuestionOutcomeStore(self.store).record(
            "q1", "verbosity", [V], 0.8, 0.4, 0.2, session_id="s1")

        from liwm.prediction import make_prediction, record_prediction, resolve_prediction
        prediction = make_prediction(0.7, 0.6)
        record_prediction(self.store, prediction, session_id="s1")
        feedback = self.store.events.record(
            "feedback", "direct_user_message", session_id="s1",
            payload={"acceptance": 0.9, "prediction_id": prediction["id"]})
        resolve_prediction(self.store, prediction["id"], session_id="s1",
                           evaluator_type="observed_human_outcome",
                           evidence_event_id=feedback["event_id"])

    def _layers(self):
        """Every active projection, as the thing a consumer would actually read."""
        return {
            "profile": {b["dimension"] for b in self.store.load()["beliefs"]},
            "runtime_context": set(self.store.context_view(min_confidence=0.0)),
            "intent_graph": {row["id"] for row in self.graph.graph()["nodes"]},
            "metrics": compute_metrics(self.store)["calibration"]["samples"],
            "question_outcomes": len(QuestionOutcomeStore(self.store).rows()),
        }


class ForgetReachesEveryActiveLayer(_Populated):
    def test_a_dimension_tombstone_clears_the_profile_and_the_graph(self):
        self.store.forget(dimension=V)
        layers = self._layers()
        self.assertNotIn(V, layers["profile"])
        self.assertNotIn(V, layers["runtime_context"])
        self.assertEqual(layers["intent_graph"], set())

    def test_a_tombstone_leaves_unrelated_evidence_alone(self):
        self.store.forget(dimension=V)
        self.assertIn("preferences.language", self._layers()["profile"])

    def test_metrics_and_question_history_are_measurement_not_belief(self):
        # These record what LIWM did, not what it believes about the user. A
        # tombstone about a preference must not silently rewrite the record of
        # how well the framework predicted, or its calibration figures would
        # improve every time someone deleted an inconvenient belief.
        before = self._layers()
        self.store.forget(dimension=V)
        after = self._layers()
        self.assertEqual(before["metrics"], after["metrics"])
        self.assertEqual(before["question_outcomes"], after["question_outcomes"])

    def test_the_audit_log_still_holds_everything(self):
        self.store.forget(dimension=V)
        ids = {event["event_id"]
               for event in self.store.events.iter_events(include_quarantined=True)}
        self.assertIn(self.evidence["event_id"], ids)
        self.assertTrue(self.store.events.verify()["ok"])


class RejectionReachesEveryActiveLayer(_Populated):
    def test_a_rejected_belief_is_zeroed_and_stays_zeroed(self):
        self.store.reject(V, "detailed")
        self.assertEqual(self.belief(V, "detailed")["confidence"], 0.0)
        self.observe(V, "detailed", source_type="single_behavioral")
        self.assertEqual(self.belief(V, "detailed")["confidence"], 0.0)

    def test_a_rejected_belief_leaves_the_runtime_context(self):
        self.store.reject(V, "detailed")
        self.assertNotIn(V, self.store.context_view(min_confidence=0.0))


class ResetAndRollbackReachEveryActiveLayer(_Populated):
    def test_reset_clears_every_derived_layer_at_once(self):
        self.store.events.record("reset", "direct_user_message", payload={"type": "soft"})
        self.store.rebuild(reason="test")
        layers = self._layers()
        self.assertEqual(layers["profile"], set())
        self.assertEqual(layers["intent_graph"], set())

    def test_rollback_restores_the_branch_in_every_layer(self):
        cutoff = self.store.events.latest(1)[0]["ts"]
        before = self._layers()
        self.observe(V, "terse")
        self.store.rollback(cutoff)
        after = self._layers()
        self.assertEqual(before["profile"], after["profile"])
        self.assertEqual(before["intent_graph"], after["intent_graph"])


class CompactionChangesNothingAnyConsumerCanSee(_Populated):
    """Compaction preserving user.json is not the same as preserving semantics.

    Every consumer folds the same log for itself, so equivalence has to be
    checked per consumer or a compaction bug shows up first in whichever
    projection nobody thought to check.
    """

    def test_every_layer_is_identical_across_compaction(self):
        before = self._layers()
        compact(self.store)
        self.assertEqual(before, self._layers())

    def test_forget_semantics_survive_compaction_in_both_directions(self):
        self.store.forget(dimension=V)
        before = self._layers()
        compact(self.store)
        self.assertEqual(before, self._layers())

        self.observe(V, "terse")
        self.assertIn(V, self._layers()["profile"])

    def test_a_tombstone_written_after_compaction_still_reaches_archived_evidence(self):
        compact(self.store)
        self.store.forget(dimension=V)
        layers = self._layers()
        self.assertNotIn(V, layers["profile"])
        self.assertEqual(layers["intent_graph"], set())

    def test_rollback_still_works_across_a_compaction_boundary(self):
        cutoff = self.store.events.latest(1)[0]["ts"]
        compact(self.store)
        self.observe(V, "terse")
        self.store.rollback(cutoff)
        self.assertEqual(self.belief(V, "detailed")["value"], "detailed")

    def test_resolved_predictions_and_question_history_survive(self):
        before = self._layers()
        compact(self.store)
        after = self._layers()
        self.assertEqual(before["metrics"], after["metrics"])
        self.assertEqual(before["question_outcomes"], after["question_outcomes"])

    def test_the_study_export_sees_the_same_events(self):
        set_study_enabled(self.home, True)
        self.observe("preferences.after_consent", "yes", session_id="s2")
        before = export_study(self.home, out=str(self.home / "before.json"))["events"]
        compact(self.store)
        after = export_study(self.home, out=str(self.home / "after.json"))["events"]
        self.assertEqual([row["event_id"] for row in before],
                         [row["event_id"] for row in after])

    def test_raw_history_is_retained_rather_than_discarded(self):
        ids = {event["event_id"]
               for event in self.store.events.iter_events(include_quarantined=True)}
        compact(self.store)
        self.assertEqual(ids, {
            event["event_id"]
            for event in self.store.events.iter_events(include_quarantined=True)})
