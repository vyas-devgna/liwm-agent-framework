"""What asking a question actually bought, and how much to believe that.

Two problems with the first version of this module.

The first was a threshold: four observations were ignored entirely and the
fifth took full control of a question family's utility.  Five noisy
conversations should not double the value of a question, and the fourth should
not count for nothing.  The estimate is now shrunk toward a heuristic prior and
moves smoothly with evidence, in the same spirit as the belief arithmetic in
:mod:`liwm.evidence`.

The second was a name.  ``observed_information_gain`` was the difference
between two uncertainty numbers that LIWM itself produced.  Latent human
uncertainty was not observed; it was estimated.  The field is now called
``estimated_uncertainty_reduction``, and where the signal really did come from
the user - they said the question helped, or the answer produced trusted
evidence - that is recorded separately and weighted higher.
"""

from __future__ import annotations

from .evidence import clamp
from .jsonio import utc_now

__all__ = [
    "EVALUATOR_WEIGHTS", "HEURISTIC_PRIOR", "PRIOR_STRENGTH", "PLANNER_BOUNDS",
    "QuestionOutcomeStore", "planner_factor",
]

#: How much authority an outcome carries, by where its signal came from.  An
#: outcome LIWM scored against its own uncertainty estimates is not the same
#: evidence as the user saying the question was worth answering.
EVALUATOR_WEIGHTS = {
    "explicit_user_usefulness": 1.00,
    "user_evidence": 0.85,
    "agent_estimate": 0.50,
}

#: What an untested question of an unknown family is assumed to return.  It is
#: the centre the estimate is pulled back toward, not a measurement.
HEURISTIC_PRIOR = 0.30

#: Pseudo-observations behind the prior.  At an effective sample size of 6 the
#: estimate is half prior and half evidence; below that, mostly prior.
PRIOR_STRENGTH = 6.0

#: Hard bounds on how far question history may move a planner utility.  History
#: is a tilt, never a veto: a question the profile says is badly needed must
#: still be reachable when past questions of its family went nowhere.
PLANNER_BOUNDS = (0.70, 1.40)

#: Successive outcomes recorded in one session are correlated, exactly as
#: successive observations are.  The same discount applies.
SAME_SESSION_DISCOUNT = 0.55


def planner_factor(estimate):
    """Bounded multiplier for :class:`liwm.questions.QuestionPlanner`."""
    if estimate is None:
        return 1.0
    low, high = PLANNER_BOUNDS
    return round(max(low, min(high, 1.0 + (float(estimate) - HEURISTIC_PRIOR))), 4)


def _value(row):
    """One outcome's usefulness, in [0, 1].

    Uncertainty reduction is the base; a decision that actually changed and a
    later signal that the answer mattered add to it; the cost of asking is
    subtracted.  Bounded, so the mean of these is a score rather than an
    unbounded quantity that could exceed 1 and then be treated as a rate.
    """
    value = float(row.get("estimated_uncertainty_reduction") or 0.0)
    value += 0.25 if row.get("changed_decision") else 0.0
    value += 0.15 if row.get("later_correction_signal") is True else 0.0
    value += 0.15 if row.get("explicit_user_usefulness") is True else 0.0
    value -= 0.15 * float(row.get("cognitive_cost") or 0.0)
    value -= min(0.15, float(row.get("turn_burden") or 0.0) * 0.03)
    return clamp(value)


def _weighted(rows):
    weights = []
    seen_sessions = set()
    for row in rows:
        weight = EVALUATOR_WEIGHTS.get(row.get("evaluator_type"), EVALUATOR_WEIGHTS["agent_estimate"])
        session = row.get("session_id")
        if session and session in seen_sessions:
            weight *= SAME_SESSION_DISCOUNT
        if session:
            seen_sessions.add(session)
        weights.append((weight, _value(row)))
    total = sum(weight for weight, _ in weights)
    if total <= 0:
        return 0.0, 0.0, 0.0
    mean = sum(weight * value for weight, value in weights) / total
    variance = sum(weight * (value - mean) ** 2 for weight, value in weights) / total
    return total, mean, variance


