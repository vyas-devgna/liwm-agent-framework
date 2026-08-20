"""Evidence weighting, provenance trust, confidence and temporal decay.

This is the arithmetic core of LIWM.  It is deliberately simple, fully
deterministic, and documented, because the alternative - a language model
asserting "confidence: 0.87" - is exactly the fake-probability failure mode this
framework exists to avoid.

The model
---------
Each observation contributes an independent, imperfect *vote* for or against a
belief.  Votes combine with a noisy-OR:

    P(supported) = 1 - prod(1 - w_i)

where ``w_i`` is the observation's effective weight.  Noisy-OR has the
properties we want: one strong observation is nearly sufficient, many weak
observations accumulate but with diminishing returns, and nothing ever reaches
certainty.

Effective weight is the product of four factors:

    w_i = base_weight(source_type)
        * provenance_trust(provenance, derived_from)   # hard gate, often 0.0
        * recency(age, decay_policy)                   # temporal drift
        * correlation_discount(rank within its source group)

Support and opposition are computed separately, then combined:

    confidence = P(supported) * (1 - P(opposed))

Finally the result is clamped to the **ceiling of the strongest source type
present**.  This is what stops ten weak agent inferences from manufacturing a
high-confidence "fact": the agent-inference ceiling is 0.15 and no amount of
self-generated repetition can lift it.

Every constant below is a *starting point* that the evaluation harness can
retune (see ``liwm.evaluation``); none of them are treated as immutable truth.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

__all__ = [
    "SOURCE_WEIGHTS",
    "SOURCE_CEILINGS",
    "PROVENANCE_TRUST",
    "TRUSTED_PROVENANCE",
    "DECAY_HALF_LIVES",
    "DECAY_FLOOR",
    "SINGLE_OBSERVATION_CLAMP",
    "effective_weight",
    "provenance_trust",
    "recency_factor",
    "combine",
    "score_belief",
    "clamp",
    "parse_ts",
    "age_days",
]

# ---------------------------------------------------------------------------
# Source-type weights.  "How much does one observation of this kind prove?"
# ---------------------------------------------------------------------------
SOURCE_WEIGHTS = {
    "explicit_statement": 1.00,       # "I prefer terse answers."
    "explicit_correction": 1.00,      # "No - that's too verbose."
    "explicit_rejection": 1.00,       # "Don't ever do that again."
    "direct_edit": 0.90,              # user rewrote the artifact, revealing preference
    "repeated_selection": 0.80,       # chose A over B, repeatedly
    "comparative_choice": 0.75,       # single A-vs-B pick
    "onboarding_answer": 0.70,        # self-report in a low-stakes framing
    "repeated_behavioral": 0.65,      # same behaviour observed several times
    "outcome_signal": 0.55,           # accepted / abandoned / reworked
    "single_behavioral": 0.30,        # one implicit signal
    "agent_inference": 0.15,          # LIWM's own reasoning, unconfirmed
}

# ---------------------------------------------------------------------------
# Per-source ceilings.  "However much of this you accumulate, you may not
# exceed this confidence on its own."  This is the anti-runaway-inference rule.
# ---------------------------------------------------------------------------
SOURCE_CEILINGS = {
    "explicit_statement": 0.98,
    "explicit_correction": 0.98,
    "explicit_rejection": 0.98,
    "direct_edit": 0.92,
    "repeated_selection": 0.88,
    "comparative_choice": 0.82,
    "onboarding_answer": 0.70,
    "repeated_behavioral": 0.78,
    "outcome_signal": 0.72,
    "single_behavioral": 0.55,
    "agent_inference": 0.15,
}

# ---------------------------------------------------------------------------
# Provenance trust.  This is the prompt-injection gate (constitution C04).
# A 0.0 multiplier means the observation is recorded for audit but contributes
# nothing to any belief, ever, regardless of how emphatically it is phrased.
# ---------------------------------------------------------------------------
PROVENANCE_TRUST = {
    "direct_user_message": 1.00,
    "direct_user_edit": 1.00,
    "explicit_user_review": 1.00,
    "onboarding_answer": 1.00,
    "agent_inference": 1.00,   # trusted *channel*, but weak weight + low ceiling
    "tool_output": 0.00,
    "repository_content": 0.00,
    "external_document": 0.00,
    "web_content": 0.00,
    "mcp_result": 0.00,
    "subagent_report": 0.00,
    "synthetic_test": 0.00,
    "other": 0.00,
}

TRUSTED_PROVENANCE = frozenset(k for k, v in PROVENANCE_TRUST.items() if v > 0.0)

#: Half-life in days per decay policy.  Older evidence loses influence but is
#: never deleted (constitution C11) - it is merely outweighed.
DECAY_HALF_LIVES = {
    "none": None,       # identity traits the user has explicitly locked
    "slow": 540.0,      # deep working style, domain fluency
    "standard": 180.0,  # ordinary preferences
    "volatile": 45.0,   # project-phase and mood-adjacent signals
    "session": 1.0,     # session-scoped context
}

#: Decay never drives an observation fully to zero; history still counts.
DECAY_FLOOR = 0.20

#: No single observation is ever conclusive, even an explicit statement.
SINGLE_OBSERVATION_CLAMP = 0.95

#: Successive observations from the same source type are correlated (the same
#: habit observed twice is not two independent proofs).  Each additional
#: observation within a source group is discounted by this factor, compounding.
CORRELATION_DECAY = 0.75

#: Observations recorded in the same session are more correlated still.
SAME_SESSION_DISCOUNT = 0.55


def clamp(x, lo=0.0, hi=1.0):
    """Coerce *x* into [lo, hi], treating unparseable input as *lo*.

    Everything in LIWM that carries a confidence, a probability or a signal
    strength goes through here, so a malformed value from a host degrades into
    "no signal" rather than propagating a NaN through the arithmetic.
    """
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return lo


def parse_ts(value):
    """Parse an ISO-8601 timestamp (with or without ``Z``) into aware UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def age_days(ts, now=None):
    """Age of *ts* in days, floored at 0."""
    dt = parse_ts(ts)
    if dt is None:
        return 0.0
    ref = parse_ts(now) or datetime.now(timezone.utc)
    return max(0.0, (ref - dt).total_seconds() / 86400.0)


