"""Opt-in, local-only study exports derived from the existing event log."""

from __future__ import annotations

import hashlib
import math
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ConfigStore
from .events import EventStore
from .jsonio import utc_now, write_json_atomic

__all__ = ["set_study_enabled", "study_status", "export_study"]

_MEASUREMENT_KEYS = frozenset({
    "acceptance", "actual_acceptance", "predicted_acceptance", "confidence",
    "utility", "changed_plan", "questions_asked", "questions_answered",
    "questions_skipped", "questions_useful", "questions_wasted", "corrections",
})
_MODES = frozenset({"auto", "low", "medium", "high", "off"})
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


def export_study(home, out=None, anonymise=False):
    """Write a minimized event-derived export; never sends it anywhere."""
    home = Path(home)
    status = study_status(home)
    if not status["enabled"]:
        raise ValueError("study mode is off; run 'liwm study on' before exporting")

    cutoff = datetime.now(timezone.utc) - timedelta(days=status["retention_days"])
    start_sequence = int(status.get("start_sequence") or 0)
    salt = uuid.uuid4().hex

    def pseudonym(value, prefix):
        if value is None:
            return None
        digest = hashlib.sha256((salt + "\0" + str(value)).encode("utf-8")).hexdigest()[:12]
        return "%s_%s" % (prefix, digest)

    rows = []
    for event in EventStore(home).iter_events():
        if int(event.get("sequence") or 0) <= start_sequence:
            continue
        try:
            event_time = datetime.fromisoformat(str(event.get("ts", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if event_time < cutoff:
            continue
        row = {
            "event_id": event.get("event_id"),
            "ts": event.get("ts"),
            "kind": event.get("kind"),
            "provenance": event.get("provenance"),
            "quarantined": bool(event.get("quarantined")),
            "session_id": event.get("session_id"),
            "project_id": event.get("project_id"),
            "domain": event.get("domain"),
            "mode": ((event.get("payload") or {}).get("mode")
                     if (event.get("payload") or {}).get("mode") in _MODES else None),
            "condition": ((event.get("payload") or {}).get("condition")
                          if (event.get("payload") or {}).get("condition") in _CONDITIONS else None),
            "task_id": (event.get("payload") or {}).get("task_id"),
            "task_type": ((event.get("payload") or {}).get("task_type")
                          if (event.get("payload") or {}).get("task_type") in _TASK_TYPES else None),
            "measurements": _measurements(event.get("payload")),
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
        rows.append(row)

    payload = {
        "export_format": "liwm-study-event-view-v1",
        "exported_at": utc_now(),
        "anonymised": bool(anonymise),
        "local_only": True,
        "automatic_upload": False,
        "retention_days": status["retention_days"],
        "events": rows,
        "privacy_notice": (
            "This minimized export may still be linkable or identifying. "
            "Inspect it before sharing; anonymisation is risk reduction, not a guarantee."
        ),
    }
    target = Path(out).expanduser() if out else (
        home / "exports" / ("liwm-study-%s.json" % utc_now().replace(":", ""))
    )
    write_json_atomic(target, payload)
    return {"path": str(target), "bytes": target.stat().st_size, **payload}
