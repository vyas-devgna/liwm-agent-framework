"""Verification cost must not grow with history, and must still catch tampering.

`verify()` runs on the read path -- the call an agent makes every turn. Before
this it re-hashed the whole event history each time, so consulting the profile
got steadily slower for exactly the users who had used LIWM longest: 1.25 s of
a 1.25 s context build at 20,000 events.

An archive whose recorded SHA-256 matches its bytes cannot have had a contained
event altered, so re-parsing and re-hashing each of those events individually
detects nothing the digest did not. These tests hold both halves: that the
cheap path is cheap, and that every tampering the expensive path caught is
still caught.
"""

from __future__ import annotations

import gzip
import json
import unittest

from helpers import LiwmTestCase

from liwm.compaction import compact


class TestTamperingIsStillCaught(LiwmTestCase):
    def _archive(self):
        for index in range(6):
            self.observe("preferences.thing_%d" % index, "value_%d" % index)
        result = compact(self.store)
        self.assertTrue(result["compacted"], result)
        archives = list(self.store.events.archive_root.glob("*.jsonl.gz"))
        self.assertEqual(len(archives), 1)
        return archives[0]

    def test_a_clean_archive_verifies(self):
        self._archive()
        self.assertTrue(self.store.events.verify()["ok"])
        self.assertTrue(self.store.events.verify(deep=True)["ok"])

    def test_editing_an_archived_event_is_caught_without_deep(self):
        """The digest is the detection. This is the property the fast path rests on."""
        archive = self._archive()
        with gzip.open(archive, "rt", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        rows[0].setdefault("observation", {})["value"] = "tampered"
        with gzip.open(archive, "wt", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")

        report = self.store.events.verify()
        self.assertFalse(report["ok"])
        self.assertIn("archive_hash_mismatch",
                      {problem["issue"] for problem in report["problems"]})

    def test_truncating_an_archive_is_caught(self):
        archive = self._archive()
        archive.write_bytes(archive.read_bytes()[:-40])
        self.assertFalse(self.store.events.verify()["ok"])

    def test_deleting_an_archive_is_caught(self):
        archive = self._archive()
        archive.unlink()
        report = self.store.events.verify()
        self.assertFalse(report["ok"])
        self.assertIn("archive_missing",
                      {problem["issue"] for problem in report["problems"]})

    def test_a_live_event_is_still_hashed_every_time(self):
        """Nothing is trusted on the strength of an archive it is not inside."""
        self._archive()
        self.observe("interaction_profile.pace", "fast")
        live = sorted(self.store.events._scan_paths())[-1]
        row = json.loads(live.read_text(encoding="utf-8"))
        row["observation"]["value"] = "tampered"
        live.write_text(json.dumps(row, sort_keys=True), encoding="utf-8")
        self.assertFalse(self.store.events.verify()["ok"])

    def test_overlapping_archive_ranges_are_caught_from_the_index(self):
        """Two archives claiming one event, noticed without decompressing either."""
        self._archive()
        index = self.store.events._archive_index()
        row = dict(index["archives"][0])
        index["archives"].append(row)
        self.store.events._write_archive_index(index["archives"])
        report = self.store.events.verify()
        self.assertFalse(report["ok"])
        self.assertIn("archive_range_overlap",
                      {problem["issue"] for problem in report["problems"]})


class TestReadPathCost(LiwmTestCase):
    def test_a_compacted_history_does_not_re_read_itself(self):
        """The scaling property, as a behavioural assertion rather than a timing one.

        Timings are not assertable in CI. What is assertable is the thing that
        made it slow: the number of files opened. After compaction the read
        path must not be touching one file per historical event.
        """
        for index in range(40):
            self.observe("preferences.thing_%d" % index, "value_%d" % index)
        compact(self.store)

        opened = []
        real_open = gzip.open

        def counting_open(*args, **kwargs):
            opened.append(args[0] if args else None)
            return real_open(*args, **kwargs)

        gzip.open = counting_open
        try:
            self.assertTrue(self.store.events.verify()["ok"])
        finally:
            gzip.open = real_open
        self.assertEqual(opened, [], "the fast path decompressed an archive")

    def test_deep_verification_still_reads_everything(self):
        for index in range(6):
            self.observe("preferences.thing_%d" % index, "value_%d" % index)
        compact(self.store)

        opened = []
        real_open = gzip.open

        def counting_open(*args, **kwargs):
            opened.append(args[0] if args else None)
            return real_open(*args, **kwargs)

        gzip.open = counting_open
        try:
            self.store.events.verify(deep=True)
        finally:
            gzip.open = real_open
        self.assertTrue(opened, "deep verification skipped the archive")


if __name__ == "__main__":
    unittest.main()
