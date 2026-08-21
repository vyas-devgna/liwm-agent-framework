"""What the request is *for*, and which stored beliefs bear on that.

Ranking by confidence answers "what is LIWM surest about", which is not the
question. A preference for tables over prose held at 0.53 is exactly what
"compare these three options" needs, and it loses to forty unrelated
preferences held at 0.55. On the 97-case retrieval suite that ranker recalls
the needed belief 29.5% of the time -- barely above projecting fourteen
beliefs out of eighty-seven at random.

The fix follows STITCH (Yang, Jiang, Han et al., *Grounding Agent Memory in
Contextual Intent*, Findings of ACL 2026, arXiv:2601.10702): index memory by a
structured intent cue and retrieve by intent compatibility, suppressing history
that is semantically similar but context-incompatible.

LIWM gets that cheaply, because its memories are not free text. Every belief
already names a dimension from a closed taxonomy, so the "what is this memory
about" half of the cue needs no extraction, no embedding and no model call --
it is a property of the dimension, declared once. Only the request has to be
classified, and one small shared classifier does that for all of them.

WHAT THIS IS NOT
================

It is not a keyword list per dimension. That was the obvious version and it
does not generalise: it needs 47 hand-tuned vocabularies, and a request phrased
in words nobody guessed matches nothing. Here there is one closed vocabulary of
ten action types, one classifier, and an affinity declared per taxonomy
*section* with a handful of overrides where a section default is wrong. Adding
a dimension usually costs nothing.

It is deterministic and inspectable on purpose. The action types a request
matched appear in the ContextReceipt, so "why did it show me that" has an
answer that is not "the embedding said so".
"""

from __future__ import annotations

import re

__all__ = ["ACTIONS", "classify_actions", "affinity", "SECTION_AFFINITY",
           "DIMENSION_AFFINITY", "NEUTRAL_AFFINITY"]

SCHEMA_VERSION = "0.4.0"

#: The closed vocabulary. Ten kinds of thing a person asks an agent to do.
#: Small on purpose: every entry has to earn a distinct set of dimensions that
#: matter for it, or it is a synonym of one already here.
ACTIONS = ("explain", "summarise", "compare", "decide", "review",
           "implement", "design", "write", "plan", "diagnose")

_PATTERNS = (
    ("explain", re.compile(
        r"\b(?:explain|describe|teach|walk me through|help me understand|"
        r"introduce me|bring me up to speed|how does|how do(?:es)? .* work|why did|"
        r"why is|what does .* do)\b", re.I)),
    ("summarise", re.compile(
        r"\b(?:summari[sz]e|recap|tl;?dr|give me the (?:outcome|result|gist)|"
        r"what changed|overview of)\b", re.I)),
    ("compare", re.compile(
        r"\b(?:compare|versus|vs\.?|differences? between|trade-?offs?|"
        r"pros and cons|lay out the differences|present the .*results|"
        r"options for|alternatives)\b", re.I)),
    ("decide", re.compile(
        r"\b(?:should (?:i|we|it|this|that|the)|which (?:one|approach|library|tool|"
        r"option|database|queue)|what should we use|pick a|pick the|choose|decide|"
        r"we need to pick|is it worth|convince me|good enough|"
        r"is (?:this|that|it) (?:\w+ )*(?:faster|better|worth|right|enough)|"
        r"how (?:aggressive|bold|much) should)\b", re.I)),
    ("review", re.compile(
        r"\b(?:review|check (?:this|my|the)|go over|look over|critique|"
        r"what do you think of|is (?:this|my) .*(?:good|right|wrong|ok)|"
        r"does this .*hold up|before i merge)\b", re.I)),
    ("implement", re.compile(
        r"\b(?:fix|implement|add|build|port|refactor|rewrite|restructure|rework|"
        r"clean up|set up|migrate|upgrade|handle|run with it|take this ticket|"
        r"drop the|delete the|start|work through|get through|convert|"
        r"get something working|prototype|ship|release the|finish|"
        r"take the whole|hand (?:this|it) off)\b", re.I)),
    ("design", re.compile(
        r"\b(?:design|lay out|propose|come up with|sketch|style the|"
        r"what (?:options|should) .*(?:take|surface)|structure for|"
        r"suggest something|redesign)\b", re.I)),
    ("write", re.compile(
        r"\b(?:write|draft|compose|put together|word|phrase|announce(?:ment)?|"
        r"changelog|commit message|release notes|document)\b", re.I)),
    ("plan", re.compile(
        r"\b(?:plan|break (?:up|down)|how should we (?:approach|break)|"
        r"roadmap|sequence|rest of this|roll(?: this)? out|rollout)\b", re.I)),
    ("diagnose", re.compile(
        r"\b(?:times? out|slow|failing|fails|flaky|bug|broken|regression|"
        r"keeps? coming back|round in circles|third time|performance problem|"
        r"what is causing|why .*(?:fail|break|slow))\b", re.I)),
    ("plan", re.compile(
        r"\b(?:we do not know|we don't know|not (?:yet )?decided|requirements are "
        r"(?:vague|unclear)|final .* shape|multi-tenancy|we need to add)\b", re.I)),
)

