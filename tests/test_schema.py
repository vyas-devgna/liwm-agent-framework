"""JSON Schema validator and the shipped schemas."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from helpers import REPO_ROOT, LiwmTestCase

from liwm.config import DEFAULT_CONFIG
from liwm.migrate import CURRENT_SCHEMA_VERSION, migrate_profile, needs_migration, version_tuple
from liwm.profile import empty_profile
from liwm.schema import SchemaStore, ValidationError, validate, validate_or_raise

SCHEMA_DIR = REPO_ROOT / "schemas"


class TestValidator(unittest.TestCase):
    def test_type_checking(self):
        self.assertEqual(validate("x", {"type": "string"}), [])
        self.assertTrue(validate(5, {"type": "string"}))
        self.assertEqual(validate(5, {"type": ["string", "integer"]}), [])

    def test_booleans_are_not_integers(self):
        self.assertTrue(validate(True, {"type": "integer"}))
        self.assertEqual(validate(True, {"type": "boolean"}), [])

    def test_float_integers_are_accepted(self):
        self.assertEqual(validate(2.0, {"type": "integer"}), [])
        self.assertTrue(validate(2.5, {"type": "integer"}))

    def test_required_and_additional_properties(self):
        schema = {"type": "object", "required": ["a"], "additionalProperties": False,
                  "properties": {"a": {"type": "integer"}}}
        self.assertEqual(validate({"a": 1}, schema), [])
        self.assertTrue(validate({}, schema))
        self.assertTrue(validate({"a": 1, "b": 2}, schema))

    def test_numeric_bounds(self):
        schema = {"type": "number", "minimum": 0, "maximum": 1}
        self.assertEqual(validate(0.5, schema), [])
        self.assertTrue(validate(1.5, schema))
        self.assertTrue(validate(-0.1, schema))

    def test_enum_const_and_pattern(self):
        self.assertEqual(validate("a", {"enum": ["a", "b"]}), [])
        self.assertTrue(validate("c", {"enum": ["a", "b"]}))
        self.assertEqual(validate("x", {"const": "x"}), [])
        self.assertEqual(validate("blf_123", {"pattern": "^blf_"}), [])
        self.assertTrue(validate("nope", {"pattern": "^blf_"}))

    def test_arrays(self):
        schema = {"type": "array", "items": {"type": "integer"}, "minItems": 1,
                  "maxItems": 3, "uniqueItems": True}
        self.assertEqual(validate([1, 2], schema), [])
        self.assertTrue(validate([], schema))
        self.assertTrue(validate([1, 1], schema))
        self.assertTrue(validate([1, 2, 3, 4], schema))

    def test_combinators(self):
        self.assertEqual(validate(3, {"anyOf": [{"type": "string"}, {"type": "integer"}]}), [])
        self.assertTrue(validate(3.5, {"anyOf": [{"type": "string"}, {"type": "integer"}]}))
        self.assertEqual(validate(3, {"oneOf": [{"type": "integer"}, {"type": "string"}]}), [])
        self.assertTrue(validate(3, {"oneOf": [{"type": "integer"}, {"type": "number"}]}))
        self.assertEqual(validate("x", {"not": {"type": "integer"}}), [])

    def test_if_then_else(self):
        schema = {
            "if": {"properties": {"q": {"const": True}}, "required": ["q"]},
            "then": {"required": ["reason"]},
        }
        self.assertTrue(validate({"q": True}, schema))
        self.assertEqual(validate({"q": True, "reason": "x"}, schema), [])
        self.assertEqual(validate({"q": False}, schema), [])

    def test_local_refs_resolve(self):
        schema = {
            "type": "object",
            "properties": {"a": {"$ref": "#/$defs/thing"}},
            "$defs": {"thing": {"type": "string"}},
        }
        self.assertEqual(validate({"a": "x"}, schema), [])
        self.assertTrue(validate({"a": 1}, schema))

    def test_date_time_format(self):
        self.assertEqual(validate("2026-08-20T10:00:00Z", {"format": "date-time"}), [])
        self.assertTrue(validate("yesterday", {"format": "date-time"}))

    def test_error_paths_are_useful(self):
        schema = {"type": "object", "properties": {"a": {"type": "object",
                  "properties": {"b": {"type": "integer"}}}}}
        errors = validate({"a": {"b": "no"}}, schema)
        self.assertEqual(errors[0]["path"], "/a/b")

    def test_validate_or_raise(self):
        with self.assertRaises(ValidationError):
            validate_or_raise({}, {"type": "object", "required": ["x"]}, subject="thing")


class TestShippedSchemas(unittest.TestCase):
    def test_every_schema_is_valid_json_with_an_id(self):
        found = list(SCHEMA_DIR.glob("*.schema.json"))
        self.assertGreaterEqual(len(found), 6)
        for path in found:
            with open(path, "r", encoding="utf-8") as fh:
                schema = json.load(fh)
            self.assertIn("$schema", schema, path.name)
            self.assertIn("title", schema, path.name)
            self.assertIn("type", schema, path.name)

    def test_schema_store_finds_them(self):
        store = SchemaStore()
        available = store.available()
        for name in ("user", "event", "project-intent", "metrics",
                     "runtime-context", "candidate-rule", "personal-strategy", "config"):
            self.assertIn(name, available, name)


class TestSchemaConformance(LiwmTestCase):
    def test_default_config_validates(self):
        self.assertEqual(SchemaStore().validate(DEFAULT_CONFIG, "config"), [])

    def setUp(self):
        super().setUp()
        self.schemas = SchemaStore()

    def test_empty_profile_validates(self):
        self.assertEqual(self.schemas.validate(empty_profile(), "user"), [])

    def test_populated_profile_validates(self):
        self.observe("interaction_profile.preferred_verbosity", "terse")
        self.observe("creative_profile.novelty_seeking", "novel",
                     scope="project", scope_key="p1", project_id="p1", domain="software")
        self.observe("creative_profile.novelty_seeking", "familiar")
        self.store.reject("reasoning_profile.novelty_preference", value="novel")
        errors = self.schemas.validate(self.store.load(), "user")
        self.assertEqual(errors, [], errors[:5])

    def test_invalid_profile_is_rejected(self):
        bad = empty_profile()
        bad["revision"] = -1
        bad["beliefs"] = [{"id": "not_a_belief_id", "scope": "planetary",
                           "dimension": "x", "value": 1, "confidence": 5, "status": "weird"}]
        errors = self.schemas.validate(bad, "user")
        self.assertGreaterEqual(len(errors), 4)

    def test_events_validate(self):
        self.observe("interaction_profile.pace", "fast")
        for event in self.store.events.read_all(include_quarantined=True):
            errors = self.schemas.validate(event, "event")
            self.assertEqual(errors, [], "%s: %s" % (event["kind"], errors[:3]))

    def test_quarantined_event_validates(self):
        event = self.store.events.record(
            "observation", "repository_content",
            observation={"dimension": "interaction_profile.pace", "value": "fast",
                         "source_type": "explicit_statement", "polarity": "support",
                         "scope": "global"},
        )
        self.assertEqual(self.schemas.validate(event, "event"), [])

    def test_runtime_context_validates(self):
        from liwm.context import build_runtime_context

        self.observe("interaction_profile.preferred_verbosity", "terse")
        context = build_runtime_context(self.store, domain="software", task="do a thing")
        errors = self.schemas.validate(context, "runtime-context")
        self.assertEqual(errors, [], errors[:5])

    def test_metrics_validate(self):
        from liwm.metrics import MetricsStore

        self.observe("interaction_profile.pace", "fast")
        metrics = MetricsStore(self.home).refresh(self.store)
        errors = self.schemas.validate(metrics, "metrics")
        self.assertEqual(errors, [], errors[:5])

    def test_project_intent_validates(self):
        from liwm.projects import ProjectStore

        ps = ProjectStore(self.home, "demo")
        ps.add("objectives", "make a thing", "USER_SAID")
        ps.add("anti_goals", "do not make it slow", "AGENT_INFERRED", confidence=0.4)
        errors = self.schemas.validate(ps.load_intent(), "project-intent")
        self.assertEqual(errors, [], errors[:5])

    def test_strategy_validates(self):
        from liwm.strategy import StrategyStore

        store = StrategyStore(self.home)
        strategy, _ = store.apply({"challenge_strength": 0.8}, reason="test")
        errors = self.schemas.validate(strategy, "personal-strategy")
        self.assertEqual(errors, [], errors[:5])


class TestMigration(LiwmTestCase):
    def test_version_comparison(self):
        self.assertEqual(version_tuple("0.1.0"), (0, 1, 0))
        self.assertTrue(needs_migration("0.0.9"))
        self.assertFalse(needs_migration(CURRENT_SCHEMA_VERSION))

    def test_old_version_is_stamped_forward(self):
        profile = empty_profile()
        profile["schema_version"] = "0.0.1"
        migrated, applied = migrate_profile(profile)
        self.assertEqual(migrated["schema_version"], CURRENT_SCHEMA_VERSION)
        self.assertTrue(applied)

    def test_migrate_home_reports_and_rebuilds(self):
        from liwm.migrate import migrate_home

        self.observe("interaction_profile.pace", "fast")
        profile = self.store.load()
        profile["schema_version"] = "0.0.1"
        self.store.save(profile)
        report = migrate_home(self.home, store=self.store)
        self.assertTrue(report["migrated"])
        self.assertEqual(self.store.load()["schema_version"], CURRENT_SCHEMA_VERSION)

    def test_unknown_dimension_is_quarantined_not_stored(self):
        """The taxonomy is an allowlist; unvetted dimensions cannot enter."""
        event = self.store.events.record(
            "observation", "direct_user_message",
            observation={"dimension": "interaction_profile.made_up_thing", "value": "x",
                         "source_type": "explicit_statement", "polarity": "support",
                         "scope": "global"},
        )
        self.assertTrue(event["quarantined"])
        self.assertIn("unknown_dimension", event["quarantine_reason"])
        self.store.rebuild(reason="test")
        self.assertIsNone(self.belief("interaction_profile.made_up_thing"))

    def test_open_namespaces_accept_free_form_leaves(self):
        self.observe("preferences.prefers_sqlite_over_postgres", True)
        self.assertIsNotNone(self.belief("preferences.prefers_sqlite_over_postgres"))
        self.observe("domain_fluency.rust", "high")
        self.assertIsNotNone(self.belief("domain_fluency.rust"))


if __name__ == "__main__":
    unittest.main()
