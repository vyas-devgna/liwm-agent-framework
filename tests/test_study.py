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
