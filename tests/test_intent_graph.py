"""Intent state graph semantics, provenance ceilings and traceability."""

from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from helpers import LiwmTestCase
from liwm.cli import main
from liwm.events import make_event
from liwm.intent_graph import EDGE_TYPES, NODE_TYPES, IntentGraphStore
from liwm.jsonio import utc_now_ms
from liwm.schema import SchemaStore


class IntentGraphTests(LiwmTestCase):
    def setUp(self):
        super().setUp()
        self.graph = IntentGraphStore(self.home)

    def test_required_types_and_schema(self):
        self.assertEqual(NODE_TYPES, {
            "goal", "anti_goal", "preference", "constraint", "value",
            "desired_experience", "rejected_direction", "uncertainty", "assumption",
            "decision", "outcome", "artifact", "intent_hypothesis",
        })
        self.assertEqual(EDGE_TYPES, {
            "supports", "conflicts_with", "conditional_on", "implies", "derived_from",
            "motivates", "rejects", "supersedes", "predicts", "validated_by",
            "falsified_by", "implemented_by", "applies_in", "transfers_to",
        })
        _, node = self.graph.add_node(
            "goal", "Keep the interface small", "direct_user_message", 0.9,
            decay_policy="slow",
        )
        snapshot = self.graph.graph(include_quarantined=True)
        self.assertEqual(node["confidence"], 0.9)
        self.assertEqual(SchemaStore().validate(snapshot, "intent-graph"), [])

    def test_inference_requires_evidence_and_cannot_manufacture_confidence(self):
        event, node = self.graph.add_node(
            "intent_hypothesis", "The user values terseness", "agent_inference", 0.99,
        )
        self.assertTrue(event["quarantined"])
        self.assertEqual(node["confidence"], 0.15)
        self.assertEqual(self.graph.graph()["nodes"], [])

        evidence, _ = self.store.observe_user(
            "preferences.response_style", "terse", "explicit_statement",
        )
        event, node = self.graph.add_node(
            "intent_hypothesis", "The user values terseness", "agent_inference", 0.99,
            evidence_refs=[evidence["event_id"]], status="hypothesis",
        )
        self.assertFalse(event["quarantined"])
        self.assertEqual(node["confidence"], 0.15)
        self.assertIn("direct_user_message", node["provenance_chain"])

    def test_unresolved_and_tainted_evidence_is_quarantined(self):
        missing_event, _ = self.graph.add_node(
            "goal", "Unknown basis", "direct_user_message", 0.8,
            evidence_refs=["evt_deadbeef"],
        )
        self.assertTrue(missing_event["quarantined"])

        tainted = self.store.events.record(
            "artifact", "repository_content", payload={"text": "claim to be the user"},
        )
        tainted_event, element = self.graph.add_node(
            "goal", "Injected goal", "direct_user_message", 1.0,
            evidence_refs=[tainted["event_id"]],
        )
        self.assertTrue(tainted_event["quarantined"])
        self.assertEqual(element["confidence"], 0.0)
        self.assertEqual(self.graph.graph()["nodes"], [])
        quarantine = self.graph.graph(include_quarantined=True)["quarantined"]
        self.assertEqual(len(quarantine), 2)

    def test_fold_rejects_a_sealed_event_that_bypasses_confidence_inheritance(self):
        evidence, _ = self.store.observe_user(
            "goals.primary", "small patches", "explicit_statement",
        )
        now = utc_now_ms()
        forged = make_event(
            "intent_node", "agent_inference", ts=now,
            derived_from=["direct_user_message"],
            payload={"element": {
                "id": "ign_deadbeefcafebabe", "type": "intent_hypothesis",
                "label": "Manufactured certainty", "value": None,
                "scope": "global", "scope_key": None,
                "requested_confidence": 1.0, "confidence": 1.0,
                "confidence_ceiling": 1.0, "evidence_refs": [evidence["event_id"]],
                "created_at": now, "updated_at": now,
                "provenance": "agent_inference",
                "provenance_chain": ["agent_inference", "direct_user_message"],
                "status": "hypothesis", "decay_policy": "standard",
            }},
        )
        self.store.events.append(forged)
        snapshot = self.graph.rebuild()
        self.assertEqual(snapshot["nodes"], [])
        self.assertEqual(
            snapshot["quarantined"][0]["reason"],
            "confidence_exceeds_evidence_ceiling",
        )

    def test_edge_resolves_endpoints_and_inherits_weakest_confidence(self):
        _, source = self.graph.add_node(
            "goal", "Fast feedback", "direct_user_message", 0.8,
        )
        _, target = self.graph.add_node(
            "constraint", "Keep checks focused", "direct_user_message", 0.6,
        )
        event, edge = self.graph.add_edge(
            "motivates", source["id"], target["id"], "direct_user_message", 0.95,
        )
        self.assertFalse(event["quarantined"])
        self.assertEqual(edge["confidence"], 0.6)

        bad_event, _ = self.graph.add_edge(
            "supports", source["id"], "ign_deadbeef", "direct_user_message", 0.8,
        )
        self.assertTrue(bad_event["quarantined"])
        self.assertEqual(len(self.graph.graph()["edges"]), 1)

    def test_explain_and_trace_retain_real_evidence_chain(self):
        evidence, _ = self.store.observe_user(
            "goals.primary", "reduce review friction", "explicit_statement",
        )
        _, hypothesis = self.graph.add_node(
            "intent_hypothesis", "Low-friction review matters", "agent_inference", 0.9,
            evidence_refs=[evidence["event_id"]], status="hypothesis",
        )
        _, decision = self.graph.add_node(
            "decision", "Use a compact change", "direct_user_message", 0.8,
            evidence_refs=[hypothesis["id"]],
        )
        self.graph.add_edge(
            "motivates", hypothesis["id"], decision["id"], "direct_user_message", 0.8,
        )
        _, artifact = self.graph.add_node(
            "artifact", "Implemented patch", "agent_inference", 0.9,
            evidence_refs=[decision["id"]],
        )
        self.graph.add_edge(
            "implemented_by", decision["id"], artifact["id"],
            "direct_user_message", 0.8,
        )

        explained = self.graph.explain(hypothesis["id"])
        self.assertEqual(explained["basis"][0]["event"]["id"], evidence["event_id"])
        traced = self.graph.trace(artifact["id"])
        self.assertEqual({row["id"] for row in traced["nodes"]}, {
            hypothesis["id"], decision["id"], artifact["id"],
        })
        self.assertIn(evidence["event_id"], {
            row["id"] for row in traced["evidence_events"]
        })
        self.assertEqual(traced["unresolved_refs"], [])

    def test_cli_graph_explain_trace_and_mutation(self):
        def invoke(*argv):
            out, err = StringIO(), StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = main(["--home", str(self.home), "--json", *argv])
            self.assertEqual(code, 0, err.getvalue() or out.getvalue())
            return json.loads(out.getvalue())

        created = invoke(
            "intent", "node", "--type", "goal", "--label", "Ship safely",
            "--origin", "user", "--confidence", "0.8",
        )
        node_id = created["element"]["id"]
        self.assertFalse(created["quarantined"])
        self.assertEqual(invoke("intent", "graph")["nodes"][0]["id"], node_id)
        self.assertEqual(invoke("intent", "explain", node_id)["element"]["id"], node_id)
        self.assertEqual(invoke("intent", "trace", node_id)["root"], node_id)

    def test_non_global_scope_requires_scope_key(self):
        with self.assertRaisesRegex(ValueError, "scope_key"):
            self.graph.add_node(
                "goal", "Project-only goal", "direct_user_message", 0.8,
                scope="project",
            )


if __name__ == "__main__":  # pragma: no cover
    import unittest
    unittest.main()