#: Affinity a belief in each taxonomy section has for each action type.
#: Read as: "when the user asks me to do X, does knowing this about them change
#: what I produce?" Absent means no particular bearing, which scores neutral
#: rather than zero -- a dimension is rarely actively irrelevant.
SECTION_AFFINITY = {
    "communication_profile": {
        "write": 1.0, "summarise": 0.9, "compare": 0.9, "explain": 0.8,
        "review": 0.4, "design": 0.3, "plan": 0.3,
    },
    "interaction_profile": {
        "explain": 0.9, "summarise": 0.9, "review": 0.7, "implement": 0.6,
        "diagnose": 0.6, "write": 0.5, "plan": 0.4, "decide": 0.4,
    },
    "reasoning_profile": {
        "diagnose": 0.9, "explain": 0.8, "decide": 0.8, "design": 0.7,
        "review": 0.6, "plan": 0.5, "compare": 0.5,
    },
    "creative_profile": {
        "design": 1.0, "write": 0.7, "implement": 0.4, "decide": 0.3,
    },
    "working_style": {
        "implement": 0.9, "plan": 0.9, "review": 0.8, "diagnose": 0.5,
        "design": 0.4,
    },
    "decision_style": {
        "decide": 1.0, "plan": 0.8, "compare": 0.7, "implement": 0.5,
        "design": 0.4,
    },
}

#: Where a section default is wrong for one dimension. Kept short deliberately:
#: a long override table means the sections are the wrong grouping.
DIMENSION_AFFINITY = {
    # Autonomy and confirmation are about *doing*, not about talking.
    "interaction_profile.autonomy_preference": {
        "implement": 1.0, "plan": 0.7, "diagnose": 0.6, "design": 0.5},
    "interaction_profile.confirmation_preference": {
        "implement": 1.0, "plan": 0.6, "decide": 0.5},
    "interaction_profile.progress_visibility": {
        "implement": 1.0, "plan": 0.6, "diagnose": 0.5},
    "interaction_profile.preferred_question_frequency": {
        "implement": 0.9, "plan": 0.8, "design": 0.6, "decide": 0.5},
    # Scope discipline and iteration style bite while building, not while
    # explaining.
    "working_style.scope_discipline": {
        "implement": 1.0, "review": 0.7, "plan": 0.6},
    "working_style.review_style": {
        "review": 1.0, "implement": 0.5},
    "working_style.documentation_appetite": {
        "write": 0.9, "implement": 0.8, "explain": 0.5},
    "working_style.frustration_triggers": {
        "diagnose": 1.0, "implement": 0.6, "plan": 0.5},
    "working_style.tooling_attitude": {
        "decide": 0.9, "implement": 0.8, "plan": 0.5},
    # Formatting is the output shape; it matters most where there is an output
    # with a shape.
    "communication_profile.formatting_preference": {
        "compare": 1.0, "summarise": 0.9, "write": 0.9, "explain": 0.8,
        "review": 0.4},
    "reasoning_profile.evidence_preference": {
        "decide": 1.0, "review": 0.8, "diagnose": 0.7, "explain": 0.5},
    "reasoning_profile.risk_tolerance_in_projects": {
        "decide": 1.0, "plan": 0.9, "design": 0.6},
    "reasoning_profile.ambiguity_tolerance": {
        "plan": 0.9, "implement": 0.8, "design": 0.7, "decide": 0.5},
    "creative_profile.polish_vs_rough": {
        "design": 0.9, "implement": 0.9, "write": 0.5},
    "creative_profile.imperfection_tolerance": {
        "decide": 0.9, "review": 0.8, "implement": 0.6, "design": 0.5},
}

#: What a dimension with nothing declared for this action scores. Not zero:
#: "no declared bearing" is weaker evidence than "actively irrelevant", and a
#: zero here would let one missing table entry bury a belief entirely.
NEUTRAL_AFFINITY = 0.12

#: What an open-namespace dimension scores. LIWM cannot know what
#: ``preferences.node.package_manager`` bears on, because the user invented it,
#: so it sits at neutral and rises only on a lexical match with the request.
OPEN_NAMESPACE_AFFINITY = 0.20


def classify_actions(task):
    """Which action types this request matches. Empty when nothing matches."""
    text = (task or "").strip()
    if not text:
        return ()
    return tuple(name for name, pattern in _PATTERNS if pattern.search(text))


def affinity(dimension, actions):
    """How much *dimension* bears on a request of these action types, 0..1.

    Takes the strongest matching action rather than the mean: a request that is
    both a comparison and an implementation should surface the formatting
    preference at its comparison strength, not have it diluted by the fact that
    formatting barely matters while editing files.
    """
    from .taxonomy import DIMENSION_INDEX, open_namespaces

    if dimension not in DIMENSION_INDEX:
        root = str(dimension).split(".", 1)[0]
        return OPEN_NAMESPACE_AFFINITY if root in open_namespaces else NEUTRAL_AFFINITY
    if not actions:
        return NEUTRAL_AFFINITY

    table = DIMENSION_AFFINITY.get(dimension)
    if table is None:
        table = SECTION_AFFINITY.get(dimension.split(".", 1)[0], {})
    return max(table.get(action, NEUTRAL_AFFINITY) for action in actions)
