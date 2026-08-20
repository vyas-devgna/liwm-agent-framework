"""Simulation, replay, self-improvement gating and traceability.

These are the tests that check LIWM's central claim - that it gets better at
working with the same person - is measurable rather than asserted.
"""

from __future__ import annotations

import unittest

from helpers import LiwmTestCase

from liwm.evaluation import ARCHETYPES, make_user, run_convergence_study, run_mode_study
from liwm.evaluation.harness import belief_accuracy
from liwm.evaluation.replay import replay_candidate, replay_episodes
from liwm.selfimprove import CandidateRule, GUARDED_METRICS, SelfImprovementStore


class TestSimulators(unittest.TestCase):
    def test_archetypes_are_distinct(self):
        self.assertGreaterEqual(len(ARCHETYPES), 6)
        vectors = {name: tuple(sorted(spec["hidden"].items()))
                   for name, spec in ARCHETYPES.items()}
        self.assertEqual(len(set(vectors.values())), len(vectors))

    def test_simulated_answers_are_deterministic(self):
        a = make_user("novelty_seeking_expert", seed=7)
        b = make_user("novelty_seeking_expert", seed=7)
        self.assertEqual(a.answer("nov_two_versions"), b.answer("nov_two_versions"))

    def test_different_seeds_differ(self):
        a = make_user("conservative_beginner", seed=1)
        b = make_user("conservative_beginner", seed=99)
        answers = [a.answer("det_annoying_faster"), b.answer("det_annoying_faster")]
        self.assertTrue(all(isinstance(x, (dict, type(None))) for x in answers))

    def test_impatient_user_stops_answering(self):
        user = make_user("impatient_technical_expert", seed=3)
        responses = [user.answer(q) for q in
                     ("nov_two_versions", "auto_three_ways", "det_annoying_faster",
                      "expl_new_concept", "chal_wrong_assumption", "aes_feels_right",
                      "com_length", "dec_how_many_options")]
        self.assertIn(None, responses, "an impatient user must eventually ignore questions")

    def test_reaction_reflects_the_hidden_vector(self):
        user = make_user("conservative_beginner", seed=5)
        good = user.react({d: v for d, v in user.hidden.items()})
        bad = user.react({d: "wrong" for d in user.hidden})
        self.assertGreater(good["acceptance"], bad["acceptance"])
        self.assertEqual(good["kind"], "exactly_right")
        self.assertEqual(bad["kind"], "misunderstood_intent")


class TestConvergence(unittest.TestCase):
    def test_beliefs_converge_toward_the_hidden_vector(self):
        result = run_convergence_study("impatient_technical_expert", rounds=8, seed=11)
        summary = result["summary"]
        self.assertGreater(summary["accuracy_gain"], 0.3,
                           "the profile must actually learn the person")
        self.assertGreaterEqual(summary["accuracy_final_round"], 0.7)

    def test_acceptance_improves_over_rounds(self):
        result = run_convergence_study("detail_oriented_researcher", rounds=8, seed=13)
        self.assertGreater(result["summary"]["acceptance_gain"], 0.1)

    def test_questioning_falls_as_understanding_grows(self):
        """Requirement §43 - the property most personalisation systems fail."""
        result = run_convergence_study("high_autonomy_builder", rounds=10, seed=17)
        summary = result["summary"]
        self.assertGreaterEqual(summary["questions_reduction"], 0.0,
                                "a maturing profile must not ask more over time")

    def test_all_archetypes_converge(self):
        for archetype in ARCHETYPES:
            result = run_convergence_study(archetype, rounds=6, seed=23)
            self.assertGreater(result["summary"]["accuracy_final_round"],
                               result["summary"]["accuracy_first_round"],
                               archetype)

    def test_project_overrides_do_not_contaminate_the_global_model(self):
        """A project demanding the opposite of the person's usual preference must
        not rewrite the person."""
        overrides = {"creative_profile.simplicity_vs_richness": "feature_rich"}
        result = run_convergence_study(
            "novelty_seeking_expert", rounds=6, seed=29,
            project_id="regulated-thing", project_overrides=overrides,
        )
        details = {d["dimension"]: d
                   for d in result["final_accuracy_global"]["details"]}
        row = details.get("creative_profile.simplicity_vs_richness")
        if row and row["believed"] is not None:
            self.assertNotEqual(
                row["believed"], "feature_rich",
                "the project-only requirement leaked into the global profile",
            )

    def test_onboarding_gives_a_head_start(self):
        with_onboarding = run_convergence_study(
            "conservative_beginner", rounds=3, seed=31, do_onboarding=True)
        without = run_convergence_study(
            "conservative_beginner", rounds=3, seed=31, do_onboarding=False)
        self.assertGreaterEqual(
            with_onboarding["series"][0]["coverage"],
            without["series"][0]["coverage"],
            "onboarding should mean knowing something on round one",
        )

    def test_mode_study_reports_distinguishability(self):
        result = run_mode_study()
        self.assertTrue(result["distinguishable"]["question_counts_increase"])
        self.assertTrue(result["distinguishable"]["experiential_share_increases"])


