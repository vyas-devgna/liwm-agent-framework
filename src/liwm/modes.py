"""Operating modes: LOW, MEDIUM, HIGH, AUTO, OFF.

The modes are not "ask 1 vs 3 vs 7 questions".  They select a *kind of
reasoning*:

* **LOW** trusts the model of the user and the environment, and buys information
  with cheap, direct, technical questions when it must.
* **MEDIUM** balances direct elicitation with experiential probes, and resolves
  ambiguity that would meaningfully change the artifact before building.
* **HIGH** is intent-first.  It refuses to make the user translate their
  imagination into specialist vocabulary, and instead asks about situations,
  comparisons, counterfactuals and anti-examples until the marginal value of
  another question drops below its cost.
* **AUTO** picks among them per task, and - critically - gets quieter as the
  profile matures.  A personalisation framework that keeps interviewing you
  forever has failed (constitution C15).

Mode never overrides an explicit instruction; it only shapes what LIWM does
about what is *unstated*.
"""

from __future__ import annotations

from .evidence import clamp

__all__ = [
    "MODES",
    "MODE_PROFILES",
    "mode_profile",
    "Signals",
    "resolve_auto",
    "question_budget",
    "STAGE_WEIGHTS",
]

MODES = ("off", "silent", "low", "medium", "high", "auto")

#: Behavioural contract per mode.  ``liwm.evaluation`` asserts that these stay
#: behaviourally distinguishable; tests fail if two modes collapse together.
MODE_PROFILES = {
    "off": {
        "mode": "off",
        "max_questions": 0,
        "min_utility": 99.0,
        "experiential_ratio": 0.0,
        "technical_ratio": 0.0,
        "styles": (),
        "one_at_a_time": True,
        "adaptive_continue": False,
        "use_profile": False,
        "record_evidence": False,
        "summary": "LIWM is dormant. No profile consultation, no learning, no questions.",
    },
    # The research ablation, and the only honest one.  A study comparing "LIWM"
    # against "LIWM with questions disabled" cannot use OFF, because OFF also
    # stops consulting the profile and stops learning, so it measures three
    # changes at once and attributes all of them to elicitation.  SILENT keeps
    # the profile and the learning and removes only the asking.
    "silent": {
        "mode": "silent",
        "max_questions": 0,
        "min_utility": 99.0,
        "experiential_ratio": 0.0,
        "technical_ratio": 0.0,
        "styles": (),
        "one_at_a_time": True,
        "adaptive_continue": False,
        "use_profile": True,
        "record_evidence": True,
        "summary": (
            "Consult the profile and keep learning, but never ask. State "
            "assumptions instead of resolving them. This is research condition "
            "E, the no-elicitation ablation - not the same thing as OFF."
        ),
    },
    "low": {
        "mode": "low",
        "max_questions": 3,
        "min_utility": 1.35,
        "experiential_ratio": 0.30,
        "technical_ratio": 0.70,
        "styles": ("direct_technical", "constraint_check", "comparative", "scenario"),
        "one_at_a_time": False,
        "adaptive_continue": False,
        "use_profile": True,
        "record_evidence": True,
        "summary": (
            "Bias hard toward execution. Lean on the existing profile, make reversible "
            "assumptions and state them. 0-3 questions, mostly direct and technical."
        ),
    },
    "medium": {
        "mode": "medium",
        "max_questions": 6,
        "min_utility": 0.85,
        "experiential_ratio": 0.50,
        "technical_ratio": 0.50,
        "styles": ("direct_technical", "scenario", "comparative", "tradeoff",
                   "anti_example", "constraint_check"),
        "one_at_a_time": False,
        "adaptive_continue": True,
        "use_profile": True,
        "record_evidence": True,
        "summary": (
            "Balanced elicitation. Resolve ambiguity that would materially change the "
            "artifact before building. 2-6 adaptive questions, half experiential."
        ),
    },
    "high": {
        "mode": "high",
        "max_questions": 12,
        "min_utility": 0.45,
        "experiential_ratio": 0.80,
        "technical_ratio": 0.20,
        "styles": ("scenario", "counterfactual", "comparative", "anti_example",
                   "lived_experience", "emotional_reaction", "tradeoff", "direct_technical"),
        "one_at_a_time": True,
        "adaptive_continue": True,
        "use_profile": True,
        "record_evidence": True,
        "summary": (
            "Intent-first. Investigate what the person is imagining rather than making them "
            "specify an implementation. One question at a time, experiential and "
            "counterfactual by default, continuing while marginal value exceeds cost."
        ),
    },
}


def mode_profile(mode):
    """Return the behavioural contract for *mode* (``auto`` must be resolved first)."""
    key = (mode or "auto").strip().lower()
    if key == "auto":
        raise ValueError("resolve AUTO with resolve_auto() before requesting a profile")
    if key not in MODE_PROFILES:
        raise ValueError("unknown mode %r (expected one of %s)" % (mode, ", ".join(MODES)))
    return dict(MODE_PROFILES[key])


#: How much investigation a project stage warrants on its own.
STAGE_WEIGHTS = {
    "inception": 1.00,
    "design": 0.75,
    "build": 0.35,
    "refine": 0.30,
    "debug": 0.15,
    "maintenance": 0.10,
    "unknown": 0.45,
}

