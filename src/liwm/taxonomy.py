"""The dimension taxonomy: what LIWM is allowed to have opinions about.

Two things make this module load-bearing rather than decorative:

1. **It is an allowlist.**  A dimension outside this taxonomy cannot be created
   by a skill, an inference, or an injected instruction.  Combined with the
   privacy gate, that is what stops the profile from quietly growing a
   ``user.religion`` field.
2. **It carries decision impact.**  The question planner needs to know which
   uncertainties actually change the artifact.  ``decision_impact`` is that
   estimate, and it is a tuned parameter rather than a guess the model makes at
   runtime.

Every dimension is *actionable*: it changes how an agent should behave.  There
are deliberately no dimensions for "how smart the user is" - see C08.  The
closest LIWM gets is domain-specific fluency and explanation-granularity
preference, which are things you can actually act on without ranking a person.
"""

from __future__ import annotations

__all__ = [
    "DIMENSIONS",
    "DIMENSION_INDEX",
    "SECTIONS",
    "DOMAINS",
    "is_known_dimension",
    "dimension_meta",
    "decision_impact",
    "dimensions_for_section",
    "open_namespaces",
]

#: Free-form namespaces where leaf names are user/project specific and cannot
#: be enumerated in advance (a preference for "tabs over spaces" is not a fixed
#: dimension).  Leaves here are still privacy-screened.
open_namespaces = ("preferences", "anti_preferences", "goals", "anti_goals",
                   "expectations", "domain_fluency")

SECTIONS = (
    "interaction_profile",
    "reasoning_profile",
    "creative_profile",
    "working_style",
    "decision_style",
    "communication_profile",
    "domain_fluency",
)

#: Domains LIWM recognises for scoping.  Extensible at runtime; these are the
#: seeds used by cross-domain transfer analysis and by the onboarding planner.
DOMAINS = (
    "software",
    "systems_infrastructure",
    "data_ml",
    "research",
    "writing",
    "visual_design",
    "product",
    "business",
    "hardware",
    "operations",
    "education",
    "personal",
)


def _d(name, values, impact, cost, decay="standard", note=""):
    return {
        "dimension": name,
        "values": tuple(values),
        "decision_impact": impact,
        "elicitation_cost": cost,
        "default_decay": decay,
        "note": note,
    }


