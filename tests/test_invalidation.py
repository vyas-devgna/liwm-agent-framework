"""Forgetting must reach every projection, not only user.json.

The defect these tests were written for: ``liwm forget`` removed a preference
from the profile while the intent graph kept a node standing on the same
evidence, so the deleted fact was still readable through a second view.
"""

from __future__ import annotations

from helpers import LiwmTestCase, days_ago
from liwm.compaction import compact
from liwm.intent_graph import IntentGraphStore
from liwm.invalidation import invalidated_event_ids
from liwm.schema import SchemaStore


class ForgetReachesTheIntentGraph(LiwmTestCase):
    def setUp(self):
        super().setUp()
        self.graph = IntentGraphStore(self.home)

    def _node_on(self, evidence, label="Terse answers", **kwargs):
        return self.graph.add_node(
            "preference", label, "direct_user_message", 0.9,
            evidence_refs=[evidence["event_id"]], **kwargs)

    def test_forgetting_a_dimension_deactivates_what_stood_on_it(self):
        evidence, _ = self.observe("interaction_profile.preferred_verbosity", "terse")
        _, node = self._node_on(evidence)
        self.assertEqual([row["id"] for row in self.graph.graph()["nodes"]], [node["id"]])

        self.store.forget(dimension="interaction_profile.preferred_verbosity")

        graph = self.graph.graph(include_inactive=True)
        self.assertEqual(graph["nodes"], [])
        self.assertEqual([(row["id"], row["reason"]) for row in graph["inactive"]],
                         [(node["id"], "forgotten_basis")])
        self.assertEqual(
            [b for b in self.store.load()["beliefs"]
             if b["dimension"] == "interaction_profile.preferred_verbosity"], [])

    def test_forgetting_a_project_deactivates_its_scoped_state(self):
        evidence, _ = self.observe("preferences.tooling", "make",
                                   scope="project", scope_key="proj_a")
        _, node = self._node_on(evidence, label="Use make", scope="project",
                                scope_key="proj_a", project_id="proj_a")
        _, elsewhere = self.graph.add_node("goal", "Ship 0.3", "direct_user_message", 0.8)

        self.store.forget(project_id="proj_a")

        active = {row["id"] for row in self.graph.graph()["nodes"]}
        self.assertEqual(active, {elsewhere["id"]})
        self.assertNotIn(node["id"], active)

    def test_forgetting_a_belief_key_deactivates_only_that_belief(self):
        kept, _ = self.observe("preferences.language", "python")
        dropped, _ = self.observe("preferences.editor", "vim")
        _, kept_node = self._node_on(kept, label="Python")
        _, dropped_node = self._node_on(dropped, label="Vim")

        key = next(b["key"] for b in self.store.load()["beliefs"]
                   if b["dimension"] == "preferences.editor")
        self.store.forget(belief_key_=key)

        active = {row["id"] for row in self.graph.graph()["nodes"]}
        self.assertEqual(active, {kept_node["id"]})
        # The tombstone's subject survived the free-text screen. It did not
        # before: a pipe-separated composite key reads as prose by shape, so
        # ``forget --belief`` reached disk with its target blanked out.
        tombstone = self.store.events.latest(1, kinds={"forget"})[0]
        self.assertEqual(tombstone["payload"]["belief_key"], key)
        self.assertEqual(
            [b for b in self.store.load()["beliefs"] if b["key"] == key], [])

    def test_an_edge_dies_with_its_endpoint(self):
        evidence, _ = self.observe("preferences.editor", "vim")
        _, doomed = self._node_on(evidence, label="Vim")
        _, survivor = self.graph.add_node("goal", "Ship", "direct_user_message", 0.8)
        _, edge = self.graph.add_edge("supports", doomed["id"], survivor["id"],
                                      "direct_user_message", 0.7)
        self.assertEqual(len(self.graph.graph()["edges"]), 1)

        self.store.forget(dimension="preferences.editor")

        graph = self.graph.graph(include_inactive=True)
        self.assertEqual(graph["edges"], [])
        self.assertEqual({row["id"]: row["reason"] for row in graph["inactive"]},
                         {doomed["id"]: "forgotten_basis",
                          edge["id"]: "endpoint_inactive"})

    def test_new_evidence_after_a_forget_establishes_new_state(self):
        first, _ = self.observe("preferences.editor", "vim")
        self._node_on(first, label="Vim")
        self.store.forget(dimension="preferences.editor")

        second, _ = self.observe("preferences.editor", "vim")
        _, reborn = self._node_on(second, label="Vim again")

        self.assertEqual([row["id"] for row in self.graph.graph()["nodes"]],
                         [reborn["id"]])

    def test_a_node_cannot_be_built_on_forgotten_evidence(self):
        evidence, _ = self.observe("preferences.editor", "vim")
        self.store.forget(dimension="preferences.editor")

        event, _ = self._node_on(evidence, label="Sneaking it back")

        self.assertTrue(event["quarantined"])
        self.assertIn("forgotten_evidence", event["quarantine_reason"])
        self.assertEqual(self.graph.graph()["nodes"], [])

    def test_explain_and_trace_honour_the_tombstone_without_a_history_flag(self):
        evidence, _ = self.observe("preferences.editor", "vim")
        _, node = self._node_on(evidence, label="Vim")
        self.store.forget(dimension="preferences.editor")

        with self.assertRaises(KeyError):
            self.graph.explain(node["id"])
        with self.assertRaises(KeyError):
            self.graph.trace(node["id"])

        explained = self.graph.explain(node["id"], history=True)
        self.assertFalse(explained["active"])
        self.assertEqual(explained["element"]["inactive_reason"], "forgotten_basis")
        self.assertTrue(explained["basis"][0]["forgotten"])

    def test_forgotten_labels_never_enter_the_materialised_projection(self):
        evidence, _ = self.observe("preferences.editor", "vim")
        self._node_on(evidence, label="A secret label")
        self.store.forget(dimension="preferences.editor")

        written = self.graph.rebuild()
        self.assertNotIn("A secret label", str(written))
        self.assertNotIn("A secret label", self.graph.path.read_text(encoding="utf-8"))
        self.assertEqual(SchemaStore().validate(
            self.graph.graph(include_quarantined=True, include_inactive=True),
            "intent-graph"), [])

    def test_compaction_preserves_forget_semantics_in_the_graph(self):
        evidence, _ = self.observe("preferences.editor", "vim")
        _, node = self._node_on(evidence, label="Vim")
        _, kept = self.graph.add_node("goal", "Ship", "direct_user_message", 0.8)
        self.store.forget(dimension="preferences.editor")
        before = self.graph.graph(include_inactive=True)

        compact(self.store)

        after = self.graph.graph(include_inactive=True)
        self.assertEqual([row["id"] for row in after["nodes"]], [kept["id"]])
        self.assertEqual({row["id"] for row in after["inactive"]},
                         {row["id"] for row in before["inactive"]})
        self.assertNotIn(node["id"], {row["id"] for row in after["nodes"]})

    def test_reset_clears_the_graph_and_rollback_restores_it(self):
        evidence, _ = self.observe("preferences.editor", "vim")
        _, node = self._node_on(evidence, label="Vim")
        cutoff = self.store.events.latest(1)[0]["ts"]

        self.store.events.record("reset", "direct_user_message",
                                 payload={"type": "soft"})
        self.assertEqual(self.graph.graph()["nodes"], [])

        self.store.rollback(cutoff)
        self.assertEqual([row["id"] for row in self.graph.graph()["nodes"]], [node["id"]])


