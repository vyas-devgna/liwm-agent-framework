"""CLI surface: the only sanctioned way for a skill to mutate LIWM state.

Every command is exercised in ``--json`` mode, because that is how the skills
consume it and a broken JSON contract silently degrades every skill at once.
"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from helpers import LiwmTestCase

from liwm.cli import main


class CliTestCase(LiwmTestCase):
    def run_cli(self, *args, expect=0):
        out, err = io.StringIO(), io.StringIO()
        argv = ["--home", str(self.home), "--json"] + list(args)
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = main(argv)
            except SystemExit as exc:   # argparse exits rather than returning
                code = exc.code if isinstance(exc.code, int) else 2
        self.assertEqual(code, expect,
                         "liwm %s -> %s\nstdout=%s\nstderr=%s"
                         % (" ".join(args), code, out.getvalue(), err.getvalue()))
        text = out.getvalue().strip()
        return json.loads(text) if text else None

    def run_cli_text(self, *args, expect=0):
        out, err = io.StringIO(), io.StringIO()
        argv = ["--home", str(self.home)] + list(args)
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = main(argv)
            except SystemExit as exc:
                code = exc.code if isinstance(exc.code, int) else 2
        self.assertEqual(code, expect, err.getvalue())
        return out.getvalue()


class TestCliCore(CliTestCase):
    def test_init_is_idempotent(self):
        first = self.run_cli("init", "--allow-in-repo")
        second = self.run_cli("init", "--allow-in-repo")
        self.assertEqual(first["profile_id"], second["profile_id"])
        self.assertFalse(second["created"])

    def test_doctor_reports_healthy(self):
        self.run_cli("init", "--allow-in-repo")
        result = self.run_cli("doctor")
        self.assertTrue(result["healthy"], result["checks"])

    def test_observe_then_profile(self):
        self.run_cli("observe", "--dimension", "interaction_profile.preferred_verbosity",
                     "--value", "terse", "--source", "explicit_statement",
                     "--provenance", "direct_user_message")
        report = self.run_cli("profile")
        dims = [row["dimension"] for row in report["high_confidence_knowledge"]]
        self.assertIn("interaction_profile.preferred_verbosity", dims)

    def test_observe_rejects_unknown_provenance(self):
        self.run_cli("observe", "--dimension", "interaction_profile.pace",
                     "--value", "fast", "--source", "explicit_statement",
                     "--provenance", "made_up", expect=2)

    def test_untrusted_provenance_is_reported_as_quarantined(self):
        result = self.run_cli("observe", "--dimension", "interaction_profile.pace",
                              "--value", "fast", "--source", "explicit_statement",
                              "--provenance", "repository_content")
        self.assertTrue(result["quarantined"])
        self.assertIsNone(result["belief"])

    def test_context_reports_mode_and_beliefs(self):
        self.run_cli("observe", "--dimension", "interaction_profile.preferred_verbosity",
                     "--value", "terse", "--source", "explicit_statement",
                     "--provenance", "direct_user_message")
        ctx = self.run_cli("context", "--domain", "software", "--task", "refactor parser",
                           "--mode", "auto")
        self.assertIn(ctx["mode"]["effective"], ("low", "medium", "high"))
        self.assertTrue(any(a["dimension"] == "interaction_profile.preferred_verbosity"
                            for a in ctx["applies"]))
        self.assertTrue(ctx["reminders"])

    def test_context_write_persists_the_projection(self):
        ctx = self.run_cli("context", "--write")
        self.assertTrue((self.home / "runtime_context.json").is_file())
        self.assertIn("_written_to", ctx)

    def test_mode_low_medium_high(self):
        for mode in ("low", "medium", "high"):
            result = self.run_cli("mode", "--mode", mode)
            self.assertEqual(result["mode"], mode)

    def test_plan_respects_budget(self):
        plan = self.run_cli("plan", "--mode", "low")
        self.assertLessEqual(len(plan["questions"]), 3)
        plan = self.run_cli("plan", "--mode", "off")
        self.assertEqual(plan["questions"], [])

    def test_feedback_flow(self):
        result = self.run_cli("feedback", "--kind", "too_complex", "--channel", "explicit",
                              "--project", "demo", "--text", "simplify this")
        self.assertEqual(result["kind"], "too_complex")
        self.assertEqual(result["acceptance"], 0.4)

    def test_feedback_rejects_unknown_kind(self):
        self.run_cli("feedback", "--kind", "vibes", expect=2)

    def test_project_lifecycle(self):
        self.run_cli("project", "init", "--project", "demo", "--name", "Demo",
                     "--domain", "software")
        item = self.run_cli("project", "add", "--project", "demo", "--section", "objectives",
                            "--text", "ship a parser", "--origin", "USER_SAID")
        self.assertEqual(item["origin"], "USER_SAID")
        decision = self.run_cli("project", "decision", "--project", "demo",
                                "--text", "use a recursive descent parser",
                                "--rationale", "simplest thing that works",
                                "--evidence", item["id"])
        self.assertTrue(decision["id"].startswith("dec_"))
        summary = self.run_cli("project", "show", "--project", "demo")
        self.assertEqual(summary["decisions"], 1)
        self.assertEqual(summary["by_origin"]["USER_SAID"], 1)

    def test_project_add_rejects_unknown_section(self):
        self.run_cli("project", "add", "--project", "demo", "--section", "vibes",
                     "--text", "x", expect=2)

    def test_why_explains_a_belief(self):
        self.run_cli("observe", "--dimension", "decision_style.option_breadth",
                     "--value", "one_recommendation", "--source", "explicit_statement",
                     "--provenance", "direct_user_message")
        result = self.run_cli("why", "decision_style.option_breadth")
        self.assertEqual(result["type"], "dimension")
        self.assertTrue(result["result"]["views"])

    def test_reject_and_forget(self):
        self.run_cli("observe", "--dimension", "creative_profile.novelty_seeking",
                     "--value", "novel", "--source", "single_behavioral",
                     "--provenance", "agent_inference")
        self.run_cli("reject", "--dimension", "creative_profile.novelty_seeking",
                     "--value", "novel", "--reason", "not true")
        self.assertEqual(self.confidence("creative_profile.novelty_seeking", "novel"), 0.0)
        self.run_cli("forget", "--dimension", "creative_profile.novelty_seeking")
        self.assertIsNone(self.belief("creative_profile.novelty_seeking"))

    def test_export_and_anonymised_export(self):
        self.run_cli("observe", "--dimension", "interaction_profile.pace", "--value", "fast",
                     "--source", "explicit_statement", "--provenance", "direct_user_message")
        result = self.run_cli("export")
        self.assertGreater(result["bytes"], 0)
        anon = self.run_cli("export", "--anonymise", "--include-events")
        self.assertTrue(anon["anonymised"])

    def test_anonymised_export_never_leaks_short_or_nested_free_text(self):
        secret = "violet comet"
        self.run_cli("observe", "--dimension", "creative_profile.aesthetic_direction",
                     "--value", secret, "--source", "explicit_statement",
                     "--provenance", "direct_user_message", "--note", "private-note-7")
        result = self.run_cli("export", "--anonymise", "--include-events")
        exported = Path(result["path"]).read_text(encoding="utf-8")
        self.assertNotIn(secret, exported)
        self.assertNotIn("private-note-7", exported)
        self.assertIn("<redacted>", exported)

    def test_stats_and_contradictions(self):
        self.run_cli("observe", "--dimension", "creative_profile.simplicity_vs_richness",
                     "--value", "minimal", "--source", "explicit_statement",
                     "--provenance", "direct_user_message")
        self.run_cli("observe", "--dimension", "creative_profile.simplicity_vs_richness",
                     "--value", "feature_rich", "--source", "explicit_statement",
                     "--provenance", "direct_user_message")
        stats = self.run_cli("stats")
        self.assertIn("counters", stats)
        contradictions = self.run_cli("contradictions")
        self.assertTrue(contradictions["contradictions"])

    def test_assume_and_assumptions(self):
        self.run_cli("assume", "using SQLite because nothing said otherwise",
                     "--impact", "medium", "--project", "demo")
        result = self.run_cli("assumptions", "--project", "demo")
        self.assertEqual(len(result["assumptions"]), 1)
        self.assertFalse(result["assumptions"][0]["disclosed"])

    def test_verify_and_rebuild(self):
        self.run_cli("observe", "--dimension", "interaction_profile.pace", "--value", "fast",
                     "--source", "explicit_statement", "--provenance", "direct_user_message")
        verify = self.run_cli("verify")
        self.assertTrue(verify["ok"], verify)
        rebuilt = self.run_cli("rebuild")
        self.assertGreaterEqual(rebuilt["beliefs"], 1)

    def test_constitution_and_schema_commands(self):
        constitution = self.run_cli("constitution")
        self.assertGreaterEqual(constitution["invariant_count"], 15)
        self.assertEqual(len(constitution["hash"]), 64)
        schemas = self.run_cli("schema", "list")
        self.assertIn("user", schemas)

    def test_events_commands(self):
        self.run_cli("observe", "--dimension", "interaction_profile.pace", "--value", "fast",
                     "--source", "explicit_statement", "--provenance", "direct_user_message")
        stats = self.run_cli("events", "stats")
        self.assertGreaterEqual(stats["total_events"], 1)
        verify = self.run_cli("events", "verify")
        self.assertTrue(verify["ok"])
        tail = self.run_cli("events", "tail", "--limit", "5")
        self.assertTrue(tail["events"])

    def test_reset_soft_and_hard(self):
        self.run_cli("observe", "--dimension", "interaction_profile.pace", "--value", "fast",
                     "--source", "explicit_statement", "--provenance", "direct_user_message")
        self.run_cli("reset")
        self.assertIsNone(self.belief("interaction_profile.pace"))
        self.run_cli("reset", "--hard", expect=2)          # refuses without --yes
        result = self.run_cli("reset", "--hard", "--yes")
        self.assertIsNone(self.belief("interaction_profile.pace"))
        backup = __import__("pathlib").Path(result["backup"])
        self.assertTrue((backup / "events").is_dir())
        self.assertTrue((backup / "manifest.json").is_file())

    def test_durable_rollback_and_new_branch(self):
        first = self.run_cli("observe", "--dimension", "interaction_profile.pace",
                             "--value", "fast", "--source", "explicit_statement",
                             "--provenance", "direct_user_message")
        cutoff = self.store.events.latest(1, include_quarantined=True)[0]["ts"]
        self.run_cli("observe", "--dimension", "creative_profile.novelty_seeking",
                     "--value", "novel", "--source", "explicit_statement",
                     "--provenance", "direct_user_message")
        self.run_cli("rollback", "--as-of", cutoff, expect=2)
        result = self.run_cli("rollback", "--as-of", cutoff, "--yes")
        self.assertEqual(result["active_branch"]["kind"], "rollback")
        self.assertIsNotNone(self.belief("interaction_profile.pace", "fast"))
        self.assertIsNone(self.belief("creative_profile.novelty_seeking", "novel"))
        self.run_cli("observe", "--dimension", "decision_style.option_breadth",
                     "--value", "one_recommendation", "--source", "explicit_statement",
                     "--provenance", "direct_user_message")
        self.assertIsNotNone(self.belief("decision_style.option_breadth", "one_recommendation"))
        self.assertEqual(first["kind"], "observation")

    def test_manual_backup_management(self):
        self.run_cli("init", "--allow-in-repo")
        created = self.run_cli("backup", "create")
        self.assertTrue((__import__("pathlib").Path(created["path"]) / "manifest.json").is_file())
        listing = self.run_cli("backup", "list")
        self.assertTrue(any(item["kind"] == "snapshot" for item in listing["backups"]))

    def test_onboarding_via_cli(self):
        self.run_cli("onboarding", "start")
        q = self.run_cli("onboarding", "next")
        self.assertIn("text", q)
        self.run_cli("onboarding", "answer", "--question-id", q["id"], "--text", "an answer",
                     "--observation",
                     json.dumps({"dimension": q["resolves"][0], "value": "something"}))
        state = self.run_cli("onboarding", "status")
        self.assertEqual(state["answered"], 1)

    def test_text_output_is_human_readable(self):
        self.run_cli("observe", "--dimension", "interaction_profile.preferred_verbosity",
                     "--value", "terse", "--source", "explicit_statement",
                     "--provenance", "direct_user_message")
        text = self.run_cli_text("profile")
        self.assertIn("LIWM profile report", text)
        self.assertIn("Caveats", text)

    def test_unknown_command_exits_with_usage(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--home", str(self.home)])
        self.assertEqual(code, 2)

    def test_errors_are_reported_as_json_in_json_mode(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--home", str(self.home), "--json", "why", "--project", "nope",
                         "dec_missing"])
        self.assertEqual(code, 0)
        self.assertIn("type", json.loads(out.getvalue()))


if __name__ == "__main__":
    unittest.main()