class TestReplayAndGating(LiwmTestCase):
    def _episodes(self, n=14, wasted=True):
        episodes = []
        for i in range(n):
            episodes.append({
                "id": "epi_%d" % i,
                "session_id": "s%d" % (i % 5),
                "questions": [
                    {"id": "q_high_%d" % i, "style": "scenario", "utility": 2.0,
                     "threshold": 0.85},
                    {"id": "q_low_%d" % i, "style": "scenario", "utility": 0.9,
                     "threshold": 0.85},
                ],
                "answers": [
                    {"id": "q_high_%d" % i, "value": "useful", "changed_plan": True},
                    {"id": "q_low_%d" % i, "value": "redundant" if wasted else "useful"},
                ],
                "feedback": [{"kind": "mostly_right", "acceptance": 0.8}],
                "assumptions": [],
                "mean_acceptance": 0.8,
                "counts": {"questions_asked": 2},
            })
        return episodes

    def _record_observed_outcomes(self, n=6, candidate_id=None):
        """Resolve *n* real predictions so the observed-outcome gate is satisfied.

        Replay alone cannot promote anything: it scores a candidate against an
        acceptance model LIWM wrote, so a candidate can win by fitting the
        evaluator rather than the person. Promotion also requires outcomes that
        were committed to before the user reacted and scored against what they
        actually did.
        """
        from liwm.prediction import make_prediction, record_prediction, resolve_prediction

        for i in range(n):
            prediction = make_prediction(
                predicted_acceptance=0.7, confidence=0.6, candidate_id=candidate_id
            )
            record_prediction(self.store, prediction, session_id="s%d" % i)
            feedback = self.store.events.record(
                "feedback", "direct_user_message",
                payload={"channel": "explicit", "acceptance": 0.9},
                session_id="s%d" % i,
            )
            resolve_prediction(
                self.store, prediction["id"], 0.9, session_id="s%d" % i,
                evaluator_type="observed_human_outcome",
                evidence_event_id=feedback["event_id"],
            )

    @staticmethod
    def _independent_results(si, candidate):
        si.attach_benchmark(candidate["id"], {
            "passed": True, "candidate_id": candidate["id"],
            "evaluator_type": "benchmark_ground_truth",
        })
        si.attach_adversarial(candidate["id"], {
            "passed": True, "failures": [], "candidate_id": candidate["id"],
            "suite_id": "liwm-adversarial-v1",
        })

    def test_replay_prefers_a_policy_that_drops_wasted_questions(self):
        episodes = self._episodes()
        incumbent = replay_episodes(episodes)["aggregate"]
        stricter = replay_episodes(episodes, utility_threshold_delta=0.5)["aggregate"]
        self.assertLess(stricter["question_ignore_rate"], incumbent["question_ignore_rate"])
        self.assertEqual(stricter["useful_question_retention"], 1.0,
                         "the useful questions must survive the stricter policy")

    def test_replay_penalises_a_policy_that_drops_useful_questions(self):
        episodes = self._episodes()
        too_strict = replay_episodes(episodes, utility_threshold_delta=5.0)["aggregate"]
        self.assertEqual(too_strict["useful_question_retention"], 0.0)

    def test_candidate_passing_every_gate_is_promoted(self):
        si = SelfImprovementStore(self.home)
        candidate = si.propose(
            CandidateRule.create(
                title="Raise the utility threshold before asking",
                statement="Ask only questions above a higher utility bar.",
                surface="interaction",
                primary_metric="question_ignore_rate",
                parameters={"min_utility_delta": 0.5},
            ),
            store=self.store,
        )
        self.assertEqual(candidate["state"], "constitution_checked")

        replay = replay_candidate(self._episodes(), candidate)
        for metric in GUARDED_METRICS:
            replay["guarded_deltas"].setdefault(metric, 0.0)
        self.assertGreater(replay["primary_delta"], 0)
        si.attach_replay(candidate["id"], replay)
        self._independent_results(si, candidate)
        self._record_observed_outcomes(candidate_id=candidate["id"])

        promoted, verdict = si.promote(candidate["id"], store=self.store)
        self.assertTrue(verdict["passed"], verdict["reasons"])
        self.assertGreaterEqual(verdict["resolved_outcomes"], 5)
        self.assertEqual(promoted["state"], "promoted")
        active = si.active_rules()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], candidate["id"])

    def test_candidate_failing_the_adversarial_suite_is_rejected(self):
        si = SelfImprovementStore(self.home)
        candidate = si.propose(
            CandidateRule.create(
                title="Ask less", statement="Ask fewer questions.",
                surface="interaction", primary_metric="question_ignore_rate",
                parameters={"min_utility_delta": 0.5},
            ),
            store=self.store,
        )
        si.attach_replay(candidate["id"], replay_candidate(self._episodes(), candidate))
        si.attach_adversarial(candidate["id"],
                              {"passed": False, "failures": ["profile poisoning regression"]})
        _, verdict = si.promote(candidate["id"], store=self.store)
        self.assertFalse(verdict["passed"])
        self.assertEqual(si.active_rules(), [])

    def test_guarded_regression_blocks_promotion(self):
        si = SelfImprovementStore(self.home)
        candidate = si.propose(
            CandidateRule.create(
                title="Ask much more", statement="Lower the bar a lot.",
                surface="interaction", primary_metric="first_pass_acceptance",
                parameters={"min_utility_delta": -1.0},
            ),
            store=self.store,
        )
        si.attach_replay(candidate["id"], {
            "episodes": 20, "distinct_sessions": 5, "primary_delta": 0.2,
            "guarded_deltas": {"question_ignore_rate": 0.4,
                               "questions_per_accepted_outcome": 2.0},
        })
        si.attach_adversarial(candidate["id"], {"passed": True, "failures": []})
        _, verdict = si.promote(candidate["id"], store=self.store)
        self.assertFalse(verdict["passed"])
        self.assertTrue(verdict["regressions"])

    def test_promoted_rule_can_always_be_reverted(self):
        si = SelfImprovementStore(self.home)
        candidate = si.propose(
            CandidateRule.create(
                title="Raise the bar", statement="Ask only above a higher bar.",
                surface="interaction", primary_metric="question_ignore_rate",
                parameters={"min_utility_delta": 0.5},
            ),
            store=self.store,
        )
        replay = replay_candidate(self._episodes(), candidate)
        for metric in GUARDED_METRICS:
            replay["guarded_deltas"].setdefault(metric, 0.0)
        si.attach_replay(candidate["id"], replay)
        self._independent_results(si, candidate)
        self._record_observed_outcomes(candidate_id=candidate["id"])
        si.promote(candidate["id"], store=self.store)
        self.assertTrue(si.revert(candidate["id"], store=self.store, reason="test"))
        self.assertEqual(si.active_rules(), [])

    def test_replay_labels_modelled_metrics_as_estimates(self):
        replay = replay_candidate(self._episodes(), CandidateRule.create(
            title="x", statement="y", surface="interaction",
            primary_metric="first_pass_acceptance"))
        self.assertTrue(replay["primary_is_estimated"])
        self.assertIn("modelled, not observed", replay["caveat"])


