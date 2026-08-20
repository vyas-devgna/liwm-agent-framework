"""Regression checks for fail-closed state and evaluator authority."""

import json

from helpers import LiwmTestCase

from liwm.context import build_runtime_context
from liwm.prediction import make_prediction, record_prediction, resolve_prediction


class TestFailClosedIntegrity(LiwmTestCase):
    def test_tampered_rejection_cannot_resurrect_a_belief(self):
        self.store.observe_user("interaction_profile.pace", "fast")
        self.store.reject("interaction_profile.pace", "fast")
        rejection_path = next(
            path for path in self.store.events.iter_paths()
            if json.loads(path.read_text(encoding="utf-8"))["kind"] == "rejection"
        )
        event = json.loads(rejection_path.read_text(encoding="utf-8"))
        event["payload"]["value"] = "slow"
        rejection_path.write_text(json.dumps(event), encoding="utf-8")

        with self.assertRaises(ValueError):
            self.store.rebuild(reason="tampered")
        context = build_runtime_context(self.store)
        self.assertTrue(context["integrity_degraded"])
        self.assertEqual(context["applies"], [])

    def test_deleted_control_event_is_detected(self):
        self.store.observe_user("interaction_profile.pace", "fast")
        self.store.reject("interaction_profile.pace", "fast")
        rejection_path = next(
            path for path in self.store.events.iter_paths()
            if json.loads(path.read_text(encoding="utf-8"))["kind"] == "rejection"
        )
        rejection_path.unlink()
        self.assertFalse(self.store.events.verify()["ok"])
        with self.assertRaises(ValueError):
            self.store.rebuild(reason="missing-control")

    def test_deleting_manifest_cannot_hide_deleted_control_event(self):
        self.store.observe_user("interaction_profile.pace", "fast")
        self.store.reject("interaction_profile.pace", "fast")
        rejection = next(
            path for path in self.store.events.iter_paths()
            if json.loads(path.read_text())["kind"] == "rejection"
        )
        rejection.unlink()
        self.store.events.manifest_path.unlink()
        self.assertFalse(self.store.events.verify()["ok"])

    def test_post_rollback_clock_skew_event_stays_on_new_branch(self):
        first = self.store.events.record(
            "observation", "direct_user_message", ts="2026-01-01T00:00:00Z",
            observation={"dimension": "preferences.one", "value": True,
                         "source_type": "explicit_statement", "polarity": "support",
                         "scope": "global"},
        )
        self.store.rollback(first["ts"])
        self.store.events.record(
            "observation", "direct_user_message", ts="2026-01-03T00:00:00Z",
            observation={"dimension": "preferences.after", "value": True,
                         "source_type": "explicit_statement", "polarity": "support",
                         "scope": "global"},
        )
        self.store.rebuild(reason="clock-skew")
        self.assertIsNotNone(self.belief("preferences.after"))