class TheTwoProjectionsShareOneRule(LiwmTestCase):
    def test_the_event_rule_names_exactly_what_the_fold_drops(self):
        kept, _ = self.observe("preferences.language", "python")
        dropped, _ = self.observe("preferences.editor", "vim")
        self.store.forget(dimension="preferences.editor")

        events = list(self.store.events.iter_events(include_quarantined=True))
        invalidated = invalidated_event_ids(events)

        self.assertIn(dropped["event_id"], invalidated)
        self.assertNotIn(kept["event_id"], invalidated)
        dimensions = {b["dimension"] for b in self.store.load()["beliefs"]}
        self.assertIn("preferences.language", dimensions)
        self.assertNotIn("preferences.editor", dimensions)

    def test_a_tombstone_never_reaches_forward(self):
        self.store.forget(dimension="preferences.editor")
        later, _ = self.observe("preferences.editor", "vim")

        events = list(self.store.events.iter_events(include_quarantined=True))
        self.assertNotIn(later["event_id"], invalidated_event_ids(events))
        self.assertIn("preferences.editor",
                      {b["dimension"] for b in self.store.load()["beliefs"]})

    def test_a_log_without_tombstones_invalidates_nothing(self):
        self.observe("preferences.language", "python")
        events = list(self.store.events.iter_events(include_quarantined=True))
        self.assertEqual(invalidated_event_ids(events), frozenset())