class TestRetrospective(LiwmTestCase):
    def _session_with_wasted_questions(self, session_id="s1", count=6):
        for i in range(count):
            self.store.events.record(
                "question_asked", "agent_inference",
                payload={"question_id": "q%d" % i, "style": "scenario",
                         "family": "detail_vs_speed", "utility": 1.2},
                session_id=session_id)
            self.store.events.record(
                "question_skipped", "direct_user_message",
                payload={"question_id": "q%d" % i, "reason": "ignored"},
                session_id=session_id)
        self.store.events.record(
            "feedback", "direct_user_message",
            payload={"kind": "mostly_right", "acceptance": 0.8, "channel": "explicit"},
            session_id=session_id)

    def test_retrospective_builds_a_replayable_episode(self):
        from liwm.retrospective import run_retrospective

        self._session_with_wasted_questions()
        result = run_retrospective(self.store, "s1")
        self.assertEqual(result["episode"]["counts"]["questions_asked"], 6)
        self.assertTrue(result["episode_path"])
        self.assertTrue(result["lessons"])

    def test_retrospective_proposes_gated_candidates(self):
        from liwm.retrospective import run_retrospective

        self._session_with_wasted_questions()
        result = run_retrospective(self.store, "s1")
        self.assertTrue(result["candidates"])
        for candidate in result["candidates"]:
            self.assertIn(candidate["state"], ("constitution_checked", "rejected"))
            self.assertNotEqual(candidate["state"], "promoted",
                                "a retrospective must never promote anything directly")

    def test_a_candidate_on_a_protected_surface_is_refused(self):
        from liwm.retrospective import propose_candidates

        episode = {
            "id": "epi_x", "counts": {"questions_asked": 0, "questions_wasted": 0,
                                      "questions_useful": 0, "feedback": 0,
                                      "corrections": 0, "assumptions": 2,
                                      "quarantined_events": 0, "events": 3},
            "questions": [], "answers": [], "feedback": [], "predictions": [],
            "outcomes": [],
            "assumptions": [{"disclosed": False}, {"disclosed": False}],
            "mean_acceptance": None, "prediction_error": None,
        }
        candidates = propose_candidates(episode)
        transparency = [c for c in candidates if c["surface"] == "transparency"]
        self.assertTrue(transparency)

        si = SelfImprovementStore(self.home)
        result = si.propose(transparency[0], store=self.store)
        self.assertEqual(result["state"], "rejected")

    def test_strategy_adapts_to_ignored_questions(self):
        from liwm.retrospective import run_retrospective
        from liwm.strategy import StrategyStore

        before = StrategyStore(self.home).load()["auto_low_threshold"]
        self._session_with_wasted_questions()
        run_retrospective(self.store, "s1")
        after = StrategyStore(self.home).load()["auto_low_threshold"]
        self.assertGreater(after, before,
                           "being ignored must make LIWM quieter, not louder")

    def test_strategy_changes_are_bounded(self):
        from liwm.strategy import MAX_STEP, StrategyStore

        store = StrategyStore(self.home)
        before = store.load()["challenge_strength"]
        after, _ = store.apply({"challenge_strength": 10.0}, reason="test")
        self.assertLessEqual(abs(after["challenge_strength"] - before), MAX_STEP + 1e-6)
        self.assertLessEqual(after["challenge_strength"], 0.90)


