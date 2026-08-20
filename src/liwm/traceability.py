"""Answering "why did you do that?" from records, not reconstruction.

A model asked to justify a past choice will produce a fluent, plausible story
whether or not that story is what happened.  The only defence is to have written
the reasoning down at the time, with identifiers, and to answer from the file.

This module walks the chain in either direction::

    user evidence -> inferred belief -> decision -> artifact -> feedback -> update

Everything it returns is quoted from stored events, project decisions and the
folded profile.  Where a link is missing, it says so rather than filling the gap.
"""

from __future__ import annotations

from .privacy import redact

__all__ = ["explain_belief", "explain_decision", "explain_dimension", "why", "recent_assumptions"]


def _event_summary(event):
    obs = event.get("observation") or {}
    return {
        "event_id": event.get("event_id"),
        "at": event.get("ts"),
        "kind": event.get("kind"),
        "provenance": event.get("provenance"),
        "source_type": obs.get("source_type"),
        "polarity": obs.get("polarity"),
        "scope": obs.get("scope"),
        "scope_key": obs.get("scope_key"),
        "session_id": event.get("session_id"),
        "project_id": event.get("project_id"),
        "quote": redact(obs.get("note") or (event.get("payload") or {}).get("answer")
                        or (event.get("payload") or {}).get("text")),
        "quarantined": event.get("quarantined", False),
        "quarantine_reason": event.get("quarantine_reason"),
    }


def explain_belief(store, belief_id=None, dimension=None, value=None):
    """Full provenance of one belief."""
    profile = store.load()
    beliefs = profile.get("beliefs", [])

    belief = None
    if belief_id:
        belief = next((b for b in beliefs if b["id"] == belief_id), None)
    if belief is None and dimension:
        candidates = [b for b in beliefs if b["dimension"] == dimension]
        if value is not None:
            candidates = [b for b in candidates if str(b["value"]) == str(value)]
        candidates.sort(key=lambda b: -b["confidence"])
        belief = candidates[0] if candidates else None
    if belief is None:
        return None

    refs = set(belief.get("evidence_refs", []))
    suppressed_refs = set(belief.get("suppressed_evidence_refs", []))
    supporting, opposing, ignored = [], [], []
    for event in store.events.iter_events(include_quarantined=True):
        obs = event.get("observation") or {}
        summary = _event_summary(event)
        if event.get("event_id") in suppressed_refs:
            ignored.append(summary)
        elif event.get("event_id") in refs:
            (supporting if obs.get("polarity", "support") == "support" else opposing).append(summary)
        elif event.get("quarantined") and obs.get("dimension") == belief["dimension"]:
            scope = obs.get("scope", "global")
            scope_key = obs.get("scope_key") or (
                event.get("project_id") if scope == "project" else
                event.get("domain") if scope == "domain" else None
            )
            if scope == belief["scope"] and scope_key == belief.get("scope_key"):
                ignored.append(summary)

    return {
        "belief": {
            "id": belief["id"],
            "dimension": belief["dimension"],
            "value": belief["value"],
            "confidence": belief["confidence"],
            "scope": belief["scope"],
            "scope_key": belief.get("scope_key"),
            "origin": belief.get("origin"),
            "status": belief.get("status"),
            "first_seen": belief["first_seen"],
            "last_seen": belief["last_seen"],
            "source_types": belief["source_types"],
            "ceiling": belief.get("ceiling"),
            "limiting_factor": belief.get("limiting_factor"),
        },
        "confidence_explanation": _confidence_sentence(belief),
        "supporting_evidence": supporting[-12:],
        "opposing_evidence": opposing[-8:],
        "ignored_evidence": ignored[-6:],
        "ignored_note": (
            "%d observation(s) touched this dimension but were quarantined - untrusted "
            "provenance or a privacy refusal. They contributed nothing." % len(ignored)
            if ignored else None
        ),
        "promoted_from": belief.get("promoted_from"),
        "promotion_reason": belief.get("promotion_reason"),
        "referenced_events": sorted(refs)[:12],
    }


def _confidence_sentence(belief):
    limiting = belief.get("limiting_factor", "")
    if belief.get("rejected_by_user"):
        return ("Confidence is zero because you explicitly rejected this. Only a direct "
                "statement or correction from you can revive it.")
    if belief.get("origin") == "promoted":
        return ("Confidence %.2f is a discounted promotion: %s"
                % (belief["confidence"], belief.get("promotion_reason", "cross-scope evidence")))
    if limiting.startswith("ceiling:"):
        source = limiting.split(":", 1)[1]
        return ("Confidence %.2f is capped by the strongest evidence type available (%s). "
                "More of the same kind of signal cannot raise it further; a direct "
                "statement from you would."
                % (belief["confidence"], source))
    return ("Confidence %.2f from %d supporting and %d contradicting observation(s) across "
            "%s." % (belief["confidence"], belief.get("evidence_count", 0),
                     belief.get("contradiction_count", 0),
                     ", ".join(belief.get("source_types", [])) or "no sources"))


