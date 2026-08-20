"""Deterministic fuzz-style checks for reducer invariants (stdlib only)."""

from __future__ import annotations

import random
import tempfile
import unittest

from helpers import LiwmTestCase

from liwm.events import make_event
from liwm.profile import ProfileStore


class TestReducerProperties(unittest.TestCase):
    @staticmethod
    def _fold(rows):
        tmp = tempfile.TemporaryDirectory(prefix="liwm-property-")
        store = ProfileStore(tmp.name)
        for row in rows:
            store.events.append(make_event(
                "observation", row["provenance"], ts=row["ts"],
                observation={
                    "dimension": "preferences.property", "value": "yes",
                    "source_type": row["source"], "polarity": row["polarity"],
                    "scope": "global", "decay_policy": "none",
                },
            ))
        profile = store.fold()
        belief = next(row for row in profile["beliefs"]
                      if row["dimension"] == "preferences.property")
        tmp.cleanup()
        return {key: belief[key] for key in (
            "confidence", "evidence_count", "contradiction_count", "ceiling", "status"
        )}

    def test_observation_order_is_irrelevant_when_no_control_event_exists(self):
        rng = random.Random(20260820)
        rows = [{
            "ts": "2026-01-01T00:%02d:%02dZ" % divmod(index, 60),
            "provenance": "agent_inference", "source": "single_behavioral",
            "polarity": rng.choice(["support", "oppose"]),
        } for index in range(120)]
        shuffled = list(rows)
        rng.shuffle(shuffled)
        self.assertEqual(self._fold(rows), self._fold(shuffled))

    def test_more_untrusted_evidence_never_changes_a_belief(self):
        trusted = [{
            "ts": "2026-01-01T00:00:00Z", "provenance": "direct_user_message",
            "source": "explicit_statement", "polarity": "support",
        }]
        baseline = self._fold(trusted)
        poisoned = trusted + [{
            "ts": "2026-01-01T00:%02d:00Z" % (index + 1),
            "provenance": "repository_content", "source": "explicit_statement",
            "polarity": "oppose",
        } for index in range(50)]
        self.assertEqual(baseline, self._fold(poisoned))

    def test_duplicate_recent_event_id_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="liwm-property-") as home:
            store = ProfileStore(home)
            event = make_event("feedback", "agent_inference")
            store.events.append(event)
            with self.assertRaises(ValueError):
                store.events.append(event)


if __name__ == "__main__":
    unittest.main()


