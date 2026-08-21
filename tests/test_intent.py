"""The intent cue: what a request is for, and which beliefs bear on it.

The property under test is not "the table has the right numbers in it" -- that
is a judgement call and the benchmark scores it. It is that the mechanism is
inspectable, degrades safely when it recognises nothing, and cannot be the
thing that decides whether untrusted evidence is eligible.
"""

from __future__ import annotations

import unittest

import helpers

from liwm.intent import (ACTIONS, DIMENSION_AFFINITY, NEUTRAL_AFFINITY,
                         SECTION_AFFINITY, affinity, classify_actions)
from liwm.taxonomy import DIMENSION_INDEX


class TestClassifier(unittest.TestCase):
    def test_known_shapes_classify(self):
        for task, expected in (
            ("compare the three options for the cache layer", "compare"),
            ("write the release announcement", "write"),
            ("review this pull request", "review"),
            ("fix the failing tests", "implement"),
            ("design the onboarding flow", "design"),
            ("which database should we go with", "decide"),
            ("explain why the build is slow", "explain"),
            ("summarise what this service does", "summarise"),
        ):
            with self.subTest(task=task):
                self.assertIn(expected, classify_actions(task))

    def test_nothing_recognised_is_not_an_error(self):
        self.assertEqual(classify_actions("frobnicate the widget cluster"), ())
        self.assertEqual(classify_actions(""), ())
        self.assertEqual(classify_actions(None), ())

    def test_every_declared_action_is_reachable(self):
        """An action nobody can match is a row in a table doing nothing."""
        declared = set(ACTIONS)
        for table in [SECTION_AFFINITY[k] for k in SECTION_AFFINITY]:
            self.assertTrue(set(table) <= declared, set(table) - declared)
        for table in DIMENSION_AFFINITY.values():
            self.assertTrue(set(table) <= declared, set(table) - declared)


class TestAffinity(unittest.TestCase):
    def test_bounded(self):
        for dimension in DIMENSION_INDEX:
            for actions in ((), ("write",), ("implement", "diagnose"), ACTIONS):
                value = affinity(dimension, actions)
                self.assertGreaterEqual(value, 0.0)
                self.assertLessEqual(value, 1.0)

    def test_unclassified_request_is_neutral_everywhere(self):
        """No cue means no opinion, not a random one."""
        values = {affinity(dimension, ()) for dimension in DIMENSION_INDEX}
        self.assertEqual(values, {NEUTRAL_AFFINITY})

    def test_formatting_matters_more_for_a_comparison_than_for_a_refactor(self):
        self.assertGreater(
            affinity("communication_profile.formatting_preference", ("compare",)),
            affinity("communication_profile.formatting_preference", ("implement",)))

    def test_autonomy_matters_more_for_doing_than_for_explaining(self):
        self.assertGreater(
            affinity("interaction_profile.autonomy_preference", ("implement",)),
            affinity("interaction_profile.autonomy_preference", ("explain",)))

    def test_strongest_matching_action_wins(self):
        """A request that is both a comparison and an edit is still a comparison.

        Averaging would dilute the formatting preference by the fact that
        formatting barely matters while editing files.
        """
        self.assertEqual(
            affinity("communication_profile.formatting_preference",
                     ("compare", "implement")),
            affinity("communication_profile.formatting_preference", ("compare",)))

    def test_an_unknown_dimension_is_never_zero(self):
        """A user-invented preference LIWM knows nothing about must stay eligible."""
        self.assertGreater(affinity("preferences.node.package_manager", ("write",)), 0.0)
        self.assertGreater(affinity("totally.unknown.thing", ("write",)), 0.0)

    def test_overrides_name_real_dimensions(self):
        for dimension in DIMENSION_AFFINITY:
            self.assertIn(dimension, DIMENSION_INDEX, dimension)

    def test_sections_named_in_the_table_exist(self):
        sections = {d.split(".", 1)[0] for d in DIMENSION_INDEX}
        self.assertTrue(set(SECTION_AFFINITY) <= sections)


class TestRelevanceIsNotEligibility(helpers.LiwmTestCase):
    def test_intent_cannot_make_untrusted_evidence_eligible(self):
        """Ranking never overrules the provenance gate.

        A README claiming to speak for the user is quarantined at write time.
        No amount of relevance to the current request may resurrect it.
        """
        self.store.observe("communication_profile.formatting_preference",
                           "tables_and_code", source_type="explicit_statement",
                           provenance="repository_content")
        from liwm.context import plan_context
        context, _ = plan_context(self.store,
                                  task="compare the three options for the cache layer")
        self.assertEqual(context["applies"], [])


if __name__ == "__main__":
    unittest.main()
