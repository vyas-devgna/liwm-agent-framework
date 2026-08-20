"""Compaction retains raw evidence and exact semantic materialisation."""

from helpers import LiwmTestCase

from liwm.compaction import compact, verify_checkpoints


class TestCompaction(LiwmTestCase):
    def test_compaction_equivalence_and_future_writes(self):
        self.store.observe_user("preferences.compact", "yes", session_id="s1")
        before = self.store.fold()["beliefs"]
        result = compact(self.store)
        self.assertTrue(result["compacted"])
        self.assertTrue(result["raw_history_retained"])
        self.assertEqual(before, self.store.fold()["beliefs"])
        self.assertTrue(self.store.events.verify()["ok"])
        self.assertTrue(verify_checkpoints(self.home)["ok"])
        event, _ = self.store.observe_user("preferences.after_compact", "yes")
        self.assertGreater(event["sequence"], result["frontier"])

    def test_reset_and_rejection_survive_compaction(self):
        self.store.observe_user("preferences.old", "yes")
        self.store.reject("preferences.old", "yes")
        compact(self.store)
        self.assertEqual(self.belief("preferences.old", "yes")["confidence"], 0.0)