class GraphConfidenceTracksTheProfile(LiwmTestCase):
    def setUp(self):
        super().setUp()
        self.graph = IntentGraphStore(self.home)

    def test_recorded_confidence_is_immutable_and_effective_confidence_decays(self):
        _, node = self.graph.add_node("preference", "Terse", "direct_user_message", 0.9,
                                      decay_policy="volatile")
        fresh = self.graph.graph()["nodes"][0]
        self.assertEqual(fresh["recorded_confidence"], 0.9)
        self.assertAlmostEqual(fresh["effective_confidence"], 0.9, places=2)

        aged = self.graph.graph(now=days_ago(-365))["nodes"][0]
        self.assertEqual(aged["confidence"], 0.9)
        self.assertEqual(aged["recorded_confidence"], 0.9)
        self.assertLess(aged["effective_confidence"], 0.3)
        self.assertGreater(aged["effective_confidence"], 0.0)

    def test_a_node_cannot_outlive_the_effective_confidence_beneath_it(self):
        evidence, _ = self.observe("preferences.editor", "vim",
                                   source_type="single_behavioral")
        _, node = self.graph.add_node("preference", "Vim", "direct_user_message", 0.9,
                                      evidence_refs=[evidence["event_id"]],
                                      decay_policy="none")
        row = self.graph.graph(now=days_ago(-720))["nodes"][0]
        # decay_policy "none" freezes the node's own clock, but the observation
        # it rests on still ages, and the node may not be worth more than it.
        self.assertLessEqual(row["effective_confidence"], row["effective_ceiling"])
        self.assertLess(row["effective_confidence"], row["recorded_confidence"])

    def test_the_same_decay_curve_governs_both_projections(self):
        from liwm.evidence import recency_factor
        _, _ = self.graph.add_node("preference", "Terse", "direct_user_message", 0.8,
                                   decay_policy="standard")
        row = self.graph.graph(now=days_ago(-180))["nodes"][0]
        expected = 0.8 * recency_factor(row["updated_at"], "standard", now=days_ago(-180))
        self.assertAlmostEqual(row["effective_confidence"], round(expected, 4), places=3)


