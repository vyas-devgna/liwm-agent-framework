"""The question bank.

These are *templates and exemplars*, not a script.  The planner selects from
them by expected utility, and the host model is expected to rewrite the chosen
question in the user's own context rather than reciting it verbatim - a question
about "the thing you're building" should name the actual thing.

Two rules shaped every entry:

1. **Do not make the user translate their imagination into jargon.**  A question
   the user can answer from lived experience beats a question that requires them
   to already know the answer in implementation terms.
2. **Each question must resolve something that changes the artifact.**  If the
   answer would not alter what gets built, the question is a tax.

Styles
------
``scenario``           imagined situation, answered from instinct
``comparative``        "which of these feels closer"
``counterfactual``     "suppose it worked perfectly / suppose it failed"
``anti_example``       "what should never happen"
``tradeoff``           forced choice between two goods
``lived_experience``   a real thing the user has used, made or abandoned
``emotional_reaction`` what would delight or irritate
``direct_technical``   plain, specific, technical
``constraint_check``   confirm a boundary before spending effort
"""

from __future__ import annotations

__all__ = ["QUESTION_BANK", "STYLE_CLASS", "questions_for", "by_id", "FAMILIES"]

#: Which styles count as "experiential" for the LOW/MEDIUM/HIGH ratio contract.
STYLE_CLASS = {
    "scenario": "experiential",
    "comparative": "experiential",
    "counterfactual": "experiential",
    "anti_example": "experiential",
    "tradeoff": "experiential",
    "lived_experience": "experiential",
    "emotional_reaction": "experiential",
    "direct_technical": "technical",
    "constraint_check": "technical",
}

#: Onboarding samples across these families, never more than two per family.
FAMILIES = (
    "novelty_vs_familiarity",
    "automation_vs_control",
    "detail_vs_speed",
    "exploration_vs_execution",
    "aesthetic_instinct",
    "frustration_triggers",
    "imperfection_tolerance",
    "being_challenged",
    "explanation_style",
    "ambition",
    "simplicity_vs_richness",
    "convention_tolerance",
    "decision_style",
    "examples_vs_theory",
    "creative_risk",
    "communication_style",
)


def _q(qid, style, family, resolves, text, cost=0.3, power=0.6, onboarding=True, followups=None):
    return {
        "id": qid,
        "style": style,
        "family": family,
        "resolves": tuple(resolves),
        "text": text,
        "cognitive_cost": cost,
        "resolution_power": power,
        "onboarding_ok": onboarding,
        "class": STYLE_CLASS[style],
        "followups": tuple(followups or ()),
    }