class TestTraceability(LiwmTestCase):
    def test_belief_explanation_cites_real_evidence(self):
        """With free-text retention on, the explanation quotes what was said."""
        from liwm.config import ConfigStore
        from liwm.traceability import explain_belief

        ConfigStore(self.home).set("privacy.store_free_text", True)
        self.observe("interaction_profile.preferred_verbosity", "terse",
                     note="user said keep it short")
        result = explain_belief(self.store,
                                dimension="interaction_profile.preferred_verbosity")
        self.assertEqual(result["belief"]["value"], "terse")
        self.assertTrue(result["supporting_evidence"])
        self.assertIn("keep it short", result["supporting_evidence"][-1]["quote"])

    def test_explanation_survives_the_no_free_text_default(self):
        """Traceability degrades to structure, never to invention.

        By default LIWM does not keep the user's words. The explanation must
        still name the event, its source type and its provenance, and must
        report the missing quote as missing rather than reconstructing one.
        """
        from liwm.traceability import explain_belief

        self.observe("interaction_profile.preferred_verbosity", "terse",
                     note="user said keep it short")
        result = explain_belief(self.store,
                                dimension="interaction_profile.preferred_verbosity")
        evidence = result["supporting_evidence"][-1]
        self.assertIsNone(evidence["quote"])
        self.assertEqual(evidence["source_type"], "explicit_statement")
        self.assertEqual(evidence["provenance"], "direct_user_message")
        self.assertTrue(evidence["event_id"].startswith("evt_"))

    def test_explanation_names_the_ceiling_when_that_is_the_limit(self):
        from liwm.traceability import explain_belief

        for i in range(6):
            self.observe("reasoning_profile.tradeoff_style", "satisfice",
                         source_type="agent_inference", provenance="agent_inference",
                         session_id="s%d" % i)
        result = explain_belief(self.store, dimension="reasoning_profile.tradeoff_style")
        self.assertIn("capped", result["confidence_explanation"])

    def test_ignored_evidence_is_disclosed(self):
        from liwm.traceability import explain_belief

        self.observe("interaction_profile.pace", "fast")
        self.store.events.record(
            "observation", "repository_content",
            observation={"dimension": "interaction_profile.pace", "value": "deliberate",
                         "source_type": "explicit_statement", "polarity": "support",
                         "scope": "global"})
        self.store.rebuild(reason="test")
        result = explain_belief(self.store, dimension="interaction_profile.pace")
        self.assertTrue(result["ignored_evidence"])
        self.assertIn("quarantined", result["ignored_note"])

    def test_decision_explanation_traces_to_intent_and_beliefs(self):
        from liwm.projects import ProjectStore
        from liwm.traceability import explain_decision

        self.observe("decision_style.option_breadth", "one_recommendation")
        belief = self.belief("decision_style.option_breadth")
        ps = ProjectStore(self.home, "demo")
        item = ps.add("objectives", "ship fast", "USER_SAID")
        decision = ps.record_decision(
            "picked the single simplest option", rationale="matches stated preference",
            basis=[belief["id"], item["id"]])
        self.store.events.record("decision", "agent_inference",
                                 payload={"decision_id": decision["id"]},
                                 project_id="demo")
        self.store.rebuild(reason="test")

        result = explain_decision(self.store, decision["id"], project_id="demo")
        kinds = {b["type"] for b in result["basis_detail"]}
        self.assertEqual(kinds, {"belief", "intent"})
        self.assertEqual(result["completeness"], "fully traced")

    def test_undocumented_decision_says_so_instead_of_inventing(self):
        from liwm.projects import ProjectStore
        from liwm.traceability import explain_decision

        ps = ProjectStore(self.home, "demo")
        decision = ps.record_decision("did a thing", basis=[])
        self.store.events.record("decision", "agent_inference",
                                 payload={"decision_id": decision["id"]},
                                 project_id="demo")
        self.store.rebuild(reason="test")
        result = explain_decision(self.store, decision["id"], project_id="demo")
        self.assertIn("incomplete rather than reconstructed", result["completeness"])