def recency_factor(ts, decay_policy="standard", now=None):
    """Exponential decay with a floor, so history fades but never vanishes."""
    half_life = DECAY_HALF_LIVES.get(decay_policy, DECAY_HALF_LIVES["standard"])
    if half_life is None:
        return 1.0
    days = age_days(ts, now=now)
    raw = math.pow(0.5, days / half_life)
    return DECAY_FLOOR + (1.0 - DECAY_FLOOR) * raw


def provenance_trust(provenance, derived_from=None):
    """Trust multiplier for a provenance label, with taint propagation.

    ``derived_from`` lists the provenance of upstream material.  An inference
    *about the user* that was derived from repository content is repository
    content wearing a hat, so the minimum trust in the chain wins.
    """
    base = PROVENANCE_TRUST.get(provenance, 0.0)
    if not derived_from:
        return base
    upstream = [PROVENANCE_TRUST.get(p, 0.0) for p in derived_from]
    return min([base] + upstream)


def effective_weight(observation, now=None, group_rank=0, same_session=False):
    """Effective vote weight of a single observation, in [0, 0.95].

    ``group_rank`` is the 0-based index of this observation within its source
    group (0 = strongest/most recent), used for the correlation discount.
    """
    source = observation.get("source_type", "agent_inference")
    base = observation.get("weight_override")
    if base is None:
        base = SOURCE_WEIGHTS.get(source, SOURCE_WEIGHTS["agent_inference"])
    base = float(base)

    trust = provenance_trust(
        observation.get("provenance", "other"),
        observation.get("derived_from"),
    )
    if trust <= 0.0:
        return 0.0

    rec = recency_factor(
        observation.get("ts"),
        observation.get("decay_policy", "standard"),
        now=now,
    )

    corr = math.pow(CORRELATION_DECAY, max(0, group_rank))
    if same_session and group_rank > 0:
        corr *= SAME_SESSION_DISCOUNT

    w = base * trust * rec * corr
    return max(0.0, min(SINGLE_OBSERVATION_CLAMP, w))


