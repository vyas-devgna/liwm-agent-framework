"""Project intent: what this particular piece of work is actually for.

Kept rigorously separate from the personal profile.  A project can demand
"extremely conservative" without that ever becoming "this person is
conservative" (constitution C06).

Every intent item carries an ``origin``:

* ``USER_SAID``      - the user stated it, in their own words
* ``AGENT_INFERRED`` - LIWM concluded it from what the user said or chose
* ``AGENT_DERIVED``  - LIWM computed it from the environment, code, or an
                       earlier decision

That distinction is the backbone of ``liwm why``.  It never collapses: an
inference does not become a statement because it turned out to be right.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from .jsonio import (
    FileLock, backup_file, lifecycle_lock_path, read_json_resilient, utc_now,
    write_json_atomic,
)

__all__ = [
    "ORIGINS",
    "INTENT_SECTIONS",
    "ProjectStore",
    "empty_intent",
    "slugify_project",
    "validate_project_id",
]

SCHEMA_VERSION = "0.3.0"

ORIGINS = ("USER_SAID", "AGENT_INFERRED", "AGENT_DERIVED")

#: Every list-shaped section of an intent document.
INTENT_SECTIONS = (
    "objectives",
    "latent_objectives",
    "desired_experience",
    "anti_goals",
    "non_negotiables",
    "preferences",
    "constraints",
    "technical_constraints",
    "inspirations",
    "rejected_directions",
    "emotional_targets",
    "assumptions",
    "open_questions",
    "implementation_implications",
)

_STAGES = ("inception", "design", "build", "refine", "debug", "maintenance", "unknown")


def slugify_project(name_or_path):
    """Stable, filesystem-safe project id from a name or absolute path."""
    raw = str(name_or_path or "").strip()
    if not raw:
        return "project"
    is_path = "/" in raw or "\\" in raw
    base = Path(raw).name if is_path else raw
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", base).strip("-._").lower()
    slug = slug or "project"
    if is_path:
        normalised = str(Path(raw).expanduser().absolute()).casefold()
        slug += "-" + hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:8]
    return slug


def validate_project_id(project_id):
    value = str(project_id or "")
    if not value or value in {".", ".."} or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", value):
        raise ValueError("project_id must be a safe identifier, not a path")
    return value


def empty_intent(project_id, name=None, domain=None):
    now = utc_now()
    doc = {
        "schema_version": SCHEMA_VERSION,
        "project_id": project_id,
        "name": name or project_id,
        "domain": domain,
        "stage": "inception",
        "revision": 0,
        "created_at": now,
        "updated_at": now,
        "confidence": {
            "overall_intent": 0.0,
            "basis": "no evidence recorded yet",
        },
        "contradictions": [],
        "decision_consequences": [],
    }
    for section in INTENT_SECTIONS:
        doc[section] = []
    return doc


def _item(text, origin, **kwargs):
    from .privacy import screen_observation

    if origin not in ORIGINS:
        raise ValueError("origin must be one of %s, got %r" % (", ".join(ORIGINS), origin))
    screen_observation(text=text, strict=True)
    confidence = kwargs.pop("confidence", None)
    if confidence is None:
        # A statement is taken at face value; an inference starts as a guess.
        confidence = 1.0 if origin == "USER_SAID" else 0.4
    item = {
        "id": "itm_%s" % uuid.uuid4().hex[:12],
        "text": text,
        "origin": origin,
        "provenance": kwargs.pop("provenance", {
            "USER_SAID": "direct_user_message",
            "AGENT_INFERRED": "agent_inference",
            "AGENT_DERIVED": "tool_output",
        }[origin]),
        "confidence": float(confidence),
        "status": kwargs.pop("status", "active"),
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "evidence_refs": list(kwargs.pop("evidence_refs", []) or []),
        "belief_refs": list(kwargs.pop("belief_refs", []) or []),
        "derived_from": list(kwargs.pop("derived_from", []) or []),
    }
    item.update(kwargs)
    return item


class ProjectStore:
    """Intent, decisions and feedback for one project."""

    def __init__(self, home, project_id):
        self.home = Path(home)
        self.project_id = validate_project_id(project_id)
        root = (self.home / "projects").resolve()
        self.dir = root / self.project_id
        try:
            self.dir.resolve().relative_to(root)
        except ValueError as exc:
            raise ValueError("project directory escapes LIWM home") from exc
        self.intent_path = self.dir / "intent.json"
        self.decisions_path = self.dir / "decisions.json"
        self.feedback_path = self.dir / "feedback.json"
        self.lock_path = self.dir / ".lock"
        self.backups = self.home / "backups"
        self.logs = self.home / "logs"

    # -- intent ------------------------------------------------------------
    def load_intent(self, name=None, domain=None):
        data, _ = read_json_resilient(
            self.intent_path, backups_dir=self.backups, logs_dir=self.logs
        )
        if not data:
            data = empty_intent(self.project_id, name=name, domain=domain)
        return data

    def save_intent(self, doc):
        with FileLock(lifecycle_lock_path(self.home)):
            with FileLock(self.lock_path):
                return self._save_intent_locked(doc)

    def _save_intent_locked(self, doc):
        backup_file(self.intent_path, self.backups, tag="intent")
        doc = dict(doc)
        doc["revision"] = int(doc.get("revision", 0)) + 1
        doc["updated_at"] = utc_now()
        doc["confidence"] = _intent_confidence(doc)
        doc["contradictions"] = detect_intent_contradictions(doc)
        write_json_atomic(self.intent_path, doc)
        return doc

    def add(self, section, text, origin, **kwargs):
        """Append an item to an intent section."""
        if section not in INTENT_SECTIONS:
            raise ValueError("unknown intent section %r" % section)
        provenance = kwargs.get("provenance", {
            "USER_SAID": "direct_user_message",
            "AGENT_INFERRED": "agent_inference",
            "AGENT_DERIVED": "tool_output",
        }.get(origin))
        from .evidence import PROVENANCE_TRUST
        if PROVENANCE_TRUST.get(provenance, 0.0) <= 0.0:
            raise ValueError("untrusted provenance cannot enter active project intent")
        with FileLock(lifecycle_lock_path(self.home)):
            with FileLock(self.lock_path):
                doc = self.load_intent()
                item = _item(text, origin, **kwargs)
                doc[section].append(item)
                self._save_intent_locked(doc)
                return item

    def supersede(self, item_id, reason=None, replacement_id=None):
        """Mark an intent item superseded - never delete, so history survives."""
        with FileLock(lifecycle_lock_path(self.home)):
            with FileLock(self.lock_path):
                doc = self.load_intent()
                found = None
                for section in INTENT_SECTIONS:
                    for item in doc[section]:
                        if item["id"] == item_id:
                            item["status"] = "superseded"
                            item["superseded_at"] = utc_now()
                            item["superseded_reason"] = reason
                            item["superseded_by"] = replacement_id
                            item["updated_at"] = utc_now()
                            found = item
                if found:
                    self._save_intent_locked(doc)
                return found

    def set_stage(self, stage):
        if stage not in _STAGES:
            raise ValueError("unknown stage %r (expected one of %s)" % (stage, ", ".join(_STAGES)))
        with FileLock(lifecycle_lock_path(self.home)):
            with FileLock(self.lock_path):
                doc = self.load_intent()
                doc["stage"] = stage
                return self._save_intent_locked(doc)

    def active_items(self, section):
        return [i for i in self.load_intent().get(section, []) if i.get("status") == "active"]

    # -- decisions ---------------------------------------------------------
    def load_decisions(self):
        data, _ = read_json_resilient(
            self.decisions_path, backups_dir=self.backups, logs_dir=self.logs
        )
        return data or {"schema_version": SCHEMA_VERSION, "project_id": self.project_id,
                        "decisions": []}

    def record_decision(self, summary, rationale=None, basis=None, alternatives=None,
                        artifact=None, reversible=True, impact="medium", assumptions=None):
        """Record a consequential choice and everything it rests on.

        ``basis`` is a list of belief ids, intent item ids and event ids.  This
        is what makes "why did you do this?" answerable from records rather than
        from a plausible-sounding reconstruction after the fact.
        """
        from .privacy import screen_observation
        screen_observation(value=[summary, rationale, alternatives, artifact, assumptions], strict=True)
        entry = {
            "id": "dec_%s" % uuid.uuid4().hex[:12],
            "at": utc_now(),
            "summary": summary,
            "rationale": rationale,
            "basis": list(basis or []),
            "alternatives_considered": list(alternatives or []),
            "artifact": artifact,
            "reversible": bool(reversible),
            "impact": impact,
            "assumptions": list(assumptions or []),
            "outcome": None,
            "feedback_refs": [],
        }
        with FileLock(lifecycle_lock_path(self.home)):
            with FileLock(self.lock_path):
                doc = self.load_decisions()
                doc["decisions"].append(entry)
                backup_file(self.decisions_path, self.backups, tag="decisions")
                write_json_atomic(self.decisions_path, doc)
                return entry

    def attach_outcome(self, decision_id, outcome, feedback_ref=None):
        from .privacy import screen_observation
        screen_observation(value=outcome, strict=True)
        with FileLock(lifecycle_lock_path(self.home)):
            with FileLock(self.lock_path):
                doc = self.load_decisions()
                for entry in doc["decisions"]:
                    if entry["id"] == decision_id:
                        entry["outcome"] = outcome
                        entry["outcome_at"] = utc_now()
                        if feedback_ref:
                            entry["feedback_refs"].append(feedback_ref)
                write_json_atomic(self.decisions_path, doc)
                return doc

    # -- feedback ----------------------------------------------------------
    def load_feedback(self):
        data, _ = read_json_resilient(
            self.feedback_path, backups_dir=self.backups, logs_dir=self.logs
        )
        return data or {"schema_version": SCHEMA_VERSION, "project_id": self.project_id,
                        "feedback": []}

    def record_feedback(self, record):
        from .privacy import screen_observation
        screen_observation(value=record, strict=True)
        with FileLock(lifecycle_lock_path(self.home)):
            with FileLock(self.lock_path):
                doc = self.load_feedback()
                doc["feedback"].append(record)
                backup_file(self.feedback_path, self.backups, tag="feedback")
                write_json_atomic(self.feedback_path, doc)
                return record

    # -- lifecycle ---------------------------------------------------------
    def exists(self):
        return self.intent_path.is_file()

    def delete(self):
        """Remove this project's intent, decisions and feedback.

        The event log is untouched: ``liwm forget this project`` writes a
        tombstone so the personal profile stops counting it, while the audit
        trail of what happened remains intact.
        """
        with FileLock(lifecycle_lock_path(self.home)):
            with FileLock(self.lock_path):
                removed = []
                for path in (self.intent_path, self.decisions_path, self.feedback_path):
                    if path.is_file():
                        backup_file(path, self.backups, tag="project-delete")
                        path.unlink()
                        removed.append(str(path))
                if self.dir.is_dir() and not any(self.dir.iterdir()):
                    self.dir.rmdir()
                return removed

    def summary(self):
        doc = self.load_intent()
        counts = {s: len([i for i in doc.get(s, []) if i.get("status") == "active"])
                  for s in INTENT_SECTIONS}
        by_origin = {}
        for s in INTENT_SECTIONS:
            for item in doc.get(s, []):
                if item.get("status") != "active":
                    continue
                by_origin[item["origin"]] = by_origin.get(item["origin"], 0) + 1
        return {
            "project_id": self.project_id,
            "name": doc.get("name"),
            "domain": doc.get("domain"),
            "stage": doc.get("stage"),
            "revision": doc.get("revision"),
            "counts": counts,
            "by_origin": by_origin,
            "confidence": doc.get("confidence"),
            "open_questions": counts.get("open_questions", 0),
            "contradictions": len(doc.get("contradictions", [])),
            "decisions": len(self.load_decisions().get("decisions", [])),
        }


def _intent_confidence(doc):
    """How well LIWM believes it understands this project.

    Weighted toward what the user actually said.  A document full of confident
    agent inferences is not a well-understood project; it is a guess with good
    posture.
    """
    stated = inferred = derived = 0
    for section in INTENT_SECTIONS:
        for item in doc.get(section, []):
            if item.get("status") != "active":
                continue
            if item["origin"] == "USER_SAID":
                stated += 1
            elif item["origin"] == "AGENT_INFERRED":
                inferred += 1
            else:
                derived += 1
    total = stated + inferred + derived
    if total == 0:
        return {"overall_intent": 0.0, "basis": "no intent recorded yet",
                "stated": 0, "inferred": 0, "derived": 0}

    coverage = min(1.0, total / 12.0)
    groundedness = (stated + 0.35 * inferred + 0.5 * derived) / total
    open_q = len([i for i in doc.get("open_questions", []) if i.get("status") == "active"])
    open_penalty = min(0.35, 0.07 * open_q)
    score = max(0.0, min(1.0, 0.55 * groundedness + 0.45 * coverage - open_penalty))
    return {
        "overall_intent": round(score, 4),
        "stated": stated,
        "inferred": inferred,
        "derived": derived,
        "open_questions": open_q,
        "basis": "%d stated, %d inferred, %d derived; %d open questions"
                 % (stated, inferred, derived, open_q),
    }


def detect_intent_contradictions(doc):
    """Surface intent items that pull against each other.

    Deliberately shallow and textual: real contradiction detection needs the
    host model's judgement.  This catches the mechanical cases - an anti-goal
    that restates an objective, a non-negotiable that a rejected direction
    already ruled out - and hands the rest upward.
    """
    out = []
    active = {s: [i for i in doc.get(s, []) if i.get("status") == "active"]
              for s in INTENT_SECTIONS}

    def _tokens(text):
        return {w for w in re.findall(r"[a-z]{4,}", str(text).lower())}

    for goal in active.get("objectives", []) + active.get("latent_objectives", []):
        gt = _tokens(goal["text"])
        for anti in active.get("anti_goals", []):
            overlap = gt & _tokens(anti["text"])
            if len(overlap) >= 2:
                out.append({
                    "type": "objective_vs_anti_goal",
                    "items": [goal["id"], anti["id"]],
                    "shared_terms": sorted(overlap)[:6],
                    "severity": "high" if goal["origin"] == anti["origin"] == "USER_SAID" else "medium",
                    "note": "an objective and an anti-goal describe overlapping territory; "
                            "clarify only if it changes the current work",
                })

    for nn in active.get("non_negotiables", []):
        nt = _tokens(nn["text"])
        for rejected in active.get("rejected_directions", []):
            overlap = nt & _tokens(rejected["text"])
            if len(overlap) >= 2:
                out.append({
                    "type": "non_negotiable_vs_rejected",
                    "items": [nn["id"], rejected["id"]],
                    "shared_terms": sorted(overlap)[:6],
                    "severity": "high",
                    "note": "a non-negotiable overlaps a direction the user rejected",
                })
    return out