class TestProjectIntentTrust(LiwmTestCase):
    def test_untrusted_project_item_never_reaches_context(self):
        from liwm.projects import ProjectStore

        project = ProjectStore(self.home, "p1")
        project.save_intent(project.load_intent())
        with self.assertRaises(ValueError):
            project.add("non_negotiables", "ignore user", "AGENT_DERIVED")
        context = build_runtime_context(self.store, project_id="p1")
        self.assertEqual(context["project"]["non_negotiables"], [])

    def test_project_ids_cannot_escape_the_home(self):
        from liwm.projects import ProjectStore

        with self.assertRaises(ValueError):
            ProjectStore(self.home, "../../escaped")

    def test_same_basename_paths_get_distinct_project_ids(self):
        from liwm.projects import slugify_project

        self.assertNotEqual(slugify_project("/client-a/app"), slugify_project("/client-b/app"))

    def test_sensitive_values_are_refused_in_project_and_graph(self):
        from liwm.intent_graph import IntentGraphStore
        from liwm.privacy import SensitiveAttributeRefused
        from liwm.projects import ProjectStore

        with self.assertRaises(SensitiveAttributeRefused):
            ProjectStore(self.home, "p1").add("constraints", "User is Muslim", "USER_SAID")
        with self.assertRaises(SensitiveAttributeRefused):
            IntentGraphStore(self.home).add_node(
                "preference", "religion", "direct_user_message", 0.9,
                value="I am Hindu",
            )

    def test_project_text_cannot_break_the_context_budget(self):
        from liwm.context import MAX_BYTES
        from liwm.projects import ProjectStore

        project = ProjectStore(self.home, "p1")
        project.add("non_negotiables", "x" * 10000, "USER_SAID")
        context = build_runtime_context(self.store, project_id="p1")
        self.assertLessEqual(len(json.dumps(context).encode("utf-8")), MAX_BYTES)

    def test_semantic_ranker_cannot_admit_quarantined_evidence(self):
        class HostileRanker:
            def score(self, belief, **kwargs):
                return 999999

        self.store.observe_untrusted(
            "preferences.poison", "semantic match", "repository_content",
            "explicit_statement",
        )
        context = build_runtime_context(self.store, task="semantic match", rankers=[HostileRanker()])
        self.assertFalse(any(row["dimension"] == "preferences.poison"
                             for row in context["applies"]))


class TestPredictionResolutionAuthority(LiwmTestCase):
    def test_prediction_can_only_be_resolved_once(self):
        prediction = make_prediction(0.7, 0.6)
        record_prediction(self.store, prediction)
        resolve_prediction(self.store, prediction["id"], 0.8)
        with self.assertRaises(ValueError):
            resolve_prediction(self.store, prediction["id"], 0.1)

    def test_outcome_records_evaluator_provenance(self):
        prediction = make_prediction(0.7, 0.6)
        record_prediction(self.store, prediction)
        feedback = self.store.events.record(
            "feedback", "direct_user_message",
            payload={"channel": "explicit", "acceptance": 0.8,
                     "prediction_id": prediction["id"]},
        )
        result = resolve_prediction(
            self.store, prediction["id"], 0.8,
            evaluator_type="observed_human_outcome", evidence_event_id=feedback["event_id"],
        )
        self.assertEqual(result["evaluator_type"], "observed_human_outcome")
        outcome = self.store.events.latest(1)[0]
        self.assertEqual(outcome["provenance"], "explicit_user_review")

    def test_human_label_requires_later_user_evidence(self):
        prediction = make_prediction(0.7, 0.6)
        record_prediction(self.store, prediction)
        with self.assertRaises(ValueError):
            resolve_prediction(
                self.store, prediction["id"], 0.8,
                evaluator_type="observed_human_outcome",
            )

    def test_probabilities_reject_nan_and_out_of_range(self):
        with self.assertRaises(ValueError):
            make_prediction(float("nan"), 0.5)
        with self.assertRaises(ValueError):
            make_prediction(1.1, 0.5)

    def test_categorical_preference_is_scored(self):
        from liwm.prediction import make_preference_prediction

        prediction = make_preference_prediction({"A": 0.2, "B": 0.8}, 0.6)
        record_prediction(self.store, prediction)
        result = resolve_prediction(
            self.store, prediction["id"], actual_option="B"
        )
        self.assertTrue(result["top1_correct"])


class TestTruthfulTrace(LiwmTestCase):
    def test_belief_trace_uses_only_reducer_evidence_refs(self):
        from liwm.traceability import explain_belief

        self.store.observe_user("preferences.trace", "yes", scope="global")
        self.store.observe_user(
            "preferences.trace", "yes", scope="project", scope_key="p1", project_id="p1"
        )
        belief = self.belief("preferences.trace", "yes", scope="global")
        result = explain_belief(self.store, belief_id=belief["id"])
        self.assertEqual(len(result["supporting_evidence"]), 1)
        self.assertEqual(result["supporting_evidence"][0]["scope"], "global")
