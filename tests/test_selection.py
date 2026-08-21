"""Belief selection: what fills the last slots, and what should not.

The failure this prevents is subtle and expensive.  With forty beliefs the
ranker cannot tell apart, a fixed top-k fills its remaining slots from that
block and presents an arbitrary sample to the model as though it were the
relevant one.  It costs the same tokens as a real selection and carries less
information than saying nothing.
"""

from __future__ import annotations

import unittest

from helpers import LiwmTestCase

from liwm.capsule import render_capsule
from liwm.context import plan_context, score_beliefs, select_beliefs


def _scored(*scores):
    return [({"id": "b%d" % index, "dimension": "d%d" % index}, score)
            for index, score in enumerate(scores)]


class TestSelectBeliefs(unittest.TestCase):
    def test_everything_is_kept_when_nothing_is_excluded(self):
        scored = _scored(0.5, 0.5, 0.5)
        kept, dropped = select_beliefs(scored, 10)
        self.assertEqual(len(kept), 3)
        self.assertEqual(dropped, 0)

    def test_a_clear_ranking_fills_every_slot(self):
        scored = _scored(0.9, 0.8, 0.7, 0.6, 0.5)
        kept, dropped = select_beliefs(scored, 3)
        self.assertEqual(len(kept), 3)
        self.assertEqual(dropped, 0)

    def test_a_tie_straddling_the_cut_is_dropped_whole(self):
        scored = _scored(0.9, 0.5, 0.5, 0.5, 0.5)
        kept, dropped = select_beliefs(scored, 3)
        self.assertEqual([b["id"] for b in kept], ["b0"])
        self.assertEqual(dropped, 2)

    def test_beliefs_above_the_tie_survive_it(self):
        scored = _scored(0.9, 0.8, 0.4, 0.4, 0.4)
        kept, _ = select_beliefs(scored, 3)
        self.assertEqual([b["id"] for b in kept], ["b0", "b1"])

    def test_a_uniform_field_selects_nothing(self):
        """Ten identical beliefs are not a top three; sampling is not selection."""
        kept, dropped = select_beliefs(_scored(*([0.5] * 10)), 3)
        self.assertEqual(kept, [])
        self.assertEqual(dropped, 3)


class TestAgainstNoise(LiwmTestCase):
    def _noise(self, count=40, confidence_source="repeated_behavioral"):
        for index in range(count):
            self.observe("preferences.legacy_%d" % index, "value_%d" % index,
                         source_type=confidence_source)

    def test_noise_does_not_crowd_the_capsule(self):
        self.observe("interaction_profile.preferred_verbosity", "terse")
        self._noise()
        context, receipt = plan_context(self.store, task="draft the release notes")
        self.assertLess(len(context["applies"]), 6)
        self.assertGreater(receipt["candidates"]["dropped_as_indistinguishable"], 0)
        self.assertIn("terse", render_capsule(context))

    def test_the_omission_is_stated_not_silent(self):
        self.observe("interaction_profile.preferred_verbosity", "terse")
        self._noise()
        context, _ = plan_context(self.store, task="draft the release notes")
        self.assertGreater(context["beliefs_withheld"], 0)
        self.assertIn("not shown", render_capsule(context))

    def test_a_withheld_belief_can_be_asked_for(self):
        self.observe("interaction_profile.preferred_verbosity", "terse")
        self._noise()
        context, receipt = plan_context(self.store, task="draft the release notes",
                                        include=["preferences.legacy_7"])
        self.assertIn("value_7", render_capsule(context))
        self.assertEqual(receipt["expanded"]["requested"], ["preferences.legacy_7"])

    def test_asking_for_everything_returns_everything(self):
        self.observe("interaction_profile.preferred_verbosity", "terse")
        self._noise(count=12)
        context, _ = plan_context(self.store, task="draft the release notes",
                                  max_beliefs=10 ** 6, gate="off")
        self.assertGreaterEqual(len(context["applies"]), 13)
        self.assertEqual(context["beliefs_withheld"], 0)


class TestScoreBeliefs(unittest.TestCase):
    def test_scores_come_back_with_the_ordering_they_produced(self):
        beliefs = [
            {"id": "a", "dimension": "interaction_profile.preferred_verbosity",
             "value": "terse", "confidence": 0.9, "scope": "global"},
            {"id": "b", "dimension": "interaction_profile.pace",
             "value": "fast", "confidence": 0.4, "scope": "global"},
        ]
        scored = score_beliefs(beliefs)
        self.assertEqual([b["id"] for b, _ in scored], ["a", "b"])
        self.assertGreater(scored[0][1], scored[1][1])


if __name__ == "__main__":
    unittest.main()