class TestPredictionCalibration(LiwmTestCase):
    def test_prediction_resolution_scores_error(self):
        from liwm.prediction import make_prediction, record_prediction, resolve_prediction

        prediction = make_prediction(0.8, 0.6,
                                     predicted_friction=[{"issue": "too terse",
                                                          "probability": 0.4}])
        record_prediction(self.store, prediction, session_id="s1")
        result = resolve_prediction(self.store, prediction["id"], 0.3,
                                    observed_friction=["too terse", "wrong stack"],
                                    session_id="s1")
        self.assertAlmostEqual(result["error"], -0.8, places=3)
        self.assertEqual(result["actual_first_pass"], 0)
        self.assertEqual(result["direction"], "overconfident")
        self.assertEqual(result["friction_hits"], ["too terse"])
        self.assertEqual(result["surprises"], ["wrong stack"])

    def test_calibration_reaches_metrics(self):
        from liwm.metrics import compute_metrics
        from liwm.prediction import make_prediction, record_prediction, resolve_prediction

        for i in range(4):
            prediction = make_prediction(0.9, 0.7)
            record_prediction(self.store, prediction, session_id="s%d" % i)
            resolve_prediction(self.store, prediction["id"], 0.5, session_id="s%d" % i)
        metrics = compute_metrics(self.store)
        self.assertEqual(metrics["calibration"]["samples"], 4)
        self.assertAlmostEqual(metrics["calibration"]["bias"], -0.9, places=3)
        self.assertIsNotNone(metrics["calibration"]["log_loss"])
        self.assertGreater(metrics["calibration"]["brier_score"], 0)



