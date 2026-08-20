"""The user model: folding events into ``user.json``.

``user.json`` is never edited in place by the learning system.  It is *folded*
from the event log, deterministically, every time.  That single decision solves
most of the hard problems at once:

* concurrent agents cannot lose each other's updates (re-fold, don't merge);
* corruption is recoverable (delete and re-fold);
* every belief is explainable (the fold knows which events produced it);
* rollback is explicit and durable (a branch marker selects an earlier cutoff).

The named sections (``interaction_profile``, ``reasoning_profile``, ...) are
*projections* of the canonical ``beliefs`` list, grouped by the dotted dimension
namespace.  There is exactly one source of truth, so the ergonomic view can
never drift from the evidence.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from . import evidence as ev
from .constitution import constitution_hash
from .events import EventStore
from .invalidation import apply_to_fold
from .jsonio import (
    FileLock,
    backup_file,
    prune_backups,
    quarantine_corrupt,
    read_json_resilient,
    sha256_of,
    utc_now,
    utc_now_ms,
    write_json_atomic,
    lifecycle_lock_path,
)
from .privacy import screen_dimension
from .scope import (
    DEFAULT_POLICY,
    belief_key,
    cross_domain_hypotheses,
    evaluate_promotions,
    resolve_for_context,
)

__all__ = [
    "SCHEMA_VERSION",
    "PROFILE_SECTIONS",
    "RevisionConflict",
    "ProfileStore",
    "empty_profile",
]

SCHEMA_VERSION = "0.2.0"

#: Dotted-dimension namespaces that get their own named section in user.json.
PROFILE_SECTIONS = (
    "interaction_profile",
    "reasoning_profile",
    "creative_profile",
    "domain_fluency",
    "working_style",
    "decision_style",
    "communication_profile",
)

#: Sections rendered as evidence-backed lists rather than dimension maps.
LIST_SECTIONS = {
    "preferences": "preferences",
    "anti_preferences": "anti_preferences",
    "persistent_goals": "goals",
    "persistent_anti_goals": "anti_goals",
    "learned_expectations": "expectations",
}

#: Sources strong enough to revive a belief the user previously rejected.
REVIVAL_SOURCES = frozenset(
    {"explicit_statement", "explicit_correction", "explicit_rejection", "direct_edit"}
)


class RevisionConflict(RuntimeError):
    """Raised when an optimistic-concurrency write loses the race."""

    def __init__(self, expected, actual):
        self.expected = expected
        self.actual = actual
        super().__init__("profile revision conflict: expected %s, on disk %s" % (expected, actual))


def empty_profile(profile_id=None):
    """A valid, empty profile - the state right after ``liwm init``."""
    now = utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "profile_id": profile_id or "usr_%s" % uuid.uuid4().hex[:16],
        "revision": 0,
        "created_at": now,
        "updated_at": now,
        "constitution_hash": constitution_hash(),
        "materialized_from": {
            "event_count": 0,
            "quarantined_event_count": 0,
            "last_event_id": None,
            "last_event_ts": None,
            "fold_hash": None,
        },
        "onboarding": {
            "status": "not_started",
            "started_at": None,
            "completed_at": None,
            "questions_asked": 0,
            "dimensions_covered": [],
            "summary_shown": None,
            "user_corrections": [],
            "confidence_basis": "self_report",
        },
        "interaction_profile": {},
        "reasoning_profile": {},
        "creative_profile": {},
        "domain_fluency": {},
        "working_style": {},
        "decision_style": {},
        "communication_profile": {},
        "persistent_goals": [],
        "persistent_anti_goals": [],
        "preferences": [],
        "anti_preferences": [],
        "learned_expectations": [],
        "cross_domain_hypotheses": [],
        "uncertainties": [],
        "contradictions": [],
        "rejections": [],
        "beliefs": [],
        "domains_seen": [],
        "projects_seen": [],
        "confidence_calibration": {
            "method": "prediction_vs_outcome",
            "samples": 0,
            "mean_absolute_error": None,
            "bins": [],
            "note": "Populated by liwm.metrics from prediction/feedback event pairs.",
        },
        "privacy": {
            "telemetry": "disabled",
            "storage": "local_only",
            "sensitive_attribute_inference": "refused",
            "refusals_recorded": 0,
            "export_count": 0,
            "last_export": None,
        },
        "statistics_summary": {
            "belief_count": 0,
            "high_confidence_beliefs": 0,
            "hypotheses": 0,
            "contradictions_open": 0,
            "domains_with_evidence": 0,
            "quarantined_events": 0,
        },
    }


class ProfileStore:
    """Read/fold/write access to a LIWM profile directory."""

    def __init__(self, home, policy=None):
        self.home = Path(home)
        self.path = self.home / "user.json"
        self.lock_path = self.home / "user.json.lock"
        self.backups = self.home / "backups"
        self.logs = self.home / "logs"
        self.events = EventStore(self.home)
        self.policy = policy or DEFAULT_POLICY
        self.last_recovery_note = None

    # -- persistence -------------------------------------------------------
    def exists(self):
        return self.path.is_file()

    def load(self, materialize_if_missing=True):
        """Load the materialised profile, recovering or rebuilding if needed.

        Recovery deliberately prefers **re-folding the event log** over
        restoring a backup.  ``user.json`` is a cache of the events, so the
        events are strictly fresher than any snapshot of it; restoring a backup
        would silently roll the profile back to whenever that backup was taken.
        Backups are the fallback for the case where the event log itself cannot
        produce a profile.
        """
        from .jsonio import CorruptFile, read_json

        self.last_recovery_note = None
        try:
            data = read_json(self.path, default=None)
        except CorruptFile as exc:
            self.last_recovery_note = str(exc)
            moved = quarantine_corrupt(self.path, self.logs)
            if moved:
                self.last_recovery_note += " | quarantined to %s" % moved
            data = None

        if data is not None:
            return data
        if not materialize_if_missing:
            return None

        try:
            return self.rebuild(reason="recovered_from_event_log")
        except Exception as exc:
            self.last_recovery_note = "%s | fold failed (%s); falling back to backup" % (
                self.last_recovery_note or "profile unreadable", exc
            )
            data, note = read_json_resilient(
                self.path, backups_dir=self.backups, logs_dir=self.logs, default=None
            )
            if note:
                self.last_recovery_note += " | %s" % note
            return data if data is not None else empty_profile()

    def save(self, profile, expected_revision=None, tag="update"):
        """Write *profile* under lock with optimistic concurrency control."""
        with FileLock(self.lock_path):
            on_disk = None
            if self.path.is_file():
                try:
                    on_disk, _ = read_json_resilient(
                        self.path, backups_dir=self.backups, logs_dir=self.logs
                    )
                except Exception:
                    on_disk = None
            current_rev = (on_disk or {}).get("revision", 0)
            if expected_revision is not None and current_rev != expected_revision:
                raise RevisionConflict(expected_revision, current_rev)
            backup_file(self.path, self.backups, tag=tag)
            from .config import ConfigStore
            keep = int(ConfigStore(self.home).load().get("retention", {}).get("backup_count", 60))
            prune_backups(self.backups, keep=keep)
            profile = dict(profile)
            profile["revision"] = current_rev + 1
            profile["updated_at"] = utc_now()
            write_json_atomic(self.path, profile)
            return profile

    # -- the fold ----------------------------------------------------------
    def fold(self, as_of=None, include_promotions=True, _events_locked=False):
        """Derive a complete profile from the event log.

        Deterministic: same events in, same profile out.  ``as_of`` folds the
        log up to a timestamp, which is how rollback and replay work.
        """
        if not _events_locked:
            with FileLock(lifecycle_lock_path(self.home), timeout=30.0):
                with FileLock(self.events.lock_path, timeout=30.0):
                    return self.fold(
                        as_of=as_of, include_promotions=include_promotions,
                        _events_locked=True,
                    )
        integrity = self.events.verify(_events_locked=True)
        if not integrity["ok"]:
            raise ValueError(
                "event integrity failed; refusing to materialise around missing or corrupt "
                "evidence (%d problem(s))" % len(integrity["problems"])
            )
        base = None
        if self.path.is_file():
            base, _ = read_json_resilient(self.path, backups_dir=self.backups, logs_dir=self.logs)
        profile = empty_profile(profile_id=(base or {}).get("profile_id"))
        if base:
            profile["created_at"] = base.get("created_at", profile["created_at"])
            profile["revision"] = base.get("revision", 0)
            profile["privacy"]["export_count"] = base.get("privacy", {}).get("export_count", 0)
            profile["privacy"]["last_export"] = base.get("privacy", {}).get("last_export")

        observations = {}          # belief_key -> list of observation dicts
        meta = {}                  # belief_key -> descriptive fields
        rejections = {}            # (scope, scope_key, dimension, value_norm) -> record
        domains_seen = set()
        projects_seen = set()
        onboarding = dict(profile["onboarding"])
        quarantined = 0
        total = 0
        last_event = None
        refusals = 0

        events = list(self.events.iter_events(include_quarantined=True))
        if as_of:
            events = [event for event in events if event.get("ts", "") <= as_of]

        # A reset or rollback is an append-only branch marker. The latest marker
        # defines the active history while leaving every original event available
        # for audit and a later rollback. New events after the marker form the new
        # branch. An explicit ``as_of`` replay only sees markers that existed then.
        branch_marker = next(
            (event for event in reversed(events)
             if not event.get("quarantined") and event.get("kind") in ("reset", "rollback")),
            None,
        )
        skipped_by_branch = 0
        if branch_marker:
            marker_sequence = int(branch_marker.get("sequence") or 0)
            if branch_marker.get("kind") == "rollback":
                cutoff = (branch_marker.get("payload") or {}).get("cutoff", "")
                cutoff_sequence = (branch_marker.get("payload") or {}).get("cutoff_sequence")
                if cutoff_sequence is None:
                    cutoff_sequence = max(
                        (int(event.get("sequence") or 0) for event in events
                         if int(event.get("sequence") or 0) < marker_sequence
                         and event.get("ts", "") <= cutoff),
                        default=0,
                    )
                active = lambda event: (  # noqa: E731 - the predicate is clearer inline
                    int(event.get("sequence") or 0) <= int(cutoff_sequence)
                    or int(event.get("sequence") or 0) >= marker_sequence
                )
            else:
                cutoff = cutoff_sequence = None
                active = lambda event: int(event.get("sequence") or 0) >= marker_sequence  # noqa: E731
            skipped_by_branch = sum(1 for event in events if not active(event))
            events = [event for event in events if active(event)]

        expanded = []
        for event in events:
            expanded.append(event)
            if event.get("kind") != "onboarding_answer":
                continue
            for observation in (event.get("payload") or {}).get("observations", []):
                observation = dict(
                    observation, ts=event.get("ts"), provenance="onboarding_answer",
                    session_id=event.get("session_id"), derived_from=[],
                )
                expanded.append(dict(event, kind="observation", observation=observation))
        events = expanded

        for event in events:
            ts = event.get("ts", "")
            total += 1
            last_event = event
            if event.get("kind") == "refusal":
                refusals += 1
            if event.get("quarantined"):
                quarantined += 1
                continue

            kind = event.get("kind")
            if event.get("domain"):
                domains_seen.add(event["domain"])
            if event.get("project_id"):
                projects_seen.add(event["project_id"])

            if kind == "forget":
                apply_to_fold(event.get("payload") or {},
                              observations, meta, rejections, projects_seen)
                continue

            if kind == "rejection":
                payload = event.get("payload") or {}
                dim = payload.get("dimension")
                val = payload.get("value")
                if dim:
                    rejection_key = (
                        payload.get("scope", "global"), payload.get("scope_key"),
                        dim, _norm(val) if val is not None else "*",
                    )
                    rejections[rejection_key] = {
                        "dimension": dim,
                        "value": val,
                        "rejected_at": ts,
                        "reason": payload.get("reason"),
                        "inference_source": payload.get("inference_source"),
                        "scope": payload.get("scope", "global"),
                        "scope_key": payload.get("scope_key"),
                    }
                continue

            if kind == "onboarding_started":
                onboarding["status"] = "in_progress"
                onboarding["started_at"] = ts
            elif kind == "onboarding_answer":
                onboarding["questions_asked"] = onboarding.get("questions_asked", 0) + 1
                dims = (event.get("payload") or {}).get("dimensions") or []
                covered = set(onboarding.get("dimensions_covered") or [])
                covered.update(dims)
                onboarding["dimensions_covered"] = sorted(covered)
            elif kind == "onboarding_completed":
                onboarding["status"] = "completed"
                onboarding["completed_at"] = ts
                onboarding["summary_shown"] = (event.get("payload") or {}).get("summary")
            elif kind == "belief_endorsed":
                payload = event.get("payload") or {}
                key = (
                    payload.get("scope", "global"), payload.get("scope_key"),
                    payload.get("dimension"), _norm(payload.get("value")),
                )
                rejections.pop(key, None)
                rejections.pop(key[:3] + ("*",), None)

            obs = event.get("observation")
            if not obs:
                continue
            dimension = obs.get("dimension")
            if not dimension or screen_dimension(dimension):
                continue

            scope = obs.get("scope", "global")
            scope_key = obs.get("scope_key")
            if scope == "project" and not scope_key:
                scope_key = event.get("project_id")
            if scope == "domain" and not scope_key:
                scope_key = event.get("domain")
            if scope == "session":
                continue  # session evidence never becomes durable belief

            key = belief_key(scope, scope_key, dimension, obs.get("value"))
            # Tag ordering against rejections during the pass itself. Comparing
            # timestamps afterwards is fragile when several events land in the
            # same instant; the fold already walks events in order, so "has a
            # rejection been seen yet" is exact and free.
            obs = dict(obs)
            obs["_event_id"] = event.get("event_id")
            rejection_key = (scope, scope_key, dimension, _norm(obs.get("value")))
            obs["_post_rejection"] = (
                rejection_key in rejections or rejection_key[:3] + ("*",) in rejections
            )
            observations.setdefault(key, []).append(obs)
            meta.setdefault(
                key,
                {
                    "scope": scope,
                    "scope_key": scope_key,
                    "dimension": dimension,
                    "value": obs.get("value"),
                    "domain": event.get("domain") or (scope_key if scope == "domain" else None),
                    "decay_policy": obs.get("decay_policy", "standard"),
                    "first_seen": ts,
                    "last_seen": ts,
                    "session_ids": set(),
                    "event_ids": [],
                    "notes": obs.get("note"),
                },
            )
            m = meta[key]
            m["first_seen"] = min(m["first_seen"], ts)
            m["last_seen"] = max(m["last_seen"], ts)
            if event.get("session_id"):
                m["session_ids"].add(event["session_id"])
            m["event_ids"].append(event.get("event_id"))

        # -- build beliefs -------------------------------------------------
        beliefs = []
        for key, obs_list in sorted(observations.items()):
            m = meta[key]
            rejection_key = (
                m["scope"], m.get("scope_key"), m["dimension"], _norm(m["value"]),
            )
            rejection = rejections.get(rejection_key) or rejections.get(
                rejection_key[:3] + ("*",)
            )
            usable = obs_list
            suppressed = 0
            if rejection:
                # A rejected conclusion may only be revived by strong, direct
                # evidence recorded *after* the rejection (requirement §38).
                # This is what stops the same weak signal from silently
                # relearning something the user has already denied.
                usable = [
                    o for o in obs_list
                    if o.get("_post_rejection")
                    and o.get("source_type") in REVIVAL_SOURCES
                ]
                suppressed = len(obs_list) - len(usable)

            scored = ev.combine(usable)
            usable_object_ids = {id(observation) for observation in usable}
            belief = {
                "id": "blf_%s" % sha256_of(key)[:16],
                "key": key,
                "scope": m["scope"],
                "scope_key": m["scope_key"],
                "domain": m["domain"],
                "dimension": m["dimension"],
                "value": m["value"],
                "confidence": scored["confidence"],
                "evidence_count": scored["evidence_count"],
                "contradiction_count": scored["contradiction_count"],
                "support_weight": scored["support_weight"],
                "oppose_weight": scored["oppose_weight"],
                "first_seen": m["first_seen"],
                "last_seen": m["last_seen"],
                "source_types": sorted({o.get("source_type", "agent_inference") for o in usable}),
                "provenance_types": sorted({o.get("provenance", "other") for o in usable}),
                "decay_policy": m["decay_policy"],
                "session_ids": sorted(m["session_ids"])[-100:],
                "session_count": len(m["session_ids"]),
                "evidence_refs": [o.get("_event_id") for o in usable if o.get("_event_id")][-25:],
                "suppressed_evidence_refs": [
                    o.get("_event_id") for o in obs_list
                    if id(o) not in usable_object_ids and o.get("_event_id")
                ][-25:],
                "origin": "observed",
                "status": "active",
                "rejected_by_user": bool(rejection and not usable),
                "suppressed_evidence": suppressed,
                "ceiling": scored["ceiling"],
                "limiting_factor": scored["limiting_factor"],
                "notes": m.get("notes"),
            }
            if rejection:
                belief["status"] = "rejected" if not usable else "active"
                belief["rejection"] = dict(
                    rejection, status="active" if not usable else "superseded"
                )
                if not usable:
                    belief["confidence"] = 0.0
            if belief["confidence"] <= 0.0 and belief["status"] == "active" and not usable:
                belief["status"] = "retired"
            beliefs.append(belief)

        # -- promotions ----------------------------------------------------
        promotions = []
        if include_promotions:
            promotions = evaluate_promotions(beliefs, policy=self.policy)
            existing_keys = {b["key"] for b in beliefs}
            beliefs_by_id = {b["id"]: b for b in beliefs}
            for prop in promotions:
                key = belief_key(
                    prop["target_scope"], prop["scope_key"], prop["dimension"], prop["value"]
                )
                if key in existing_keys:
                    continue
                rejection_key = (
                    prop["target_scope"], prop.get("scope_key"), prop["dimension"],
                    _norm(prop["value"]),
                )
                if rejections.get(rejection_key) or rejections.get(rejection_key[:3] + ("*",)):
                    continue
                beliefs.append(
                    {
                        "id": "blf_%s" % sha256_of(key)[:16],
                        "key": key,
                        "scope": prop["target_scope"],
                        "scope_key": prop["scope_key"],
                        "domain": prop.get("domain"),
                        "dimension": prop["dimension"],
                        "value": prop["value"],
                        "confidence": prop["confidence"],
                        "evidence_count": 0,
                        "contradiction_count": 0,
                        "support_weight": 0.0,
                        "oppose_weight": 0.0,
                        "first_seen": prop["first_seen"],
                        "last_seen": prop["last_seen"],
                        "source_types": ["promotion"],
                        "provenance_types": ["derived"],
                        "decay_policy": "standard",
                        "session_ids": [],
                        "evidence_refs": sorted({
                            ref for source_id in prop["promoted_from"]
                            for ref in beliefs_by_id.get(source_id, {}).get("evidence_refs", [])
                        })[-25:],
                        "origin": "promoted",
                        "promoted_from": prop["promoted_from"],
                        "promotion_reason": prop["reason"],
                        "promotion_policy": prop["policy"],
                        "status": "active",
                        "rejected_by_user": False,
                        "ceiling": prop["confidence"],
                        "limiting_factor": "promotion_discount",
                        "notes": None,
                    }
                )
                existing_keys.add(key)

        beliefs.sort(key=lambda b: (b["dimension"], -b["confidence"], b["scope"]))

        # -- assemble ------------------------------------------------------
        profile["beliefs"] = beliefs
        profile["onboarding"] = onboarding
        profile["domains_seen"] = sorted(domains_seen)
        profile["projects_seen"] = sorted(projects_seen)
        profile["rejections"] = sorted(rejections.values(), key=lambda r: r["rejected_at"])
        profile["cross_domain_hypotheses"] = cross_domain_hypotheses(
            beliefs, domains_seen, policy=self.policy
        )
        profile["contradictions"] = detect_contradictions(beliefs)
        profile["uncertainties"] = detect_uncertainties(beliefs)
        _project_sections(profile, beliefs)
        profile["privacy"]["refusals_recorded"] = refusals
        profile["materialized_from"] = {
            "event_count": total,
            "quarantined_event_count": quarantined,
            "last_event_id": (last_event or {}).get("event_id"),
            "last_event_ts": (last_event or {}).get("ts"),
            "last_event_sequence": (last_event or {}).get("sequence"),
            "fold_hash": sha256_of(beliefs),
            "as_of": as_of,
            "folded_at": utc_now_ms(),
            "skipped_by_branch": skipped_by_branch,
            "active_branch": (
                {
                    "marker_event_id": branch_marker.get("event_id"),
                    "kind": branch_marker.get("kind"),
                    "marker_ts": branch_marker.get("ts"),
                    "cutoff": (branch_marker.get("payload") or {}).get("cutoff"),
                    "cutoff_sequence": cutoff_sequence,
                }
                if branch_marker else None
            ),
        }
        profile["statistics_summary"] = {
            "belief_count": len(beliefs),
            "high_confidence_beliefs": sum(1 for b in beliefs if b["confidence"] >= 0.7),
            "medium_confidence_beliefs": sum(1 for b in beliefs if 0.4 <= b["confidence"] < 0.7),
            "hypotheses": len(profile["cross_domain_hypotheses"]),
            "contradictions_open": len(profile["contradictions"]),
            "domains_with_evidence": len({b["domain"] for b in beliefs if b.get("domain")}),
            "quarantined_events": quarantined,
            "promoted_beliefs": sum(1 for b in beliefs if b.get("origin") == "promoted"),
            "rejected_beliefs": sum(1 for b in beliefs if b.get("rejected_by_user")),
        }
        profile["constitution_hash"] = constitution_hash()
        return profile

    def rebuild(self, reason="manual", as_of=None, minimum_sequence=None):
        """Re-fold from events and persist.  This is also the conflict resolver."""
        with FileLock(self.lock_path):
            if minimum_sequence is not None and self.path.is_file():
                current, _ = read_json_resilient(
                    self.path, backups_dir=self.backups, logs_dir=self.logs
                )
                materialized = (current or {}).get("materialized_from") or {}
                if (materialized.get("as_of") is None
                        and int(materialized.get("last_event_sequence") or 0)
                        >= int(minimum_sequence)):
                    return current
            # Folding under the materialisation lock is load-bearing. Folding
            # before acquiring it allows an older, slower fold to overwrite a
            # newer one. Event appends remain lock-free and distinct-file based.
            profile = self.fold(as_of=as_of)
            backup_file(self.path, self.backups, tag="rebuild")
            from .config import ConfigStore
            keep = int(ConfigStore(self.home).load().get("retention", {}).get("backup_count", 60))
            prune_backups(self.backups, keep=keep)
            on_disk, _ = read_json_resilient(self.path, backups_dir=self.backups, logs_dir=self.logs)
            profile["revision"] = (on_disk or {}).get("revision", 0) + 1
            profile["updated_at"] = utc_now()
            profile["last_rebuild"] = {"at": utc_now(), "reason": reason}
            write_json_atomic(self.path, profile)
        return profile

    # -- convenience -------------------------------------------------------
    def observe(self, dimension, value, source_type, provenance, **kwargs):
        """Record an explicitly labelled observation; retained for imports.

        New callers should use the intention-specific methods below so a
        high-trust provenance/source pair is selected by code rather than
        supplied as two freely combinable strings.
        """
        scope = kwargs.pop("scope", "global")
        scope_key = kwargs.pop("scope_key", None)
        polarity = kwargs.pop("polarity", "support")
        decay_policy = kwargs.pop("decay_policy", "standard")
        note = kwargs.pop("note", None)
        event = self.events.record(
            kwargs.pop("kind", "observation"),
            provenance,
            observation={
                "dimension": dimension,
                "value": value,
                "source_type": source_type,
                "polarity": polarity,
                "scope": scope,
                "scope_key": scope_key,
                "decay_policy": decay_policy,
                "note": note,
            },
            **kwargs,
        )
        # A concurrent rebuild may already include this event. Avoid serially
        # repeating the same fold for every writer, which is especially costly
        # on Windows filesystems.
        profile = self.rebuild(
            reason="observation", minimum_sequence=event.get("sequence")
        )
        return event, profile

    def observe_user(self, dimension, value, source_type="explicit_statement", **kwargs):
        allowed = {"explicit_statement", "explicit_correction", "explicit_rejection",
                   "comparative_choice", "repeated_selection"}
        if source_type not in allowed:
            raise ValueError("user observation source must be one of: %s" % ", ".join(sorted(allowed)))
        return self.observe(dimension, value, source_type, "direct_user_message", **kwargs)

    def observe_edit(self, dimension, value, **kwargs):
        return self.observe(dimension, value, "direct_edit", "direct_user_edit", **kwargs)

    def observe_review(self, dimension, value, source_type="explicit_correction", **kwargs):
        allowed = {"explicit_statement", "explicit_correction", "explicit_rejection",
                   "comparative_choice", "repeated_selection"}
        if source_type not in allowed:
            raise ValueError("review observation source must be one of: %s" % ", ".join(sorted(allowed)))
        return self.observe(dimension, value, source_type, "explicit_user_review", **kwargs)

    def observe_inference(self, dimension, value, source_type="agent_inference", **kwargs):
        allowed = {"agent_inference", "single_behavioral", "repeated_behavioral", "outcome_signal"}
        if source_type not in allowed:
            raise ValueError("inference source must be one of: %s" % ", ".join(sorted(allowed)))
        return self.observe(dimension, value, source_type, "agent_inference", **kwargs)

    def observe_untrusted(self, dimension, value, provenance, source_type="agent_inference", **kwargs):
        from .evidence import PROVENANCE_TRUST
        if provenance not in PROVENANCE_TRUST or PROVENANCE_TRUST[provenance] > 0.0:
            raise ValueError("observe_untrusted requires a zero-trust provenance")
        return self.observe(dimension, value, source_type, provenance, **kwargs)

    def reject(self, dimension, value=None, reason=None, inference_source=None,
               session_id=None, scope="global", scope_key=None):
        """Record that the user says a belief is wrong about them."""
        self.events.record(
            "rejection",
            "direct_user_message",
            payload={
                "dimension": dimension,
                "value": value,
                "reason": reason,
                "inference_source": inference_source,
                "scope": scope,
                "scope_key": scope_key,
            },
            session_id=session_id,
        )
        return self.rebuild(reason="user_rejection")

    def forget(self, dimension=None, belief_key_=None, project_id=None, session_id=None):
        """Tombstone a dimension, belief or project.

        Evidence before the tombstone no longer affects the profile. Evidence
        explicitly supplied later can establish a new belief, so forgetting is
        not an accidental permanent ban on learning that dimension.
        """
        self.events.record(
            "forget",
            "direct_user_message",
            payload={
                "dimension": dimension,
                "belief_key": belief_key_,
                "project_id": project_id,
            },
            session_id=session_id,
        )
        return self.rebuild(reason="user_forget")

    def rollback(self, cutoff, reason=None, session_id=None):
        """Select a durable event-log branch ending at *cutoff*.

        The skipped events remain immutable and auditable. New events recorded
        after the rollback marker form the active branch.
        """
        event = self.events.record(
            "rollback",
            "direct_user_message",
            payload={"cutoff": cutoff, "reason": reason},
            session_id=session_id,
        )
        return event, self.rebuild(reason="user_rollback")

    def context_view(self, domain=None, project_id=None, min_confidence=0.35):
        profile = self.load()
        return resolve_for_context(
            profile.get("beliefs", []),
            domain=domain,
            project_id=project_id,
            min_confidence=min_confidence,
        )


# ---------------------------------------------------------------------------
# Derived views
# ---------------------------------------------------------------------------

def _norm(value):
    from .scope import _norm as scope_norm  # local import keeps the module graph flat
    return scope_norm(value)


def _project_sections(profile, beliefs):
    """Populate the named, human-friendly sections from the belief list."""
    for section in PROFILE_SECTIONS:
        profile[section] = {}
    for field in LIST_SECTIONS:
        profile[field] = []

    section_names = set(PROFILE_SECTIONS)
    list_roots = {root: field for field, root in LIST_SECTIONS.items()}

    for b in beliefs:
        if b.get("status") not in ("active",):
            continue
        # These named sections are the global user model. Domain/project
        # beliefs remain fully available in the canonical beliefs list and in
        # context-specific reports, but must not masquerade as global defaults.
        if b.get("scope") != "global":
            continue
        dim = b.get("dimension") or ""
        root, _, leaf = dim.partition(".")
        entry = {
            "value": b["value"],
            "confidence": b["confidence"],
            "scope": b["scope"],
            "scope_key": b["scope_key"],
            "evidence_count": b["evidence_count"],
            "contradiction_count": b["contradiction_count"],
            "first_seen": b["first_seen"],
            "last_seen": b["last_seen"],
            "source_types": b["source_types"],
            "origin": b.get("origin", "observed"),
            "belief_id": b["id"],
        }
        if root in section_names and leaf:
            bucket = profile[root].setdefault(leaf, {"candidates": []})
            bucket["candidates"].append(entry)
        elif root in list_roots:
            item = dict(entry)
            item["name"] = leaf or dim
            profile[list_roots[root]].append(item)

    # Collapse each dimension to a winner plus its alternatives.
    for section in PROFILE_SECTIONS:
        for leaf, bucket in profile[section].items():
            candidates = sorted(bucket["candidates"], key=lambda c: -c["confidence"])
            winner = dict(candidates[0])
            winner["alternatives"] = candidates[1:4]
            profile[section][leaf] = winner

    for field in LIST_SECTIONS:
        profile[field].sort(key=lambda item: -item["confidence"])


def detect_contradictions(beliefs):
    """Find dimensions where active beliefs materially disagree.

    Contradictions are *reported*, not resolved.  Resolution needs context that
    only the current task provides, and often the honest answer is "both are
    true, at different scopes".
    """
    by_dim = {}
    for b in beliefs:
        if b.get("status") != "active" or b.get("rejected_by_user"):
            continue
        if b.get("confidence", 0.0) < 0.3:
            continue
        by_dim.setdefault(b["dimension"], []).append(b)

    out = []
    for dim, group in sorted(by_dim.items()):
        values = {}
        for b in group:
            values.setdefault(_norm(b["value"]), []).append(b)
        if len(values) < 2:
            continue
        ranked = sorted(group, key=lambda b: -b["confidence"])
        top, second = ranked[0], next(
            (b for b in ranked[1:] if _norm(b["value"]) != _norm(ranked[0]["value"])), None
        )
        if second is None:
            continue
        same_scope = top["scope"] == second["scope"] and top["scope_key"] == second["scope_key"]
        out.append(
            {
                "dimension": dim,
                "type": "same_scope_conflict" if same_scope else "cross_scope_tension",
                "severity": round(min(top["confidence"], second["confidence"]), 4),
                "resolvable_by_scope": not same_scope,
                "candidates": [
                    {
                        "value": b["value"],
                        "confidence": b["confidence"],
                        "scope": b["scope"],
                        "scope_key": b["scope_key"],
                        "last_seen": b["last_seen"],
                        "source_types": b["source_types"],
                        "belief_id": b["id"],
                    }
                    for b in (top, second)
                ],
                "suggested_resolution": (
                    "narrower scope wins for the current context"
                    if not same_scope
                    else "prefer the more recent, more directly sourced value; ask only if it "
                         "materially changes the current work"
                ),
            }
        )
    return out


def detect_uncertainties(beliefs, threshold=0.45):
    """Dimensions LIWM is aware it does not understand well."""
    by_dim = {}
    for b in beliefs:
        if b.get("status") != "active":
            continue
        cur = by_dim.get(b["dimension"])
        if cur is None or b["confidence"] > cur["confidence"]:
            by_dim[b["dimension"]] = b
    out = []
    for dim, b in sorted(by_dim.items()):
        if b["confidence"] < threshold:
            out.append(
                {
                    "dimension": dim,
                    "best_guess": b["value"],
                    "confidence": b["confidence"],
                    "limiting_factor": b.get("limiting_factor"),
                    "evidence_count": b["evidence_count"],
                    "why_uncertain": (
                        "capped by weak source types (%s)" % ", ".join(b["source_types"])
                        if b.get("limiting_factor", "").startswith("ceiling")
                        else "insufficient evidence"
                    ),
                }
            )
    return out
