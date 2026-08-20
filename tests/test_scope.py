"""Scope isolation: the firewall between a project and a person.

The canonical failure this prevents: "this banking app must be extremely
conservative" silently becoming "this person is conservative", and then
suppressing adventurous suggestions on their art project six weeks later.
"""

from __future__ import annotations

import unittest

from helpers import LiwmTestCase, days_ago

from liwm.scope import DEFAULT_POLICY, evaluate_promotions, resolve_for_context


class TestScopeIsolation(LiwmTestCase):
    def test_project_requirement_does_not_become_a_global_trait(self):
        for _ in range(5):
            self.observe("reasoning_profile.risk_tolerance_in_projects", "conservative",
                         scope="project", scope_key="banking-app",
                         project_id="banking-app", domain="software")
        self.assertGreater(
            self.confidence("reasoning_profile.risk_tolerance_in_projects",
                            "conservative", scope="project"), 0.9)
        self.assertIsNone(
            self.belief("reasoning_profile.risk_tolerance_in_projects", scope="global"),
            "five observations in ONE project must not create a global trait",
        )

    def test_other_projects_are_unaffected_by_a_project_belief(self):
        for _ in range(5):
            self.observe("reasoning_profile.risk_tolerance_in_projects", "conservative",
                         scope="project", scope_key="banking-app",
                         project_id="banking-app", domain="software")
        profile = self.store.load()
        art = resolve_for_context(profile["beliefs"], domain="visual_design",
                                  project_id="art-thing")
        self.assertNotIn("reasoning_profile.risk_tolerance_in_projects", art)

    def test_domain_promotion_requires_multiple_distinct_projects(self):
        beliefs = [
            {"id": "blf_a", "scope": "project", "scope_key": "proj-one", "domain": "software",
             "dimension": "creative_profile.simplicity_vs_richness", "value": "minimal",
             "confidence": 0.9, "status": "active", "session_ids": ["s1"],
             "first_seen": days_ago(30), "last_seen": days_ago(1)},
        ]
        self.assertEqual(evaluate_promotions(beliefs), [],
                         "one project is never enough for a domain claim")

        beliefs.append(
            {"id": "blf_b", "scope": "project", "scope_key": "proj-two", "domain": "software",
             "dimension": "creative_profile.simplicity_vs_richness", "value": "minimal",
             "confidence": 0.9, "status": "active", "session_ids": ["s2"],
             "first_seen": days_ago(20), "last_seen": days_ago(2)}
        )
        proposals = evaluate_promotions(beliefs)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["target_scope"], "domain")
        self.assertLess(proposals[0]["confidence"], 0.9,
                        "promotion must be confidence-discounted")

    def test_global_promotion_requires_multiple_distinct_domains(self):
        beliefs = [
            {"id": "blf_a", "scope": "domain", "scope_key": "software", "domain": "software",
             "dimension": "interaction_profile.preferred_verbosity", "value": "terse",
             "confidence": 0.8, "status": "active", "session_ids": ["s1", "s2"],
             "first_seen": days_ago(40), "last_seen": days_ago(1)},
        ]
        self.assertEqual(
            [p for p in evaluate_promotions(beliefs) if p["target_scope"] == "global"], [],
            "one domain is never enough for a global claim",
        )

        beliefs.append(
            {"id": "blf_b", "scope": "domain", "scope_key": "writing", "domain": "writing",
             "dimension": "interaction_profile.preferred_verbosity", "value": "terse",
             "confidence": 0.8, "status": "active", "session_ids": ["s3"],
             "first_seen": days_ago(35), "last_seen": days_ago(3)}
        )
        proposals = [p for p in evaluate_promotions(beliefs) if p["target_scope"] == "global"]
        self.assertEqual(len(proposals), 1)
        self.assertAlmostEqual(proposals[0]["confidence"],
                               round(0.8 * DEFAULT_POLICY.global_discount, 4), places=3)

    def test_promotion_is_blocked_by_a_conflicting_belief(self):
        beliefs = [
            {"id": "blf_a", "scope": "project", "scope_key": "p1", "domain": "software",
             "dimension": "creative_profile.novelty_seeking", "value": "novel",
             "confidence": 0.9, "status": "active", "session_ids": ["s1"],
             "first_seen": days_ago(30), "last_seen": days_ago(1)},
            {"id": "blf_b", "scope": "project", "scope_key": "p2", "domain": "software",
             "dimension": "creative_profile.novelty_seeking", "value": "novel",
             "confidence": 0.9, "status": "active", "session_ids": ["s2"],
             "first_seen": days_ago(25), "last_seen": days_ago(2)},
            {"id": "blf_c", "scope": "domain", "scope_key": "software", "domain": "software",
             "dimension": "creative_profile.novelty_seeking", "value": "familiar",
             "confidence": 0.7, "status": "active", "session_ids": ["s3"],
             "first_seen": days_ago(10), "last_seen": days_ago(1)},
        ]
        self.assertEqual([p for p in evaluate_promotions(beliefs)
                          if p["target_scope"] == "domain"], [])

    def test_narrower_scope_wins_for_its_own_context(self):
        self.observe("creative_profile.novelty_seeking", "novel")
        self.observe("creative_profile.novelty_seeking", "familiar",
                     scope="project", scope_key="banking-app", project_id="banking-app")
        profile = self.store.load()

        in_project = resolve_for_context(profile["beliefs"], project_id="banking-app")
        self.assertEqual(in_project["creative_profile.novelty_seeking"]["value"], "familiar")

        elsewhere = resolve_for_context(profile["beliefs"], project_id="other")
        self.assertEqual(elsewhere["creative_profile.novelty_seeking"]["value"], "novel")

    def test_cross_scope_tension_is_reported_not_resolved(self):
        self.observe("creative_profile.novelty_seeking", "novel")
        self.observe("creative_profile.novelty_seeking", "familiar",
                     scope="project", scope_key="banking-app", project_id="banking-app")
        profile = self.store.load()
        conflict = next(c for c in profile["contradictions"]
                        if c["dimension"] == "creative_profile.novelty_seeking")
        self.assertEqual(conflict["type"], "cross_scope_tension")
        self.assertTrue(conflict["resolvable_by_scope"])

    def test_session_scope_never_becomes_durable(self):
        self.observe("interaction_profile.pace", "fast", scope="session",
                     session_id="s1")
        self.assertIsNone(self.belief("interaction_profile.pace"))

    def test_cross_domain_transfer_is_a_hypothesis_not_a_belief(self):
        from liwm.scope import cross_domain_hypotheses

        beliefs = [
            {"id": "blf_a", "scope": "domain", "scope_key": "visual_design",
             "domain": "visual_design", "dimension": "creative_profile.simplicity_vs_richness",
             "value": "minimal", "confidence": 0.85, "status": "active",
             "session_ids": ["s1"], "first_seen": days_ago(30), "last_seen": days_ago(1)},
        ]
        hypotheses = cross_domain_hypotheses(beliefs, {"visual_design", "writing"})
        self.assertEqual(len(hypotheses), 1)
        h = hypotheses[0]
        self.assertEqual(h["status"], "hypothesis")
        self.assertEqual(h["target_domain"], "writing")
        self.assertLessEqual(h["confidence"], DEFAULT_POLICY.cross_domain_max_confidence)
        self.assertIn("independent observation", h["requires"])

    def test_feedback_defaults_to_project_scope(self):
        from liwm.feedback import interpret

        parsed = interpret("too_complex", channel="explicit", project_id="banking-app")
        scopes = {o["scope"] for o in parsed["observations"]
                  if o["dimension"] == "creative_profile.simplicity_vs_richness"}
        self.assertEqual(scopes, {"project"})

    def test_interaction_meta_feedback_requires_explicit_global_intent(self):
        from liwm.feedback import interpret

        parsed = interpret("too_many_questions", channel="explicit", project_id="banking-app")
        for obs in parsed["observations"]:
            self.assertEqual(obs["scope"], "project")
        global_parsed = interpret(
            "too_many_questions", channel="explicit", project_id="banking-app",
            global_intent=True,
        )
        self.assertTrue(all(obs["scope"] == "global"
                            for obs in global_parsed["observations"]))


if __name__ == "__main__":
    unittest.main()
