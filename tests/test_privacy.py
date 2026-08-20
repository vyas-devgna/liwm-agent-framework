"""The privacy gate.

Two properties must hold together: protected attributes never become durable
profile features, and ordinary technical conversation is not mangled by
over-eager pattern matching.  A gate that blocks "the user prefers Python" is
not a privacy feature, it is a bug.
"""

from __future__ import annotations

import unittest

from helpers import LiwmTestCase

from liwm.constitution import FORBIDDEN_DIMENSION_ROOTS
from liwm.privacy import (
    SensitiveAttributeRefused,
    redact,
    screen_dimension,
    screen_observation,
    screen_value,
)


class TestDimensionScreening(unittest.TestCase):
    def test_forbidden_dimension_roots_are_refused(self):
        for root in FORBIDDEN_DIMENSION_ROOTS:
            self.assertEqual(screen_dimension(root), root)
            self.assertIsNotNone(screen_dimension("profile.%s" % root))
            self.assertIsNotNone(screen_dimension("user_%s" % root))

    def test_legitimate_dimensions_pass(self):
        for dimension in (
            "interaction_profile.preferred_verbosity",
            "reasoning_profile.abstraction_comfort",
            "domain_fluency.political_science",   # a field of study, not an affiliation
            "domain_fluency.health_informatics",  # a technical domain, not a condition
            "preferences.dark_mode",
            "working_style.review_style",
        ):
            self.assertIsNone(screen_dimension(dimension), dimension)

    def test_iq_is_never_a_dimension(self):
        self.assertIsNotNone(screen_dimension("intelligence"))
        self.assertIsNotNone(screen_dimension("iq"))
        self.assertIsNotNone(screen_dimension("user.iq"))


class TestValueScreening(unittest.TestCase):
    def test_sensitive_self_descriptions_are_caught(self):
        for text in (
            "I am a Muslim and I want the UI to reflect that",
            "the user is gay",
            "I was diagnosed with ADHD last year",
            "I am a registered Republican",
            "I was arrested in 2019",
            "my IQ is 140",
        ):
            category, _ = screen_value(text)
            self.assertIsNotNone(category, text)

    def test_ordinary_technical_text_is_not_flagged(self):
        for text in (
            "I prefer Python over Go for this",
            "the user is right about the race condition here",
            "we need to fix the memory leak in the parser",
            "I am a backend engineer who likes terse code review",
            "this belief propagation code is slow",
            "the health check endpoint returns 503",
            "I am blind to why this test fails",  # figurative; see note below
            "our conservative retry policy is fine",
            "I was convicted by the argument that we should use SQLite",
        ):
            category, pattern = screen_value(text)
            self.assertIsNone(category, "false positive on %r via %r" % (text, pattern))

    def test_account_shaped_numbers_are_caught(self):
        category, _ = screen_value("card 4111 1111 1111 1111")
        self.assertEqual(category, "financial_account")

    def test_redaction_removes_the_match(self):
        redacted = redact("I am a Muslim developer")
        self.assertNotIn("Muslim", redacted)
        self.assertIn("redacted", redacted)


class TestGateIntegration(LiwmTestCase):
    def test_sensitive_dimension_raises_in_strict_mode(self):
        with self.assertRaises(SensitiveAttributeRefused):
            screen_observation(dimension="religion", value="x", strict=True)

    def test_sensitive_observation_becomes_a_redacted_refusal_event(self):
        event = self.store.events.record(
            "observation", "direct_user_message",
            observation={"dimension": "political_affiliation", "value": "libertarian",
                         "source_type": "explicit_statement", "polarity": "support",
                         "scope": "global"},
        )
        self.assertEqual(event["kind"], "refusal")
        self.assertTrue(event["quarantined"])
        self.assertEqual(event["payload"]["reason"], "privacy_gate")
        self.assertNotIn("libertarian", str(event["payload"]))

    def test_user_volunteering_sensitive_info_is_not_persisted_as_a_trait(self):
        """Even a direct, trusted statement must not create a protected-attribute
        belief. The user may say anything; LIWM simply does not build a
        personality feature out of it."""
        self.store.events.record(
            "observation", "direct_user_message",
            observation={"dimension": "creative_profile.aesthetic_direction",
                         "value": "I am a Christian and want this to feel reverent",
                         "source_type": "explicit_statement", "polarity": "support",
                         "scope": "global"},
        )
        self.store.rebuild(reason="test")
        self.assertIsNone(self.belief("creative_profile.aesthetic_direction"))
        self.assertGreater(self.store.load()["privacy"]["refusals_recorded"], 0)

    def test_refusals_are_counted_in_the_profile(self):
        for dimension in ("religion", "health", "criminal_history"):
            self.store.events.record(
                "observation", "direct_user_message",
                observation={"dimension": dimension, "value": "x",
                             "source_type": "explicit_statement", "polarity": "support",
                             "scope": "global"},
            )
        profile = self.store.rebuild(reason="test")
        self.assertGreaterEqual(profile["privacy"]["refusals_recorded"], 3)

    def test_privacy_block_is_declared_in_the_profile(self):
        profile = self.store.load()
        self.assertEqual(profile["privacy"]["telemetry"], "disabled")
        self.assertEqual(profile["privacy"]["storage"], "local_only")
        self.assertEqual(profile["privacy"]["sensitive_attribute_inference"], "refused")

    def test_export_anonymisation_strips_free_text(self):
        from liwm.cli import _anonymise

        payload = {
            "profile": {"profile_id": "usr_secret",
                        "beliefs": [{"dimension": "x", "notes": "a private note",
                                     "confidence": 0.8}]},
            "events": [{"payload": {"answer": "something the user typed"}}],
        }
        out = _anonymise(payload)
        self.assertNotEqual(out["profile"]["profile_id"], "usr_secret")
        self.assertTrue(out["profile"]["profile_id"].startswith("profile_"),
                        "identifiers become per-export pseudonyms, so two exports "
                        "of the same profile cannot be linked back together")
        self.assertNotEqual(_anonymise(payload)["profile"]["profile_id"],
                            out["profile"]["profile_id"],
                            "the pseudonym salt is per export, not global")
        self.assertNotIn("notes", out["profile"]["beliefs"][0])
        self.assertNotIn("payload", out["events"][0],
                         "event payloads are not allowlisted at all: only the "
                         "kind, provenance and observation shape are released")
        self.assertEqual(out["profile"]["beliefs"][0]["confidence"], 0.8,
                         "structure and numbers survive anonymisation")


if __name__ == "__main__":
    unittest.main()
