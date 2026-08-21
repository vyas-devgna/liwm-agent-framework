"""The Zero-Memory Gate: deciding that the right amount of memory is none.

Every persistent-memory layer pays a tax on every turn.  Most turns do not
earn it.  "What is 17% of 340" does not become a better answer because the
model also knows the user prefers terse prose, and the tokens spent saying so
are pure loss.  The cheapest context is the context never assembled.

The gate is deterministic and reads as a rule list on purpose.  A model asked
"do you need memory?" is a second inference charged against the budget the gate
exists to protect, and its answer cannot be audited afterwards.  Every decision
here names the signals that produced it, so ``liwm context --receipt`` can show
why a turn got nothing.

**The error costs are not symmetric.** Skipping memory that was needed degrades
the answer silently and is only visible to the user as the agent being worse at
knowing them.  Retrieving memory that was not needed costs a few hundred
tokens and is visible in the receipt.  So the gate opens on the weakest hint of
need and closes only on positive evidence of self-containment: ``NEED`` wins
ties, and an empty or unrecognised request retrieves.
"""

from __future__ import annotations

import re

__all__ = ["gate_decision", "needs_memory", "SELF_CONTAINED", "NEED_SIGNALS"]

SCHEMA_VERSION = "0.3.0"

#: Positive evidence that the request carries everything it needs.  Each entry
#: is ``(signal name, pattern)`` and matching one is a vote to skip.
SELF_CONTAINED = (
    ("arithmetic", re.compile(r"^[\s\d+\-*/^%().,]+=?\s*\??$")),
    ("arithmetic_phrase", re.compile(
        r"\b(?:what(?:'s| is)|calculate|compute|how much is)\b[^?]*?\b\d+[\s\d+\-*/^%().,]*\d*\s*\??$",
        re.I)),
    ("unit_conversion", re.compile(
        r"\b(?:convert|how many)\b.*\b(?:km|miles?|kg|lbs?|pounds?|celsius|fahrenheit|"
        r"bytes?|kb|mb|gb|tb|inch(?:es)?|cm|mm|metres?|meters?|feet|ft|litres?|liters?|"
        r"ounces?|oz|grams?|seconds?|minutes?|hours?)\b", re.I)),
    ("definition_lookup", re.compile(
        r"^\s*(?:what(?:'s| is| are)|who (?:is|was|were)|when (?:did|was|is))\b(?![^?]*\b(?:my|our|we|i)\b)",
        re.I)),
    ("mechanical_transform", re.compile(
        r"\b(?:base64|url ?encode|url ?decode|hex|md5|sha\d*|uuid|timestamp|epoch|"
        r"regex for|escape|unescape)\b", re.I)),
    ("syntax_lookup", re.compile(
        r"\b(?:syntax|signature|flag|option|argument)s?\s+(?:for|of)\b", re.I)),
)

#: Evidence that the request depends on something LIWM might hold.  Any match
#: opens the gate regardless of how self-contained the request otherwise looks.
NEED_SIGNALS = (
    ("unresolved_reference", re.compile(
        r"\b(?:the usual|as (?:always|before|usual)|like (?:last time|before|we did)|"
        r"same as|that one|the other one|carry on|continue where)\b", re.I)),
    ("prior_work_reference", re.compile(
        r"\b(?:earlier|yesterday|last (?:time|week|session)|previously|we (?:decided|agreed|chose)|"
        r"you (?:said|suggested|wrote)|before we|already (?:did|discussed))\b", re.I)),
    ("stated_preference", re.compile(
        r"\b(?:my|our)\s+(?:style|preference|convention|standard|setup|workflow|way)\b|"
        r"\b(?:how i (?:like|prefer|usually)|the way i|i (?:always|usually|prefer|hate|like))\b", re.I)),
    ("subjective_output", re.compile(
        r"\b(?:write|draft|design|compose|name|rename|word|phrase|rewrite|polish|"
        r"review|critique|refactor|improve|suggest|recommend|advise|explain|summari[sz]e)\b", re.I)),
    ("open_decision", re.compile(
        r"\b(?:should (?:i|we)|which (?:one|approach|library|tool|option)|"
        r"what(?:'s| is) better|trade-?offs?|pros and cons|help me (?:choose|decide|pick)|"
        # "compare the three options" reached the model with no memory at all
        # until contextecon caught it; presenting a comparison is a formatting
        # and decision-style question before it is a factual one.
        r"compare|options for|alternatives|versus|vs\.?)\b", re.I)),
    ("project_work", re.compile(
        r"\b(?:this (?:repo|repository|project|codebase)|our (?:repo|project|codebase)|"
        r"the codebase|ship|release|deploy|merge|commit)\b", re.I)),
)

#: A request shorter than this in words is usually a fragment continuing
#: something the gate cannot see, so it is not treated as self-contained.
_MIN_SELF_CONTAINED_WORDS = 3


def gate_decision(task, project_id=None, domain=None, force=None):
    """Decide whether this turn should assemble user-model context.

    ``force`` of ``"on"``/``"off"`` records an explicit override and says so,
    rather than pretending the rules produced the answer.
    """
    text = (task or "").strip()
    decision = {
        "needs_memory": True,
        "reason": "no_task_hint",
        "signals": [],
        "self_contained_signals": [],
        "task_words": len(text.split()),
        "overridden": False,
    }

    if force in ("on", "off"):
        decision["needs_memory"] = force == "on"
        decision["reason"] = "explicit_override"
        decision["overridden"] = True
        return decision

    if not text:
        # No hint at all is not evidence of self-containment.  Retrieve.
        return decision

    need = [name for name, pattern in NEED_SIGNALS if pattern.search(text)]
    contained = [name for name, pattern in SELF_CONTAINED if pattern.search(text)]
    decision["signals"] = need
    decision["self_contained_signals"] = contained

    if need:
        # NEED wins ties: a self-contained-looking request that also references
        # prior work is a request about prior work.
        decision["reason"] = "needs:%s" % ",".join(need)
        return decision

    # An explicit project or domain is the caller telling us the turn is
    # situated, which is itself a need signal.
    if project_id or domain:
        decision["needs_memory"] = True
        decision["reason"] = "scoped_request"
        return decision

    if contained and decision["task_words"] >= _MIN_SELF_CONTAINED_WORDS:
        decision["needs_memory"] = False
        decision["reason"] = "self_contained:%s" % ",".join(contained)
        return decision

    decision["reason"] = "no_self_containment_evidence"
    return decision


def needs_memory(task, project_id=None, domain=None, force=None):
    """Boolean form of :func:`gate_decision`."""
    return gate_decision(task, project_id=project_id, domain=domain, force=force)["needs_memory"]