def explain_decision(store, decision_id, project_id=None):
    """What a recorded decision rested on, and how it turned out."""
    from .projects import ProjectStore

    project_ids = [project_id] if project_id else store.load().get("projects_seen", [])
    for pid in project_ids:
        ps = ProjectStore(store.home, pid)
        # A project can have recorded decisions before anyone wrote down its
        # intent, so absence of intent.json must not hide the decision log.
        if not (ps.decisions_path.is_file() or ps.exists()):
            continue
        for entry in ps.load_decisions().get("decisions", []):
            if entry["id"] != decision_id:
                continue
            intent = ps.load_intent()
            basis = []
            for ref in entry.get("basis", []):
                if str(ref).startswith("blf_"):
                    detail = explain_belief(store, belief_id=ref)
                    basis.append({"type": "belief", "ref": ref,
                                  "detail": detail["belief"] if detail else "not found"})
                elif str(ref).startswith("itm_"):
                    item = _find_intent_item(intent, ref)
                    basis.append({"type": "intent", "ref": ref, "detail": item or "not found"})
                elif str(ref).startswith("evt_"):
                    event = next((e for e in store.events.iter_events(include_quarantined=True)
                                  if e.get("event_id") == ref), None)
                    basis.append({"type": "event", "ref": ref,
                                  "detail": _event_summary(event) if event else "not found"})
                else:
                    basis.append({"type": "other", "ref": ref})
            feedback = [f for f in ps.load_feedback().get("feedback", [])
                        if f.get("decision_id") == decision_id]
            return {
                "decision": entry,
                "project_id": pid,
                "basis_detail": basis,
                "feedback": feedback,
                "outcome": entry.get("outcome"),
                "completeness": (
                    "fully traced" if entry.get("basis")
                    and all(row.get("detail") != "not found" for row in basis) else
                    "no basis was recorded at decision time; this explanation is therefore "
                    "incomplete rather than reconstructed" if not entry.get("basis") else
                    "some recorded basis references could not be resolved; this explanation "
                    "is incomplete rather than reconstructed"
                ),
            }
    return None


def _find_intent_item(intent, item_id):
    from .projects import INTENT_SECTIONS
    for section in INTENT_SECTIONS:
        for item in intent.get(section, []):
            if item.get("id") == item_id:
                out = dict(item)
                out["section"] = section
                return out
    return None


def explain_dimension(store, dimension):
    """Every scope's view of one dimension, side by side."""
    profile = store.load()
    rows = [b for b in profile.get("beliefs", []) if b["dimension"] == dimension]
    rows.sort(key=lambda b: (b["scope"], -b["confidence"]))
    return {
        "dimension": dimension,
        "views": [
            {
                "scope": b["scope"],
                "scope_key": b.get("scope_key"),
                "value": b["value"],
                "confidence": b["confidence"],
                "status": b.get("status"),
                "origin": b.get("origin"),
                "last_seen": b["last_seen"],
                "belief_id": b["id"],
            }
            for b in rows
        ],
        "contradictions": [c for c in profile.get("contradictions", [])
                           if c["dimension"] == dimension],
        "note": ("Narrower scope wins for work in that scope. A project value does not "
                 "override the global one anywhere else."),
    }


def recent_assumptions(store, project_id=None, limit=10):
    """Assumptions LIWM acted on, and whether they were disclosed (C07)."""
    out = []
    for event in store.events.iter_events(kinds={"assumption_made"}, project_id=project_id):
        payload = event.get("payload") or {}
        out.append({
            "event_id": event.get("event_id"),
            "at": event.get("ts"),
            "assumption": payload.get("assumption"),
            "reversible": payload.get("reversible"),
            "impact": payload.get("impact"),
            "disclosed": payload.get("disclosed", False),
            "basis": payload.get("basis", []),
            "project_id": event.get("project_id"),
        })
    return out[-limit:]


def why(store, query=None, belief_id=None, decision_id=None, dimension=None, project_id=None):
    """Dispatch to the right explanation for whatever the user pointed at."""
    if decision_id or (query or "").startswith("dec_"):
        return {"type": "decision",
                "result": explain_decision(store, decision_id or query, project_id=project_id)}
    if belief_id or (query or "").startswith("blf_"):
        return {"type": "belief", "result": explain_belief(store, belief_id=belief_id or query)}
    target = dimension or query
    if target and "." in str(target):
        return {"type": "dimension", "result": explain_dimension(store, target)}
    if target:
        profile = store.load()
        matches = [b["dimension"] for b in profile.get("beliefs", [])
                   if str(target).lower() in b["dimension"].lower()]
        if matches:
            return {"type": "dimension", "result": explain_dimension(store, matches[0]),
                    "other_matches": sorted(set(matches))[1:6]}
    return {"type": "assumptions", "result": recent_assumptions(store, project_id=project_id)}
