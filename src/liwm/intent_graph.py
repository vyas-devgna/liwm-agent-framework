"""Compact, event-derived intent state graph.

The graph is a compatible sidecar to ``user.json``.  Nodes and edges are
immutable events; ``intent-graph.json`` is only a rebuildable projection.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from .evidence import (
    PROVENANCE_TRUST, SOURCE_CEILINGS, SINGLE_OBSERVATION_CLAMP, recency_factor,
)
from .events import EventStore, SCHEMA_VERSION
from .invalidation import invalidated_event_ids
from .jsonio import FileLock, utc_now_ms, write_json_atomic
from .privacy import screen_observation

__all__ = ["EDGE_TYPES", "NODE_TYPES", "IntentGraphStore"]

NODE_TYPES = frozenset({
    "goal", "anti_goal", "preference", "constraint", "value",
    "desired_experience", "rejected_direction", "uncertainty", "assumption",
    "decision", "outcome", "artifact", "intent_hypothesis",
})
EDGE_TYPES = frozenset({
    "supports", "conflicts_with", "conditional_on", "implies", "derived_from",
    "motivates", "rejects", "supersedes", "predicts", "validated_by",
    "falsified_by", "implemented_by", "applies_in", "transfers_to",
})
SCOPES = frozenset({"global", "domain", "project", "session"})
STATUSES = frozenset({
    "active", "hypothesis", "validated", "falsified", "superseded", "rejected",
})
DECAY_POLICIES = frozenset({"none", "slow", "standard", "volatile", "session"})

#: Edges that change the state of an element rather than merely describing it.
#: The value is ``(endpoint, resulting status)``: ``supersedes`` acts on its
#: target, ``falsified_by`` on its source.  Every other edge type is
#: descriptive, and deliberately stays that way - an opaque inference engine
#: would cost the inspectability that is the point of a graph.
STATE_EDGES = {
    "falsified_by": ("source", "falsified"),
    "validated_by": ("source", "validated"),
    "supersedes": ("target", "superseded"),
    "rejects": ("target", "rejected"),
}

_PROVENANCE_CEILINGS = {
    "direct_user_message": SINGLE_OBSERVATION_CLAMP,
    "direct_user_edit": 0.92,
    "explicit_user_review": 0.98,
    "onboarding_answer": 0.70,
    "agent_inference": 0.15,
}


def _id(prefix):
    return "%s_%s" % (prefix, uuid.uuid4().hex[:16])


def _provenance_ceiling(provenance):
    if PROVENANCE_TRUST.get(provenance, 0.0) <= 0.0:
        return 0.0
    return _PROVENANCE_CEILINGS.get(provenance, 0.0)


def _event_ceiling(event):
    observation = event.get("observation") or {}
    if observation:
        return min(
            _provenance_ceiling(event.get("provenance")),
            SOURCE_CEILINGS.get(observation.get("source_type"), 0.0),
        )
    element = (event.get("payload") or {}).get("element") or {}
    if event.get("kind") in {"intent_node", "intent_edge"} and element:
        return min(
            _provenance_ceiling(event.get("provenance")),
            float(element.get("confidence", 0.0)),
        )
    return _provenance_ceiling(event.get("provenance"))


def _summary(event):
    return {
        "id": event.get("event_id"), "kind": event.get("kind"), "ts": event.get("ts"),
        "provenance": event.get("provenance"),
        "confidence_ceiling": _event_ceiling(event),
        "quarantined": bool(event.get("quarantined")),
        "quarantine_reason": event.get("quarantine_reason"),
    }


class IntentGraphStore:
    """Append graph events and materialise a compact JSON-native graph."""

    def __init__(self, home):
        self.home = Path(home)
        self.events = EventStore(self.home)
        self.path = self.home / "intent-graph.json"
        self.lock_path = self.home / ".intent-graph.lock"

    def add_node(self, node_type, label, provenance, confidence, *, value=None,
                 scope="global", scope_key=None, evidence_refs=None, status="active",
                 decay_policy="standard", node_id=None, session_id=None,
                 project_id=None, domain=None):
        """Record one node, quarantining rather than folding unsafe derivations."""
        self._validate_common(node_type, NODE_TYPES, label, provenance, confidence,
                              scope, scope_key, status, decay_policy)
        screen_observation(value=value, text=label, strict=True)
        refs = list(dict.fromkeys(evidence_refs or []))
        snapshot, event_index = self._snapshot_and_events()
        resolved, problems = self._resolve_refs(refs, snapshot, event_index)
        if provenance == "agent_inference" and not refs:
            problems.append("inference_requires_evidence")
        ceiling = min([_provenance_ceiling(provenance)] +
                      [row["confidence_ceiling"] for row in resolved])
        now = utc_now_ms()
        element = {
            "id": node_id or _id("ign"), "type": node_type, "label": label,
            "value": value, "scope": scope, "scope_key": scope_key,
            "requested_confidence": float(confidence),
            "confidence": min(float(confidence), ceiling),
            "confidence_ceiling": ceiling, "evidence_refs": refs,
            "created_at": now, "updated_at": now, "provenance": provenance,
            "provenance_chain": self._provenance_chain(provenance, resolved),
            "status": status, "decay_policy": decay_policy,
        }
        self._validate_id(element["id"], "ign")
        event = self.events.record(
            "intent_node", provenance, payload={"element": element}, ts=now,
            session_id=session_id, project_id=project_id, domain=domain,
            derived_from=[row["provenance"] for row in resolved],
            quarantine_reason=";".join(problems) if problems else None,
        )
        self.rebuild()
        return event, element

    def add_edge(self, edge_type, source, target, provenance, confidence, *,
                 scope="global", scope_key=None, evidence_refs=None, status="active",
                 decay_policy="standard", edge_id=None, session_id=None,
                 project_id=None, domain=None):
        """Record an edge whose endpoints and evidence must already resolve."""
        self._validate_common(edge_type, EDGE_TYPES, edge_type, provenance, confidence,
                              scope, scope_key, status, decay_policy)
        refs = list(dict.fromkeys([source, target] + list(evidence_refs or [])))
        snapshot, event_index = self._snapshot_and_events()
        resolved, problems = self._resolve_refs(refs, snapshot, event_index)
        for endpoint in (source, target):
            if not any(row["id"] == endpoint and row["kind"] == "node" for row in resolved):
                problems.append("endpoint_not_active_node:%s" % endpoint)
        ceiling = min([_provenance_ceiling(provenance)] +
                      [row["confidence_ceiling"] for row in resolved])
        now = utc_now_ms()
        element = {
            "id": edge_id or _id("ige"), "type": edge_type,
            "source": source, "target": target, "scope": scope, "scope_key": scope_key,
            "requested_confidence": float(confidence),
            "confidence": min(float(confidence), ceiling),
            "confidence_ceiling": ceiling,
            "evidence_refs": list(dict.fromkeys(evidence_refs or [])),
            "created_at": now, "updated_at": now, "provenance": provenance,
            "provenance_chain": self._provenance_chain(provenance, resolved),
            "status": status, "decay_policy": decay_policy,
        }
        self._validate_id(element["id"], "ige")
        event = self.events.record(
            "intent_edge", provenance, payload={"element": element}, ts=now,
            session_id=session_id, project_id=project_id, domain=domain,
            derived_from=[row["provenance"] for row in resolved],
            quarantine_reason=";".join(dict.fromkeys(problems)) if problems else None,
        )
        self.rebuild()
        return event, element

    def graph(self, *, scope=None, scope_key=None, include_quarantined=False,
              include_inactive=False, now=None):
        graph = self._materialize(now=now)
        if scope is not None or scope_key is not None:
            def matches(row):
                return ((scope is None or row["scope"] == scope) and
                        (scope_key is None or row.get("scope_key") == scope_key))
            graph["nodes"] = [row for row in graph["nodes"] if matches(row)]
            node_ids = {row["id"] for row in graph["nodes"]}
            graph["edges"] = [row for row in graph["edges"] if matches(row) and
                              row["source"] in node_ids and row["target"] in node_ids]
        if not include_quarantined:
            graph.pop("quarantined", None)
        if not include_inactive:
            graph.pop("inactive", None)
        return graph

    def rebuild(self):
        with FileLock(self.lock_path, timeout=30.0):
            graph = self._materialize()
            write_json_atomic(self.path, graph)
        return graph

    def explain(self, element_id, history=False):
        """Explain one active element.

        Elements the user forgot are not active state, so by default asking
        about one fails the same way asking about a deleted belief does.
        ``history=True`` is the audit path: the events themselves are immutable
        and remain inspectable, but a normal explanation honours the tombstone
        rather than reading around it.
        """
        graph = self._materialize()
        index = self._element_index(graph)
        element = index.get(element_id) or self._historical(graph, element_id, history)
        event_index = self._event_index()
        invalidated = invalidated_event_ids(list(event_index.values()))
        basis = []
        for ref in element.get("evidence_refs", []):
            if ref in index:
                basis.append({"kind": "graph_element", "active": True,
                              "element": index[ref]})
            elif ref in event_index:
                basis.append({"kind": "event", "active": ref not in invalidated,
                              "forgotten": ref in invalidated,
                              "event": _summary(event_index[ref])})
            else:
                basis.append({"kind": "unresolved", "active": False, "id": ref})
        result = {"element": element, "basis": basis,
                  "active": element_id in index}
        if element_id.startswith("ign_"):
            result["incoming_edges"] = [e for e in graph["edges"] if e["target"] == element_id]
            result["outgoing_edges"] = [e for e in graph["edges"] if e["source"] == element_id]
        return result

    def trace(self, element_id, history=False):
        graph = self._materialize()
        index = self._element_index(graph)
        if element_id not in index:
            self._historical(graph, element_id, history)
        event_index = self._event_index()
        invalidated = invalidated_event_ids(list(event_index.values()))
        nodes, edges, evidence, unresolved, seen = {}, {}, {}, set(), set()
        incoming = {}
        for edge in graph["edges"]:
            incoming.setdefault(edge["target"], []).append(edge)

        def visit(ref):
            if ref in seen:
                return
            seen.add(ref)
            if ref in event_index and ref not in index:
                evidence[ref] = dict(_summary(event_index[ref]),
                                     forgotten=ref in invalidated)
                return
            element = index.get(ref)
            if element is None:
                unresolved.add(ref)
                return
            target = nodes if ref.startswith("ign_") else edges
            target[ref] = element
            for evidence_ref in element.get("evidence_refs", []):
                visit(evidence_ref)
            if ref.startswith("ign_"):
                for edge in incoming.get(ref, []):
                    visit(edge["id"])
            else:
                visit(element["source"])
                visit(element["target"])

        visit(element_id)
        return {
            "root": element_id, "nodes": list(nodes.values()), "edges": list(edges.values()),
            "evidence_events": list(evidence.values()), "unresolved_refs": sorted(unresolved),
            "active": element_id in index,
        }

    def _historical(self, graph, element_id, history):
        """The recorded form of an element that is not in the active graph."""
        row = next((row for row in graph.get("inactive") or []
                    if row["id"] == element_id), None)
        if row is None:
            raise KeyError("intent graph element %s not found" % element_id)
        if not history:
            raise KeyError(
                "intent graph element %s is no longer active state (%s); pass "
                "history to inspect the retained audit record" % (element_id, row["reason"])
            )
        event = next((event for event in self.events.iter_events(
            kinds={"intent_node", "intent_edge"}, include_quarantined=True)
            if ((event.get("payload") or {}).get("element") or {}).get("id") == element_id), None)
        element = dict((event.get("payload") or {}).get("element") or {}) if event else {}
        element["active"] = False
        element["inactive_reason"] = row["reason"]
        return element

    def _snapshot_and_events(self):
        return self._materialize(), self._event_index()

    def _invalidated(self, event_index):
        return invalidated_event_ids(list(event_index.values()))

    def _event_index(self):
        events = self._active_branch(list(
            self.events.iter_events(include_quarantined=True)
        ))
        return {event["event_id"]: event for event in events}

    @staticmethod
    def _element_index(graph):
        return {row["id"]: row for row in graph["nodes"] + graph["edges"]}

    def _resolve_refs(self, refs, graph, event_index):
        elements = self._element_index(graph)
        quarantined_ids = {row.get("id") for row in graph.get("quarantined", [])}
        resolved, problems = [], []
        for ref in refs:
            if ref in elements:
                element = elements[ref]
                resolved.append({
                    "id": ref, "kind": "node" if ref.startswith("ign_") else "edge",
                    "provenance": element["provenance"],
                    "provenance_chain": element.get("provenance_chain", []),
                    "confidence_ceiling": element["confidence"],
                })
            elif ref in event_index:
                event = event_index[ref]
                if ref in self._invalidated(event_index):
                    problems.append("forgotten_evidence:%s" % ref)
                if event.get("quarantined") or _event_ceiling(event) <= 0.0:
                    problems.append("tainted_evidence:%s" % ref)
                resolved.append({
                    "id": ref, "kind": "event", "provenance": event.get("provenance"),
                    "provenance_chain": [event.get("provenance")] +
                                        list(event.get("derived_from") or []),
                    "confidence_ceiling": _event_ceiling(event),
                })
            elif ref in quarantined_ids:
                problems.append("tainted_evidence:%s" % ref)
            else:
                problems.append("unresolved_evidence:%s" % ref)
        return resolved, problems

    def _materialize(self, now=None):
        """Project the event log into the graph the user is entitled to see.

        Four passes, in order, each answering one question:

        1. *Was this element validly recorded?*  Structure, provenance and
           confidence inheritance, unchanged - the immutable record.
        2. *Does it still have a basis?*  A ``forget`` tombstone invalidates the
           evidence beneath it, and an element whose whole basis is gone is no
           longer active state.  Without this pass, deleting a preference from
           ``user.json`` left it standing here.
        3. *What is it worth now?*  Recorded confidence is what the evidence
           supported on the day it was recorded.  Effective confidence applies
           the same decay the profile applies, and can never exceed the
           effective confidence of what it stands on.
        4. *What state is it in?*  A handful of edge types are claims about
           status rather than descriptions of it.
        """
        nodes, edges, quarantined, seen = [], [], [], set()
        elements = {}
        origin = {}
        all_events = self._active_branch(list(
            self.events.iter_events(include_quarantined=True)
        ))
        event_index = {event["event_id"]: event for event in all_events}
        invalidated = invalidated_event_ids(all_events)
        events = [event for event in all_events
                  if event.get("kind") in {"intent_node", "intent_edge"}]
        for event in events:
            element = dict((event.get("payload") or {}).get("element") or {})
            element_id = element.get("id")
            reason = event.get("quarantine_reason") if event.get("quarantined") else None
            expected = "ign" if event.get("kind") == "intent_node" else "ige"
            if not isinstance(element_id, str) or not element_id.startswith(expected + "_"):
                reason = reason or "invalid_element_id"
            elif element_id in seen:
                reason = reason or "duplicate_element_id"
            else:
                reason = reason or self._element_issue(element, event, elements, event_index)
            if reason:
                quarantined.append({
                    "id": element_id, "event_id": event.get("event_id"),
                    "kind": event.get("kind"), "reason": reason,
                })
                if element_id:
                    seen.add(element_id)
                continue
            seen.add(element_id)
            if event.get("kind") == "intent_node":
                nodes.append(element)
            else:
                edges.append(element)
            elements[element_id] = element
            origin[element_id] = event

        inactive = self._forget_pass(elements, origin, invalidated)
        active = [element for element_id, element in elements.items()
                  if element_id not in inactive]
        as_of = now or utc_now_ms()
        self._confidence_pass(active, elements, event_index, as_of)
        self._status_pass(active)
        active_ids = {element["id"] for element in active}
        return {
            "schema_version": SCHEMA_VERSION, "generated_at": utc_now_ms(),
            "as_of": as_of,
            "nodes": [row for row in nodes if row["id"] in active_ids],
            "edges": [row for row in edges if row["id"] in active_ids],
            "quarantined": quarantined,
            "inactive": [{"id": element_id, "kind": origin[element_id].get("kind"),
                          "event_id": origin[element_id].get("event_id"),
                          "reason": reason}
                         for element_id, reason in inactive.items()],
            "source_event_count": len(events),
        }

    @staticmethod
    def _forget_pass(elements, origin, invalidated):
        """Element ids the user's tombstones removed from active state.

        An element is inactive when the event that recorded it was forgotten,
        when every piece of evidence it stands on was forgotten, or - for an
        edge - when either endpoint is inactive.  An element resting on nothing
        was never derived from the forgotten evidence, so it survives; that is
        the same rule the fold applies to a belief with independent support.
        """
        inactive = {}

        def refs_of(element):
            refs = list(element.get("evidence_refs") or [])
            if "source" in element:
                refs = [element["source"], element["target"]] + refs
            return refs

        for element_id, element in elements.items():
            if origin[element_id].get("event_id") in invalidated:
                inactive[element_id] = "forgotten_evidence"

        changed = True
        while changed:
            changed = False
            for element_id, element in elements.items():
                if element_id in inactive:
                    continue
                if "source" in element and (element["source"] in inactive
                                            or element["target"] in inactive):
                    inactive[element_id] = "endpoint_inactive"
                    changed = True
                    continue
                refs = refs_of(element)
                if refs and all(ref in invalidated or ref in inactive for ref in refs):
                    inactive[element_id] = "forgotten_basis"
                    changed = True
        return inactive

    @staticmethod
    def _confidence_pass(active, elements, event_index, as_of):
        """Attach decayed, evidence-bounded confidence without touching the record.

        ``confidence`` and ``confidence_ceiling`` stay exactly as the immutable
        event recorded them.  The effective pair is what any consumer deciding
        how much to believe should read, and it uses the profile's own decay
        curve so the two projections cannot drift into disagreeing about how
        stale the same fact is.
        """
        effective = {}
        for element in active:
            policy = element.get("decay_policy", "standard")
            recorded = float(element.get("confidence", 0.0))
            ceilings = [float(element.get("confidence_ceiling", 0.0))]
            refs = list(element.get("evidence_refs") or [])
            if "source" in element:
                refs = [element["source"], element["target"]] + refs
            for ref in refs:
                if ref in effective:
                    ceilings.append(effective[ref])
                elif ref in elements:
                    ceilings.append(0.0)   # inactive basis contributes nothing
                elif ref in event_index:
                    # Evidence ages on its own clock, not the element's. A node
                    # pinned at decay_policy "none" must not freeze the
                    # observation it rests on along with itself.
                    referenced = event_index[ref]
                    ref_policy = (referenced.get("observation") or {}).get(
                        "decay_policy") or policy
                    ceilings.append(_event_ceiling(referenced) * recency_factor(
                        referenced.get("ts"), ref_policy, now=as_of))
            ceiling = min(ceilings)
            value = min(recorded * recency_factor(
                element.get("updated_at"), policy, now=as_of), ceiling)
            element["recorded_confidence"] = recorded
            element["recorded_ceiling"] = float(element.get("confidence_ceiling", 0.0))
            element["effective_ceiling"] = round(ceiling, 4)
            element["effective_confidence"] = round(max(0.0, value), 4)
            effective[element["id"]] = element["effective_confidence"]

    @staticmethod
    def _status_pass(active):
        """Let the four state-changing edge types actually change state.

        A ``falsified_by`` edge that leaves its hypothesis "active" is
        decoration.  The guard is that an edge may not overrule an element it is
        weaker than: an agent inference capped at 0.15 cannot retire something
        the user said directly, however many edges it draws.
        """
        index = {element["id"]: element for element in active}
        for element in active:
            element["recorded_status"] = element.get("status")
            element.setdefault("status_reason", None)
        for edge in active:
            rule = STATE_EDGES.get(edge.get("type")) if "source" in edge else None
            if rule is None:
                continue
            endpoint, status = rule
            target = index.get(edge[endpoint])
            if target is None:
                continue
            if edge["effective_confidence"] + 1e-12 < target["effective_confidence"]:
                edge["status_reason"] = "too weak to change %s (%.3f < %.3f)" % (
                    target["id"], edge["effective_confidence"],
                    target["effective_confidence"])
                continue
            target["status"] = status
            target["status_reason"] = "%s by %s" % (status, edge["id"])

    @staticmethod
    def _active_branch(events):
        """Apply the same reset/rollback branch markers as the profile fold."""
        marker = next((event for event in reversed(events)
                       if not event.get("quarantined") and
                       event.get("kind") in {"reset", "rollback"}), None)
        if marker is None:
            return events
        marker_sequence = int(marker.get("sequence") or 0)
        if marker.get("kind") == "reset":
            return [event for event in events
                    if int(event.get("sequence") or 0) >= marker_sequence]
        payload = marker.get("payload") or {}
        cutoff_sequence = payload.get("cutoff_sequence")
        if cutoff_sequence is None:
            cutoff = payload.get("cutoff", "")
            cutoff_sequence = max(
                (int(event.get("sequence") or 0) for event in events
                 if int(event.get("sequence") or 0) < marker_sequence and
                 event.get("ts", "") <= cutoff),
                default=0,
            )
        return [event for event in events if (
            int(event.get("sequence") or 0) <= int(cutoff_sequence) or
            int(event.get("sequence") or 0) >= marker_sequence
        )]

    @staticmethod
    def _element_issue(element, event, elements, event_index):
        is_node = event.get("kind") == "intent_node"
        required = {
            "id", "type", "scope", "scope_key", "requested_confidence", "confidence",
            "confidence_ceiling", "evidence_refs", "created_at", "updated_at",
            "provenance", "provenance_chain", "status", "decay_policy",
        }
        if is_node:
            required |= {"label", "value"}
        else:
            required |= {"source", "target"}
        if not required.issubset(element):
            return "missing_element_fields"
        allowed = NODE_TYPES if is_node else EDGE_TYPES
        if element.get("type") not in allowed:
            return "invalid_element_type"
        if is_node and (not isinstance(element.get("label"), str) or
                        not element["label"].strip()):
            return "invalid_label"
        if element.get("provenance") != event.get("provenance"):
            return "provenance_mismatch"
        if element.get("scope") not in SCOPES or (
                element.get("scope") != "global" and not element.get("scope_key")):
            return "invalid_scope"
        if element.get("status") not in STATUSES:
            return "invalid_status"
        if element.get("decay_policy") not in DECAY_POLICIES:
            return "invalid_decay_policy"
        if not isinstance(element.get("evidence_refs"), list):
            return "invalid_evidence_refs"
        try:
            requested = float(element["requested_confidence"])
            confidence = float(element["confidence"])
            recorded_ceiling = float(element["confidence_ceiling"])
        except (TypeError, ValueError):
            return "invalid_confidence"
        if not all(0.0 <= value <= 1.0
                   for value in (requested, confidence, recorded_ceiling)):
            return "invalid_confidence"

        refs = list(element["evidence_refs"])
        if not is_node:
            source, target = element.get("source"), element.get("target")
            if not (isinstance(source, str) and source.startswith("ign_") and
                    isinstance(target, str) and target.startswith("ign_")):
                return "invalid_endpoint"
            if source not in elements or target not in elements:
                return "unresolved_endpoint"
            refs = [source, target] + refs
        if is_node and element.get("provenance") == "agent_inference" and not refs:
            return "inference_requires_evidence"

        ceilings = [_provenance_ceiling(element.get("provenance"))]
        for ref in refs:
            if ref in elements:
                ceilings.append(float(elements[ref].get("confidence", 0.0)))
                continue
            referenced = event_index.get(ref)
            if referenced is None:
                return "unresolved_evidence:%s" % ref
            if int(referenced.get("sequence") or 0) >= int(event.get("sequence") or 0):
                return "future_evidence:%s" % ref
            ceiling = _event_ceiling(referenced)
            if referenced.get("quarantined") or ceiling <= 0.0:
                return "tainted_evidence:%s" % ref
            ceilings.append(ceiling)
        inherited_ceiling = min(ceilings)
        if confidence > requested + 1e-12 or confidence > inherited_ceiling + 1e-12:
            return "confidence_exceeds_evidence_ceiling"
        if recorded_ceiling > inherited_ceiling + 1e-12:
            return "invalid_confidence_ceiling"
        return None

    @staticmethod
    def _provenance_chain(provenance, resolved):
        chain = [provenance]
        for row in resolved:
            chain.extend(row.get("provenance_chain") or [row["provenance"]])
        return list(dict.fromkeys(chain))

    @staticmethod
    def _validate_id(value, prefix):
        if not isinstance(value, str) or not value.startswith(prefix + "_") or len(value) < 12:
            raise ValueError("invalid %s id" % prefix)

    @staticmethod
    def _validate_common(kind, allowed, label, provenance, confidence, scope, scope_key,
                         status, decay_policy):
        if kind not in allowed:
            raise ValueError("unknown intent graph type %r" % kind)
        if not isinstance(label, str) or not label.strip():
            raise ValueError("label must be a non-empty string")
        if provenance not in PROVENANCE_TRUST:
            raise ValueError("unknown provenance %r" % provenance)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence must be a number from 0 to 1") from exc
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be a number from 0 to 1")
        if scope not in SCOPES:
            raise ValueError("unknown scope %r" % scope)
        if scope != "global" and not scope_key:
            raise ValueError("scope_key is required for %s scope" % scope)
        if status not in STATUSES:
            raise ValueError("unknown status %r" % status)
        if decay_policy not in DECAY_POLICIES:
            raise ValueError("unknown decay policy %r" % decay_policy)
