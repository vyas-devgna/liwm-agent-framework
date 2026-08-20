from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path

import helpers  # noqa: F401 - adds src/ to sys.path

from liwm.cli import main  # noqa: E402
from liwm.config import ConfigStore  # noqa: E402
from liwm.integration import MalformedBootstrap, remove_bootstrap, upsert_bootstrap  # noqa: E402
from liwm.profile import ProfileStore  # noqa: E402


BLOCK = """<!-- LIWM:BEGIN v0.1.0 -->
LIWM test block.
<!-- LIWM:END -->
"""


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="liwm-config-")
        self.home = Path(self.tmp.name)
        self.run_cli("init", "--allow-in-repo")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([*args, "--home", str(self.home), "--json"])
        self.assertEqual(code, 0, err.getvalue() or out.getvalue())
        return json.loads(out.getvalue())

    def test_init_persists_config_and_preserves_unknown_fields(self):
        path = self.home / "config.json"
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        data["future_extension"] = {"kept": True}
        path.write_text(json.dumps(data), encoding="utf-8")
        ConfigStore(self.home).set("default_mode", "low")
        self.assertTrue(ConfigStore(self.home).load()["future_extension"]["kept"])

    def test_off_removes_profile_projection_and_learning(self):
        ProfileStore(self.home).observe(
            "interaction_profile.preferred_verbosity", "terse",
            source_type="explicit_statement", provenance="direct_user_message",
        )
        self.run_cli("config", "set", "--key", "enabled", "--value", "false")
        context = self.run_cli("context", "--domain", "software")
        self.assertEqual(context["mode"]["effective"], "off")
        self.assertEqual(context["applies"], [])
        self.assertFalse(context["learning_enabled"])

        before = len(ProfileStore(self.home).events.read_all(include_quarantined=True))
        result = self.run_cli(
            "observe", "--dimension", "interaction_profile.pace", "--value", "fast",
            "--source", "explicit_statement", "--provenance", "direct_user_message",
        )
        after = len(ProfileStore(self.home).events.read_all(include_quarantined=True))
        self.assertTrue(result["skipped"])
        self.assertEqual(before, after)

    def test_off_plan_and_mode_ask_nothing(self):
        self.run_cli("config", "set", "--key", "enabled", "--value", "false")
        plan = self.run_cli("plan", "--mode", "auto")
        mode = self.run_cli("mode", "--mode", "auto")
        self.assertEqual(plan["questions"], [])
        self.assertEqual(mode["mode"], "off")

    def test_global_flags_work_after_subcommand(self):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["profile", "--home", str(self.home), "--json"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIsInstance(json.loads(out.getvalue()), dict)


class TestBootstrapEditing(unittest.TestCase):
    def test_install_is_idempotent_and_preserves_persona(self):
        persona = "# My instructions\n\nKeep this byte-for-byte.\n"
        once = upsert_bootstrap(persona, BLOCK)
        twice = upsert_bootstrap(once, BLOCK)
        self.assertEqual(once, twice)
        self.assertTrue(once.startswith(persona))
        self.assertEqual(once.count("<!-- LIWM:BEGIN"), 1)

    def test_update_replaces_only_block(self):
        original = "before\n" + BLOCK + "after\n"
        replacement = BLOCK.replace("test block", "updated block")
        result = upsert_bootstrap(original, replacement)
        self.assertTrue(result.startswith("before\n"))
        self.assertTrue(result.endswith("after\n"))
        self.assertIn("updated block", result)

    def test_uninstall_restores_unrelated_text(self):
        persona = "before\n\nafter\n"
        installed = upsert_bootstrap(persona, BLOCK)
        self.assertEqual(remove_bootstrap(installed), persona)

    def test_malformed_markers_stop(self):
        with self.assertRaises(MalformedBootstrap):
            upsert_bootstrap("persona\n<!-- LIWM:BEGIN v0.1.0 -->\n", BLOCK)


if __name__ == "__main__":
    unittest.main()
