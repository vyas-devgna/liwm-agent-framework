"""Deterministic synthetic users.

These are **test fixtures**, not categories any real person gets sorted into.
Their whole purpose is falsifiability: each archetype has a hidden preference
vector, and the harness checks whether LIWM's beliefs move toward it, how many
questions that costs, and whether project-scoped noise leaks into the global
model.

Every simulator is seeded and deterministic, so a CI failure is reproducible.
"""

from __future__ import annotations

import hashlib

from ..question_bank import by_id

__all__ = ["ARCHETYPES", "SyntheticUser", "make_user"]


def _seeded_unit(seed, *parts):
    """Deterministic pseudo-random float in [0, 1) from a seed and some strings."""
    h = hashlib.sha256(("%s|%s" % (seed, "|".join(str(p) for p in parts))).encode("utf-8"))
    return int.from_bytes(h.digest()[:8], "big") / float(1 << 64)


#: Hidden preference vectors.  ``answer_noise`` is the probability that a
#: simulated answer contradicts the hidden truth, which is how the fixtures stay
#: honest about humans being inconsistent.
ARCHETYPES = {
    "novelty_seeking_expert": {
        "description": "Deep domain expertise, bored by conventional solutions, tolerant of rough edges.",
        "hidden": {
            "interaction_profile.preferred_verbosity": "terse",
            "interaction_profile.explanation_depth": "conclusion_plus_why",
            "interaction_profile.technical_language_preference": "specialist",
            "interaction_profile.preferred_question_frequency": "low",
            "interaction_profile.challenge_level": "challenge_me",
            "interaction_profile.autonomy_preference": "act_then_report",
            "reasoning_profile.novelty_preference": "novel",
            "reasoning_profile.abstraction_comfort": "abstract",
            "reasoning_profile.exploration_vs_execution": "lean_explore",
            "creative_profile.novelty_seeking": "unprecedented",
            "creative_profile.conventionality_tolerance": "low",
            "creative_profile.imperfection_tolerance": "high",
            "creative_profile.simplicity_vs_richness": "minimal",
            "decision_style.option_breadth": "one_recommendation",
            "working_style.planning_preference": "build_to_think",
        },
        "answer_noise": 0.10,
        "acceptance_strictness": 0.75,
        "question_patience": 0.45,
    },
    "conservative_beginner": {
        "description": "New to the domain, wants proven approaches and explanation, dislikes surprises.",
        "hidden": {
            "interaction_profile.preferred_verbosity": "thorough",
            "interaction_profile.explanation_depth": "full_derivation",
            "interaction_profile.technical_language_preference": "plain",
            "interaction_profile.preferred_question_frequency": "moderate",
            "interaction_profile.challenge_level": "balanced",
            "interaction_profile.autonomy_preference": "checkpoint",
            "interaction_profile.confirmation_preference": "confirm_risky",
            "interaction_profile.examples_vs_first_principles": "examples",
            "reasoning_profile.novelty_preference": "proven",
            "reasoning_profile.abstraction_comfort": "concrete",
            "creative_profile.novelty_seeking": "familiar",
            "creative_profile.conventionality_tolerance": "high",
            "creative_profile.imperfection_tolerance": "low",
            "decision_style.option_breadth": "two_or_three",
            "decision_style.reversibility_preference": "prefer_reversible",
        },
        "answer_noise": 0.15,
        "acceptance_strictness": 0.55,
        "question_patience": 0.80,
    },
    "impatient_technical_expert": {
        "description": "Knows exactly what they want, hates being asked, punishes verbosity.",
        "hidden": {
            "interaction_profile.preferred_verbosity": "terse",
            "interaction_profile.explanation_depth": "conclusion_only",
            "interaction_profile.technical_language_preference": "specialist",
            "interaction_profile.preferred_question_frequency": "minimal",
            "interaction_profile.preferred_directness": "blunt",
            "interaction_profile.autonomy_preference": "full_autonomy",
            "interaction_profile.confirmation_preference": "confirm_irreversible",
            "interaction_profile.pace": "fast",
            "reasoning_profile.exploration_vs_execution": "execute",
            "reasoning_profile.step_omission_tolerance": "skip_obvious",
            "decision_style.option_breadth": "one_recommendation",
            "decision_style.speed": "decisive",
            "working_style.documentation_appetite": "minimal",
            "communication_profile.formatting_preference": "tables_and_code",
        },
        "answer_noise": 0.08,
        "acceptance_strictness": 0.85,
        "question_patience": 0.15,
    },
    "exploratory_nontechnical_creator": {
        "description": "Strong taste, weak jargon; answers scenarios well and technical questions badly.",
        "hidden": {
            "interaction_profile.preferred_verbosity": "balanced",
            "interaction_profile.technical_language_preference": "plain",
            "interaction_profile.examples_vs_first_principles": "examples",
            "interaction_profile.preferred_question_frequency": "moderate",
            "interaction_profile.autonomy_preference": "checkpoint",
            "reasoning_profile.exploration_vs_execution": "explore",
            "reasoning_profile.abstraction_comfort": "concrete",
            "creative_profile.novelty_seeking": "novel",
            "creative_profile.aesthetic_direction": "warm_and_tactile",
            "creative_profile.creative_risk_appetite": "high",
            "creative_profile.simplicity_vs_richness": "minimal",
            "working_style.planning_preference": "sketch_then_build",
            "decision_style.option_breadth": "two_or_three",
        },
        "answer_noise": 0.20,
        "acceptance_strictness": 0.60,
        "question_patience": 0.70,
        "technical_question_penalty": 0.6,
    },
    "detail_oriented_researcher": {
        "description": "Wants derivations, citations and edge cases; tolerant of long answers.",
        "hidden": {
            "interaction_profile.preferred_verbosity": "thorough",
            "interaction_profile.explanation_depth": "full_derivation",
            "interaction_profile.examples_vs_first_principles": "first_principles",
            "interaction_profile.technical_language_preference": "specialist",
            "interaction_profile.preferred_question_frequency": "moderate",
            "reasoning_profile.detail_sensitivity": "detail_oriented",
            "reasoning_profile.evidence_preference": "measurement",
            "reasoning_profile.abstraction_comfort": "abstract",
            "reasoning_profile.systems_thinking_preference": "systemic",
            "working_style.review_style": "read_everything",
            "working_style.documentation_appetite": "thorough",
            "decision_style.option_breadth": "wide_survey",
            "decision_style.speed": "deliberative",
        },
        "answer_noise": 0.10,
        "acceptance_strictness": 0.80,
        "question_patience": 0.85,
    },
    "high_autonomy_builder": {
        "description": "Delegates hard, checks results, wants milestones not commentary.",
        "hidden": {
            "interaction_profile.preferred_verbosity": "balanced",
            "interaction_profile.autonomy_preference": "full_autonomy",
            "interaction_profile.confirmation_preference": "confirm_irreversible",
            "interaction_profile.progress_visibility": "milestones",
            "interaction_profile.preferred_question_frequency": "low",
            "reasoning_profile.exploration_vs_execution": "lean_execute",
            "decision_style.delegation_comfort": "high",
            "decision_style.automation_appetite": "automate_by_default",
            "decision_style.option_breadth": "one_recommendation",
            "working_style.scope_discipline": "tight_scope",
            "working_style.iteration_style": "few_iterations",
        },
        "answer_noise": 0.12,
        "acceptance_strictness": 0.70,
        "question_patience": 0.35,
    },
}