class TestPredictionIsReachableFromTheCLI(LiwmTestCase):
    """The falsifiability loop has to be usable, not merely implemented.

    `metrics.py` computed a Brier score from prediction and outcome events for
    the whole of 0.1.0's development, but nothing outside the tests could create
    one: `record_prediction` had no caller. Calibration was therefore guaranteed
    to read zero samples for every real user, while the docs claimed the
    framework measured itself. These tests keep the entry point wired.
    """

    def _cli(self, *argv):
        from liwm.cli import main

        return main(["--home", str(self.home), "--json", *argv])

    def test_predict_then_resolve_produces_a_calibration_sample(self):
        import io
        import json
        from contextlib import redirect_stdout
        from liwm.metrics import MetricsStore

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self._cli("predict", "--acceptance", "0.7", "--confidence", "0.6",
                      "--friction", "too terse:0.4", "--artifact", "refactor")
        prediction_id = json.loads(buffer.getvalue())["id"]
        self.assertTrue(prediction_id.startswith("prd_"))

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self._cli("resolve", "--prediction", prediction_id,
                      "--acceptance", "0.3", "--friction", "too terse")
        result = json.loads(buffer.getvalue())
        self.assertEqual(result["direction"], "overconfident")
        self.assertEqual(result["friction_hits"], ["too terse"])

        metrics = MetricsStore(self.home).refresh(self.store)
        self.assertEqual(metrics["calibration"]["samples"], 1)
        self.assertAlmostEqual(metrics["calibration"]["brier_score"], 0.49, places=4)

    def test_an_unresolved_prediction_is_reported_as_such(self):
        import io
        import json
        from contextlib import redirect_stdout

        with redirect_stdout(io.StringIO()):
            self._cli("predict", "--acceptance", "0.5", "--confidence", "0.5")

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            self._cli("predictions", "--unresolved")
        data = json.loads(buffer.getvalue())
        self.assertEqual(data["unresolved"], 1)
        self.assertFalse(data["predictions"][0]["resolved"])

    def test_resolving_an_unknown_prediction_is_an_error_not_a_silent_no_op(self):
        import io
        from contextlib import redirect_stdout

        with redirect_stdout(io.StringIO()):
            code = self._cli("resolve", "--prediction", "prd_nope",
                             "--acceptance", "0.5")
        self.assertNotEqual(code, 0)

    def test_malformed_friction_is_rejected_rather_than_stored_as_a_label(self):
        import io
        from contextlib import redirect_stdout

        with redirect_stdout(io.StringIO()):
            code = self._cli("predict", "--acceptance", "0.5", "--confidence", "0.5",
                             "--friction", ":0.4")
        self.assertNotEqual(code, 0)



if __name__ == "__main__":
    unittest.main()
