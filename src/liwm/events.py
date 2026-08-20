"""The append-only event log: LIWM's source of truth.

``user.json`` is a *materialised view*.  This log is the thing it is derived
from.  That inversion buys three properties that matter:

* **Concurrency without locks on the hot path.**  Two agents appending two
  events write two different files and can never clobber each other.  The only
  contended write is the materialised view, and a lost update there is repaired
  by re-folding the log rather than by merge heuristics.
* **Auditability.**  Every belief can be traced to the exact observations that
  produced it, with their provenance intact.
* **Recoverability.**  Delete ``user.json`` and it can be rebuilt exactly.

Events are immutable.  Nothing in LIWM edits or deletes an event except an
explicit user-initiated ``forget``, which writes a *tombstone* event rather than
mutating history.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .evidence import PROVENANCE_TRUST, TRUSTED_PROVENANCE
from .jsonio import (
    read_json,
    sha256_of,
    utc_now_ms,
    write_json_atomic,
)
from .privacy import SensitiveAttributeRefused, redact, screen_observation
from .taxonomy import is_known_dimension

__all__ = [
    "EVENT_KINDS",
    "EventStore",
    "make_event",
    "SCHEMA_VERSION",
]

SCHEMA_VERSION = "0.1.0"

#: Every event kind LIWM knows how to fold.  Unknown kinds are stored and
#: ignored by the folder, which keeps forward compatibility cheap.
EVENT_KINDS = frozenset(
    {
        # evidence about the person
        "observation",
        "correction",
        "rejection",
        "belief_endorsed",
        # interaction
        "question_asked",
        "question_answered",
        "question_skipped",
        "mode_selected",
        "assumption_made",
        # artifacts and outcomes
        "prediction",
        "artifact",
        "feedback",
        "outcome",
        "decision",
        # project intent
        "project_intent_update",
        # learning machinery
        "scope_promotion",
        "scope_demotion",
        "strategy_update",
        "candidate_rule",
        "rule_promoted",
        "rule_rejected",
        "retrospective",
        # lifecycle / governance
        "session_start",
        "session_end",
        "onboarding_started",
        "onboarding_answer",
        "onboarding_completed",
        "refusal",
        "forget",
        "reset",
        "rollback",
        "export",
        "migration",
    }
)

DIRECT_USER_CONTROL_KINDS = frozenset(
    {"rejection", "belief_endorsed", "forget", "reset", "rollback"}
)
DIRECT_USER_PROVENANCE = frozenset(
    {"direct_user_message", "direct_user_edit", "explicit_user_review"}
)
_EVENT_ID_RE = re.compile(r"^evt_[0-9a-f]{8,}$")


def _shard_for(ts):
    return ts[:7] if len(ts) >= 7 else "unknown"


def make_event(
    kind,
    provenance,
    payload=None,
    observation=None,
    session_id=None,
    project_id=None,
    domain=None,
    actor="liwm",
    derived_from=None,
    ts=None,
    quarantine_reason=None,
):
    """Build (but do not persist) a well-formed event.

    Two gates run here, before anything reaches disk:

    1. **Privacy gate** - an observation touching a protected attribute is
       refused; a redacted ``refusal`` event is produced instead so that the
       refusal itself is auditable.
    2. **Provenance gate** - an observation whose provenance (or whose upstream
       taint) is untrusted is marked ``quarantined``.  It is still recorded, but
       :func:`liwm.profile.fold` will never let it influence a belief.
    """
    ts = ts or utc_now_ms()
    event = {
        "event_id": "evt_%s" % uuid.uuid4().hex[:16],
        "schema_version": SCHEMA_VERSION,
        "ts": ts,
        "kind": kind,
        "actor": actor,
        "provenance": provenance,
        "derived_from": list(derived_from or []),
        "session_id": session_id,
        "project_id": project_id,
        "domain": domain,
        "payload": payload or {},
        "quarantined": False,
        "quarantine_reason": None,
    }

    if observation is not None:
        obs = dict(observation)
        try:
            screen_observation(
                dimension=obs.get("dimension"),
                value=obs.get("value"),
                text=obs.get("note") or obs.get("quote"),
                strict=True,
            )
        except SensitiveAttributeRefused as exc:
            refused = {
                "event_id": "evt_%s" % uuid.uuid4().hex[:16],
                "schema_version": SCHEMA_VERSION,
                "ts": ts,
                "kind": "refusal",
                "actor": actor,
                "provenance": provenance,
                "derived_from": list(derived_from or []),
                "session_id": session_id,
                "project_id": project_id,
                "domain": domain,
                "payload": {
                    "refused_kind": kind,
                    "category": exc.category,
                    "reason": "privacy_gate",
                    "detail": redact(exc.detail),
                    "dimension_redacted": redact(str(obs.get("dimension"))),
                },
                "quarantined": True,
                "quarantine_reason": "privacy_gate:%s" % exc.category,
            }
            refused["integrity"] = {"algo": "sha256", "hash": sha256_of(refused)}
            return refused
        # The taxonomy is an allowlist. A dimension nobody vetted cannot become
        # a durable property of a person, which is what keeps the profile from
        # quietly growing fields under an injected instruction's direction.
        # Open namespaces (preferences, goals, domain_fluency, ...) cover the
        # genuinely free-form cases.
        if not is_known_dimension(obs.get("dimension")):
            quarantine_reason = quarantine_reason or (
                "unknown_dimension:%s (add it to liwm.taxonomy.DIMENSIONS or use an "
                "open namespace such as preferences.*)" % obs.get("dimension")
            )

        obs.setdefault("polarity", "support")
        obs.setdefault("source_type", "agent_inference")
        obs.setdefault("scope", "global")
        obs.setdefault("decay_policy", "standard")
        obs["ts"] = ts
        obs["provenance"] = provenance
        obs["derived_from"] = list(derived_from or [])
        obs["session_id"] = session_id
        event["observation"] = obs

    if quarantine_reason:
        event["quarantined"] = True
        event["quarantine_reason"] = quarantine_reason

    authorization_issue = _authorization_issue(event)
    if authorization_issue:
        event["quarantined"] = True
        event["quarantine_reason"] = authorization_issue

    # Content hash over everything except the hash field itself: tamper-evident
    # without pretending to be tamper-proof.
    event["integrity"] = {"algo": "sha256", "hash": sha256_of(event)}
    return event


class EventStore:
    """Append-only, month-sharded event log rooted at ``<home>/events``."""

    def __init__(self, home):
        self.home = Path(home)
        self.root = self.home / "events"

    # -- writing -----------------------------------------------------------
    def append(self, event):
        """Persist *event* and return its path."""
        _validate_event_envelope(event)
        ts = event.get("ts") or utc_now_ms()
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        shard = self.root / parsed.strftime("%Y-%m")
        shard.mkdir(parents=True, exist_ok=True)
        safe_ts = ts.replace(":", "").replace("-", "").replace(".", "")
        name = "%s-%s.json" % (safe_ts, event["event_id"][4:12])
        path = shard / name
        # Collisions are effectively impossible (ms + uuid) but cheap to handle.
        while path.exists():  # pragma: no cover
            name = "%s-%s.json" % (safe_ts, uuid.uuid4().hex[:8])
            path = shard / name
        write_json_atomic(path, event, fsync=True)
        return path

    def record(self, kind, provenance, **kwargs):
        """Build and persist an event in one step; returns the event."""
        event = make_event(kind, provenance, **kwargs)
        from .config import ConfigStore
        if not ConfigStore(self.home).load().get("privacy", {}).get("store_free_text", False):
            event = _without_free_text(event)
        self.append(event)
        return event

    # -- reading -----------------------------------------------------------
    def shards(self):
        if not self.root.is_dir():
            return []
        return sorted(d for d in self.root.iterdir() if d.is_dir())

    def iter_paths(self, since_shard=None):
        for shard in self.shards():
            if since_shard and shard.name < since_shard:
                continue
            for path in sorted(shard.glob("*.json")):
                yield path

    def iter_events(self, kinds=None, project_id=None, session_id=None,
                    include_quarantined=False, since=None, limit=None):
        """Yield events in timestamp order, with cheap filtering."""
        count = 0
        for path in self.iter_paths():
            try:
                event = read_json(path)
            except Exception:  # noqa: BLE001 - a single bad file must not kill a fold
                self._log_bad(path)
                continue
            if not isinstance(event, dict):
                self._log_bad(path)
                continue
            integrity_issue = _integrity_issue(event)
            authorization_issue = _authorization_issue(event)
            if integrity_issue or authorization_issue:
                # Never fold content whose hash no longer matches. Keep the
                # on-disk event untouched for forensic inspection and expose a
                # transient quarantine marker to readers.
                event = dict(event)
                event["quarantined"] = True
                event["quarantine_reason"] = integrity_issue or authorization_issue
            if not include_quarantined and event.get("quarantined"):
                continue
            if kinds and event.get("kind") not in kinds:
                continue
            if project_id is not None and event.get("project_id") != project_id:
                continue
            if session_id is not None and event.get("session_id") != session_id:
                continue
            if since and str(event.get("ts", "")) < since:
                continue
            yield event
            count += 1
            if limit and count >= limit:
                return

    def read_all(self, **kwargs):
        return list(self.iter_events(**kwargs))

    def count(self, **kwargs):
        return sum(1 for _ in self.iter_events(**kwargs))

    def latest(self, n=20, **kwargs):
        events = self.read_all(**kwargs)
        return events[-n:]

    # -- integrity ---------------------------------------------------------
    def verify(self):
        """Recompute every event hash; return a report of any mismatches."""
        checked = tampered = unreadable = missing_integrity = 0
        problems = []
        for path in self.iter_paths():
            try:
                event = read_json(path)
            except Exception as exc:  # noqa: BLE001
                unreadable += 1
                problems.append({"path": str(path), "issue": "unreadable", "detail": str(exc)})
                continue
            integrity = (event or {}).get("integrity") or {}
            stored = integrity.get("hash")
            if not stored:
                missing_integrity += 1
                problems.append({"path": str(path), "issue": "missing_integrity",
                                 "event_id": (event or {}).get("event_id")})
                continue
            body = {k: v for k, v in event.items() if k != "integrity"}
            checked += 1
            if sha256_of(body) != stored:
                tampered += 1
                problems.append({"path": str(path), "issue": "hash_mismatch",
                                 "event_id": event.get("event_id")})
        return {
            "checked": checked,
            "tampered": tampered,
            "unreadable": unreadable,
            "missing_integrity": missing_integrity,
            "ok": tampered == 0 and unreadable == 0 and missing_integrity == 0,
            "problems": problems[:50],
        }
    def _log_bad(self, path):
        logs = self.home / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with open(logs / "event-read-errors.log", "a", encoding="utf-8") as fh:
            fh.write("%s\tunreadable\t%s\n" % (utc_now_ms(), path))

    # -- statistics --------------------------------------------------------
    def stats(self):
        by_kind = {}
        by_provenance = {}
        quarantined = 0
        total = 0
        first_ts = last_ts = None
        for path in self.iter_paths():
            try:
                event = read_json(path)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(event, dict):
                continue
            total += 1
            by_kind[event.get("kind", "?")] = by_kind.get(event.get("kind", "?"), 0) + 1
            prov = event.get("provenance", "?")
            by_provenance[prov] = by_provenance.get(prov, 0) + 1
            if event.get("quarantined") or _integrity_issue(event):
                quarantined += 1
            ts = event.get("ts")
            if ts:
                first_ts = ts if first_ts is None else min(first_ts, ts)
                last_ts = ts if last_ts is None else max(last_ts, ts)
        return {
            "total_events": total,
            "quarantined": quarantined,
            "by_kind": dict(sorted(by_kind.items())),
            "by_provenance": dict(sorted(by_provenance.items())),
            "trusted_provenance": sorted(TRUSTED_PROVENANCE),
            "first_event": first_ts,
            "last_event": last_ts,
        }


def _integrity_issue(event):
    """Return a quarantine reason when an event's content hash is invalid."""
    integrity = (event or {}).get("integrity") or {}
    stored = integrity.get("hash")
    if not stored:
        return "integrity_missing"
    body = {k: v for k, v in event.items() if k != "integrity"}
    if sha256_of(body) != stored:
        return "integrity_hash_mismatch"
    return None


