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
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .evidence import PROVENANCE_TRUST, TRUSTED_PROVENANCE
from .jsonio import (
    FileLock,
    lifecycle_lock_path,
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

SCHEMA_VERSION = "0.2.0"

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
        # intent state graph
        "intent_node",
        "intent_edge",
        # learning machinery
        "scope_promotion",
        "scope_demotion",
        "strategy_update",
        "candidate_rule",
        "experiment_started",
        "experiment_assignment",
        "experiment_stopped",
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
HIGH_TRUST_SOURCES = frozenset({
    "explicit_statement", "explicit_correction", "explicit_rejection",
    "direct_edit", "repeated_selection", "comparative_choice", "onboarding_answer",
})
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
                    # Never retain the rejected dimension/value, even when the
                    # user explicitly enabled general free-text storage.
                    "location": "observation",
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
        self.manifest_path = self.home / "events-manifest.json"
        self.lock_path = self.home / ".events.lock"
        self.transaction_path = self.home / "events-transaction.json"
        self.archive_root = self.home / "archives"
        self.archive_index_path = self.archive_root / "index.json"

    def _archive_index(self):
        index = read_json(self.archive_index_path, default=None)
        if index is None:
            return {"schema_version": SCHEMA_VERSION, "archives": []}
        if not isinstance(index, dict):
            raise ValueError("archive index must be an object")
        integrity = index.get("integrity") or {}
        body = {k: v for k, v in index.items() if k != "integrity"}
        if integrity.get("hash") != sha256_of(body):
            raise ValueError("archive index integrity mismatch")
        return index

    def _write_archive_index(self, archives):
        self.archive_root.mkdir(parents=True, exist_ok=True)
        body = {"schema_version": SCHEMA_VERSION, "archives": archives}
        body["integrity"] = {"algo": "sha256", "hash": sha256_of(body)}
        write_json_atomic(self.archive_index_path, body, fsync=True)

    def _archive_frontier(self):
        archives = self._archive_index().get("archives") or []
        return max((int(row.get("last_sequence") or 0) for row in archives), default=0)

    def _iter_archived_events(self):
        for row in sorted(self._archive_index().get("archives") or [],
                          key=lambda item: int(item.get("first_sequence") or 0)):
            path = self.archive_root / row["path"]
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        yield json.loads(line)

    def _manifest(self):
        manifest = read_json(self.manifest_path, default=None)
        if not isinstance(manifest, dict):
            return None
        integrity = manifest.get("integrity") or {}
        body = {k: v for k, v in manifest.items() if k != "integrity"}
        if integrity.get("hash") != sha256_of(body):
            raise ValueError("event manifest integrity mismatch")
        return manifest

    @staticmethod
    def _chain_step(previous, sequence, event_id, event_hash):
        return sha256_of({
            "previous": previous, "sequence": sequence,
            "event_id": event_id, "event_hash": event_hash,
        })

    def _write_manifest(self, state):
        body = {"schema_version": SCHEMA_VERSION, **state}
        body["integrity"] = {"algo": "sha256", "hash": sha256_of(body)}
        write_json_atomic(self.manifest_path, body, fsync=True)

    def _write_transaction(self, body):
        body = dict(body)
        body["integrity"] = {"algo": "sha256", "hash": sha256_of(body)}
        write_json_atomic(self.transaction_path, body, fsync=True)

    def _recover_transaction_locked(self):
        journal = read_json(self.transaction_path, default=None)
        if not journal:
            return
        body = {key: value for key, value in journal.items() if key != "integrity"}
        if (journal.get("integrity") or {}).get("hash") != sha256_of(body):
            raise ValueError("event transaction journal integrity mismatch")
        if journal.get("operation") == "append":
            path = self.root / journal["path"]
            if path.is_file():
                event = read_json(path)
                if _integrity_issue(event):
                    raise ValueError("interrupted append left an invalid event")
                self._write_manifest(journal["manifest"])
        elif journal.get("operation") == "compact":
            archive = self.archive_root / journal["archive"]
            checkpoint = self.home / journal["checkpoint"]
            indexed = any(
                row.get("path") == journal["archive"]
                for row in self._archive_index().get("archives", [])
            )
            complete = archive.is_file() and checkpoint.is_file() and indexed
            if complete:
                for relative in journal["live_paths"]:
                    (self.root / relative).unlink(missing_ok=True)
                self._write_manifest(journal["manifest"])
            else:
                self._write_archive_index(journal["old_archives"])
                archive.unlink(missing_ok=True)
                checkpoint.unlink(missing_ok=True)
        else:
            raise ValueError("unknown event transaction operation")
        self.transaction_path.unlink(missing_ok=True)

    def _index_existing(self):
        base = self._archive_frontier()
        chain = None
        recent = []
        last = base
        rows = []
        for offset, path in enumerate(self._scan_paths(), 1):
            event = read_json(path)
            rows.append((int(event.get("sequence") or (base + offset)), path, event))
        for offset, (sequence, path, event) in enumerate(sorted(rows), 1):
            if sequence != base + offset:
                raise ValueError("event sequence gap at %s" % path)
            event_id = event.get("event_id")
            event_hash = (event.get("integrity") or {}).get("hash")
            chain = self._chain_step(chain, sequence, event_id, event_hash)
            recent.append(event_id)
            last = sequence
        return {
            "base_sequence": base,
            "event_count": last - base,
            "last_sequence": last,
            "chain_head": chain,
            # ponytail: a bounded retry guard keeps append O(1); full uniqueness
            # remains fail-closed in verify().
            "recent_event_ids": recent[-256:],
        }

    # -- writing -----------------------------------------------------------
    def append(self, event):
        """Persist *event* and return its path."""
        _validate_event_envelope(event)
        # ponytail: one short global append lock; shard-local sequencing can replace it
        # if measured write throughput ever makes this a bottleneck.
        with FileLock(lifecycle_lock_path(self.home), timeout=30.0):
            with FileLock(self.lock_path, timeout=30.0):
                return self._append_locked(event)

    def _append_locked(self, event):
        """Append while the caller holds the lifecycle and event locks."""
        _validate_event_envelope(event)
        self._recover_transaction_locked()
        manifest = self._manifest()
        state = self._index_existing() if not manifest or "entries" in manifest else {
                "base_sequence": int(manifest.get("base_sequence") or 0),
                "event_count": int(manifest.get("event_count") or 0),
                "last_sequence": int(manifest.get("last_sequence") or 0),
                "chain_head": manifest.get("chain_head"),
                "recent_event_ids": list(manifest.get("recent_event_ids") or []),
        }
        if event["event_id"] in state["recent_event_ids"]:
            raise ValueError("duplicate event_id %s" % event["event_id"])
        event["sequence"] = max(state["last_sequence"], self._archive_frontier()) + 1
        event["integrity"] = {
            "algo": "sha256", "hash": sha256_of({k: v for k, v in event.items()
                                                   if k != "integrity"})
        }
        ts = event.get("ts") or utc_now_ms()
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        shard = self.root / parsed.strftime("%Y-%m")
        shard.mkdir(parents=True, exist_ok=True)
        safe_ts = ts.replace(":", "").replace("-", "").replace(".", "")
        name = "%s-%s.json" % (safe_ts, event["event_id"][4:12])
        path = shard / name
        while path.exists():  # pragma: no cover
            name = "%s-%s.json" % (safe_ts, uuid.uuid4().hex[:8])
            path = shard / name
        recent = (state["recent_event_ids"] + [event["event_id"]])[-256:]
        next_manifest = {
            "base_sequence": state["base_sequence"],
            "event_count": state["event_count"] + 1,
            "last_sequence": event["sequence"],
            "chain_head": self._chain_step(
                state["chain_head"], event["sequence"], event["event_id"],
                event["integrity"]["hash"],
            ),
            "recent_event_ids": recent,
        }
        self._write_transaction({
            "schema_version": SCHEMA_VERSION, "operation": "append",
            "path": str(path.relative_to(self.root)), "manifest": next_manifest,
        })
        write_json_atomic(path, event, fsync=True)
        self._write_manifest(next_manifest)
        self.transaction_path.unlink(missing_ok=True)
        return path

    def transaction(self, callback):
        """Run one event-log check-and-append operation atomically."""
        with FileLock(lifecycle_lock_path(self.home), timeout=30.0):
            with FileLock(self.lock_path, timeout=30.0):
                return callback(self)

    def record(self, kind, provenance, **kwargs):
        """Build and persist an event in one step; returns the event."""
        event = make_event(kind, provenance, **kwargs)
        from .config import ConfigStore
        if not ConfigStore(self.home).load().get("privacy", {}).get("store_free_text", False):
            event = _without_free_text(event)
        self.append(event)
        return event

    def record_if(self, kind, provenance, predicate, **kwargs):
        """Atomically validate the current log and append one event."""
        event = make_event(kind, provenance, **kwargs)
        from .config import ConfigStore
        if not ConfigStore(self.home).load().get("privacy", {}).get("store_free_text", False):
            event = _without_free_text(event)

        def commit(store):
            predicate(list(store.iter_events(include_quarantined=True)))
            store._append_locked(event)
            return event

        return self.transaction(commit)

    # -- reading -----------------------------------------------------------
    def shards(self):
        if not self.root.is_dir():
            return []
        return sorted(d for d in self.root.iterdir() if d.is_dir())

    def _scan_paths(self, since_shard=None):
        for shard in self.shards():
            if since_shard and shard.name < since_shard:
                continue
            for path in sorted(shard.glob("*.json")):
                yield path

    def iter_paths(self, since_shard=None):
        yield from self._scan_paths(since_shard=since_shard)

    def iter_events(self, kinds=None, project_id=None, session_id=None,
                    include_quarantined=False, since=None, limit=None):
        """Yield events in timestamp order, with cheap filtering."""
        count = 0
        sources = list(self._iter_archived_events())
        base = self._archive_frontier()
        live = []
        for offset, path in enumerate(self.iter_paths(), 1):
            try:
                event = read_json(path)
                if not event.get("sequence"):
                    # v0.1 events were sealed before append sequences existed.
                    # Verify the original bytes first, then create a resealed
                    # in-memory ordering view; never hash the transient field
                    # against the legacy seal.
                    if _integrity_issue(event) is None:
                        event = dict(event, sequence=base + offset)
                        event["integrity"] = {
                            "algo": "sha256",
                            "hash": sha256_of({
                                key: value for key, value in event.items()
                                if key != "integrity"
                            }),
                        }
                live.append(event)
            except Exception:  # noqa: BLE001 - a single bad file must not kill a fold
                self._log_bad(path)
        sources.extend(sorted(live, key=lambda event: int(event.get("sequence") or 0)))
        sources.sort(key=lambda event: int((event or {}).get("sequence") or 0))
        for event in sources:
            if not isinstance(event, dict):
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
    def verify(self, _events_locked=False):
        """Recompute every event hash; return a report of any mismatches."""
        if not _events_locked:
            with FileLock(lifecycle_lock_path(self.home), timeout=30.0):
                with FileLock(self.lock_path, timeout=30.0):
                    return self.verify(_events_locked=True)
        self._recover_transaction_locked()
        checked = tampered = unreadable = missing_integrity = 0
        problems = []
        archive_ids = set()
        archive_frontier = 0
        try:
            archive_index = self._archive_index()
            for row in archive_index.get("archives") or []:
                path = self.archive_root / row["path"]
                if not path.is_file():
                    problems.append({"path": str(path), "issue": "archive_missing"})
                    continue
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest != row.get("sha256"):
                    problems.append({"path": str(path), "issue": "archive_hash_mismatch"})
                    continue
                archive_events = []
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    archive_events = [json.loads(line) for line in handle if line.strip()]
                if len(archive_events) != int(row.get("event_count") or -1):
                    problems.append({"path": str(path), "issue": "archive_count_mismatch"})
                for archived in archive_events:
                    issue = _integrity_issue(archived)
                    if issue:
                        problems.append({"path": str(path), "issue": issue,
                                         "event_id": archived.get("event_id")})
                    event_id = archived.get("event_id")
                    if event_id in archive_ids:
                        problems.append({"path": str(path), "issue": "duplicate_event_id",
                                         "event_id": event_id})
                    archive_ids.add(event_id)
                archive_frontier = max(archive_frontier, int(row.get("last_sequence") or 0))
        except Exception as exc:  # noqa: BLE001
            problems.append({"path": str(self.archive_index_path),
                             "issue": "archive_invalid", "detail": str(exc)})

        try:
            manifest = self._manifest()
        except Exception as exc:  # noqa: BLE001
            return {"checked": 0, "tampered": 0, "unreadable": 0,
                    "missing_integrity": 0, "manifest_present": True,
                    "ok": False, "problems": [{"path": str(self.manifest_path),
                                                 "issue": "manifest_invalid",
                                                 "detail": str(exc)}]}
        if manifest is None and (any(self._scan_paths()) or archive_frontier):
            problems.append({"path": str(self.manifest_path), "issue": "manifest_missing"})
        legacy_entries = (manifest or {}).get("entries")
        legacy_by_path = {
            entry.get("path"): entry for entry in (legacy_entries or [])
        }
        disk_paths = list(self._scan_paths())
        if legacy_entries is not None:
            indexed = set(legacy_by_path)
            present = {str(path.relative_to(self.root)) for path in disk_paths}
            for missing in sorted(indexed - present):
                problems.append({"path": missing, "issue": "event_missing"})
            for extra in sorted(present - indexed):
                problems.append({"path": extra, "issue": "event_unindexed"})

        live_ids = set(archive_ids)
        live_chain = None
        live_sequences = []
        loaded = []
        for offset, path in enumerate(disk_paths, 1):
            try:
                event = read_json(path)
            except Exception as exc:  # noqa: BLE001
                unreadable += 1
                problems.append({"path": str(path), "issue": "unreadable", "detail": str(exc)})
                continue
            loaded.append((int(event.get("sequence") or (archive_frontier + offset)), path, event))
        for sequence, path, event in sorted(loaded):
            integrity = (event or {}).get("integrity") or {}
            stored = integrity.get("hash")
            if not stored:
                missing_integrity += 1
                problems.append({"path": str(path), "issue": "missing_integrity",
                                 "event_id": (event or {}).get("event_id")})
                continue
            body = {k: v for k, v in event.items() if k != "integrity"}
            checked += 1
            event_id = event.get("event_id")
            live_sequences.append(sequence)
            if event_id in live_ids:
                problems.append({"path": str(path), "issue": "duplicate_event_id",
                                 "event_id": event_id})
            live_ids.add(event_id)
            live_chain = self._chain_step(live_chain, sequence, event_id, stored)
            if sha256_of(body) != stored:
                tampered += 1
                problems.append({"path": str(path), "issue": "hash_mismatch",
                                 "event_id": event_id})
            elif legacy_entries is not None:
                rel = str(path.relative_to(self.root))
                expected = (legacy_by_path.get(rel) or {}).get("hash")
                if expected != stored:
                    problems.append({"path": str(path), "issue": "manifest_hash_mismatch",
                                     "event_id": event_id})
        expected_sequences = list(range(
            archive_frontier + 1, archive_frontier + 1 + len(loaded)
        ))
        if live_sequences != expected_sequences:
            problems.append({"path": str(self.manifest_path), "issue": "sequence_gap"})
        if manifest and legacy_entries is None:
            expected_state = {
                "base_sequence": archive_frontier,
                "event_count": len(loaded),
                "last_sequence": live_sequences[-1] if live_sequences else archive_frontier,
                "chain_head": live_chain,
            }
            for key, actual in expected_state.items():
                if manifest.get(key) != actual:
                    problems.append({
                        "path": str(self.manifest_path),
                        "issue": "manifest_%s_mismatch" % key,
                    })
        return {
            "checked": checked,
            "tampered": tampered,
            "unreadable": unreadable,
            "missing_integrity": missing_integrity,
            "manifest_present": manifest is not None,
            "ok": tampered == 0 and unreadable == 0 and missing_integrity == 0 and not problems,
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
        for event in self.iter_events(include_quarantined=True):
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

    kind = (event or {}).get("kind")
    payload = (event or {}).get("payload") or {}
    if kind in {"correction", "onboarding_answer"} and provenance not in {
            "direct_user_message", "explicit_user_review"}:
        return "%s_requires_direct_user" % kind
    if kind == "feedback":
        channel = payload.get("channel")
        allowed = {
            "explicit": {"direct_user_message", "explicit_user_review"},
            "corrective": {"direct_user_message", "explicit_user_review"},
            "comparative": {"direct_user_message", "explicit_user_review"},
            "repeated_comparative": {"direct_user_message", "explicit_user_review"},
            "edit": {"direct_user_edit"},
            "outcome": {"agent_inference"}, "behavioral": {"agent_inference"},
            "repeated_behavioral": {"agent_inference"},
        }
        if channel in allowed and provenance not in allowed[channel]:
            return "feedback_channel_provenance_mismatch:%s:%s" % (channel, provenance)
    if kind == "outcome" and payload.get("evaluator_type") == "observed_human_outcome" \
            and provenance != "explicit_user_review":
        return "observed_outcome_requires_user_review"

    observation = (event or {}).get("observation") or {}
    source = observation.get("source_type")
    scope = observation.get("scope", "global")
    scope_key = observation.get("scope_key")
    if scope == "project" and not (scope_key or (event or {}).get("project_id")):
        return "missing_scope_key:project"
    if scope == "domain" and not (scope_key or (event or {}).get("domain")):
        return "missing_scope_key:domain"
    if provenance == "agent_inference" and source in HIGH_TRUST_SOURCES:
        return "source_provenance_mismatch:%s:%s" % (provenance, source)
    if source == "direct_edit" and provenance != "direct_user_edit":
        return "source_requires_provenance:%s:%s" % (source, "direct_user_edit")
    if source == "onboarding_answer" and provenance != "onboarding_answer":
        return "source_requires_provenance:%s:%s" % (source, "onboarding_answer")
    if provenance == "onboarding_answer" and source not in (None, "onboarding_answer"):
        return "source_provenance_mismatch:%s:%s" % (provenance, source)
    if provenance == "onboarding_answer" and not (event or {}).get("session_id"):
        return "onboarding_requires_session"
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
#: something was refused.  ``belief_key`` is LIWM's own composite identity and
#: is pipe-separated, so shape alone reads it as prose; without it here, a
#: ``forget --belief`` tombstone reached disk with its subject stripped out and
#: quietly forgot nothing.
STRUCTURAL_KEYS = frozenset({
    "value", "label", "dimension", "scope_key", "belief_key", "path", "issue",
    "quarantine_reason",
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
