from __future__ import annotations

import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from datetime import datetime, timedelta, timezone

from helpers import LiwmTestCase

from liwm.cli import main
from liwm.study import export_study, set_study_enabled, study_status


class TestStudyMode(LiwmTestCase):
    def test_default_off_and_export_requires_opt_in(self):
        self.assertFalse(study_status(self.home)["enabled"])
        with self.assertRaises(ValueError):
            export_study(self.home)

    def test_export_is_local_minimized_and_anonymised(self):
        secret = "violet-comet-secret"
        set_study_enabled(self.home, True)
        self.store.events.record(
            "feedback", "direct_user_message",
            payload={"kind": "mostly_right", "acceptance": 0.75, "comment": secret},
            session_id="session-secret", project_id="project-secret", domain="health-secret",
        )
        result = export_study(self.home, anonymise=True)
        exported = Path(result["path"]).read_text(encoding="utf-8")
        self.assertTrue(result["local_only"])
        self.assertFalse(result["automatic_upload"])
        self.assertNotIn(secret, exported)
        self.assertNotIn("session-secret", exported)
        self.assertEqual(result["events"][-1]["measurements"]["acceptance"], 0.75)

    def test_cli_status_on_off_and_export(self):
        def run(*args):
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main([*args, "--home", str(self.home), "--json"])
            self.assertEqual(code, 0, err.getvalue() or out.getvalue())
            return json.loads(out.getvalue())

        self.assertFalse(run("study", "status")["enabled"])
        self.assertTrue(run("study", "on")["enabled"])
        exported = run("study", "export", "--anonymise")
        self.assertTrue(exported["anonymised"])
        self.assertFalse(run("study", "off")["enabled"])

    def test_retention_window_filters_old_events(self):
        set_study_enabled(self.home, True)
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat().replace("+00:00", "Z")
        self.store.events.record("feedback", "direct_user_message",
                                 payload={"acceptance": 0.1}, ts=old)
        self.store.events.record("feedback", "direct_user_message",
                                 payload={"acceptance": 0.9})
        from liwm.config import ConfigStore
        ConfigStore(self.home).set("study.retention_days", 2)
        result = export_study(self.home)
        acceptances = [row["measurements"].get("acceptance") for row in result["events"]]
        self.assertNotIn(0.1, acceptances)
        self.assertIn(0.9, acceptances)

    def test_opt_in_excludes_pre_consent_history(self):
        self.store.events.record("feedback", "direct_user_message", payload={"acceptance": 0.2})
        set_study_enabled(self.home, True)
        self.store.events.record("feedback", "direct_user_message", payload={"acceptance": 0.8})
        values = [row["measurements"].get("acceptance") for row in export_study(self.home)["events"]]
        self.assertEqual(values, [0.8])

    def test_quarantined_or_out_of_range_measurements_are_not_exported(self):
        set_study_enabled(self.home, True)
        self.store.events.record(
            "feedback", "repository_content", payload={"acceptance": 4111111111111111}
        )
        self.store.events.record(
            "feedback", "direct_user_message", payload={"acceptance": 9.0}
        )
        self.assertEqual(export_study(self.home, anonymise=True)["events"][0]["measurements"], {})


if __name__ == "__main__":
    unittest.main()


class LongitudinalExportTests(LiwmTestCase):
    """A fresh salt per export makes repeated measures impossible to join."""

    def setUp(self):
        super().setUp()
        from liwm.study import set_study_enabled
        set_study_enabled(self.home, True)
        self.observe("preferences.editor", "vim", session_id="s1")
        self.store.events.record("feedback", "direct_user_message", session_id="s1",
                                 payload={"acceptance": 0.9, "task_id": "t1"})
        self.store.events.record("feedback", "direct_user_message", session_id="s2",
                                 payload={"acceptance": 0.4, "task_id": "t2"})

    def _export(self, **kwargs):
        from liwm.study import export_study
        return export_study(self.home, out=str(self.home / "out.json"), **kwargs)

    def test_one_off_exports_cannot_be_joined_to_each_other(self):
        first = self._export(anonymise=True)
        second = self._export(anonymise=True)
        self.assertEqual(first["mode"], "one_off")
        self.assertNotEqual([row["session_id"] for row in first["events"]],
                            [row["session_id"] for row in second["events"]])

    def test_longitudinal_exports_share_pseudonyms_within_one_study(self):
        first = self._export(anonymise=True, longitudinal=True)
        second = self._export(anonymise=True, longitudinal=True)
        self.assertEqual(first["study_id"], second["study_id"])
        self.assertEqual([row["session_id"] for row in first["events"]],
                         [row["session_id"] for row in second["events"]])
        self.assertIn("pseudonymity, not", first["privacy_notice"])

    def test_rotating_the_key_severs_linkage(self):
        from liwm.study import rotate_study_key
        before = self._export(anonymise=True, longitudinal=True)
        rotate_study_key(self.home)
        after = self._export(anonymise=True, longitudinal=True)
        self.assertNotEqual(before["study_id"], after["study_id"])
        self.assertNotEqual([row["session_id"] for row in before["events"]],
                            [row["session_id"] for row in after["events"]])

    def test_deleting_the_key_is_offered_and_effective(self):
        from liwm.study import delete_study_key, study_key_status
        self._export(anonymise=True, longitudinal=True)
        self.assertTrue(study_key_status(self.home)["exists"])
        self.assertTrue(delete_study_key(self.home)["deleted"])
        self.assertFalse(study_key_status(self.home)["exists"])

    def test_a_longitudinal_row_carries_ordering_and_no_wall_clock(self):
        rows = self._export(anonymise=True, longitudinal=True)["events"]
        self.assertTrue(rows)
        for row in rows:
            self.assertIsNone(row["ts"])
            self.assertIsNotNone(row["relative_day"])
            self.assertGreaterEqual(row["event_sequence_offset"], 1)
        sessions = {row["session_id"]: row["session_ordinal"]
                    for row in rows if row.get("session_ordinal")}
        self.assertEqual(sorted(sessions.values()), list(range(1, len(sessions) + 1)))

    def test_a_longitudinal_export_must_be_anonymised(self):
        with self.assertRaises(ValueError):
            self._export(longitudinal=True)

    def test_the_key_never_reaches_the_export(self):
        from liwm.study import study_key_status
        payload = self._export(anonymise=True, longitudinal=True)
        key = json.loads((self.home / "study-key.json").read_text())["key"]
        self.assertNotIn(key, json.dumps(payload))
        self.assertNotIn(key, json.dumps(study_key_status(self.home)))
