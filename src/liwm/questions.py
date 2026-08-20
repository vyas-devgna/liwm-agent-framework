"""The adaptive question planner.

The planner answers one question about questions:

    What unresolved uncertainty could most change what I am about to make,
    and what is the cheapest human question that would resolve it?

Utility model
-------------
::

                 EIG x decision_impact x misunderstanding_risk x relevance
    utility =  ------------------------------------------------------------
                    cognitive_cost x fatigue_penalty x redundancy_penalty

Expected information gain is estimated as ``uncertainty x resolution_power x
style_effectiveness``, where uncertainty comes from the profile's actual
confidence (not a number the model invents), resolution_power is a per-template
constant, and style_effectiveness is the Level-3 personal-strategy weight that
this specific user's history has earned.

No claim is made that these are true probabilities.  They are calibrated
heuristics whose parameters are measured and tuned by ``liwm.evaluation``
against replayed episodes, which is the honest version of the thing.
"""

from __future__ import annotations

from .question_bank import QUESTION_BANK, STYLE_CLASS, by_id
from .taxonomy import decision_impact, dimension_meta

__all__ = [
    "QuestionPlanner",
    "score_question",
    "uncertainty_for",
    "PlannedQuestion",
]


def uncertainty_for(dimension, resolved, default=0.85):
    """Uncertainty in [0, 1] for *dimension*, from the resolved context view."""
    belief = (resolved or {}).get(dimension)
    if not belief:
        return default
    return max(0.0, 1.0 - float(belief.get("confidence", 0.0)))


class PlannedQuestion(dict):
    """A question the planner recommends, with its full justification."""

    @property
    def text(self):
        return self["text"]


def score_question(
    question,
    resolved,
    relevance_by_dimension=None,
    misunderstanding_risk=0.5,
    fatigue=0.0,
    asked_dimensions=None,
    style_weights=None,
    min_relevance=0.0,
):
    """Compute the utility of asking *question* right now."""
    relevance_by_dimension = relevance_by_dimension or {}
    asked_dimensions = asked_dimensions or {}
    style_weights = style_weights or {}

    contributions = []
    for dim in question["resolves"]:
        u = uncertainty_for(dim, resolved)
        impact = decision_impact(dim)
        relevance = float(relevance_by_dimension.get(dim, _default_relevance(dim)))
        if relevance < min_relevance:
            continue
        contributions.append(
            {
                "dimension": dim,
                "uncertainty": round(u, 4),
                "decision_impact": round(impact, 4),
                "relevance": round(relevance, 4),
                "gain": round(u * impact * relevance, 5),
            }
        )
    if not contributions:
        return None

    # A question resolving several dimensions is worth more than the best one
    # alone, but much less than their sum (the answers are correlated).
    contributions.sort(key=lambda c: -c["gain"])
    combined_gain = contributions[0]["gain"]
    for extra in contributions[1:]:
        combined_gain += 0.35 * extra["gain"]

    style_effectiveness = float(style_weights.get(question["style"], 1.0))
    eig = combined_gain * question["resolution_power"] * style_effectiveness

    redundancy = 1.0
    for dim in question["resolves"]:
        redundancy += 1.4 * float(asked_dimensions.get(dim, 0))

    fatigue_penalty = 1.0 + 2.2 * max(0.0, min(1.0, fatigue))
    cost = max(0.05, float(question["cognitive_cost"]))

    utility = (eig * max(0.05, misunderstanding_risk)) / (cost * fatigue_penalty * redundancy)

    return PlannedQuestion(
        {
            "id": question["id"],
            "text": question["text"],
            "style": question["style"],
            "class": STYLE_CLASS[question["style"]],
            "family": question["family"],
            "resolves": list(question["resolves"]),
            "utility": round(utility, 4),
            "expected_information_gain": round(eig, 4),
            "cognitive_cost": cost,
            "fatigue_penalty": round(fatigue_penalty, 3),
            "redundancy_penalty": round(redundancy, 3),
            "misunderstanding_risk": misunderstanding_risk,
            "contributions": contributions,
            "why": _why(contributions, question),
        }
    )


def _default_relevance(dimension):
    """Without task-specific relevance, fall back to how universally the
    dimension applies.  Interaction dimensions apply to literally every turn."""
    root = dimension.split(".", 1)[0]
    return {
        "interaction_profile": 0.85,
        "communication_profile": 0.7,
        "decision_style": 0.7,
        "reasoning_profile": 0.65,
        "working_style": 0.6,
        "creative_profile": 0.55,
        "preferences": 0.6,
        "anti_preferences": 0.6,
        "persistent_goals": 0.65,
        "domain_fluency": 0.5,
    }.get(root, 0.5)


def _why(contributions, question):
    top = contributions[0]
    return (
        "resolves %s (uncertainty %.2f, decision impact %.2f) via a %s question costing %.2f"
        % (top["dimension"], top["uncertainty"], top["decision_impact"],
           question["style"], question["cognitive_cost"])
    )


