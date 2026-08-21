"""Local measurement: is this actually working?

``metrics.json`` exists so that claims about LIWM improving are checkable rather
than rhetorical.  It is derived from the event log, so it can always be
recomputed and never drifts from reality.

Everything here is local.  There is no telemetry, no upload, no identifier that
leaves the machine (constitution C12).  The rolling windows keep recent
behaviour dominant so a good month a year ago cannot mask a bad week now.
"""

from __future__ import annotations

import math
from pathlib import Path

from .jsonio import read_json_resilient, utc_now, write_json_atomic
from .prediction import brier, calibration_bins, log_loss

__all__ = ["ROLLING_WINDOW", "compute_metrics", "MetricsStore", "improvement_trend"]

SCHEMA_VERSION = "0.4.0"

#: How many recent outcomes dominate the rolling figures.
ROLLING_WINDOW = 50


def _rate(numerator, denominator):
    if not denominator:
        return None
    return round(numerator / denominator, 4)


#: Below this, a reliability diagram is describing noise.  The number is
#: reported anyway, next to the warning, because hiding it invites someone to
#: recompute it themselves without one.
ECE_MIN_SAMPLES = 30


def _evaluator_key(payload):
    """Evaluator label, keeping unverified historical outcomes distinguishable.

    An outcome resolved before labels had to be derived from their evidence was
    never checked against anything.  Folding those into the same bucket as
    verified ones would make the strongest calibration figure the least
    trustworthy one.
    """
    evaluator = payload.get("evaluator_type") or "unknown"
    if (evaluator == "observed_human_outcome"
            and payload.get("outcome_binding") != "structured_feedback_event"):
        return "observed_human_outcome_unverified"
    return evaluator


def _ece(pairs, bins=10):
    populated = [row for row in calibration_bins(pairs, bins=bins) if row["n"]]
    total = sum(row["n"] for row in populated)
    if not total:
        return None
    return round(sum(row["n"] * abs(row["gap"]) for row in populated) / total, 4)


