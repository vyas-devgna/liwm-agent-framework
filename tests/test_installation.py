from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import helpers  # noqa: F401 - adds src/ to sys.path

from liwm.cli import main
from liwm.installation import (
    InstallationError, apply_plan, create_install_plan, create_uninstall_plan,
    load_plan, save_plan, verify_plan, _finish_plan,
)
from liwm.schema import SchemaStore


BLOCK = """<!-- LIWM:BEGIN v0.2.0 -->
Use `liwm context` before non-trivial work.
<!-- LIWM:END -->
"""


class TestInstallationLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="liwm-install-")
        self.root = Path(self.tmp.name)
        self.home = self.root / "liwm-home"
        self.home.mkdir()
        self.instructions = self.root / "agent" / "AGENTS.md"
        self.instructions.parent.mkdir()
        self.instructions.write_bytes(b"# Persona\r\n\r\nKeep this.\r\n")
        self.skills = self.root / "agent" / "skills"
        self.source = self.root / "source-skills"
        (self.source / "liwm").mkdir(parents=True)
        (self.source / "liwm" / "SKILL.md").write_text("new skill\n", encoding="utf-8")
        (self.skills / "liwm").mkdir(parents=True)
        (self.skills / "liwm" / "SKILL.md").write_text("old skill\n", encoding="utf-8")
        (self.home / "hosts.json").write_text(json.dumps({"hosts": [{
            "id": "test-host", "name": "Test host",
            "global_instruction_file": str(self.instructions),
            "skills_path": str(self.skills),
            "capabilities": {"skills": True}
        }]}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_deterministic_round_trip_with_backup_and_idempotence(self):
        before = self.instructions.read_bytes()
        first = create_install_plan("test-host", self.home, BLOCK, self.source)
        second = create_install_plan("test-host", self.home, BLOCK, self.source)
        self.assertEqual(first, second)
        self.assertEqual(SchemaStore().validate(first, "install-plan"), [])
        path = self.root / "install-plan.json"
        save_plan(first, path)
        installed = apply_plan(load_plan(path))
        self.assertTrue(installed["ok"])
        self.assertEqual(installed["changed"], 2)
        self.assertIn(b"LIWM:BEGIN", self.instructions.read_bytes())
        self.assertIn(b"\r\n", self.instructions.read_bytes())
        self.assertEqual((self.skills / "liwm" / "SKILL.md").read_text(), "new skill\n")
        self.assertEqual(apply_plan(first)["changed"], 0)
        self.assertTrue(verify_plan(first)["ok"])

        removal = create_uninstall_plan("test-host", self.home)
        self.assertTrue(apply_plan(removal)["ok"])
        self.assertEqual(self.instructions.read_bytes(), before)
        self.assertEqual((self.skills / "liwm" / "SKILL.md").read_text(), "old skill\n")
        self.assertFalse((self.home / "installations" / "test-host.json").exists())

    def test_apply_refuses_precondition_drift_before_writing(self):
        plan = create_install_plan("test-host", self.home, BLOCK, self.source,
                                   include_skills=False)
        self.instructions.write_bytes(self.instructions.read_bytes() + b"drift\r\n")
        drifted = self.instructions.read_bytes()
        with self.assertRaises(InstallationError):
            apply_plan(plan)
        self.assertEqual(self.instructions.read_bytes(), drifted)

    def test_forged_plan_cannot_target_unrelated_file(self):
        victim = self.root / "victim.txt"
        victim.write_text("keep", encoding="utf-8")
        plan = create_install_plan("test-host", self.home, BLOCK, include_skills=False)
        plan["steps"][0]["target"] = str(victim)
        plan = _finish_plan(plan)
        with self.assertRaises(InstallationError):
            apply_plan(plan)
        self.assertEqual(victim.read_text(), "keep")

    def test_receipt_failure_rolls_back_target(self):
        before = self.instructions.read_bytes()
        (self.home / "installations").write_text("not a directory", encoding="utf-8")
        plan = create_install_plan("test-host", self.home, BLOCK, include_skills=False)
        with self.assertRaises(OSError):
            apply_plan(plan)
        self.assertEqual(self.instructions.read_bytes(), before)

    def test_update_preserves_first_install_uninstall_baseline(self):
        before_instructions = self.instructions.read_bytes()
        before_skill = (self.skills / "liwm" / "SKILL.md").read_bytes()
        apply_plan(create_install_plan("test-host", self.home, BLOCK, self.source))
        (self.source / "liwm" / "SKILL.md").write_text("newer skill\n", encoding="utf-8")
        updated = BLOCK.replace("Use `liwm context`", "Consult `liwm context`")
        apply_plan(create_install_plan("test-host", self.home, updated, self.source))
        apply_plan(create_uninstall_plan("test-host", self.home))
        self.assertEqual(self.instructions.read_bytes(), before_instructions)
        self.assertEqual((self.skills / "liwm" / "SKILL.md").read_bytes(), before_skill)

    def test_malformed_markers_fail_during_plan(self):
        self.instructions.write_text("<!-- LIWM:BEGIN v0.1.0 -->\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            create_install_plan("test-host", self.home, BLOCK, include_skills=False)

    def test_uninstall_removes_instruction_file_created_by_install(self):
        self.instructions.unlink()
        plan = create_install_plan("test-host", self.home, BLOCK, include_skills=False)
        apply_plan(plan)
        self.assertTrue(self.instructions.is_file())
        apply_plan(create_uninstall_plan("test-host", self.home))
        self.assertFalse(self.instructions.exists())

    def test_apply_preserves_existing_file_mode_and_refuses_symlinks(self):
        if os.name != "nt":
            self.instructions.chmod(0o640)
            apply_plan(create_install_plan(
                "test-host", self.home, BLOCK, include_skills=False
            ))
            self.assertEqual(stat.S_IMODE(self.instructions.stat().st_mode), 0o640)
        link = self.root / "linked.md"
        try:
            link.symlink_to(self.instructions)
        except OSError:
            self.skipTest("symlinks unavailable")
        (self.home / "hosts.json").write_text(json.dumps({"hosts": [{
            "id": "linked-host", "name": "Linked",
            "global_instruction_file": str(link)
        }]}), encoding="utf-8")
        with self.assertRaises(InstallationError):
            create_install_plan("linked-host", self.home, BLOCK, include_skills=False)

    def test_cli_plan_apply_verify_and_uninstall(self):
        block = self.root / "block.md"
        block.write_text(BLOCK, encoding="utf-8")
        plan_path = self.root / "plan.json"
        planned = self.run_cli(
            "install", "plan", "--host", "test-host", "--block", str(block),
            "--no-skills", "--output", str(plan_path),
        )
        self.assertEqual(planned["plan_file"], str(plan_path))
        self.run_cli("install", "apply", "--plan", str(plan_path))
        self.assertTrue(self.run_cli("install", "verify", "--plan", str(plan_path))["ok"])
        removal_path = self.root / "remove.json"
        self.run_cli(
            "uninstall", "plan", "--host", "test-host", "--output", str(removal_path)
        )
        self.run_cli("uninstall", "apply", "--plan", str(removal_path))
        self.assertNotIn("LIWM:BEGIN", self.instructions.read_text(encoding="utf-8"))

    def run_cli(self, *args):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([*args, "--home", str(self.home), "--json"])
        self.assertEqual(code, 0, err.getvalue() or out.getvalue())
        return json.loads(out.getvalue())


if __name__ == "__main__":
    unittest.main()
