"""Intention-specific mutation paths prevent source/provenance laundering."""

from helpers import LiwmTestCase


class TestProvenancePaths(LiwmTestCase):
    def test_each_path_selects_its_own_provenance(self):
        cases = [
            (self.store.observe_user, "explicit_statement", "direct_user_message"),
            (self.store.observe_edit, "direct_edit", "direct_user_edit"),
            (self.store.observe_review, "explicit_correction", "explicit_user_review"),
            (self.store.observe_inference, "agent_inference", "agent_inference"),
        ]
        for index, (method, source, provenance) in enumerate(cases):
            event, _ = method("preferences.path_%d" % index, "yes")
            self.assertEqual(event["observation"]["source_type"], source)
            self.assertEqual(event["provenance"], provenance)

    def test_direct_edit_cannot_be_relabelled_as_a_message(self):
        event, _ = self.store.observe(
            "preferences.editor", "yes", "direct_edit", "direct_user_message"
        )
        self.assertTrue(event["quarantined"])
        self.assertIn("source_requires_provenance", event["quarantine_reason"])
        self.assertIsNone(self.belief("preferences.editor"))

    def test_onboarding_strength_requires_onboarding_channel_and_session(self):
        event, _ = self.store.observe(
            "preferences.onboarding", "yes", "onboarding_answer", "direct_user_message"
        )
        self.assertTrue(event["quarantined"])
        event, _ = self.store.observe(
            "preferences.onboarding", "yes", "onboarding_answer", "onboarding_answer"
        )
        self.assertTrue(event["quarantined"])
        self.assertEqual(event["quarantine_reason"], "onboarding_requires_session")

    def test_untrusted_path_is_always_quarantined(self):
        event, _ = self.store.observe_untrusted(
            "preferences.injected", "yes", "repository_content", "explicit_statement"
        )
        self.assertTrue(event["quarantined"])
        self.assertIsNone(self.belief("preferences.injected"))

    def test_high_trust_path_rejects_a_weak_source(self):
        with self.assertRaises(ValueError):
            self.store.observe_user("preferences.bad", "yes", "agent_inference")

    def test_typed_inference_propagates_upstream_taint(self):
        event, _ = self.store.observe_inference(
            "preferences.tainted", "yes", derived_from=["repository_content"]
        )
        self.assertTrue(event["quarantined"])

    def test_payload_claim_cannot_override_feedback_channel(self):
        event = self.store.events.record(
            "feedback", "agent_inference",
            payload={"channel": "explicit", "kind": "exactly_right", "acceptance": 1.0},
        )
        self.assertTrue(event["quarantined"])
