"""Deterministic fuzz-style checks for reducer invariants (stdlib only)."""

from __future__ import annotations

import random
import tempfile
import unittest

import helpers  # noqa: F401 - adds src/ to sys.path

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
