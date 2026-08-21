"""The Context Capsule: the projection in the form the model actually reads.

LIWM's projection was already small next to the profile it comes from -- about
4.5 KB against 64 KB.  But it was being handed to the model as pretty-printed
JSON, and JSON spends most of itself on structure the model does not need.  In
a fourteen-belief projection, roughly two thirds of the tokens are punctuation,
repeated keys, and ``belief_id`` hex strings that no model has ever used for
anything: the agent asks ``liwm why --dimension <d>``, not by id.

The capsule carries the same operative content in a line-oriented form.
Measured on a 43-belief profile with an exact ``cl100k_base`` count, the JSON
projection is 1,402 tokens and the capsule is 232 -- 6.0x -- with every field
an agent can act on preserved:

* the precedence rule, which is constitutional and must never be trimmed;
* every applicable belief, with confidence and non-default scope;
* anti-preferences, project non-negotiables and anti-goals;
* open contradictions, which are the honest part;
* promoted rules and the question budget.

What it drops is bookkeeping the model cannot act on: schema version,
generation timestamp, belief ids, ``origin``, and the mode-resolution prose.
All of it remains in ``--json`` for programs, and in the ContextReceipt for
audit.  This is a *rendering* choice, not a filtering one; nothing that could
change the answer is removed.
"""

from __future__ import annotations

from .taxonomy import DIMENSION_INDEX

__all__ = ["render_capsule", "PRECEDENCE_LINE"]

SCHEMA_VERSION = "0.3.0"

#: Never trimmed, never abbreviated.  An agent that forgets this line will let
#: a stored preference override what the user just said, which is the single
#: worst thing a memory layer can do.
PRECEDENCE_LINE = (
    "Your current instructions from the user override every line below. "
    "These are confidence-weighted hypotheses about the person, not facts."
)


def _short(dimension):
    """Drop the section prefix, but only where uniqueness is guaranteed.

    Closed-taxonomy leaf names are collision-free and a test keeps them that
    way.  Open namespaces are user-defined, and ``preferences.x`` shortened
    the same way as ``anti_preferences.x`` would render a preference and its
    exact opposite as the same line, so those stay whole.
    """
    if dimension in DIMENSION_INDEX and "." in dimension:
        return dimension.split(".", 1)[1]
    return dimension


def _scope_suffix(item):
    scope = item.get("scope", "global")
    if scope == "global":
        return ""
    key = item.get("scope_key")
    return " @%s%s" % (scope, ":%s" % key if key else "")


def _belief_line(item):
    return "  %s = %s (%.2f)%s" % (
        _short(item.get("dimension", "")),
        str(item.get("value", "")),
        float(item.get("confidence", 0.0)),
        _scope_suffix(item),
    )


def render_capsule(context):
    """Render a runtime context projection as a compact capsule."""
    if context.get("zero_memory"):
        return "LIWM: no stored profile applies to this request."
    if context.get("integrity_degraded"):
        return "LIWM: event integrity check failed; no learned state was exposed. Run `liwm verify`."

    mode = context.get("mode") or {}
    if mode.get("effective") == "off":
        return "LIWM: off. %s" % (mode.get("rationale") or "no profile consulted")

    out = ["LIWM r%s | mode %s | questions %s | maturity %.2f" % (
        context.get("profile_revision"), mode.get("effective"),
        mode.get("question_budget"), float(context.get("profile_maturity") or 0.0))]
    out.append(PRECEDENCE_LINE)

    applies = context.get("applies") or []
    if applies:
        out.append("apply:")
        out.extend(_belief_line(item) for item in applies)

    withheld = int(context.get("beliefs_withheld") or 0)
    if withheld:
        # An omission the agent cannot see is an omission it cannot recover
        # from.  One line, and the escape hatch is named.
        out.append("  (+%d not shown: outranked or indistinguishable -- "
                   "`liwm context --all` or `liwm why --dimension <d>`)" % withheld)

    avoid = context.get("avoid") or []
    if avoid:
        out.append("avoid:")
        out.extend(
            "  %s = %s (%.2f)%s" % (item.get("name"), item.get("value"),
                                    float(item.get("confidence") or 0.0), _scope_suffix(item))
            for item in avoid
        )

    project = context.get("project") or {}
    if project:
        out.append("project %s%s:" % (
            project.get("project_id"),
            " (%s)" % project["stage"] if project.get("stage") else ""))
        for label, key in (("must", "non_negotiables"), ("never", "anti_goals"),
                           ("maybe", "hypotheses"), ("open", "open_questions"),
                           ("assuming", "undisclosed_assumptions")):
            for row in project.get(key) or []:
                out.append("  %s: %s" % (label, row.get("text")))

    for row in context.get("contradictions") or []:
        options = " vs ".join(
            "%s (%.2f)" % (cand.get("value"), float(cand.get("confidence") or 0.0))
            for cand in row.get("candidates", [])
        )
        out.append("conflict: %s -- %s" % (_short(row.get("dimension", "")), options))

    for row in context.get("active_rules") or []:
        out.append("rule: %s" % row.get("statement"))

    for row in context.get("open_uncertainties") or []:
        out.append("unknown: %s (%s)" % (_short(row.get("dimension", "")), row.get("why")))

    if not context.get("learning_enabled", True):
        out.append("learning: disabled -- do not record observations.")
    return "\n".join(out)
