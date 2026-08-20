"""Predict before receiving feedback.

Without a prediction recorded *before* the user reacts, "the framework is
learning" is unfalsifiable.  With one, it becomes measurable: LIWM commits to an
expected acceptance and a list of likely friction points, then finds out.

Predictions are internal.  They are not narrated to the user unless the
uncertainty is high enough to be worth flagging, in which case the honest move
is to state the assumption (constitution C07) rather than to display a number.
"""

from __future__ import annotations

import uuid

from .evidence import clamp
from .jsonio import utc_now

__all__ = ["make_prediction", "record_prediction", "resolve_prediction", "brier", "calibration_bins"]


def make_prediction(
    predicted_acceptance,
    confidence,
    predicted_friction=None,
    uncertain_dimensions=None,
    intent_assumptions=None,
    basis=None,
    artifact=None,
):
    """Build a structured prediction about how an artifact will land."""
    return {
        "id": "prd_%s" % uuid.uuid4().hex[:12],
        "at": utc_now(),
        "artifact": artifact,
        "predicted_acceptance": clamp(predicted_acceptance),
        "confidence": clamp(confidence),
        "predicted_friction": [
            {
                "issue": f.get("issue"),
                "probability": clamp(f.get("probability", 0.3)),
                "dimension": f.get("dimension"),
            }
            for f in (predicted_friction or [])
        ],
        "uncertain_dimensions": list(uncertain_dimensions or []),
        "intent_assumptions": list(intent_assumptions or []),
        "basis": list(basis or []),
        "resolved": False,
        "actual_acceptance": None,
        "error": None,
        "friction_hits": [],
        "friction_misses": [],
        "surprises": [],
    }


def record_prediction(store, prediction, session_id=None, project_id=None, domain=None):
    store.events.record(
        "prediction", "agent_inference",
        payload=prediction,
        session_id=session_id, project_id=project_id, domain=domain,
    )
    return prediction


def resolve_prediction(store, prediction_id, actual_acceptance, observed_friction=None,
                       session_id=None, project_id=None, domain=None):
    """Score a prediction against what actually happened.

    The resulting event is what ``liwm stats`` uses for calibration, and what
    Level-3 strategy adaptation uses to decide whether its current questioning
    mix is working.
    """
    prediction = None
    for event in store.events.iter_events(kinds={"prediction"}):
        if (event.get("payload") or {}).get("id") == prediction_id:
            prediction = event["payload"]
    if prediction is None:
        raise KeyError("no prediction %r in the event log" % prediction_id)

    observed = set(observed_friction or [])
    predicted = {f["issue"] for f in prediction.get("predicted_friction", []) if f.get("issue")}
    actual = clamp(actual_acceptance)
    error = actual - prediction["predicted_acceptance"]

    result = {
        "prediction_id": prediction_id,
        "predicted_acceptance": prediction["predicted_acceptance"],
        "confidence": prediction["confidence"],
        "actual_acceptance": actual,
        "error": round(error, 4),
        "absolute_error": round(abs(error), 4),
        "squared_error": round(error * error, 4),
        "direction": "overconfident" if error < -0.15 else (
            "underconfident" if error > 0.15 else "calibrated"
        ),
        "friction_hits": sorted(predicted & observed),
        "friction_misses": sorted(predicted - observed),
        "surprises": sorted(observed - predicted),
        "uncertain_dimensions": prediction.get("uncertain_dimensions", []),
        "resolved_at": utc_now(),
    }
    store.events.record(
        "outcome", "agent_inference",
        payload=result,
        session_id=session_id, project_id=project_id, domain=domain,
    )
    return result


def brier(pairs):
    """Mean squared error between predicted and actual acceptance."""
    pairs = [(p, a) for p, a in pairs if p is not None and a is not None]
    if not pairs:
        return None
    return round(sum((p - a) ** 2 for p, a in pairs) / len(pairs), 4)


def calibration_bins(pairs, bins=10):
    """Reliability diagram data: predicted band vs observed mean.

    A well-calibrated LIWM has observed ≈ predicted in every populated bin.  A
    systematically optimistic one has observed < predicted everywhere, which is
    exactly the failure mode a self-improving system needs to be able to see in
    itself.
    """
    pairs = [(p, a) for p, a in pairs if p is not None and a is not None]
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        members = [(p, a) for p, a in pairs if (lo <= p < hi or (i == bins - 1 and p == 1.0))]
        if not members:
            out.append({"bin": "%.1f-%.1f" % (lo, hi), "n": 0,
                        "mean_predicted": None, "mean_actual": None, "gap": None})
            continue
        mp = sum(p for p, _ in members) / len(members)
        ma = sum(a for _, a in members) / len(members)
        out.append({
            "bin": "%.1f-%.1f" % (lo, hi),
            "n": len(members),
            "mean_predicted": round(mp, 4),
            "mean_actual": round(ma, 4),
            "gap": round(ma - mp, 4),
        })
    return out