class StateEdgesChangeState(LiwmTestCase):
    def setUp(self):
        super().setUp()
        self.graph = IntentGraphStore(self.home)

    def _hypothesis(self):
        evidence, _ = self.observe("preferences.editor", "vim")
        _, node = self.graph.add_node(
            "intent_hypothesis", "Prefers vim", "agent_inference", 0.15,
            evidence_refs=[evidence["event_id"]], status="hypothesis")
        return node

    def test_falsified_by_actually_falsifies(self):
        hypothesis = self._hypothesis()
        _, outcome = self.graph.add_node("outcome", "Chose emacs", "direct_user_message", 0.9)
        self.graph.add_edge("falsified_by", hypothesis["id"], outcome["id"],
                            "direct_user_message", 0.9)

        row = next(r for r in self.graph.graph()["nodes"] if r["id"] == hypothesis["id"])
        self.assertEqual(row["recorded_status"], "hypothesis")
        self.assertEqual(row["status"], "falsified")
        self.assertIn("falsified by", row["status_reason"])

    def test_supersedes_retires_the_older_node(self):
        _, old = self.graph.add_node("goal", "Ship 0.2", "direct_user_message", 0.9)
        _, new = self.graph.add_node("goal", "Ship 0.3", "direct_user_message", 0.9)
        self.graph.add_edge("supersedes", new["id"], old["id"],
                            "direct_user_message", 0.9)

        rows = {r["id"]: r for r in self.graph.graph()["nodes"]}
        self.assertEqual(rows[old["id"]]["status"], "superseded")
        self.assertEqual(rows[new["id"]]["status"], "active")

    def test_a_weak_inference_cannot_retire_what_the_user_said(self):
        _, stated = self.graph.add_node("goal", "Ship 0.3", "direct_user_message", 0.9)
        evidence, _ = self.observe("preferences.editor", "vim")
        _, guess = self.graph.add_node("goal", "Maybe ship 0.4", "agent_inference", 0.15,
                                       evidence_refs=[evidence["event_id"]])
        self.graph.add_edge("supersedes", guess["id"], stated["id"],
                            "agent_inference", 0.15,
                            evidence_refs=[evidence["event_id"]])

        rows = {r["id"]: r for r in self.graph.graph()["nodes"]}
        self.assertEqual(rows[stated["id"]]["status"], "active")
        edge = self.graph.graph()["edges"][0]
        self.assertIn("too weak", edge["status_reason"])

    def test_descriptive_edges_leave_status_alone(self):
        _, a = self.graph.add_node("goal", "Ship", "direct_user_message", 0.9)
        _, b = self.graph.add_node("value", "Simplicity", "direct_user_message", 0.9)
        self.graph.add_edge("supports", b["id"], a["id"], "direct_user_message", 0.9)

        self.assertEqual({r["status"] for r in self.graph.graph()["nodes"]}, {"active"})