def compute_metrics(store, window=ROLLING_WINDOW):
    """Recompute every metric from the event log."""
    events = store.events.read_all(include_quarantined=True)

    counters = {
        "meaningful_interactions": 0,
        "feedback_bearing_interactions": 0,
        "explicit_corrections": 0,
        "inferred_corrections": 0,
        "accepted_outputs": 0,
        "rejected_outputs": 0,
        "questions_asked": 0,
        "questions_answered": 0,
        "questions_skipped": 0,
        "questions_ignored": 0,
        "assumptions_made": 0,
        "assumptions_wrong": 0,
        "artifacts": 0,
        "revisions": 0,
        "predictions": 0,
        "predictions_made": 0,
        "predictions_resolved": 0,
        "quarantined_events": 0,
        "privacy_refusals": 0,
        "profile_rejections": 0,
        "scope_promotions": 0,
        "candidate_rules_proposed": 0,
        "candidate_rules_promoted": 0,
        "candidate_rules_rejected": 0,
        "regressions_detected": 0,
        "onboarding_answers": 0,
    }

    acceptance_series = []       # (ts, acceptance)
    prediction_pairs = []        # (predicted, actual)
    categorical_outcomes = []
    calibration_by_domain = {}
    calibration_by_evaluator = {}
    per_mode = {}
    per_scope_corrections = {"global": 0, "domain": 0, "project": 0}
    question_value = {"useful": 0, "redundant": 0, "unknown": 0}
    cross_domain = {"tested": 0, "confirmed": 0}
    sessions = set()
    first_ts = last_ts = None

    for e in events:
        ts = e.get("ts")
        if ts:
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
        if e.get("session_id"):
            sessions.add(e["session_id"])
        if e.get("quarantined"):
            counters["quarantined_events"] += 1
            if e.get("kind") == "refusal":
                counters["privacy_refusals"] += 1
            continue
        kind = e.get("kind")
        payload = e.get("payload") or {}

        if kind == "question_asked":
            counters["questions_asked"] += 1
            mode = payload.get("mode")
            if mode:
                per_mode.setdefault(mode, {"questions": 0, "accepted": 0, "artifacts": 0})
                per_mode[mode]["questions"] += 1
        elif kind == "question_answered":
            counters["questions_answered"] += 1
            value = payload.get("value")
            if value in question_value:
                question_value[value] += 1
            else:
                question_value["unknown"] += 1
        elif kind == "question_skipped":
            if payload.get("reason") == "ignored":
                counters["questions_ignored"] += 1
            else:
                counters["questions_skipped"] += 1
        elif kind == "correction":
            counters["explicit_corrections"] += 1
            scope = payload.get("scope", "project")
            if scope in per_scope_corrections:
                per_scope_corrections[scope] += 1
        elif kind == "rejection":
            counters["profile_rejections"] += 1
        elif kind == "assumption_made":
            counters["assumptions_made"] += 1
        elif kind == "artifact":
            counters["artifacts"] += 1
            if payload.get("revision_of"):
                counters["revisions"] += 1
            mode = payload.get("mode")
            if mode:
                per_mode.setdefault(mode, {"questions": 0, "accepted": 0, "artifacts": 0})
                per_mode[mode]["artifacts"] += 1
        elif kind == "prediction":
            counters["predictions"] += 1
        elif kind == "feedback":
            counters["feedback_bearing_interactions"] += 1
            counters["meaningful_interactions"] += 1
            acc = payload.get("acceptance")
            if acc is not None:
                acceptance_series.append((ts, float(acc)))
                if acc >= 0.8:
                    counters["accepted_outputs"] += 1
                elif acc <= 0.4:
                    counters["rejected_outputs"] += 1
            if payload.get("kind") in ("misunderstood_intent", "should_have_asked"):
                counters["assumptions_wrong"] += 1
            if payload.get("channel") in ("outcome", "behavioral", "repeated_behavioral"):
                counters["inferred_corrections"] += 1
        elif kind == "prediction":
            counters["predictions_made"] += 1
        elif kind == "outcome" and payload.get("target_type") == "categorical_preference":
            counters["predictions_resolved"] += 1
            categorical_outcomes.append(payload)
        elif kind == "outcome" and "predicted_acceptance" in payload:
            counters["predictions_resolved"] += 1
            pair = (payload.get("predicted_acceptance"), payload.get("actual_first_pass"))
            prediction_pairs.append(pair)
            calibration_by_domain.setdefault(e.get("domain") or "<none>", []).append(pair)
            calibration_by_evaluator.setdefault(_evaluator_key(payload), []).append(pair)
        elif kind == "scope_promotion":
            counters["scope_promotions"] += 1
            if payload.get("cross_domain"):
                cross_domain["tested"] += 1
                if payload.get("confirmed"):
                    cross_domain["confirmed"] += 1
        elif kind == "candidate_rule":
            counters["candidate_rules_proposed"] += 1
        elif kind == "rule_promoted":
            counters["candidate_rules_promoted"] += 1
        elif kind == "rule_rejected":
            counters["candidate_rules_rejected"] += 1
            if payload.get("reason") == "regression":
                counters["regressions_detected"] += 1
        elif kind == "onboarding_answer":
            counters["onboarding_answers"] += 1
        elif kind in ("observation", "decision", "project_intent_update"):
            counters["meaningful_interactions"] += 1

    recent = acceptance_series[-window:]
    older = acceptance_series[:-window] if len(acceptance_series) > window else []

    first_pass = [a for _, a in acceptance_series if a >= 0.8]
    profile = store.load()
    stats = profile.get("statistics_summary", {})

    metrics = {
        "schema_version": SCHEMA_VERSION,
        "computed_at": utc_now(),
        "window": window,
        "span": {"first_event": first_ts, "last_event": last_ts, "sessions": len(sessions)},
        "counters": counters,
        "rates": {
            "first_pass_acceptance": _rate(len(first_pass), len(acceptance_series)),
            "rolling_first_pass_acceptance": _rate(
                len([a for _, a in recent if a >= 0.8]), len(recent)
            ),
            "explicit_correction_rate": _rate(
                counters["explicit_corrections"], counters["meaningful_interactions"]
            ),
            "assumption_error_rate": _rate(
                counters["assumptions_wrong"], max(counters["assumptions_made"], counters["artifacts"])
            ),
            "question_answer_rate": _rate(counters["questions_answered"], counters["questions_asked"]),
            "question_ignore_rate": _rate(
                counters["questions_ignored"] + counters["questions_skipped"],
                counters["questions_asked"],
            ),
            "useful_question_rate": _rate(
                question_value["useful"], sum(question_value.values())
            ),
            "questions_per_accepted_outcome": _rate(
                counters["questions_asked"], counters["accepted_outputs"]
            ),
            "revisions_per_artifact": _rate(counters["revisions"], counters["artifacts"]),
            "candidate_promotion_rate": _rate(
                counters["candidate_rules_promoted"], counters["candidate_rules_proposed"]
            ),
        },
        "calibration": {
            "samples": len(prediction_pairs),
            "brier_score": brier(prediction_pairs),
            "log_loss": log_loss(prediction_pairs),
            "mean_absolute_error": (
                round(sum(abs(p - a) for p, a in prediction_pairs) / len(prediction_pairs), 4)
                if prediction_pairs else None
            ),
            "bias": (
                round(sum(a - p for p, a in prediction_pairs) / len(prediction_pairs), 4)
                if prediction_pairs else None
            ),
            "bins": calibration_bins(prediction_pairs),
            "expected_calibration_error": _ece(prediction_pairs),
            "expected_calibration_error_reliable": len(prediction_pairs) >= ECE_MIN_SAMPLES,
            "resolution_rate": _rate(counters["predictions_resolved"],
                                     counters["predictions_made"]),
            "unresolved_predictions": max(
                0, counters["predictions_made"] - counters["predictions_resolved"]),
            "top1_preference_accuracy": _rate(
                len([row for row in categorical_outcomes if row.get("top1_correct")]),
                len(categorical_outcomes),
            ),
            "categorical_samples": len(categorical_outcomes),
            "categorical_brier_score": (
                round(sum(
                    sum((float(probability) - float(option == row.get("actual_option"))) ** 2
                        for option, probability in (row.get("option_probabilities") or {}).items())
                    for row in categorical_outcomes
                ) / len(categorical_outcomes), 4) if categorical_outcomes else None
            ),
            "categorical_log_loss": (
                round(sum(-math.log(max(1e-15, float(
                    (row.get("option_probabilities") or {}).get(row.get("actual_option"), 0.0)
                ))) for row in categorical_outcomes) / len(categorical_outcomes), 4)
                if categorical_outcomes else None
            ),
            "by_domain": {
                domain: {"samples": len(pairs), "brier_score": brier(pairs),
                         "log_loss": log_loss(pairs), "ece": _ece(pairs)}
                for domain, pairs in sorted(calibration_by_domain.items())
            },
            "by_evaluator": {
                evaluator: {"samples": len(pairs), "brier_score": brier(pairs),
                            "log_loss": log_loss(pairs), "ece": _ece(pairs)}
                for evaluator, pairs in sorted(calibration_by_evaluator.items())
            },
        },
        "scope_health": {
            "corrections_by_scope": per_scope_corrections,
            "global_correction_rate": _rate(
                per_scope_corrections["global"], sum(per_scope_corrections.values())
            ),
            "promotions": counters["scope_promotions"],
            "cross_domain_transfer": {
                "tested": cross_domain["tested"],
                "confirmed": cross_domain["confirmed"],
                "accuracy": _rate(cross_domain["confirmed"], cross_domain["tested"]),
            },
        },
        "by_mode": per_mode,
        "profile": {
            "belief_count": stats.get("belief_count", 0),
            "high_confidence_beliefs": stats.get("high_confidence_beliefs", 0),
            "contradictions_open": stats.get("contradictions_open", 0),
            "domains_with_evidence": stats.get("domains_with_evidence", 0),
            "promoted_beliefs": stats.get("promoted_beliefs", 0),
            "rejected_beliefs": stats.get("rejected_beliefs", 0),
        },
        "improvement": improvement_trend(older, recent),
        "security": {
            "quarantined_events": counters["quarantined_events"],
            "privacy_refusals": counters["privacy_refusals"],
            "note": "quarantined events are recorded but can never influence a belief",
        },
        "interpretation_note": (
            "Rates are computed from locally recorded events only. Small sample sizes are "
            "common early on; treat any rate with fewer than 20 samples as indicative."
        ),
    }
    return metrics