def _noisy_or(weights):
    """1 - prod(1 - w). Independent-evidence accumulation."""
    product = 1.0
    for w in weights:
        product *= (1.0 - max(0.0, min(SINGLE_OBSERVATION_CLAMP, w)))
    return 1.0 - product


def combine(observations, now=None):
    """Combine supporting and opposing observations into a confidence score.

    *observations* is an iterable of dicts with at least ``source_type``,
    ``provenance``, ``ts`` and ``polarity`` (``"support"`` or ``"oppose"``).

    Returns a dict with the score plus the intermediate quantities, so that
    ``liwm why`` can explain the number instead of asserting it.
    """
    supporting, opposing = [], []
    for obs in observations:
        (opposing if obs.get("polarity") == "oppose" else supporting).append(obs)

    def _score(items):
        # Group by source type, sort each group newest-first, and apply the
        # compounding correlation discount within the group.
        groups = {}
        for obs in items:
            groups.setdefault(obs.get("source_type", "agent_inference"), []).append(obs)
        weights = []
        per_source = {}
        seen_sessions = {}
        for source, obs_list in groups.items():
            obs_list.sort(key=lambda o: str(o.get("ts") or ""), reverse=True)
            group_weights = []
            for rank, obs in enumerate(obs_list):
                sess = obs.get("session_id")
                same_session = bool(sess) and seen_sessions.get(source) == sess
                seen_sessions[source] = sess
                w = effective_weight(obs, now=now, group_rank=rank, same_session=same_session)
                if w > 0.0:
                    group_weights.append(w)
            if group_weights:
                per_source[source] = _noisy_or(group_weights)
                weights.extend(group_weights)
        return _noisy_or(weights), per_source, weights

    p_support, support_by_source, support_w = _score(supporting)
    p_oppose, oppose_by_source, oppose_w = _score(opposing)

    raw = p_support * (1.0 - p_oppose)

    # Ceiling: the best source type that actually contributed anything.
    contributing = [s for s, v in support_by_source.items() if v > 0.0]
    ceiling = max((SOURCE_CEILINGS.get(s, 0.30) for s in contributing), default=0.0)
    confidence = min(raw, ceiling)

    return {
        "confidence": round(confidence, 4),
        "raw_confidence": round(raw, 4),
        "ceiling": round(ceiling, 4),
        "p_support": round(p_support, 4),
        "p_oppose": round(p_oppose, 4),
        "support_weight": round(sum(support_w), 4),
        "oppose_weight": round(sum(oppose_w), 4),
        "evidence_count": len(supporting),
        "contradiction_count": len(opposing),
        "counted_evidence": len(support_w),
        "ignored_evidence": len(supporting) - len(support_w),
        "support_by_source": {k: round(v, 4) for k, v in support_by_source.items()},
        "oppose_by_source": {k: round(v, 4) for k, v in oppose_by_source.items()},
        "limiting_factor": (
            "ceiling:%s" % max(contributing, key=lambda s: SOURCE_CEILINGS.get(s, 0.0))
            if contributing and raw > ceiling else "evidence"
        ),
    }


def score_belief(belief, observations, now=None):
    """Apply :func:`combine` to *belief*, returning an updated copy.

    Beliefs the user has explicitly rejected keep a hard zero and a sticky flag,
    so the same weak signal cannot silently relearn a rejected conclusion
    (requirement §38).
    """
    result = combine(observations, now=now)
    updated = dict(belief)
    updated.update(
        {
            "confidence": result["confidence"],
            "evidence_count": result["evidence_count"],
            "contradiction_count": result["contradiction_count"],
            "support_weight": result["support_weight"],
            "oppose_weight": result["oppose_weight"],
            "scoring": result,
        }
    )
    if belief.get("rejected_by_user"):
        updated["confidence"] = 0.0
        updated["status"] = "rejected"
        updated["scoring"]["limiting_factor"] = "user_rejection"
    return updated
