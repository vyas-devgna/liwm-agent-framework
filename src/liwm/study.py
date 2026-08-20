"""Opt-in, local-only study exports derived from the existing event log."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ConfigStore
from .events import EventStore
from .jsonio import utc_now, write_json_atomic

__all__ = ["set_study_enabled", "study_status", "export_study",
           "study_key_status", "rotate_study_key", "delete_study_key"]

#: Where the longitudinal pseudonym key lives.  Local, never exported, never
#: uploaded, and deletable.  Holding it is what lets two exports from the same
#: participant be joined; deleting it is what makes that permanently
#: impossible, which is the point of being able to.
_KEY_FILE = "study-key.json"

_MEASUREMENT_KEYS = frozenset({
    "acceptance", "actual_acceptance", "predicted_acceptance", "confidence",
    "utility", "changed_plan", "questions_asked", "questions_answered",
    "questions_skipped", "questions_useful", "questions_wasted", "corrections",
})
_MODES = frozenset({"auto", "low", "medium", "high", "silent", "off"})
_CONDITIONS = frozenset({"A", "B", "C", "D", "E", "F"})
_TASK_TYPES = frozenset({
    "preference_prediction", "cross_domain_transfer", "question_selection",
    "traceability", "scope_contamination", "poisoning_resistance",
})


def study_status(home):
    config = ConfigStore(home).load().get("study", {})
    return {
        "enabled": bool(config.get("enabled", False)),
        "local_only": True,
        "automatic_upload": False,
        "retention_days": int(config.get("retention_days", 90)),
        "enabled_at": config.get("enabled_at"),
        "start_sequence": config.get("start_sequence"),
        "eligible_events": EventStore(home).count(),
        "quarantined_events": EventStore(home).count(include_quarantined=True)
                              - EventStore(home).count(),
    }


def set_study_enabled(home, enabled):
    config_store = ConfigStore(home)
    config = config_store.load()
    was_enabled = bool(config.get("study", {}).get("enabled"))
    config["study"]["enabled"] = bool(enabled)
    if enabled and not was_enabled:
        manifest = EventStore(home)._manifest() or {}
        config["study"]["enabled_at"] = utc_now()
        config["study"]["start_sequence"] = int(manifest.get("last_sequence") or 0)
    config_store.save(config)
    return study_status(home)


def _measurements(payload):
    out = {}
    counts = {key for key in _MEASUREMENT_KEYS if key.startswith("questions_")} | {"corrections"}
    for key, value in (payload or {}).items():
        if key not in _MEASUREMENT_KEYS or not isinstance(value, (int, float, bool)):
            continue
        if isinstance(value, bool):
            if key == "changed_plan":
                out[key] = value
            continue
        value = float(value)
        if not math.isfinite(value):
            continue
        if key in counts:
            if value >= 0 and value.is_integer() and value <= 1_000_000:
                out[key] = int(value)
        elif 0.0 <= value <= 1.0:
            out[key] = value
    return out


def _key_path(home):
    return Path(home) / _KEY_FILE


def study_key_status(home):
    path = _key_path(home)
    if not path.is_file():
        return {"exists": False, "path": str(path)}
    body = json.loads(path.read_text(encoding="utf-8"))
    return {"exists": True, "path": str(path), "created_at": body.get("created_at"),
            "study_id": body.get("study_id"),
            "fingerprint": hashlib.sha256(
                body["key"].encode("utf-8")).hexdigest()[:8]}


def rotate_study_key(home, study_id=None):
    """Mint a new longitudinal key, severing linkage to earlier exports."""
    path = _key_path(home)
    body = {"key": uuid.uuid4().hex, "created_at": utc_now(),
            "study_id": study_id or ("study_%s" % uuid.uuid4().hex[:8])}
    write_json_atomic(path, body)
    return study_key_status(home)


def delete_study_key(home):
    """Destroy the key.  Exports already made can never be joined again."""
    existed = _key_path(home).is_file()
    _key_path(home).unlink(missing_ok=True)
    return {"deleted": existed, "path": str(_key_path(home))}


def _longitudinal_key(home):
    if not _key_path(home).is_file():
        rotate_study_key(home)
    body = json.loads(_key_path(home).read_text(encoding="utf-8"))
    return body["key"], body["study_id"]


def export_study(home, out=None, anonymise=False, longitudinal=False):
    """Write a minimized event-derived export; never sends it anywhere.

    Two anonymisation modes, because they want opposite things.  A one-off
    export salts freshly, so two exports of the same session cannot be linked
    by anyone, including the researcher.  A longitudinal export must be
    joinable across weeks, so it uses a locally stored study key and reports
    time as offsets from the study start rather than as wall-clock stamps.
    Stable pseudonyms are pseudonymity, not anonymity, and the notice says so.
    """
    home = Path(home)
    status = study_status(home)
    if not status["enabled"]:
        raise ValueError("study mode is off; run 'liwm study on' before exporting")
    if longitudinal and not anonymise:
        raise ValueError("a longitudinal export is an anonymised export; pass --anonymise")

    cutoff = datetime.now(timezone.utc) - timedelta(days=status["retention_days"])
    start_sequence = int(status.get("start_sequence") or 0)
    study_id = None
    if longitudinal:
        salt, study_id = _longitudinal_key(home)
    else:
        salt = uuid.uuid4().hex

    def pseudonym(value, prefix):
        if value is None:
            return None
        digest = hashlib.sha256((salt + "\0" + str(value)).encode("utf-8")).hexdigest()[:12]
        return "%s_%s" % (prefix, digest)

    eligible = [event for event in EventStore(home).iter_events()
                if int(event.get("sequence") or 0) > start_sequence]
    study_start = None
    if longitudinal:
        stamps = [_parse(event.get("ts")) for event in eligible]
        study_start = min([stamp for stamp in stamps if stamp], default=None)
    session_ordinal, task_ordinal = {}, {}

    rows = []
    for event in eligible:
        event_time = _parse(event.get("ts"))
        if event_time is None or event_time < cutoff:
            continue
        payload = event.get("payload") or {}
        row = {
            "event_id": event.get("event_id"),
            "ts": event.get("ts"),
            "kind": event.get("kind"),
            "provenance": event.get("provenance"),
            "quarantined": bool(event.get("quarantined")),
            "session_id": event.get("session_id"),
            "project_id": event.get("project_id"),
            "domain": event.get("domain"),
            "mode": (payload.get("mode") if payload.get("mode") in _MODES else None),
            "condition": (payload.get("condition")
                          if payload.get("condition") in _CONDITIONS else None),
            "task_id": payload.get("task_id"),
            "task_type": (payload.get("task_type")
                          if payload.get("task_type") in _TASK_TYPES else None),
            "measurements": _measurements(payload),
        }
        if anonymise:
            row.update({
                "event_id": pseudonym(row["event_id"], "event"),
                "ts": str(row["ts"] or "")[:7] or None,
                "session_id": pseudonym(row["session_id"], "session"),
                "project_id": pseudonym(row["project_id"], "project"),
                "domain": pseudonym(row["domain"], "domain"),
                "task_id": pseudonym(row["task_id"], "task"),
            })
        if longitudinal:
            # Wall-clock stamps identify a person by their working hours, so a
            # longitudinal export carries ordering instead: enough structure for
            # a mixed-effects model, not enough to say when anything happened.
            row["ts"] = None
            row["relative_day"] = (
                (event_time - study_start).days if study_start else None)
            row["event_sequence_offset"] = int(event.get("sequence") or 0) - start_sequence
            if row["session_id"] is not None:
                session_ordinal.setdefault(row["session_id"], len(session_ordinal) + 1)
                row["session_ordinal"] = session_ordinal[row["session_id"]]
            if row["task_id"] is not None:
                task_ordinal.setdefault(row["task_id"], len(task_ordinal) + 1)
                row["task_ordinal"] = task_ordinal[row["task_id"]]
        rows.append(row)

    payload = {
        "export_format": "liwm-study-event-view-v1",
        "exported_at": utc_now(),
        "anonymised": bool(anonymise),
        "mode": "longitudinal" if longitudinal else "one_off",
        "study_id": study_id,
        "local_only": True,
        "automatic_upload": False,
        "retention_days": status["retention_days"],
        "events": rows,
        "privacy_notice": (
            "Pseudonyms in this export are stable within study %s so repeated "
            "measures can be joined. Stable pseudonyms are pseudonymity, not "
            "anonymity: anyone holding two exports can link them, and the "
            "local key can re-identify every row. Rotate or delete the key when "
            "the study ends. Inspect this file before sharing." % study_id
            if longitudinal else
            "This minimized export may still be linkable or identifying. "
            "Inspect it before sharing; anonymisation is risk reduction, not a guarantee."
        ),
    }
    target = Path(out).expanduser() if out else (
        home / "exports" / ("liwm-study-%s.json" % utc_now().replace(":", ""))
    )
    write_json_atomic(target, payload)
    return {"path": str(target), "bytes": target.stat().st_size, **payload}


def _parse(value):
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