class TestInvariantsUnderRandomHistories(LiwmTestCase):
    """Properties that must hold for any history, not just the ones we wrote.

    Randomised with fixed seeds rather than a property-testing library. The
    library would be a real dependency for a shrinking algorithm we do not
    need: these histories are small, the seeds are printed on failure, and a
    counterexample is reproducible by rerunning the test.
    """

    KINDS = ("observe", "inference", "untrusted", "forget", "reject")

    def _random_history(self, seed, length=25):
        rng = random.Random(seed)
        dimensions = ["preferences.a", "preferences.b", "interaction_profile.pace"]
        values = ["one", "two"]
        applied = []
        for index in range(length):
            kind = rng.choice(self.KINDS)
            dimension = rng.choice(dimensions)
            value = rng.choice(values)
            session = "s%d" % rng.randint(0, 3)
            try:
                if kind == "observe":
                    self.store.observe(dimension, value, source_type="explicit_statement",
                                       provenance="direct_user_message", session_id=session)
                elif kind == "inference":
                    self.store.observe(dimension, value, source_type="agent_inference",
                                       provenance="agent_inference", session_id=session)
                elif kind == "untrusted":
                    self.store.observe_untrusted(dimension, value, "repository_content")
                elif kind == "forget":
                    self.store.forget(dimension=dimension)
                else:
                    self.store.reject(dimension, value)
            except ValueError:  # a control the current state does not allow
                continue
            applied.append((index, kind, dimension, value))
        return applied

    def test_folding_twice_gives_the_same_answer(self):
        for seed in (1, 2, 3):
            self.setUp()
            self._random_history(seed)
            first = self.store.fold()
            second = self.store.fold()
            self.assertEqual(first["beliefs"], second["beliefs"], "seed %d" % seed)

    def test_untrusted_evidence_never_reaches_a_belief(self):
        for seed in (4, 5, 6):
            self.setUp()
            self._random_history(seed)
            for belief in self.store.load()["beliefs"]:
                self.assertNotIn("repository_content", belief["provenance_types"],
                                 "seed %d" % seed)

    def test_no_belief_ever_exceeds_the_ceiling_of_its_strongest_source(self):
        from liwm.evidence import SINGLE_OBSERVATION_CLAMP, SOURCE_CEILINGS
        for seed in (7, 8, 9):
            self.setUp()
            self._random_history(seed)
            for belief in self.store.load()["beliefs"]:
                ceiling = max((SOURCE_CEILINGS.get(name, 0.0)
                               for name in belief["source_types"]), default=0.0)
                where = "seed %d, %s" % (seed, belief["key"])
                self.assertLessEqual(belief["confidence"], ceiling + 1e-9, where)
                self.assertLessEqual(belief["confidence"], belief["ceiling"] + 1e-9, where)
                # Nothing is ever certain, however much evidence agrees.
                self.assertLess(belief["confidence"], 1.0, where)
                self.assertLessEqual(belief["confidence"],
                                     SINGLE_OBSERVATION_CLAMP + 0.05, where)

    def test_agent_inference_alone_never_passes_its_own_ceiling(self):
        from liwm.evidence import SOURCE_CEILINGS
        for count in (1, 3, 10, 40):
            self.setUp()
            for index in range(count):
                self.store.observe("preferences.ceiling", "yes",
                                   source_type="agent_inference",
                                   provenance="agent_inference", session_id="s%d" % index)
            belief = self.belief("preferences.ceiling", "yes")
            self.assertLessEqual(belief["confidence"],
                                 SOURCE_CEILINGS["agent_inference"] + 1e-9,
                                 "%d inferences" % count)

    def test_a_rejected_belief_is_never_active(self):
        for seed in (10, 11, 12):
            self.setUp()
            self._random_history(seed)
            for belief in self.store.load()["beliefs"]:
                if belief.get("rejected_by_user"):
                    self.assertEqual(belief["confidence"], 0.0, "seed %d" % seed)

    def test_the_graph_never_outranks_the_evidence_beneath_it(self):
        from liwm.intent_graph import IntentGraphStore
        rng = random.Random(13)
        graph = IntentGraphStore(self.home)
        for index in range(12):
            event, _ = self.store.observe(
                "preferences.graph%d" % index, "yes",
                source_type=rng.choice(["explicit_statement", "single_behavioral",
                                        "agent_inference"]),
                provenance="direct_user_message")
            graph.add_node("preference", "node %d" % index, "direct_user_message",
                           rng.random(), evidence_refs=[event["event_id"]],
                           decay_policy=rng.choice(["none", "slow", "standard"]))
        for row in graph.graph()["nodes"]:
            # Both sides are rounded to four places for the projection, so the
            # tolerance is a rounding step rather than a fudge factor.
            self.assertLessEqual(row["effective_confidence"],
                                 row["effective_ceiling"] + 1e-4, row["id"])
            self.assertLessEqual(row["effective_confidence"],
                                 row["recorded_confidence"] + 1e-4, row["id"])

    def test_the_event_log_verifies_after_any_history(self):
        for seed in (14, 15, 16):
            self.setUp()
            self._random_history(seed)
            self.assertTrue(self.store.events.verify()["ok"], "seed %d" % seed)

    def test_compaction_preserves_the_fold_for_any_history(self):
        from liwm.compaction import compact
        for seed in (17, 18):
            self.setUp()
            self._random_history(seed)
            before = self.store.fold()["beliefs"]
            compact(self.store)
            self.assertEqual(before, self.store.fold()["beliefs"], "seed %d" % seed)


class TestMalformedInputDegradesSafely(LiwmTestCase):
    def test_a_truncated_profile_cache_is_recovered_not_trusted(self):
        self.observe("preferences.recover", "yes")
        (self.home / "user.json").write_text('{"beliefs": [', encoding="utf-8")
        profile = self.store.load()
        self.assertEqual(
            [b["dimension"] for b in profile["beliefs"]], ["preferences.recover"])

    def test_garbage_in_a_confidence_field_becomes_no_signal(self):
        from liwm.evidence import clamp
        for garbage in ("", "abc", None, [], {}, float("nan"), float("inf")):
            self.assertGreaterEqual(clamp(garbage), 0.0)
            self.assertLessEqual(clamp(garbage), 1.0)

    def test_an_unreadable_host_overlay_is_ignored_rather_than_fatal(self):
        from liwm.hosts import load_registry
        (self.home / "hosts.json").write_text("{not json", encoding="utf-8")
        self.assertTrue(load_registry(self.home))