QUESTION_BANK = (
    # ---------------- novelty vs familiarity ----------------
    _q("nov_two_versions", "comparative", "novelty_vs_familiarity",
       ["creative_profile.novelty_seeking", "reasoning_profile.novelty_preference",
        "creative_profile.conventionality_tolerance"],
       "Two versions of this land on your desk tomorrow. One is extremely polished but "
       "predictable. The other feels unlike anything you've used, with some rough edges. "
       "Which do you open first — and which do you still have open an hour later?",
       cost=0.25, power=0.75),
    _q("nov_boring_but_right", "tradeoff", "novelty_vs_familiarity",
       ["reasoning_profile.novelty_preference", "creative_profile.creative_risk_appetite"],
       "If the boring approach is 95% as good and half the risk, is that a win or a "
       "disappointment to you?",
       cost=0.2, power=0.6),
    _q("nov_abandoned_tool", "lived_experience", "novelty_vs_familiarity",
       ["creative_profile.novelty_seeking", "working_style.tooling_attitude"],
       "Think of something clever you tried and then abandoned. What made you drop it?",
       cost=0.4, power=0.65),

    # ---------------- automation vs control ----------------
    _q("auto_delete_decision", "scenario", "automation_vs_control",
       ["decision_style.automation_appetite", "interaction_profile.autonomy_preference"],
       "You can make one repetitive decision disappear from your life forever — it just "
       "gets made for you, correctly, every time. Which decision do you pick?",
       cost=0.25, power=0.7),
    _q("auto_three_ways", "comparative", "automation_vs_control",
       ["interaction_profile.autonomy_preference", "interaction_profile.confirmation_preference",
        "decision_style.reversibility_preference"],
       "Three ways this could work: (A) it just does the thing, (B) it shows you exactly "
       "what it will do and waits, (C) it does the thing but leaves an obvious undo. "
       "Which feels right — and does your answer change when the stakes go up?",
       cost=0.3, power=0.85),
    _q("auto_wake_up_done", "counterfactual", "automation_vs_control",
       ["interaction_profile.autonomy_preference", "decision_style.delegation_comfort"],
       "Imagine you go to sleep and wake up to this already finished, exactly as you'd have "
       "wanted. Is that a relief or does something about it bother you?",
       cost=0.3, power=0.7),

    # ---------------- detail vs speed ----------------
    _q("det_annoying_faster", "comparative", "detail_vs_speed",
       ["interaction_profile.explanation_depth", "reasoning_profile.step_omission_tolerance",
        "interaction_profile.preferred_verbosity"],
       "When someone explains something complicated, which becomes annoying faster: too much "
       "explanation, or unexplained jumps you have to reconstruct?",
       cost=0.2, power=0.8),
    _q("det_rough_draft", "scenario", "detail_vs_speed",
       ["creative_profile.polish_vs_rough", "working_style.iteration_style"],
       "Would you rather see something rough in ten minutes, or something considered in two "
       "hours? Be honest about which one you'd actually rather receive.",
       cost=0.2, power=0.7),
    _q("det_last_10_percent", "tradeoff", "detail_vs_speed",
       ["creative_profile.polish_vs_rough", "working_style.scope_discipline"],
       "The last 10% of polish usually costs as much as the first 90%. Where do you normally "
       "want to stop?",
       cost=0.25, power=0.6),

    # ---------------- exploration vs execution ----------------
    _q("exp_map_or_walk", "comparative", "exploration_vs_execution",
       ["reasoning_profile.exploration_vs_execution", "working_style.planning_preference"],
       "Do you figure out where you're going by drawing the map first, or by walking and "
       "seeing what's there?",
       cost=0.2, power=0.75),
    _q("exp_detour", "scenario", "exploration_vs_execution",
       ["working_style.scope_discipline", "reasoning_profile.exploration_vs_execution"],
       "Halfway through, something interesting but off-topic appears. Do you want me to chase "
       "it, mention it and move on, or say nothing until we're done?",
       cost=0.25, power=0.7),

    # ---------------- aesthetic instinct ----------------
    _q("aes_feels_right", "lived_experience", "aesthetic_instinct",
       ["creative_profile.aesthetic_direction", "creative_profile.simplicity_vs_richness"],
       "Name something you enjoy using even though alternatives technically do more. What "
       "makes it feel right?",
       cost=0.35, power=0.8),
    _q("aes_ugly_but_works", "tradeoff", "aesthetic_instinct",
       ["creative_profile.aesthetic_direction", "creative_profile.simplicity_vs_richness"],
       "Something that works perfectly but looks wrong, versus something beautiful with a "
       "known rough patch. Which bothers you more?",
       cost=0.25, power=0.65),
    _q("aes_first_impression", "emotional_reaction", "aesthetic_instinct",
       ["creative_profile.aesthetic_direction"],
       "When this is done and you show it to someone, what's the reaction you're hoping for "
       "in the first three seconds?",
       cost=0.3, power=0.75),

    # ---------------- frustration triggers ----------------
    _q("fru_close_the_tab", "emotional_reaction", "frustration_triggers",
       ["working_style.frustration_triggers", "interaction_profile.preferred_verbosity"],
       "What's the fastest way for a tool — or a person helping you — to make you close the "
       "tab and do it yourself?",
       cost=0.25, power=0.8),
    _q("fru_never_happen", "anti_example", "frustration_triggers",
       ["working_style.frustration_triggers", "anti_preferences.general"],
       "What should never happen here? Even once.",
       cost=0.2, power=0.85),
    _q("fru_last_time_annoyed", "lived_experience", "frustration_triggers",
       ["working_style.frustration_triggers"],
       "Last time an AI assistant genuinely irritated you, what had it just done?",
       cost=0.3, power=0.75),

    # ---------------- imperfection tolerance ----------------
    _q("imp_half_works", "scenario", "imperfection_tolerance",
       ["creative_profile.imperfection_tolerance", "reasoning_profile.ambiguity_tolerance"],
       "An experiment that half works and teaches you something, versus a safe result that "
       "teaches you nothing. Which is the better afternoon?",
       cost=0.25, power=0.7),
    _q("imp_show_me_broken", "scenario", "imperfection_tolerance",
       ["creative_profile.polish_vs_rough", "interaction_profile.progress_visibility"],
       "If something's half-built and clearly not working yet, do you want to see it, or "
       "would you rather I fix it first?",
       cost=0.2, power=0.65),

    # ---------------- being challenged ----------------
    _q("chal_wrong_assumption", "scenario", "being_challenged",
       ["interaction_profile.challenge_level", "interaction_profile.preferred_directness"],
       "You ask for something and I think the underlying assumption is wrong. Do you want me "
       "to build it anyway and say so, argue first, or just build it?",
       cost=0.3, power=0.85),
    _q("chal_pushback_style", "comparative", "being_challenged",
       ["interaction_profile.preferred_directness", "interaction_profile.challenge_level"],
       "When someone disagrees with you, does 'I think this is wrong, here's why' land better "
       "than 'have you considered…'?",
       cost=0.25, power=0.7),

    # ---------------- explanation style ----------------
    _q("expl_new_concept", "comparative", "explanation_style",
       ["interaction_profile.examples_vs_first_principles", "reasoning_profile.abstraction_comfort"],
       "Learning something genuinely new: do you want the underlying principle first and the "
       "examples after, or three examples until the pattern appears on its own?",
       cost=0.25, power=0.8),
    _q("expl_how_much_why", "comparative", "explanation_style",
       ["interaction_profile.explanation_depth", "interaction_profile.preferred_verbosity"],
       "When I make a judgement call, do you want the reasoning alongside it, the reasoning "
       "only if you ask, or just the call?",
       cost=0.2, power=0.8),
    _q("expl_jargon", "direct_technical", "explanation_style",
       ["interaction_profile.technical_language_preference",
        "communication_profile.vocabulary_register"],
       "Should I use the precise technical terms even when they're less readable, or plainer "
       "language even when it's slightly imprecise?",
       cost=0.2, power=0.7),

    # ---------------- ambition ----------------
    _q("amb_best_case", "counterfactual", "ambition",
       ["persistent_goals.general", "creative_profile.creative_risk_appetite"],
       "Suppose this works better than you expected. What does that unlock — what do you do "
       "next because it exists?",
       cost=0.35, power=0.85),
    _q("amb_good_enough", "direct_technical", "ambition",
       ["persistent_goals.general", "working_style.scope_discipline"],
       "What's the smallest version of this that would still be worth having?",
       cost=0.25, power=0.75),

    # ---------------- simplicity vs richness ----------------
    _q("simp_one_feature", "tradeoff", "simplicity_vs_richness",
       ["creative_profile.simplicity_vs_richness"],
       "If you had to delete one thing from this to make it simpler, what goes — and does "
       "cutting it feel like a loss or a relief?",
       cost=0.3, power=0.75),
    _q("simp_grows_or_stays", "scenario", "simplicity_vs_richness",
       ["creative_profile.simplicity_vs_richness", "working_style.scope_discipline"],
       "A year from now, is this the same size it is today, or has it grown a lot?",
       cost=0.25, power=0.7),

    # ---------------- convention tolerance ----------------
    _q("conv_standard_way", "comparative", "convention_tolerance",
       ["creative_profile.conventionality_tolerance", "reasoning_profile.novelty_preference"],
       "There's a completely standard way to do this that everyone would recognise. Is that "
       "reassuring or disappointing?",
       cost=0.2, power=0.75),
    _q("conv_who_else", "scenario", "convention_tolerance",
       ["creative_profile.conventionality_tolerance"],
       "Would you rather this look like the thing people already know, or like nothing they've "
       "seen?",
       cost=0.25, power=0.7),

    # ---------------- decision style ----------------
    _q("dec_how_many_options", "comparative", "decision_style",
       ["decision_style.option_breadth", "interaction_profile.autonomy_preference"],
       "When there's a real choice to make, do you want one recommendation with reasoning, "
       "two or three options, or everything laid out?",
       cost=0.2, power=0.85),
    _q("dec_reversible", "scenario", "decision_style",
       ["decision_style.reversibility_preference", "decision_style.speed"],
       "Would you rather commit early and adjust later, or keep options open longer even if "
       "it slows things down?",
       cost=0.25, power=0.7),
    _q("dec_stuck", "lived_experience", "decision_style",
       ["decision_style.speed", "reasoning_profile.ambiguity_tolerance"],
       "When you're genuinely torn between two options, what usually breaks the tie for you?",
       cost=0.35, power=0.6),

    # ---------------- examples vs theory ----------------
    _q("ex_show_or_tell", "comparative", "examples_vs_theory",
       ["interaction_profile.examples_vs_first_principles", "reasoning_profile.abstraction_comfort"],
       "Would you rather I show you a working example you can poke at, or explain the design "
       "and let you decide before anything gets built?",
       cost=0.25, power=0.8),

    # ---------------- creative risk ----------------
    _q("cr_special", "counterfactual", "creative_risk",
       ["creative_profile.creative_risk_appetite", "creative_profile.aesthetic_direction"],
       "What would make this feel special rather than merely correct?",
       cost=0.35, power=0.8),
    _q("cr_worst_outcome", "anti_example", "creative_risk",
       ["reasoning_profile.risk_tolerance_in_projects", "anti_preferences.general"],
       "What's the version of this you'd be embarrassed to show anyone?",
       cost=0.3, power=0.75),

    # ---------------- communication style ----------------
    _q("com_good_update", "scenario", "communication_style",
       ["interaction_profile.progress_visibility", "communication_profile.formatting_preference"],
       "While I'm working on something long, what's the right amount of noise: nothing until "
       "it's done, a line at each milestone, or thinking out loud?",
       cost=0.2, power=0.75),
    _q("com_length", "comparative", "communication_style",
       ["interaction_profile.preferred_verbosity", "communication_profile.formatting_preference"],
       "Two answers, same content: one is three sentences, one is a page with headings. Which "
       "one do you actually want?",
       cost=0.2, power=0.75),

    # ---------------- direct/technical (project work, not onboarding) ----------
    # These carry LOW mode. In LOW the remaining ambiguity is usually concrete,
    # so a plain question is cheaper for the user than a scenario they have to
    # interpret. They resolve high-impact interaction dimensions directly.
    _q("tech_autonomy", "direct_technical", "automation_vs_control",
       ["interaction_profile.autonomy_preference",
        "interaction_profile.confirmation_preference"],
       "Should I make these changes directly, or show you the plan first?",
       cost=0.15, power=0.85, onboarding=False),
    _q("tech_verbosity", "direct_technical", "communication_style",
       ["interaction_profile.preferred_verbosity", "interaction_profile.explanation_depth"],
       "How much do you want written up afterwards — one line, a paragraph, or full notes?",
       cost=0.15, power=0.8, onboarding=False),
    _q("tech_options", "direct_technical", "decision_style",
       ["decision_style.option_breadth", "interaction_profile.autonomy_preference"],
       "Do you want one recommendation, or the options laid out so you can pick?",
       cost=0.15, power=0.85, onboarding=False),
    _q("tech_reversibility", "constraint_check", "decision_style",
       ["decision_style.reversibility_preference",
        "reasoning_profile.risk_tolerance_in_projects"],
       "If this turns out wrong, is it easy to undo — or do we need to be right first time?",
       cost=0.2, power=0.8, onboarding=False),
    _q("tech_horizon", "constraint_check", "simplicity_vs_richness",
       ["creative_profile.simplicity_vs_richness", "working_style.scope_discipline"],
       "Optimise for shipping this today, or for something you'll still be maintaining "
       "in two years?",
       cost=0.2, power=0.8, onboarding=False),
    _q("tech_updates", "direct_technical", "communication_style",
       ["interaction_profile.progress_visibility", "interaction_profile.pace"],
       "Do you want progress updates while I work, or just the finished result?",
       cost=0.15, power=0.75, onboarding=False),
    _q("tech_register", "direct_technical", "explanation_style",
       ["interaction_profile.technical_language_preference",
        "communication_profile.vocabulary_register"],
       "Precise technical terms, or plainer language?",
       cost=0.15, power=0.7, onboarding=False),
    _q("tech_pushback", "direct_technical", "being_challenged",
       ["interaction_profile.challenge_level", "interaction_profile.preferred_directness"],
       "If I think you're wrong about something here, should I say so directly?",
       cost=0.2, power=0.8, onboarding=False),

    _q("tech_constraints", "direct_technical", "detail_vs_speed",
       ["preferences.constraints"],
       "Any hard constraints I should treat as non-negotiable — stack, deadline, "
       "compatibility, something that must not change?",
       cost=0.25, power=0.85, onboarding=False),
    _q("tech_audience", "direct_technical", "ambition",
       ["persistent_goals.general", "preferences.audience"],
       "Who is this actually for — you, a team, or strangers?",
       cost=0.2, power=0.8, onboarding=False),
    _q("tech_done", "direct_technical", "ambition",
       ["persistent_goals.general"],
       "How will you know this is done — what's the check you'd run?",
       cost=0.25, power=0.8, onboarding=False),
    _q("tech_existing", "constraint_check", "convention_tolerance",
       ["preferences.constraints"],
       "Is there existing code, prior art, or a previous attempt I should be consistent with?",
       cost=0.2, power=0.75, onboarding=False),
    _q("tech_scale", "constraint_check", "detail_vs_speed",
       ["preferences.constraints", "creative_profile.simplicity_vs_richness"],
       "Is this a throwaway, something you'll maintain, or something other people will "
       "depend on?",
       cost=0.2, power=0.8, onboarding=False),
    _q("tech_failure_mode", "anti_example", "frustration_triggers",
       ["anti_preferences.general", "reasoning_profile.risk_tolerance_in_projects"],
       "If this breaks in production at 3am, which failure would be the bad one?",
       cost=0.3, power=0.8, onboarding=False),
)

_BY_ID = {q["id"]: q for q in QUESTION_BANK}


def by_id(qid):
    return _BY_ID.get(qid)


def questions_for(dimension=None, styles=None, onboarding_only=False, family=None):
    """Filter the bank."""
    out = []
    for q in QUESTION_BANK:
        if onboarding_only and not q["onboarding_ok"]:
            continue
        if styles and q["style"] not in styles:
            continue
        if family and q["family"] != family:
            continue
        if dimension and dimension not in q["resolves"]:
            continue
        out.append(q)
    return out
