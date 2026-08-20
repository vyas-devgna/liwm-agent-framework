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
import math

from .evidence import clamp
from .jsonio import utc_now

__all__ = [
    "make_prediction", "make_preference_prediction", "record_prediction",
    "resolve_prediction", "brier", "log_loss", "calibration_bins",
]


def _unit_interval(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("%s must be a number from 0 to 1" % name) from exc
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError("%s must be finite and between 0 and 1" % name)
    return number


def make_prediction(
    predicted_acceptance,
    confidence,
    predicted_friction=None,
    uncertain_dimensions=None,
    intent_assumptions=None,
    basis=None,
    artifact=None,
    candidate_id=None,
    unit=None,
):
    """Build a structured prediction about how an artifact will land."""
    return {
        "id": "prd_%s" % uuid.uuid4().hex[:12],
        "at": utc_now(),
        "artifact": artifact,
        "candidate_id": candidate_id,
        # The interaction this prediction belongs to, matching the unit an
        # experiment assignment was committed for. Without it an outcome cannot
        # be tied back to whether the user actually saw candidate output.
        "unit": unit,
        "target_type": "binary_first_pass_acceptance",
        "predicted_acceptance": _unit_interval(predicted_acceptance, "predicted_acceptance"),
        "confidence": _unit_interval(confidence, "confidence"),
        "probability_status": "uncalibrated" if not basis else "locally_calibrated_candidate",
        "predicted_friction": [
            {
                "issue": f.get("issue"),
                "probability": _unit_interval(f.get("probability", 0.3), "friction probability"),
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


def make_preference_prediction(options, confidence, **kwargs):
    """Commit to an A/B/C preference distribution before observing the choice."""
    probabilities = {str(label): _unit_interval(value, "option probability")
                     for label, value in dict(options or {}).items()}
    if len(probabilities) < 2 or abs(sum(probabilities.values()) - 1.0) > 1e-6:
        raise ValueError("preference prediction needs at least two probabilities summing to 1")
    prediction = make_prediction(0.5, confidence, **kwargs)
    prediction.update({
        "target_type": "categorical_preference",
        "option_probabilities": probabilities,
        "predicted_option": max(probabilities, key=probabilities.get),
        "predicted_acceptance": None,
    })
    return prediction


def record_prediction(store, prediction, session_id=None, project_id=None, domain=None):
    store.events.record(
        "prediction", "agent_inference",
        payload=prediction,
        session_id=session_id, project_id=project_id, domain=domain,
    )
    return prediction


def resolve_prediction(store, prediction_id, actual_acceptance=None, observed_friction=None,
                       session_id=None, project_id=None, domain=None,
                       evaluator_type="agent_recorded", actual_option=None,
                       evidence_event_id=None):
    """Score a prediction against what actually happened.

    The resulting event is what ``liwm stats`` uses for calibration, and what
    Level-3 strategy adaptation uses to decide whether its current questioning
    mix is working.
    """
    prediction = None
    prediction_event = None
    for event in store.events.iter_events(kinds={"prediction"}):
        if (event.get("payload") or {}).get("id") == prediction_id:
            prediction = event["payload"]
            prediction_event = event
    if prediction is None:
        raise KeyError("no prediction %r in the event log" % prediction_id)
    for event in store.events.iter_events(kinds={"outcome"}):
        if (event.get("payload") or {}).get("prediction_id") == prediction_id:
            raise ValueError("prediction %r is already resolved" % prediction_id)

    evaluator_types = {
        "agent_recorded",
        "synthetic_replay", "historical_counterfactual_estimate",
        "observed_human_outcome", "external_evaluator", "benchmark_ground_truth",
    }
    if evaluator_type not in evaluator_types:
        raise ValueError("unknown evaluator type %r" % evaluator_type)
    binding = None
    if evaluator_type == "observed_human_outcome":
        evidence_event = _bound_evidence(store, prediction, prediction_event,
                                         evidence_event_id)
        actual_acceptance, actual_option = _derive_labels(
            prediction, evidence_event, actual_acceptance, actual_option)
        binding = "structured_feedback_event"

    observed = set(observed_friction or [])
    predicted = {f["issue"] for f in prediction.get("predicted_friction", []) if f.get("issue")}
    target_type = prediction.get("target_type", "binary_first_pass_acceptance")
    if target_type == "categorical_preference":
        probabilities = prediction.get("option_probabilities") or {}
        if actual_option not in probabilities:
            raise ValueError("actual_option must be one of the predicted options")
        actual = None
        actual_first_pass = None
        error = None
    else:
        actual = _unit_interval(actual_acceptance, "actual_acceptance")
        actual_first_pass = 1 if actual >= 0.8 else 0
        error = actual_first_pass - prediction["predicted_acceptance"]

    result = {
        "prediction_id": prediction_id,
        "predicted_acceptance": prediction["predicted_acceptance"],
        "confidence": prediction["confidence"],
        "target_type": target_type,
        "actual_acceptance": actual,
        "actual_first_pass": actual_first_pass,
        "actual_option": actual_option,
        "predicted_option": prediction.get("predicted_option"),
        "option_probabilities": prediction.get("option_probabilities"),
        "top1_correct": (prediction.get("predicted_option") == actual_option
                         if target_type == "categorical_preference" else None),
        "error": round(error, 4) if error is not None else None,
        "absolute_error": round(abs(error), 4) if error is not None else None,
        "squared_error": round(error * error, 4) if error is not None else None,
        "direction": ("categorical" if error is None else
                      "overconfident" if error < -0.15 else
                      "underconfident" if error > 0.15 else "calibrated"),
        "friction_hits": sorted(predicted & observed),
        "friction_misses": sorted(predicted - observed),
        "surprises": sorted(observed - predicted),
        "uncertain_dimensions": prediction.get("uncertain_dimensions", []),
        "resolved_at": utc_now(),
        "evaluator_type": evaluator_type,
        "evaluator_provenance": (
            "explicit_user_review" if evaluator_type == "observed_human_outcome"
            else "agent_inference"
        ),
        "candidate_id": prediction.get("candidate_id"),
        "unit": prediction.get("unit"),
        "evidence_event_id": evidence_event_id,
        # Absent on every 0.2 outcome, which is the point: an observed label
        # recorded before this rule existed was never checked against its
        # evidence, and must not be counted as though it had been.
        "outcome_binding": binding,
    }
    def unresolved(events):
        if any((event.get("payload") or {}).get("prediction_id") == prediction_id
               for event in events if event.get("kind") == "outcome"):
            raise ValueError("prediction %r is already resolved" % prediction_id)

    store.events.record_if(
        "outcome", result["evaluator_provenance"], unresolved, payload=result,
        session_id=session_id, project_id=project_id, domain=domain,
    )
    return result


#: What an observed human outcome is allowed to be derived from.  A generic
#: later message is not evidence of a choice; the label has to come out of the
#: event that recorded the choice.
_OUTCOME_EVIDENCE_KINDS = frozenset({"feedback"})
_OUTCOME_EVIDENCE_PROVENANCE = frozenset({
    "direct_user_message", "direct_user_edit", "explicit_user_review",
})


def _bound_evidence(store, prediction, prediction_event, evidence_event_id):
    """The trusted feedback event that this prediction is resolved against.

    The previous rule only checked that *some* later trusted user event
    existed, while the caller supplied the label separately.  A prediction of
    option A could therefore be resolved as "the user chose B, observed" on the
    strength of the user having said "thanks".  A compliant agent would not do
    that, but research infrastructure should not need the agent to be
    interpreting correctly for its strongest evidence class to mean anything.
    """
    event = next(
        (event for event in store.events.iter_events(include_quarantined=True)
         if event.get("event_id") == evidence_event_id), None)
    if event is None:
        raise ValueError("observed_human_outcome requires an evidence event id")
    payload = event.get("payload") or {}
    problems = []
    if event.get("quarantined"):
        problems.append("evidence is quarantined")
    if event.get("kind") not in _OUTCOME_EVIDENCE_KINDS:
        problems.append("evidence must be a %s event, not %r"
                        % ("/".join(sorted(_OUTCOME_EVIDENCE_KINDS)), event.get("kind")))
    if event.get("provenance") not in _OUTCOME_EVIDENCE_PROVENANCE:
        problems.append("evidence provenance %r is not a direct user channel"
                        % event.get("provenance"))
    if int(event.get("sequence") or 0) <= int(prediction_event.get("sequence") or 0):
        problems.append("evidence precedes the prediction it is supposed to test")
    if payload.get("prediction_id") != prediction["id"]:
        problems.append("evidence is not linked to prediction %s" % prediction["id"])
    if problems:
        raise ValueError("observed_human_outcome refused: %s" % "; ".join(problems))
    return event


def _derive_labels(prediction, event, actual_acceptance, actual_option):
    """Read the outcome out of the evidence, and refuse to be told otherwise."""
    payload = event.get("payload") or {}
    if prediction.get("target_type") == "categorical_preference":
        chosen = payload.get("selected_option")
        if chosen is None:
            raise ValueError(
                "observed_human_outcome for a preference prediction needs feedback "
                "recording which option was selected")
        if chosen not in (prediction.get("option_probabilities") or {}):
            raise ValueError("selected option %r was not among the predicted options"
                             % chosen)
        if actual_option is not None and actual_option != chosen:
            raise ValueError(
                "actual_option %r contradicts the evidence event, which recorded %r"
                % (actual_option, chosen))
        return actual_acceptance, chosen
    acceptance = payload.get("acceptance")
    if acceptance is None:
        raise ValueError(
            "observed_human_outcome for an acceptance prediction needs feedback "
            "carrying an acceptance score")
    acceptance = _unit_interval(acceptance, "evidence acceptance")
    if actual_acceptance is not None and abs(
            _unit_interval(actual_acceptance, "actual_acceptance") - acceptance) > 1e-9:
        raise ValueError(
            "actual_acceptance %s contradicts the evidence event, which recorded %s"
            % (actual_acceptance, acceptance))
    return acceptance, actual_option


def brier(pairs):
    """Binary Brier score for first-pass acceptance probabilities."""
    pairs = [(p, a) for p, a in pairs if p is not None and a is not None]
    if not pairs:
        return None
    return round(sum((p - a) ** 2 for p, a in pairs) / len(pairs), 4)


def log_loss(pairs):
    """Binary logarithmic loss with finite clipping at machine-safe bounds."""
    pairs = [(p, a) for p, a in pairs if p is not None and a is not None]
    if not pairs:
        return None
    eps = 1e-15
    return round(-sum(a * math.log(max(eps, min(1 - eps, p)))
                      + (1 - a) * math.log(max(eps, min(1 - eps, 1 - p)))
                      for p, a in pairs) / len(pairs), 4)


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
