"""Concurrency and corruption recovery.

Several agents may hold the same profile open at once.  The design answer is
that events are the truth and ``user.json`` is a cache: conflicting writes are
resolved by re-folding rather than by merging, so a lost update is impossible by
construction rather than by luck.
"""

from __future__ import annotations

import json
import threading
import unittest

from helpers import LiwmTestCase

from liwm.jsonio import FileLock, LockTimeout, read_json_resilient, write_json_atomic
from liwm.profile import ProfileStore, RevisionConflict


class TestConcurrency(LiwmTestCase):
    def test_two_agents_updating_different_dimensions_both_survive(self):
        a = ProfileStore(self.home)
        b = ProfileStore(self.home)
        a.observe("interaction_profile.preferred_verbosity", "terse",
                  source_type="explicit_statement", provenance="direct_user_message")
        b.observe("decision_style.option_breadth", "one_recommendation",
                  source_type="explicit_statement", provenance="direct_user_message")
        profile = ProfileStore(self.home).load()
        dims = {x["dimension"] for x in profile["beliefs"]}
        self.assertIn("interaction_profile.preferred_verbosity", dims)
        self.assertIn("decision_style.option_breadth", dims)

    def test_conflicting_dimension_updates_both_appear_as_evidence(self):
        a = ProfileStore(self.home)
        b = ProfileStore(self.home)
        a.observe("creative_profile.simplicity_vs_richness", "minimal",
                  source_type="explicit_statement", provenance="direct_user_message")
        b.observe("creative_profile.simplicity_vs_richness", "feature_rich",
                  source_type="explicit_statement", provenance="direct_user_message")
        profile = ProfileStore(self.home).load()
        values = {str(x["value"]) for x in profile["beliefs"]
                  if x["dimension"] == "creative_profile.simplicity_vs_richness"}
        self.assertEqual(values, {"minimal", "feature_rich"})
        self.assertTrue(any(c["dimension"] == "creative_profile.simplicity_vs_richness"
                            for c in profile["contradictions"]))

    def test_stale_revision_write_is_refused(self):
        profile = self.store.load()
        stale = profile["revision"]
        self.store.save(dict(profile), expected_revision=stale)
        with self.assertRaises(RevisionConflict):
            self.store.save(dict(profile), expected_revision=stale)

    def test_parallel_writers_lose_no_events(self):
        """The property that matters: N concurrent observations produce N
        pieces of evidence, regardless of write interleaving."""
        errors = []

        def worker(i):
            try:
                store = ProfileStore(self.home)
                store.observe("working_style.iteration_style", "many_iterations",
                              source_type="single_behavioral", provenance="agent_inference",
                              session_id="s%d" % i)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        final = ProfileStore(self.home).rebuild(reason="post-concurrency")
        belief = next(b for b in final["beliefs"]
                      if b["dimension"] == "working_style.iteration_style")
        self.assertEqual(belief["evidence_count"], 8, "no observation may be lost")

    def test_lock_times_out_rather_than_hanging(self):
        lock_path = self.home / "test.lock"
        with FileLock(lock_path, timeout=0.2, stale_after=999):
            with self.assertRaises(LockTimeout):
                FileLock(lock_path, timeout=0.2, stale_after=999).acquire()

    def test_live_lock_is_never_broken_solely_for_age(self):
        lock_path = self.home / "stale.lock"
        first = FileLock(lock_path, timeout=0.2, stale_after=999).acquire()
        try:
            with self.assertRaises(LockTimeout):
                FileLock(lock_path, timeout=0.2, stale_after=0.0).acquire()
        finally:
            first.release()

    def test_dead_owner_lock_is_broken(self):
        import os
        import socket
        import time

        lock_path = self.home / "dead.lock"
        lock_path.write_text(json.dumps({
            "pid": 999999999, "host": socket.gethostname(),
            "monotonic": time.time() - 999, "token": "dead",
        }), encoding="utf-8")
        lock = FileLock(lock_path, timeout=1.0, stale_after=0.0)
        lock.acquire()
        try:
            self.assertTrue(lock.broke_stale_lock)
            self.assertNotEqual(os.getpid(), 999999999)
        finally:
            lock.release()


class TestRecovery(LiwmTestCase):
    def test_malformed_profile_is_quarantined_and_rebuilt(self):
        self.observe("interaction_profile.pace", "fast")
        self.store.path.write_text("{ this is not json", encoding="utf-8")
        profile = self.store.load()
        self.assertIsNotNone(profile)
        self.assertIsNotNone(self.belief("interaction_profile.pace", profile=profile))
        quarantined = list((self.home / "logs" / "corrupt").glob("user.json.*"))
        self.assertTrue(quarantined, "the corrupt file must be preserved, not deleted")

    def test_missing_profile_is_regenerated_from_events(self):
        self.observe("decision_style.speed", "decisive")
        self.store.path.unlink()
        profile = self.store.load()
        self.assertIsNotNone(self.belief("decision_style.speed", profile=profile))

    def test_partial_write_recovers_from_backup(self):
        self.observe("interaction_profile.preferred_verbosity", "terse")
        self.observe("decision_style.option_breadth", "two_or_three")
        self.store.path.write_text('{"schema_version": "0.1.0", "revi', encoding="utf-8")
        data, note = read_json_resilient(
            self.store.path, backups_dir=self.home / "backups", logs_dir=self.home / "logs"
        )
        self.assertIsNotNone(data)
        self.assertIn("quarantined", note)

    def test_a_single_unreadable_event_does_not_break_the_fold(self):
        self.observe("interaction_profile.pace", "fast")
        self.observe("decision_style.speed", "decisive")
        paths = list(self.store.events.iter_paths())
        paths[0].write_text("<<corrupt>>", encoding="utf-8")
        profile = self.store.rebuild(reason="test")
        self.assertGreaterEqual(len(profile["beliefs"]), 1)
        log = self.home / "logs" / "event-read-errors.log"
        self.assertTrue(log.is_file())

    def test_deleted_metrics_are_recomputed(self):
        from liwm.metrics import MetricsStore

        ms = MetricsStore(self.home)
        self.observe("interaction_profile.pace", "fast")
        ms.refresh(self.store)
        ms.path.unlink()
        metrics = ms.refresh(self.store)
        self.assertIn("counters", metrics)

    def test_unknown_fields_are_preserved_across_a_save(self):
        profile = self.store.load()
        profile["experimental_future_field"] = {"kept": True}
        saved = self.store.save(profile)
        reloaded = self.store.load()
        self.assertEqual(saved["experimental_future_field"], {"kept": True})
        self.assertEqual(reloaded["experimental_future_field"], {"kept": True})

    def test_newer_schema_version_is_refused_not_guessed(self):
        from liwm.migrate import MigrationError, migrate_profile

        with self.assertRaises(MigrationError):
            migrate_profile({"schema_version": "99.0.0"})

    def test_atomic_write_leaves_no_temp_files(self):
        target = self.home / "atomic.json"
        write_json_atomic(target, {"a": 1})
        leftovers = [p for p in self.home.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"a": 1})


if __name__ == "__main__":
    unittest.main()