def _authorization_issue(event):
    """Return why an event may not influence state, independently of its flags."""
    provenance = (event or {}).get("provenance")
    if PROVENANCE_TRUST.get(provenance, 0.0) <= 0.0:
        return "untrusted_provenance:%s" % provenance
    derived_from = (event or {}).get("derived_from") or []
    tainted = [p for p in derived_from if PROVENANCE_TRUST.get(p, 0.0) <= 0.0]
    if tainted:
        return "tainted_derivation:%s" % ",".join(str(p) for p in tainted)
    if (event or {}).get("kind") in DIRECT_USER_CONTROL_KINDS \
            and provenance not in DIRECT_USER_PROVENANCE:
        return "control_requires_direct_user:%s" % (event or {}).get("kind")

    observation = (event or {}).get("observation") or {}
    source = observation.get("source_type")
    scope = observation.get("scope", "global")
    scope_key = observation.get("scope_key")
    if scope == "project" and not (scope_key or (event or {}).get("project_id")):
        return "missing_scope_key:project"
    if scope == "domain" and not (scope_key or (event or {}).get("domain")):
        return "missing_scope_key:domain"
    if provenance == "agent_inference" and source in {
        "explicit_statement", "explicit_correction", "explicit_rejection",
        "direct_edit", "repeated_selection", "comparative_choice", "onboarding_answer",
    }:
        return "source_provenance_mismatch:%s:%s" % (provenance, source)
    if provenance == "onboarding_answer" and source not in (None, "onboarding_answer"):
        return "source_provenance_mismatch:%s:%s" % (provenance, source)
    if provenance == "direct_user_edit" and source not in (None, "direct_edit"):
        return "source_provenance_mismatch:%s:%s" % (provenance, source)
    return None