class QuestionOutcomeStore:
    def __init__(self, store):
        self.store = store

    def record(self, question_id, family, dimensions, pre_uncertainty,
               predicted_information_gain, post_uncertainty, changed_decision=False,
               later_correction_signal=None, answer_evidence=None, cognitive_cost=None,
               elapsed_seconds=None, turn_burden=None, scope="global", domain=None,
               project_id=None, session_id=None, explicit_user_usefulness=None,
               evaluator_type=None):
        prior = [event for event in self.store.events.iter_events(
            kinds={"question_asked", "question_answered"}, session_id=session_id
        ) if (event.get("payload") or {}).get("question_id") == question_id]
        if not any(event.get("kind") == "question_asked" for event in prior):
            raise ValueError("question outcome requires a linked question_asked event")
        if any(event.get("kind") == "question_answered" for event in prior):
            raise ValueError("question outcome was already recorded")

        evidence = self._resolve_evidence(answer_evidence)
        if evaluator_type is None:
            evaluator_type = ("explicit_user_usefulness" if explicit_user_usefulness is not None
                              else "user_evidence" if evidence["trusted"]
                              else "agent_estimate")
        if evaluator_type not in EVALUATOR_WEIGHTS:
            raise ValueError("unknown evaluator type %r" % evaluator_type)
        if evaluator_type != "agent_estimate" and not (
                evidence["trusted"] or explicit_user_usefulness is not None):
            raise ValueError(
                "%r requires trusted answer evidence or an explicit usefulness signal"
                % evaluator_type)

        payload = {
            "question_id": question_id, "family": family,
            "dimensions": list(dimensions or []),
            "pre_uncertainty": clamp(pre_uncertainty),
            "predicted_information_gain": clamp(predicted_information_gain),
            "post_uncertainty": clamp(post_uncertainty),
            # LIWM's own before-and-after estimate of its own uncertainty.  Not
            # a measurement of what the person knew or resolved.
            "estimated_uncertainty_reduction": round(
                max(0.0, clamp(pre_uncertainty) - clamp(post_uncertainty)), 4
            ),
            "changed_decision": bool(changed_decision),
            "later_correction_signal": later_correction_signal,
            "explicit_user_usefulness": explicit_user_usefulness,
            "evaluator_type": evaluator_type,
            "answer_evidence": evidence["resolved"],
            "unresolved_evidence": evidence["unresolved"],
            "cognitive_cost": clamp(cognitive_cost) if cognitive_cost is not None else None,
            "elapsed_seconds": max(0.0, float(elapsed_seconds)) if elapsed_seconds is not None else None,
            "turn_burden": turn_burden, "scope": scope, "recorded_at": utc_now(),
        }
        return self.store.events.record(
            "question_answered", "agent_inference", payload=payload,
            domain=domain, project_id=project_id, session_id=session_id,
        )

    def _resolve_evidence(self, answer_evidence):
        """Check that the cited answer events exist and are trusted.

        Storing ids without looking at them let an outcome claim user evidence
        that was never recorded, or that was recorded and quarantined.
        """
        wanted = list(dict.fromkeys(answer_evidence or []))
        if not wanted:
            return {"resolved": [], "unresolved": [], "trusted": False}
        index = {event["event_id"]: event
                 for event in self.store.events.iter_events(include_quarantined=True)
                 if event.get("event_id") in set(wanted)}
        resolved, unresolved, trusted = [], [], False
        for ref in wanted:
            event = index.get(ref)
            if event is None:
                unresolved.append(ref)
                continue
            resolved.append(ref)
            if not event.get("quarantined") and event.get("provenance") in {
                    "direct_user_message", "direct_user_edit", "explicit_user_review",
                    "onboarding_answer"}:
                trusted = True
        return {"resolved": resolved, "unresolved": unresolved, "trusted": trusted}

    def rows(self):
        out = []
        for event in self.store.events.iter_events(kinds={"question_answered"}):
            payload = event.get("payload") or {}
            reduction = payload.get("estimated_uncertainty_reduction")
            if reduction is None:
                # 0.2 wrote this under its old name.  Read it, but treat it as
                # what it always was: an agent estimate.
                reduction = payload.get("observed_information_gain")
                if reduction is None:
                    continue
            out.append({
                "domain": event.get("domain"), "project_id": event.get("project_id"),
                "session_id": event.get("session_id"),
                **payload,
                "estimated_uncertainty_reduction": reduction,
                "later_correction_signal": payload.get(
                    "later_correction_signal", payload.get("later_correction_useful")),
                "evaluator_type": payload.get("evaluator_type", "agent_estimate"),
            })
        return out

    def effectiveness(self, family, dimension=None, domain=None):
        """Shrunk estimate of what this question family returns, with its spread.

        Hierarchical: the broadest matching group updates the prior, then the
        narrower groups update that.  Specific evidence therefore dominates when
        there is enough of it and barely moves the number when there is not,
        with no threshold anywhere for a single observation to cross.
        """
        rows = self.rows()
        levels = [
            ("family", [row for row in rows if row.get("family") == family]),
            ("family_dimension", [row for row in rows if row.get("family") == family
                                  and dimension in row.get("dimensions", [])]),
            ("family_dimension_domain", [
                row for row in rows if row.get("family") == family and domain
                and row.get("domain") == domain and dimension in row.get("dimensions", [])]),
        ]

        # Broad to narrow, each level updating what the previous one produced.
        # A row is counted once: the broader levels contribute only the rows the
        # narrower one does not already have, so the same outcome cannot
        # manufacture three observations' worth of confidence out of one.
        estimate, strength = HEURISTIC_PRIOR, PRIOR_STRENGTH
        level, dispersion, evaluators, samples = "prior", None, {}, 0
        for index, (name, group) in enumerate(levels):
            narrower = {row.get("question_id")
                        for _, later in levels[index + 1:] for row in later}
            contributing = [row for row in group
                            if row.get("question_id") not in narrower]
            if not group:
                continue
            if contributing:
                ess, mean, variance = _weighted(contributing)
                if ess > 0:
                    estimate = (strength * estimate + ess * mean) / (strength + ess)
                    strength += ess
                    dispersion = round(variance ** 0.5, 4)
            level, samples = name, len(group)
            evaluators = {}
            for row in group:
                key = row.get("evaluator_type", "agent_estimate")
                evaluators[key] = evaluators.get(key, 0) + 1

        effective_sample = round(strength - PRIOR_STRENGTH, 4)
        return {
            # Not a probability.  A bounded usefulness score with a prior.
            "estimate": round(estimate, 4),
            "prior": HEURISTIC_PRIOR,
            "samples": samples,
            "effective_sample_size": effective_sample,
            "shrinkage": round(PRIOR_STRENGTH / strength, 4),
            "dispersion": dispersion,
            "evaluator_mix": evaluators,
            "level": level,
            "empirical": level != "prior",
            "planner_factor": planner_factor(estimate),
        }
