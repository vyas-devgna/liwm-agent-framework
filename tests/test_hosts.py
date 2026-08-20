"""Host registry: portability, detection honesty, and budget arithmetic.

The claim these tests defend is "LIWM works with any agent that reads a Markdown
file at startup". That claim is only worth making if adding a host requires no
code change, if detection never overstates what it knows, and if LIWM refuses to
overflow an instruction budget that belongs to the user.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest

from helpers import LiwmTestCase

from liwm.hosts import (
    BUILTIN_HOSTS,
    check_budget,
    config_dir_for,
    detect_hosts,
    get_host,
    installation_plan,
    instruction_file_for,
    load_registry,
    skills_dir_for,
)
from liwm.integration import remove_bootstrap, upsert_bootstrap


def _tmp(*parts):
    """A throwaway absolute path, spelled the way this platform spells one."""
    return str(pathlib.Path(tempfile.gettempdir(), *parts))


def _expect(*parts):
    """The absolute path the resolver should produce for :func:`_tmp`."""
    return pathlib.Path(tempfile.gettempdir(), *parts).expanduser().absolute()



class TestRegistryShape(unittest.TestCase):
    def test_every_builtin_host_is_well_formed(self):
        seen = set()
        for spec in BUILTIN_HOSTS:
            self.assertTrue(spec["id"], "every host needs an id")
            self.assertNotIn(spec["id"], seen, "host ids must be unique")
            seen.add(spec["id"])
            self.assertTrue(spec["name"])
            self.assertTrue(spec["docs"], "%s: a host claim needs a citable source"
                            % spec["id"])
            self.assertTrue(
                instruction_file_for(spec) or spec["project_instruction_files"],
                "%s: a host LIWM cannot write to anywhere is not a host" % spec["id"],
            )

    def test_a_host_without_skills_is_not_promised_progressive_disclosure(self):
        for spec in BUILTIN_HOSTS:
            caps = spec["capabilities"]
            if not caps.get("skills"):
                self.assertFalse(
                    caps.get("progressive_disclosure"),
                    "%s cannot disclose progressively without a skills mechanism"
                    % spec["id"],
                )

    def test_claude_code_hook_context_injection_is_recorded_as_unavailable(self):
        """A design that depended on this would silently do nothing."""
        spec = get_host("claude-code")
        self.assertFalse(spec["capabilities"]["hook_injects_context"])


class TestPathResolution(unittest.TestCase):
    def tearDown(self):
        for name in ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "OPENCODE_CONFIG_DIR"):
            os.environ.pop(name, None)

    def test_env_override_relocates_the_host_home(self):
        os.environ["CODEX_HOME"] = _tmp("codex-elsewhere")
        spec = get_host("codex")
        self.assertEqual(instruction_file_for(spec),
                         _expect("codex-elsewhere", "AGENTS.md"))
        self.assertEqual(config_dir_for(spec), _expect("codex-elsewhere"))

    def test_a_nested_config_dir_is_relocated_whole(self):
        """The override replaces the whole config dir, not just its last segment.

        opencode's default is ``~/.config/opencode``. Deriving the tail from the
        displayed template used to leave a stray ``opencode/`` segment under the
        override, which pointed the installer at a file that does not exist.
        """
        os.environ["OPENCODE_CONFIG_DIR"] = _tmp("oc")
        self.assertEqual(instruction_file_for(get_host("opencode")),
                         _expect("oc", "AGENTS.md"))

    def test_a_multi_segment_instruction_path_survives_relocation(self):
        spec = dict(get_host("windsurf"))
        spec["home_env"] = "OPENCODE_CONFIG_DIR"  # any override variable will do
        os.environ["OPENCODE_CONFIG_DIR"] = _tmp("ws")
        self.assertEqual(instruction_file_for(spec),
                         _expect("ws", "memories", "global_rules.md"))

    def test_codex_skills_live_outside_its_config_dir(self):
        """~/.agents/skills is cross-vendor and is not moved by CODEX_HOME.

        Deriving it from the config directory would send the installer to
        $CODEX_HOME/skills, which Codex never reads.
        """
        os.environ["CODEX_HOME"] = _tmp("codex-elsewhere")
        self.assertEqual(skills_dir_for(get_host("codex")),
                         pathlib.Path.home() / ".agents" / "skills")

    def test_claude_skills_move_with_the_config_dir(self):
        os.environ["CLAUDE_CONFIG_DIR"] = _tmp("cc")
        self.assertEqual(skills_dir_for(get_host("claude-code")), _expect("cc", "skills"))
        self.assertEqual(instruction_file_for(get_host("claude-code")),
                         _expect("cc", "CLAUDE.md"))

    def test_a_host_without_skills_has_no_skills_directory(self):
        self.assertIsNone(skills_dir_for(get_host("gemini-cli")))

    def test_paths_are_absolute_and_tilde_expanded(self):
        resolved = instruction_file_for(get_host("claude-code"))
        self.assertTrue(resolved.is_absolute())
        self.assertNotIn("~", str(resolved))

    def test_a_host_with_no_user_level_file_resolves_to_none(self):
        self.assertIsNone(instruction_file_for(get_host("cursor")))

    def test_a_user_supplied_absolute_path_is_taken_as_given(self):
        """A user naming a specific file must not have it relocated under them."""
        spec = {"id": "x", "global_instruction_file": _tmp("explicit", "RULES.md")}
        self.assertEqual(instruction_file_for(spec), _expect("explicit", "RULES.md"))


class TestUserExtensibility(LiwmTestCase):
    """The universality claim rests entirely on this working."""

    def _write_overlay(self, payload):
        (self.home / "hosts.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_a_new_host_needs_no_code_change(self):
        self._write_overlay({"hosts": [{
            "id": "my-agent",
            "name": "My Agent",
            "global_instruction_file": str(self.home / "myagent" / "INSTRUCTIONS.md"),
            "project_instruction_files": ["AGENTS.md"],
        }]})
        spec = get_host("my-agent", self.home)
        self.assertIsNotNone(spec)
        self.assertEqual(spec["source"], "user-defined")
        self.assertEqual(spec["confidence"], "user-supplied")
        ids = [row["id"] for row in detect_hosts(self.home)]
        self.assertIn("my-agent", ids)

    def test_a_user_can_correct_one_field_of_a_builtin(self):
        """When a vendor moves a path, a user must not have to wait for a release."""
        self._write_overlay({"hosts": [
            {"id": "codex", "global_instruction_file": "~/.codex/MOVED.md"}]})
        spec = get_host("codex", self.home)
        self.assertEqual(instruction_file_for(spec),
                         pathlib.Path.home() / ".codex" / "MOVED.md",
                         "the correction must win over the built-in derived path")
        self.assertEqual(spec["name"], "Codex CLI", "unstated fields survive the merge")
        self.assertEqual(spec["source"], "user-override")

    def test_an_override_can_move_the_file_out_of_the_config_dir(self):
        """The override is a path, not a filename inside the vendor's directory."""
        self._write_overlay({"hosts": [
            {"id": "claude-code", "global_instruction_file": _tmp("elsewhere", "RULES.md")}]})
        self.assertEqual(instruction_file_for(get_host("claude-code", self.home)),
                         _expect("elsewhere", "RULES.md"))

    def test_a_malformed_overlay_is_ignored_rather_than_fatal(self):
        (self.home / "hosts.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(len(load_registry(self.home)), len(BUILTIN_HOSTS))

    def test_an_overlay_entry_without_an_id_is_skipped(self):
        self._write_overlay({"hosts": [{"name": "nameless"}, "not-a-dict"]})
        self.assertEqual(len(load_registry(self.home)), len(BUILTIN_HOSTS))


class TestDetectionHonesty(LiwmTestCase):
    def test_detection_reports_the_evidence_it_used(self):
        target = self.home / "fakehost" / "INSTRUCTIONS.md"
        target.parent.mkdir(parents=True)
        target.write_text("hello\n", encoding="utf-8")
        (self.home / "hosts.json").write_text(json.dumps({"hosts": [{
            "id": "fakehost", "name": "Fake",
            "config_dir": str(self.home / "fakehost"),
            "global_instruction_file": str(target),
        }]}), encoding="utf-8")

        row = next(r for r in detect_hosts(self.home) if r["id"] == "fakehost")
        self.assertTrue(row["detected"])
        self.assertTrue(row["evidence"], "detection must say what it saw")
        self.assertTrue(any("exists" in e for e in row["evidence"]))

    def test_an_absent_host_is_reported_absent_with_no_evidence(self):
        (self.home / "hosts.json").write_text(json.dumps({"hosts": [{
            "id": "ghost", "name": "Ghost",
            "global_instruction_file": str(self.home / "nope" / "X.md"),
        }]}), encoding="utf-8")
        row = next(r for r in detect_hosts(self.home) if r["id"] == "ghost")
        self.assertFalse(row["detected"])
        self.assertEqual(row["evidence"], [])

    def test_installed_state_is_read_from_the_marker_not_assumed(self):
        target = self.home / "h" / "I.md"
        target.parent.mkdir(parents=True)
        target.write_text("# my own instructions\n", encoding="utf-8")
        (self.home / "hosts.json").write_text(json.dumps({"hosts": [{
            "id": "h", "name": "H", "global_instruction_file": str(target)}]}),
            encoding="utf-8")

        row = next(r for r in detect_hosts(self.home) if r["id"] == "h")
        self.assertTrue(row["detected"])
        self.assertFalse(row["liwm_installed"])

        block = "<!-- LIWM:BEGIN v0.1.0 -->\nx\n<!-- LIWM:END -->\n"
        target.write_text(upsert_bootstrap(target.read_text(encoding="utf-8"), block),
                          encoding="utf-8")
        row = next(r for r in detect_hosts(self.home) if r["id"] == "h")
        self.assertTrue(row["liwm_installed"])

        target.write_text(remove_bootstrap(target.read_text(encoding="utf-8")),
                          encoding="utf-8")
        self.assertEqual(target.read_text(encoding="utf-8"), "# my own instructions\n",
                         "uninstall must be byte-exact")


class TestBudgets(unittest.TestCase):
    def test_a_host_with_no_documented_limit_is_never_reported_over_budget(self):
        spec = get_host("claude-code")
        result = check_budget(spec, "x" * 100000)
        self.assertTrue(result["within_budget"])
        self.assertIsNone(result["headroom_bytes"])

    def test_the_users_existing_content_counts_against_the_budget(self):
        """LIWM must not be the reason a user's own rules get truncated."""
        spec = get_host("windsurf")
        self.assertEqual(spec["instruction_budget_bytes"], 6000)
        result = check_budget(spec, "x" * 500, existing_text="y" * 5800)
        self.assertFalse(result["within_budget"])
        self.assertLess(result["headroom_bytes"], 0)

    def test_the_compact_block_fits_the_tightest_documented_budget(self):
        from pathlib import Path as _Path

        root = _Path(__file__).resolve().parents[1]
        compact = (root / "adapters" / "blocks" / "compact.md").read_text(encoding="utf-8")
        spec = get_host("windsurf")
        result = check_budget(spec, compact)
        self.assertTrue(result["within_budget"])
        self.assertGreater(result["headroom_bytes"], 5000,
                           "the block must leave the user most of their own budget")


class TestInstallationPlan(LiwmTestCase):
    def test_the_plan_pairs_every_edit_of_an_existing_file_with_a_backup(self):
        target = self.home / "h" / "I.md"
        target.parent.mkdir(parents=True)
        target.write_text("existing\n", encoding="utf-8")
        (self.home / "hosts.json").write_text(json.dumps({"hosts": [{
            "id": "h", "name": "H", "global_instruction_file": str(target)}]}),
            encoding="utf-8")

        plan = installation_plan("h", home=self.home, block_text="block")
        actions = [step["action"] for step in plan["steps"]]
        self.assertEqual(actions[0], "backup",
                         "nothing is edited before it is backed up")
        self.assertIn("upsert_block", actions)
        self.assertTrue(plan["reversible"])

    def test_a_file_that_does_not_exist_yet_needs_no_backup(self):
        (self.home / "hosts.json").write_text(json.dumps({"hosts": [{
            "id": "h", "name": "H",
            "global_instruction_file": str(self.home / "h" / "new.md")}]}),
            encoding="utf-8")
        plan = installation_plan("h", home=self.home, block_text="block")
        self.assertNotIn("backup", [s["action"] for s in plan["steps"]])

    def test_a_host_with_no_editable_file_plans_a_manual_step(self):
        plan = installation_plan("cursor", home=self.home, block_text="block")
        self.assertEqual([s["action"] for s in plan["steps"]], ["manual"])
        self.assertIn("paste", plan["steps"][0]["detail"])

    def test_skill_capable_hosts_plan_a_skills_step(self):
        plan = installation_plan("claude-code", home=self.home, block_text="block")
        self.assertIn("link_skills", [s["action"] for s in plan["steps"]])

    def test_an_unknown_host_yields_no_plan_rather_than_a_guess(self):
        self.assertIsNone(installation_plan("no-such-host", home=self.home))


if __name__ == "__main__":
    unittest.main()