def _validate_event_envelope(event):
    """Reject path-unsafe, unsealed dictionaries at the append boundary."""
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    if not _EVENT_ID_RE.match(str(event.get("event_id", ""))):
        raise ValueError("invalid event_id")
    if event.get("kind") not in EVENT_KINDS:
        raise ValueError("unknown event kind %r" % event.get("kind"))
    ts = str(event.get("ts", ""))
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid event timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("event timestamp must include a timezone")
    issue = _integrity_issue(event)
    if issue:
        raise ValueError("event is not sealed: %s" % issue)


#: Keys whose values are user prose by construction.  These are dropped even
#: when they happen to be short, because a one-word answer is still an answer.
PROSE_KEYS = frozenset({
    "answer", "assumption", "comment", "description", "detail", "message",
    "note", "notes", "prompt", "question", "quote", "rationale", "statement",
    "summary", "task_hint", "text", "title",
})

#: Keys whose string values are structural even when they contain spaces:
#: a belief's value in an open namespace ("prefers small reversible steps") is
#: the belief itself, not incidental prose, and dropping it would erase the
#: very thing the event exists to record.  ``issue`` labels are compared across
#: prediction and outcome, so calibration depends on them surviving verbatim;
#: ``quarantine_reason`` is written by LIWM and is the only record of why
#: something was refused.
STRUCTURAL_KEYS = frozenset({
    "value", "dimension", "scope_key", "path", "issue", "quarantine_reason",
})

