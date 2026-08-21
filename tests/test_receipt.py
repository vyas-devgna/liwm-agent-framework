"""The ContextReceipt: every injected token accounted for, and nothing else.

A receipt exists so that "LIWM only sends what the turn needs" is a checkable
statement rather than a slogan.  Two properties carry that weight: the receipt
must account for what was actually sent, and it must never itself become part
of what is sent.
"""

from __future__ import annotations

import json
import unittest

from helpers import LiwmTestCase

from liwm.capsule import render_capsule
from liwm.context import plan_context


class TestReceipt(LiwmTestCase):
    def _plan(self, **kwargs):
        return plan_context(self.store, **kwargs)

    def test_receipt_is_not_part_of_the_context(self):
        """An audit record that inflates what it audits is worse than none."""
        self.observe("interaction_profile.preferred_verbosity", "terse")
        context, receipt = self._plan(task="draft the notes")
        body = json.dumps(context)
        self.assertNotIn("receipt", body)
        self.assertNotIn("rejected", body)
        self.assertNotIn("candidates", body)

    def test_costs_match_the_rendered_payloads(self):
        self.observe("interaction_profile.preferred_verbosity", "terse")
        context, receipt = self._plan(task="draft the notes")
        self.assertEqual(
            receipt["cost"]["json_projection_bytes"],
            len(json.dumps(context, indent=2, ensure_ascii=False).encode("utf-8")))
        self.assertEqual(receipt["cost"]["capsule_bytes"],
                         len(render_capsule(context).encode("utf-8")))

    def test_costs_are_alternatives_never_a_sum(self):
        """A turn sends one wire format; adding them would invent a cost."""
        _, receipt = self._plan(task="draft the notes")
        self.assertNotIn("total_tokens", receipt["cost"])
        self.assertIn("method", receipt["cost"])

    def test_estimated_costs_carry_their_error_bounds(self):
        _, receipt = self._plan(task="draft the notes")
        if receipt["cost"]["method"] == "estimated":
            self.assertIn("error_bounds", receipt["cost"])

    def test_selection_and_rejection_are_both_recorded(self):
        for index in range(20):
            self.observe("preferences.tool_%d" % index, "choice_%d" % index,
                         source_type="repeated_behavioral")
        context, receipt = self._plan(task="draft the notes")
        self.assertEqual(receipt["candidates"]["selected"], len(context["applies"]))
        self.assertGreater(receipt["candidates"]["stored_beliefs"],
                           receipt["candidates"]["selected"])
        self.assertTrue(receipt["rejected"])
        self.assertTrue(all(row.get("reason") for row in receipt["rejected"]))

    def test_out_of_scope_beliefs_are_rejected_with_that_reason(self):
        self.observe("interaction_profile.preferred_verbosity", "verbose",
                     scope="project", scope_key="other-project", project_id="other-project")
        _, receipt = self._plan(task="draft the notes", project_id="acme")
        reasons = {row["reason"] for row in receipt["rejected"]}
        self.assertIn("other_project", reasons)

    def test_gate_decision_is_always_on_the_receipt(self):
        _, receipt = self._plan(task="what is 17% of 340")
        self.assertEqual(receipt["outcome"], "zero_memory")
        self.assertFalse(receipt["gate"]["needs_memory"])
        self.assertTrue(receipt["gate"]["self_contained_signals"])

    def test_gate_can_be_turned_off(self):
        self.observe("interaction_profile.preferred_verbosity", "terse")
        context, receipt = self._plan(task="what is 17% of 340", gate="off")
        self.assertEqual(receipt["outcome"], "assembled")
        self.assertTrue(receipt["gate"]["overridden"])
        self.assertTrue(context["applies"])

    def test_gate_rejects_an_unknown_setting_rather_than_guessing(self):
        with self.assertRaises(ValueError):
            self._plan(task="anything", gate="maybe")

    def test_a_gated_turn_costs_far_less_than_an_open_one(self):
        for index in range(12):
            self.observe("preferences.tool_%d" % index, "choice_%d" % index,
                         source_type="repeated_behavioral")
        _, gated = self._plan(task="what is 17% of 340")
        _, open_turn = self._plan(task="what is 17% of 340", gate="off")
        self.assertLess(gated["cost"]["capsule_tokens"] * 5,
                        open_turn["cost"]["capsule_tokens"])

    def test_withheld_paths_say_why(self):
        from liwm.config import ConfigStore
        config = ConfigStore(self.home)
        data = config.load()
        data["enabled"] = False
        config.save(data)
        _, receipt = self._plan(task="draft the notes")
        self.assertEqual(receipt["outcome"], "withheld")
        self.assertEqual(receipt["outcome_reason"], "disabled")


if __name__ == "__main__":
    unittest.main()