class SyntheticUser:
    """A deterministic stand-in for a person, with a hidden preference vector."""

    def __init__(self, archetype, seed=1337, project_overrides=None):
        if archetype not in ARCHETYPES:
            raise KeyError("unknown archetype %r" % archetype)
        spec = ARCHETYPES[archetype]
        self.archetype = archetype
        self.seed = seed
        self.hidden = dict(spec["hidden"])
        self.answer_noise = spec["answer_noise"]
        self.acceptance_strictness = spec["acceptance_strictness"]
        self.question_patience = spec["question_patience"]
        self.technical_question_penalty = spec.get("technical_question_penalty", 0.0)
        #: Project-only requirements that must NOT leak into the global model.
        self.project_overrides = dict(project_overrides or {})
        self.questions_seen = 0
        self.log = []

    # -- answering ---------------------------------------------------------
    def answer(self, question_id):
        """Answer a planned question, returning observations LIWM would extract.

        Returns ``None`` when the simulated user ignores the question, which
        happens more often as patience is exhausted - the behaviour that should
        teach LIWM to ask less.
        """
        q = by_id(question_id)
        if q is None:
            return None
        self.questions_seen += 1

        tolerance = self.question_patience * (0.85 ** (self.questions_seen - 1))
        if q["class"] == "technical":
            tolerance -= self.technical_question_penalty * 0.5
        roll = _seeded_unit(self.seed, "patience", question_id, self.questions_seen)
        if roll > max(0.05, tolerance):
            self.log.append({"question": question_id, "response": "ignored"})
            return None

        observations = []
        for dim in q["resolves"]:
            truth = self.hidden.get(dim)
            if truth is None:
                continue
            noisy = _seeded_unit(self.seed, "noise", question_id, dim) < self.answer_noise
            value = _perturb(truth, dim, self.seed) if noisy else truth
            observations.append({
                "dimension": dim,
                "value": value,
                "polarity": "support",
                "truthful": not noisy,
            })
        self.log.append({"question": question_id, "response": "answered",
                         "observations": len(observations)})
        return {
            "question_id": question_id,
            "style": q["style"],
            "class": q["class"],
            "observations": observations,
            "useful": bool(observations),
        }

    # -- reacting ----------------------------------------------------------
    def react(self, proposed):
        """Judge an artifact described as a dict of dimension -> chosen value."""
        matched = total = 0
        mismatches = []
        for dim, value in (proposed or {}).items():
            truth = self.project_overrides.get(dim, self.hidden.get(dim))
            if truth is None:
                continue
            total += 1
            if str(value) == str(truth):
                matched += 1
            else:
                mismatches.append({"dimension": dim, "wanted": truth, "got": value})

        if total == 0:
            return {"acceptance": 0.5, "kind": "custom", "mismatches": [],
                    "note": "nothing measurable"}

        ratio = matched / total
        # A strict user needs a higher match ratio before saying it is right.
        acceptance = max(0.0, min(1.0, (ratio - (1.0 - self.acceptance_strictness))
                                  / max(1e-6, self.acceptance_strictness)))
        kind = (
            "exactly_right" if acceptance >= 0.95 else
            "mostly_right" if acceptance >= 0.75 else
            "direction_right_execution_wrong" if acceptance >= 0.45 else
            "misunderstood_intent"
        )
        return {
            "acceptance": round(acceptance, 4),
            "kind": kind,
            "mismatches": mismatches,
            "match_ratio": round(ratio, 4),
        }

    def preferred(self, dimension, project_id=None):
        """The truth for a dimension, honouring project-only overrides."""
        if project_id and dimension in self.project_overrides:
            return self.project_overrides[dimension]
        return self.hidden.get(dimension)

    def hidden_dimensions(self):
        return sorted(self.hidden)


def _perturb(value, dimension, seed):
    """Pick a different plausible value, for simulating inconsistent answers."""
    from ..taxonomy import dimension_meta

    options = [v for v in dimension_meta(dimension).get("values", ()) if v != value]
    if not options:
        return "%s_variant" % value
    idx = int(_seeded_unit(seed, "perturb", dimension, value) * len(options))
    return options[min(idx, len(options) - 1)]


def make_user(archetype, seed=1337, project_overrides=None):
    return SyntheticUser(archetype, seed=seed, project_overrides=project_overrides)