#: Stated preference for being asked things -> additive nudge.
QUESTION_PREFERENCE_NUDGE = {
    "minimal": -0.28,
    "low": -0.15,
    "moderate": 0.0,
    "high": 0.12,
}


class Signals:
    """Inputs to the AUTO decision.

    All fields are in [0, 1] unless noted.  They are estimates the calling skill
    supplies from the current situation; AUTO is a policy over them, not a
    mind-reader.
    """

    __slots__ = (
        "intent_uncertainty", "novelty", "consequence", "reversibility",
        "specification_completeness", "profile_maturity", "recent_correction_rate",
        "fatigue", "project_stage", "question_preference", "domain_evidence",
    )

    def __init__(
        self,
        intent_uncertainty=0.5,
        novelty=0.3,
        consequence=0.5,
        reversibility=0.7,
        specification_completeness=0.5,
        profile_maturity=0.0,
        recent_correction_rate=0.0,
        fatigue=0.0,
        project_stage="unknown",
        question_preference="moderate",
        domain_evidence=0.0,
    ):
        self.intent_uncertainty = clamp(intent_uncertainty)
        self.novelty = clamp(novelty)
        self.consequence = clamp(consequence)
        self.reversibility = clamp(reversibility)
        self.specification_completeness = clamp(specification_completeness)
        self.profile_maturity = clamp(profile_maturity)
        self.recent_correction_rate = clamp(recent_correction_rate)
        self.fatigue = clamp(fatigue)
        self.project_stage = project_stage or "unknown"
        self.question_preference = question_preference or "moderate"
        self.domain_evidence = clamp(domain_evidence)

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}


def resolve_auto(signals, thresholds=(0.30, 0.62)):
    """Resolve AUTO into a concrete mode, with a legible rationale.

    The scoring is intentionally simple and inspectable.  Three properties are
    load-bearing and are asserted by the test suite:

    * irreversible + high-consequence work raises investigation even when the
      request looks clear;
    * a mature profile *lowers* investigation - understanding must convert into
      fewer questions, not more;
    * fatigue and a stated preference for not being asked can veto questioning
      almost entirely.
    """
    s = signals if isinstance(signals, Signals) else Signals(**(signals or {}))

    stage_weight = STAGE_WEIGHTS.get(s.project_stage, STAGE_WEIGHTS["unknown"])
    irreversibility = 1.0 - s.reversibility

    terms = {
        "intent_uncertainty": 0.34 * s.intent_uncertainty,
        "novelty": 0.18 * s.novelty,
        "consequence_x_irreversibility": 0.22 * s.consequence * irreversibility,
        "project_stage": 0.14 * stage_weight,
        "recent_corrections": 0.12 * s.recent_correction_rate,
    }
    raw = sum(terms.values())

    modifiers = {
        # Exploiting accumulated understanding is the entire point.
        "profile_maturity": -0.26 * s.profile_maturity,
        "domain_evidence": -0.10 * s.domain_evidence,
        "already_specified": -0.22 * s.specification_completeness,
        "fatigue": -0.30 * s.fatigue,
        "stated_question_preference": QUESTION_PREFERENCE_NUDGE.get(s.question_preference, 0.0),
    }
    need = clamp(raw + sum(modifiers.values()))

    low_t, high_t = thresholds
    if need < low_t:
        mode = "low"
    elif need < high_t:
        mode = "medium"
    else:
        mode = "high"

    profile = mode_profile(mode)
    profile["resolved_from"] = "auto"
    profile["investigation_need"] = round(need, 4)
    profile["max_questions"] = question_budget(mode, s)
    profile["rationale"] = _rationale(mode, need, terms, modifiers)
    profile["terms"] = {k: round(v, 4) for k, v in terms.items()}
    profile["modifiers"] = {k: round(v, 4) for k, v in modifiers.items()}
    profile["signals"] = s.to_dict()
    return profile


def _rationale(mode, need, terms, modifiers):
    drivers = sorted(terms.items(), key=lambda kv: -kv[1])[:2]
    dampers = sorted(modifiers.items(), key=lambda kv: kv[1])[:2]
    parts = ["investigation need %.2f -> %s" % (need, mode.upper())]
    if drivers and drivers[0][1] > 0.05:
        parts.append("driven by " + ", ".join(k for k, v in drivers if v > 0.05))
    if dampers and dampers[0][1] < -0.05:
        parts.append("damped by " + ", ".join(k for k, v in dampers if v < -0.05))
    return "; ".join(parts)


def question_budget(mode, signals=None):
    """Concrete question budget after fatigue and stated preference."""
    base = MODE_PROFILES[mode]["max_questions"]
    if signals is None:
        return base
    s = signals if isinstance(signals, Signals) else Signals(**(signals or {}))
    budget = base * (1.0 - 0.6 * s.fatigue)
    if s.question_preference == "minimal":
        budget = min(budget, 1)
    elif s.question_preference == "low":
        budget = min(budget, max(1, base - 2))
    # A mature profile should convert into fewer questions, never more.
    budget *= (1.0 - 0.25 * s.profile_maturity)
    return max(0, int(round(budget)))