def improvement_trend(older, recent):
    """Compare an earlier acceptance window against the current one."""
    def _mean(series):
        vals = [a for _, a in series]
        return round(sum(vals) / len(vals), 4) if vals else None

    old_mean, new_mean = _mean(older), _mean(recent)
    delta = None
    if old_mean is not None and new_mean is not None:
        delta = round(new_mean - old_mean, 4)
    return {
        "earlier_window_mean_acceptance": old_mean,
        "recent_window_mean_acceptance": new_mean,
        "delta": delta,
        "samples_earlier": len(older),
        "samples_recent": len(recent),
        "verdict": (
            "insufficient data" if delta is None or len(older) < 10 or len(recent) < 10
            else "improving" if delta > 0.05
            else "regressing" if delta < -0.05
            else "flat"
        ),
    }


class MetricsStore:
    """Persistence for ``metrics.json``."""

    def __init__(self, home):
        self.home = Path(home)
        self.path = self.home / "metrics.json"
        self.backups = self.home / "backups"
        self.logs = self.home / "logs"

    def load(self):
        data, _ = read_json_resilient(
            self.path, backups_dir=self.backups, logs_dir=self.logs,
            default={"schema_version": SCHEMA_VERSION, "computed_at": None, "counters": {}},
        )
        return data

    def refresh(self, store, window=ROLLING_WINDOW):
        metrics = compute_metrics(store, window=window)
        write_json_atomic(self.path, metrics)
        return metrics