class ObservedOutcomesComeFromTheirEvidence(LiwmTestCase):
    """An "observed" label must be read out of the event that observed it.

    The old rule only required *some* later trusted user event to exist while
    the caller supplied the label separately, so a prediction of option A could
    be resolved as "the user chose B, observed" on the strength of the user
    having said "thanks".
    """

    def _predict(self, **kwargs):
        from liwm.prediction import make_prediction, record_prediction
        prediction = make_prediction(0.7, 0.6, **kwargs)
        record_prediction(self.store, prediction)
        return prediction

    def _preference(self):
        from liwm.prediction import make_preference_prediction, record_prediction
        prediction = make_preference_prediction({"a": 0.7, "b": 0.3}, 0.6)
        record_prediction(self.store, prediction)
        return prediction

    def _feedback(self, **payload):
        return self.store.events.record("feedback", "direct_user_message", payload=payload)

    def test_a_generic_later_message_is_not_an_observed_outcome(self):
        from liwm.prediction import resolve_prediction
        prediction = self._predict()
        thanks = self.store.events.record(
            "observation", "direct_user_message",
            observation={"dimension": "preferences.editor", "value": "vim",
                         "source_type": "explicit_statement", "polarity": "support"})
        with self.assertRaises(ValueError) as caught:
            resolve_prediction(self.store, prediction["id"], 0.9,
                               evaluator_type="observed_human_outcome",
                               evidence_event_id=thanks["event_id"])
        self.assertIn("must be a feedback event", str(caught.exception))

    def test_unlinked_feedback_is_not_evidence_for_this_prediction(self):
        from liwm.prediction import resolve_prediction
        prediction = self._predict()
        other = self._feedback(acceptance=0.9, prediction_id="prd_somethingelse")
        with self.assertRaises(ValueError) as caught:
            resolve_prediction(self.store, prediction["id"], 0.9,
                               evaluator_type="observed_human_outcome",
                               evidence_event_id=other["event_id"])
        self.assertIn("not linked to prediction", str(caught.exception))

    def test_the_caller_cannot_contradict_the_evidence(self):
        from liwm.prediction import resolve_prediction
        prediction = self._predict()
        evidence = self._feedback(acceptance=0.2, prediction_id=prediction["id"])
        with self.assertRaises(ValueError) as caught:
            resolve_prediction(self.store, prediction["id"], 0.95,
                               evaluator_type="observed_human_outcome",
                               evidence_event_id=evidence["event_id"])
        self.assertIn("contradicts the evidence event", str(caught.exception))

    def test_the_label_is_read_out_of_the_evidence(self):
        from liwm.prediction import resolve_prediction
        prediction = self._predict()
        evidence = self._feedback(acceptance=0.2, prediction_id=prediction["id"])
        result = resolve_prediction(self.store, prediction["id"],
                                    evaluator_type="observed_human_outcome",
                                    evidence_event_id=evidence["event_id"])
        self.assertEqual(result["actual_acceptance"], 0.2)
        self.assertEqual(result["actual_first_pass"], 0)
        self.assertEqual(result["outcome_binding"], "structured_feedback_event")

    def test_a_preference_needs_the_chosen_option_on_the_record(self):
        from liwm.prediction import resolve_prediction
        prediction = self._preference()
        vague = self._feedback(acceptance=0.9, prediction_id=prediction["id"])
        with self.assertRaises(ValueError) as caught:
            resolve_prediction(self.store, prediction["id"],
                               evaluator_type="observed_human_outcome",
                               actual_option="b", evidence_event_id=vague["event_id"])
        self.assertIn("which option was selected", str(caught.exception))

        chose_b = self._feedback(acceptance=0.9, selected_option="b",
                                 prediction_id=prediction["id"])
        with self.assertRaises(ValueError):
            resolve_prediction(self.store, prediction["id"],
                               evaluator_type="observed_human_outcome",
                               actual_option="a", evidence_event_id=chose_b["event_id"])

        result = resolve_prediction(self.store, prediction["id"],
                                    evaluator_type="observed_human_outcome",
                                    evidence_event_id=chose_b["event_id"])
        self.assertEqual(result["actual_option"], "b")
        self.assertFalse(result["top1_correct"])

    def test_evidence_recorded_before_the_prediction_is_refused(self):
        from liwm.prediction import make_prediction, record_prediction, resolve_prediction
        early = self._feedback(acceptance=0.9, prediction_id="prd_unknown")
        prediction = make_prediction(0.7, 0.6)
        record_prediction(self.store, prediction)
        with self.assertRaises(ValueError):
            resolve_prediction(self.store, prediction["id"], 0.9,
                               evaluator_type="observed_human_outcome",
                               evidence_event_id=early["event_id"])

    def test_calibration_keeps_unverified_history_in_its_own_bucket(self):
        from liwm.metrics import compute_metrics
        from liwm.prediction import make_prediction, record_prediction, resolve_prediction
        legacy = make_prediction(0.7, 0.6)
        record_prediction(self.store, legacy)
        resolve_prediction(self.store, legacy["id"], 0.9)   # agent_recorded

        prediction = self._predict()
        evidence = self._feedback(acceptance=0.9, prediction_id=prediction["id"])
        resolve_prediction(self.store, prediction["id"],
                           evaluator_type="observed_human_outcome",
                           evidence_event_id=evidence["event_id"])

        calibration = compute_metrics(self.store)["calibration"]
        self.assertIn("observed_human_outcome", calibration["by_evaluator"])
        self.assertIn("agent_recorded", calibration["by_evaluator"])
        self.assertFalse(calibration["expected_calibration_error_reliable"])
        self.assertEqual(calibration["unresolved_predictions"], 0)