class QuestionPlanner:
    """Selects which questions to ask, in what order, under a mode contract."""

    def __init__(self, mode_contract, resolved=None, strategy=None, bank=None):
        self.contract = dict(mode_contract)
        self.resolved = resolved or {}
        self.strategy = strategy or {}
        self.bank = list(bank if bank is not None else QUESTION_BANK)

    # -- helpers -----------------------------------------------------------
    def _style_weights(self):
        weights = {}
        s = self.strategy or {}
        for style in STYLE_CLASS:
            weights[style] = float(s.get("style_effectiveness", {}).get(style, 1.0))
        # Mode shapes the experiential/technical mix by reweighting, not by
        # hard exclusion - a genuinely necessary technical question still gets
        # through in HIGH mode if nothing else can resolve the ambiguity.
        exp_ratio = float(self.contract.get("experiential_ratio", 0.5))
        for style, klass in STYLE_CLASS.items():
            target = exp_ratio if klass == "experiential" else (1.0 - exp_ratio)
            weights[style] = weights[style] * (0.55 + 0.9 * target)
        return weights

    def _eligible(self):
        allowed = set(self.contract.get("styles") or STYLE_CLASS.keys())
        return [q for q in self.bank if q["style"] in allowed]

    # -- planning ----------------------------------------------------------
    def plan(
        self,
        relevance_by_dimension=None,
        misunderstanding_risk=0.5,
        fatigue=0.0,
        asked_dimensions=None,
        max_questions=None,
        exclude_ids=None,
    ):
        """Return an ordered list of questions worth asking, best first.

        The list may be empty.  That is a valid and frequently correct plan.
        """
        if self.contract.get("mode") == "off":
            return []

        budget = self.contract.get("max_questions", 0) if max_questions is None else max_questions
        if budget <= 0:
            return []

        threshold = float(self.contract.get("min_utility", 1.0))
        style_weights = self._style_weights()
        asked = dict(asked_dimensions or {})
        exclude = set(exclude_ids or ())

        chosen = []
        pool = [q for q in self._eligible() if q["id"] not in exclude]
        exp_ratio = float(self.contract.get("experiential_ratio", 0.5))
        experiential_taken = 0

        while len(chosen) < budget and pool:
            scored = []
            for q in pool:
                s = score_question(
                    q,
                    self.resolved,
                    relevance_by_dimension=relevance_by_dimension,
                    misunderstanding_risk=misunderstanding_risk,
                    fatigue=fatigue,
                    asked_dimensions=asked,
                    style_weights=style_weights,
                )
                if s is not None:
                    scored.append(s)
            if not scored:
                break
            scored.sort(key=lambda s: -s["utility"])

            # Enforce the mode's experiential/technical mix as a quota rather
            # than only as a weight. Weighting alone collapses MEDIUM into HIGH
            # whenever experiential questions happen to score better, which
            # would make the modes indistinguishable in practice. The quota is
            # a preference, not a wall: if no question of the desired class
            # clears the utility bar, the other class is still allowed through,
            # because a genuinely necessary question outranks a target ratio.
            target_experiential = int(round(exp_ratio * (len(chosen) + 1)))
            want = "experiential" if experiential_taken < target_experiential else "technical"
            preferred = [s for s in scored if s["class"] == want and s["utility"] >= threshold]
            best = preferred[0] if preferred else scored[0]

            if best["utility"] < threshold:
                best["stopped_because"] = (
                    "marginal utility %.2f fell below the %s-mode threshold %.2f"
                    % (best["utility"], self.contract.get("mode", "?"), threshold)
                )
                break
            chosen.append(best)
            if best["class"] == "experiential":
                experiential_taken += 1
            pool = [q for q in pool if q["id"] != best["id"]]
            # Asking about a dimension makes further questions about it redundant.
            for dim in best["resolves"]:
                asked[dim] = asked.get(dim, 0) + 1
            # Simulate the answer partially resolving the uncertainty, which is
            # what makes the plan adaptive rather than a top-N list.
            for dim in best["resolves"]:
                belief = dict(self.resolved.get(dim) or {})
                prior = float(belief.get("confidence", 0.0))
                belief["confidence"] = prior + (1.0 - prior) * 0.55 * best["contributions"][0].get(
                    "relevance", 0.6
                )
                belief.setdefault("value", None)
                belief["provisional"] = True
                self.resolved[dim] = belief

            if not self.contract.get("adaptive_continue", True):
                continue

        return chosen

    def next_question(self, **kwargs):
        """Single highest-utility question, for HIGH mode's one-at-a-time loop."""
        kwargs["max_questions"] = 1
        plan = self.plan(**kwargs)
        return plan[0] if plan else None

    def should_stop(self, asked_count, last_utility, fatigue=0.0):
        """Whether HIGH mode's adaptive loop should end."""
        contract = self.contract
        if asked_count >= contract.get("max_questions", 0):
            return True, "question budget exhausted"
        threshold = float(contract.get("min_utility", 1.0)) * (1.0 + 1.5 * fatigue)
        if last_utility is not None and last_utility < threshold:
            return True, "marginal value (%.2f) below fatigue-adjusted cost (%.2f)" % (
                last_utility, threshold
            )
        return False, "continue"

    def explain(self, question_id):
        q = by_id(question_id)
        if not q:
            return None
        meta = [dimension_meta(d) for d in q["resolves"]]
        return {
            "question": q["text"],
            "style": q["style"],
            "resolves": [
                {"dimension": m["dimension"], "decision_impact": m["decision_impact"],
                 "note": m.get("note", "")}
                for m in meta
            ],
        }