#: A "token": an identifier, enum member, path, version or hash.  Prose is
#: characterised by shape rather than by field name, because a denylist of
#: field names silently leaks every field nobody thought of.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+=\\-]{0,79}$")


def _without_free_text(event):
    """Drop raw prose while preserving structured evidence, then reseal.

    Retention is **deny-by-default for strings**.  The previous implementation
    named the fields to remove, which meant any newly added prose field was
    retained until somebody remembered to list it -- exactly the failure mode
    LIWM refuses everywhere else.  Here the rules are, in order:

    1. a key in :data:`PROSE_KEYS` is dropped outright;
    2. a key in :data:`STRUCTURAL_KEYS` is kept, prose-shaped or not;
    3. any other string is kept only if it is token-shaped;
    4. numbers, booleans and null are structure and always survive.

    So ``reason="privacy_gate"`` (a control token LIWM emitted) is retained and
    stays auditable, while ``reason="because I kept repeating myself"`` (typed
    by a person) is not.  Set ``privacy.store_free_text`` to keep everything.
    """
    def clean(value, key=None):
        if isinstance(value, dict):
            out = {}
            for k, item in value.items():
                if k in PROSE_KEYS:
                    continue
                out[k] = clean(item, k)
            return out
        if isinstance(value, list):
            return [clean(item, key) for item in value]
        if isinstance(value, str) and key not in STRUCTURAL_KEYS:
            return value if _TOKEN_RE.match(value) else None
        return value

    cleaned = clean({key: value for key, value in event.items() if key != "integrity"})
    cleaned["integrity"] = {"algo": "sha256", "hash": sha256_of(cleaned)}
    return cleaned