DIMENSIONS = (
    # ---------------- interaction ----------------
    _d("interaction_profile.preferred_verbosity",
       ("terse", "balanced", "thorough"), 0.85, 0.25, "standard",
       "How much prose the user wants around an answer."),
    _d("interaction_profile.preferred_directness",
       ("blunt", "direct", "diplomatic", "gentle"), 0.7, 0.3, "standard",
       "How hedged conclusions and disagreement should be."),
    _d("interaction_profile.preferred_question_frequency",
       ("minimal", "low", "moderate", "high"), 0.95, 0.2, "standard",
       "Directly sets the question budget; the highest-leverage dimension."),
    _d("interaction_profile.technical_language_preference",
       ("plain", "mixed", "specialist"), 0.6, 0.3, "slow"),
    _d("interaction_profile.explanation_depth",
       ("conclusion_only", "conclusion_plus_why", "full_derivation"), 0.8, 0.3),
    _d("interaction_profile.examples_vs_first_principles",
       ("examples", "balanced", "first_principles"), 0.7, 0.35),
    _d("interaction_profile.pace",
       ("deliberate", "steady", "fast"), 0.55, 0.35, "volatile"),
    _d("interaction_profile.challenge_level",
       ("agreeable", "balanced", "challenge_me"), 0.75, 0.4, "standard",
       "How readily the agent should push back. Never tuned toward flattery (C09)."),
    _d("interaction_profile.autonomy_preference",
       ("ask_first", "checkpoint", "act_then_report", "full_autonomy"), 0.95, 0.3),
    _d("interaction_profile.confirmation_preference",
       ("confirm_everything", "confirm_risky", "confirm_irreversible", "rarely_confirm"), 0.9, 0.3),
    _d("interaction_profile.progress_visibility",
       ("silent", "milestones", "running_commentary"), 0.5, 0.3, "standard"),

    # ---------------- reasoning ----------------
    _d("reasoning_profile.abstraction_comfort",
       ("concrete", "mixed", "abstract"), 0.7, 0.45, "slow"),
    _d("reasoning_profile.systems_thinking_preference",
       ("local_fix", "balanced", "systemic"), 0.75, 0.45, "slow"),
    _d("reasoning_profile.exploration_vs_execution",
       ("execute", "lean_execute", "lean_explore", "explore"), 0.9, 0.35, "volatile"),
    _d("reasoning_profile.novelty_preference",
       ("proven", "balanced", "novel"), 0.85, 0.4),
    _d("reasoning_profile.ambiguity_tolerance",
       ("low", "moderate", "high"), 0.6, 0.45),
    _d("reasoning_profile.risk_tolerance_in_projects",
       ("conservative", "moderate", "bold"), 0.85, 0.4, "standard",
       "Notoriously project-specific; promote to global only with cross-project evidence."),
    _d("reasoning_profile.detail_sensitivity",
       ("big_picture", "balanced", "detail_oriented"), 0.7, 0.4, "slow"),
    _d("reasoning_profile.evidence_preference",
       ("intuition", "mixed", "measurement"), 0.65, 0.4, "slow"),
    _d("reasoning_profile.tradeoff_style",
       ("optimise_one_axis", "balanced", "satisfice"), 0.6, 0.5),
    _d("reasoning_profile.step_omission_tolerance",
       ("show_all_steps", "moderate", "skip_obvious"), 0.6, 0.35, "slow",
       "How much intermediate reasoning can be omitted without losing the user."),
    _d("reasoning_profile.conceptual_uptake_speed",
       ("deliberate", "typical", "fast"), 0.45, 0.5, "slow",
       "Observed pace of picking up a new concept in a specific domain. "
       "Never a global ranking of the person (C08)."),

    # ---------------- creative ----------------
    _d("creative_profile.novelty_seeking",
       ("familiar", "balanced", "novel", "unprecedented"), 0.85, 0.35),
    _d("creative_profile.conventionality_tolerance",
       ("rejects_convention", "low", "moderate", "high"), 0.7, 0.4),
    _d("creative_profile.polish_vs_rough",
       ("polish_first", "balanced", "rough_and_fast"), 0.7, 0.3, "volatile"),
    _d("creative_profile.simplicity_vs_richness",
       ("minimal", "balanced", "feature_rich"), 0.85, 0.3),
    _d("creative_profile.aesthetic_direction",
       (), 0.6, 0.45, "standard", "Free-text aesthetic pulls; multi-valued."),
    _d("creative_profile.creative_risk_appetite",
       ("safe", "moderate", "high"), 0.75, 0.4),
    _d("creative_profile.imperfection_tolerance",
       ("low", "moderate", "high"), 0.6, 0.35),

    # ---------------- working style ----------------
    _d("working_style.session_length_preference",
       ("short_bursts", "medium", "deep_sessions"), 0.4, 0.35, "volatile"),
    _d("working_style.iteration_style",
       ("one_shot", "few_iterations", "many_iterations"), 0.7, 0.35),
    _d("working_style.review_style",
       ("trust_and_spot_check", "read_everything", "test_driven"), 0.65, 0.35),
    _d("working_style.planning_preference",
       ("plan_first", "sketch_then_build", "build_to_think"), 0.8, 0.35),
    _d("working_style.scope_discipline",
       ("tight_scope", "balanced", "opportunistic_expansion"), 0.7, 0.4),
    _d("working_style.tooling_attitude",
       ("minimal_tooling", "pragmatic", "tooling_enthusiast"), 0.5, 0.4, "slow"),
    _d("working_style.documentation_appetite",
       ("minimal", "proportionate", "thorough"), 0.55, 0.3),
    _d("working_style.frustration_triggers",
       (), 0.8, 0.4, "slow", "Free-text; high value for avoiding known irritants."),

    # ---------------- decision style ----------------
    _d("decision_style.speed",
       ("deliberative", "balanced", "decisive"), 0.7, 0.35, "slow"),
    _d("decision_style.reversibility_preference",
       ("prefer_reversible", "balanced", "commit_hard"), 0.8, 0.4),
    _d("decision_style.option_breadth",
       ("one_recommendation", "two_or_three", "wide_survey"), 0.85, 0.25, "standard",
       "How many alternatives to present. Directly shapes every answer's shape."),
    _d("decision_style.delegation_comfort",
       ("low", "moderate", "high"), 0.8, 0.35),
    _d("decision_style.automation_appetite",
       ("manual_control", "assisted", "automate_by_default"), 0.8, 0.3),

    # ---------------- communication ----------------
    _d("communication_profile.tone",
       ("formal", "neutral", "casual", "playful"), 0.4, 0.25, "slow"),
    _d("communication_profile.humour",
       ("none", "occasional", "welcome"), 0.25, 0.3, "slow"),
    _d("communication_profile.formatting_preference",
       ("prose", "mixed", "bullets", "tables_and_code"), 0.55, 0.2),
    _d("communication_profile.emoji_tolerance",
       ("none", "sparing", "welcome"), 0.2, 0.15, "slow"),
    _d("communication_profile.vocabulary_register",
       ("plain", "professional", "technical", "academic"), 0.5, 0.3, "slow"),
)

DIMENSION_INDEX = {d["dimension"]: d for d in DIMENSIONS}


def is_known_dimension(dimension):
    """True when *dimension* is in the taxonomy or in an open namespace."""
    if not dimension:
        return False
    if dimension in DIMENSION_INDEX:
        return True
    root = str(dimension).split(".", 1)[0]
    return root in open_namespaces


def dimension_meta(dimension):
    """Metadata for a dimension, with sensible defaults for open namespaces."""
    if dimension in DIMENSION_INDEX:
        return DIMENSION_INDEX[dimension]
    root = str(dimension).split(".", 1)[0]
    if root in open_namespaces:
        return {
            "dimension": dimension,
            "values": (),
            "decision_impact": 0.6 if root in ("preferences", "anti_preferences") else 0.5,
            "elicitation_cost": 0.35,
            "default_decay": "slow" if root == "domain_fluency" else "standard",
            "note": "open namespace",
        }
    return {
        "dimension": dimension,
        "values": (),
        "decision_impact": 0.3,
        "elicitation_cost": 0.5,
        "default_decay": "standard",
        "note": "unknown dimension",
    }


def decision_impact(dimension):
    """How much getting this dimension wrong changes the produced artifact."""
    return float(dimension_meta(dimension).get("decision_impact", 0.3))


def dimensions_for_section(section):
    return tuple(d for d in DIMENSIONS if d["dimension"].startswith(section + "."))
