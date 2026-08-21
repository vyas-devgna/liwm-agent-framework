"""The context capsule: cheaper than the JSON projection, and no less faithful.

Compression is only worth having if nothing an agent could act on is lost.
These tests hold both ends of that: the capsule is measurably smaller, and
every field that could change what the agent produces survives the rendering.
"""

from __future__ import annotations

import collections
import json
import unittest

from helpers import LiwmTestCase

from liwm.budget import estimate_tokens
from liwm.capsule import PRECEDENCE_LINE, render_capsule
from liwm.context import plan_context
from liwm.taxonomy import DIMENSION_INDEX


class TestShorteningIsSafe(unittest.TestCase):
    def test_closed_taxonomy_leaf_names_do_not_collide(self):
        """The capsule drops section prefixes on the strength of this.

        If a future dimension makes two leaves collide, two different beliefs
        would render as the same line and the capsule would start lying.  It
        should fail here instead.
        """
        leaves = collections.Counter(k.rsplit(".", 1)[-1] for k in DIMENSION_INDEX)
        self.assertEqual([name for name, n in leaves.items() if n > 1], [])

    def test_open_namespace_dimensions_are_not_shortened(self):
        """``preferences.x`` and ``anti_preferences.x`` mean opposite things."""
        context = {
            "profile_revision": 1, "profile_maturity": 0.5,
            "mode": {"effective": "low", "question_budget": 1},
            "applies": [
                {"dimension": "preferences.editor", "value": "vim",
                 "confidence": 0.9, "scope": "global"},
                {"dimension": "anti_preferences.editor", "value": "vim",
                 "confidence": 0.4, "scope": "global"},
            ],
        }
        text = render_capsule(context)
        self.assertIn("preferences.editor = vim", text)
        self.assertIn("anti_preferences.editor = vim", text)


class TestFidelity(LiwmTestCase):
    def _context(self, **kwargs):
        return plan_context(self.store, **kwargs)[0]

    def test_every_applicable_belief_appears(self):
        for dimension, value in (("interaction_profile.preferred_verbosity", "terse"),
                                 ("working_style.iteration_style", "small increments"),
                                 ("decision_style.speed", "fast")):
            self.observe(dimension, value)
        context = self._context(task="write the release notes")
        text = render_capsule(context)
        self.assertTrue(context["applies"])
        for item in context["applies"]:
            self.assertIn(str(item["value"]), text)

    def test_precedence_line_is_always_present(self):
        self.observe("interaction_profile.preferred_verbosity", "terse")
        text = render_capsule(self._context(task="draft something"))
        self.assertIn(PRECEDENCE_LINE, text)

    def test_non_global_scope_is_shown(self):
        self.observe("interaction_profile.preferred_verbosity", "verbose",
                     scope="project", scope_key="acme", project_id="acme")
        text = render_capsule(self._context(task="draft something", project_id="acme"))
        self.assertIn("@project:acme", text)

    def test_global_scope_is_left_implicit(self):
        self.observe("interaction_profile.preferred_verbosity", "terse")
        text = render_capsule(self._context(task="draft something"))
        self.assertNotIn("@global", text)

    def test_capsule_is_cheaper_than_the_json_projection(self):
        for index in range(12):
            self.observe("preferences.tool_%d" % index, "choice_%d" % index,
                         source_type="repeated_behavioral")
        context = self._context(task="write the release notes")
        json_tokens = estimate_tokens(json.dumps(context, indent=2, ensure_ascii=False))
        capsule_tokens = estimate_tokens(render_capsule(context))
        self.assertLess(capsule_tokens * 3, json_tokens,
                        "capsule %d vs json %d" % (capsule_tokens, json_tokens))

    def test_gated_turn_renders_as_one_line(self):
        self.observe("interaction_profile.preferred_verbosity", "terse")
        text = render_capsule(self._context(task="what is 17% of 340"))
        self.assertEqual(len(text.splitlines()), 1)
        self.assertNotIn("terse", text)

    def test_disabled_learning_is_stated(self):
        context = self._context(task="draft something")
        context["learning_enabled"] = False
        self.assertIn("learning: disabled", render_capsule(context))


class TestDegradedPaths(unittest.TestCase):
    def test_integrity_failure_exposes_nothing(self):
        text = render_capsule({"integrity_degraded": True, "applies": [],
                               "mode": {"effective": "off"}})
        self.assertIn("integrity", text)
        self.assertIn("liwm verify", text)

    def test_off_mode_exposes_nothing(self):
        text = render_capsule({"mode": {"effective": "off", "rationale": "disabled"},
                               "applies": [{"dimension": "x", "value": "secret",
                                            "confidence": 1.0, "scope": "global"}]})
        self.assertNotIn("secret", text)


if __name__ == "__main__":
    unittest.main()
