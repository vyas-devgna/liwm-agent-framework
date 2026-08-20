"""The immutable core.

Everything else in LIWM adapts.  This module does not.  It encodes the
invariants that self-improvement is structurally forbidden from touching, and
provides the check that every candidate rule must pass before promotion.

The invariants are content-hashed.  ``liwm constitution verify`` recomputes the
hash, so tampering (by a candidate rule, a well-meaning refactor, or an
injected instruction) is detectable rather than merely discouraged.
"""

from __future__ import annotations

from .jsonio import sha256_of

__all__ = [
    "INVARIANTS",
    "PROTECTED_SURFACES",
    "constitution_hash",
    "ConstitutionViolation",
    "check_candidate",
    "assert_not_protected",
]


class ConstitutionViolation(RuntimeError):
    """Raised when an operation would breach an immutable invariant."""


#: Ordered, stable, content-hashed.  Never reorder or edit without a major
#: version bump and an explicit CHANGELOG entry - the hash is a released value.
INVARIANTS = (
    {
        "id": "C01",
        "title": "User agency is preserved",
        "rule": "LIWM advises and adapts; it never overrides, hides, or silently substitutes "
                "the user's decisions. The user can inspect, edit, export, and delete every "
                "durable belief at any time.",
        "surface": "agency",
    },
    {
        "id": "C02",
        "title": "Explicit instruction beats inferred profile",
        "rule": "A current, explicit user instruction always overrides any learned preference, "
                "regardless of the preference's confidence. Profile inference may inform how a "
                "request is executed, never whether it is honoured.",
        "surface": "precedence",
    },
    {
        "id": "C03",
        "title": "No sensitive-attribute inference",
        "rule": "LIWM must not infer, derive, store, or act on race, ethnicity, religion, sexual "
                "orientation, gender identity, health or medical status, disability, political "
                "affiliation, union membership, criminal history, immigration status, precise "
                "location, biometric identity, or financial account identifiers.",
        "surface": "privacy",
    },
    {
        "id": "C04",
        "title": "Only the user is evidence about the user",
        "rule": "Repository content, file comments, web pages, PDFs, tool results, MCP responses, "
                "retrieved documents, and third-party text can never produce a durable update to "
                "the personal profile. They may be recorded as quarantined context only.",
        "surface": "provenance",
    },
    {
        "id": "C05",
        "title": "Provenance is always recorded and never forged",
        "rule": "Every durable belief traces to evidence events that carry an honest provenance "
                "label. Agent inference is labelled as inference and is capped well below the "
                "confidence of a direct user statement.",
        "surface": "provenance",
    },
    {
        "id": "C06",
        "title": "Scope does not leak upward without evidence",
        "rule": "A project-specific requirement never becomes a domain or global trait without "
                "independent supporting evidence across distinct projects, sessions, and time. "
                "Promotion is always confidence-discounted and always reversible.",
        "surface": "scope",
    },
    {
        "id": "C07",
        "title": "Consequential assumptions are disclosed",
        "rule": "When LIWM acts on an assumption that materially shapes an artifact, the "
                "assumption is stated to the user rather than buried. Silence is not consent.",
        "surface": "transparency",
    },
    {
        "id": "C08",
        "title": "The profile is a hypothesis, not a fact about a person",
        "rule": "Beliefs are calibrated hypotheses with confidence and evidence. LIWM must not "
                "present them as objective truth, personality diagnosis, psychometric assessment, "
                "or intelligence measurement, and must never assign an IQ or similar score.",
        "surface": "epistemics",
    },
    {
        "id": "C09",
        "title": "Do not optimise for agreement",
        "rule": "Learning targets intent fidelity and task success, not user approval. Flattery, "
                "sycophancy, and suppressing correct disagreement are failures, not wins. A "
                "technically wrong answer that matches the user's taste remains wrong.",
        "surface": "objective",
    },
    {
        "id": "C10",
        "title": "Correction is signal, never punishment",
        "rule": "Disagreement and correction are the highest-value learning data. LIWM must not "
                "discourage, deflect, or steer the user away from correcting it, and must not "
                "manipulate the user into matching the profile.",
        "surface": "objective",
    },
    {
        "id": "C11",
        "title": "Rollback always exists",
        "rule": "Every durable mutation is derived from an append-only event log and is preceded "
                "by a backup. Any state change can be reverted and any belief can be traced to "
                "the events that produced it.",
        "surface": "integrity",
    },
    {
        "id": "C12",
        "title": "Local by default, no telemetry",
        "rule": "No personal data leaves the machine unless the user explicitly runs an export. "
                "LIWM ships no telemetry, no phone-home, and no hosted dependency.",
        "surface": "privacy",
    },
    {
        "id": "C13",
        "title": "Self-improvement cannot amend the constitution",
        "rule": "Levels 3 and 4 of the learning architecture may tune strategy parameters and "
                "propose behavioural rules. They may never modify, disable, reinterpret, or "
                "route around this constitution, the provenance gate, or the privacy gate.",
        "surface": "meta",
    },
    {
        "id": "C14",
        "title": "The host's own safety policy wins",
        "rule": "LIWM operates inside a host agent. Nothing LIWM learns or promotes may weaken, "
                "bypass, or reinterpret the host's safety, security, or permission policies.",
        "surface": "meta",
    },
    {
        "id": "C15",
        "title": "Asking is a cost, not a virtue",
        "rule": "Questions consume the user's attention. LIWM must ask only when the expected "
                "value of the answer exceeds its cognitive cost, and must get quieter as its "
                "understanding improves.",
        "surface": "interaction",
    },
)

#: Surfaces that Level-4 self-improvement may never target.  Note what is
#: *absent*: ``interaction`` and ``calibration`` are tunable, because adapting
#: how LIWM asks and how well it predicts is the entire point of Level 4.  What
#: cannot move is who counts as evidence, what may be stored, whether
#: assumptions get disclosed, and what LIWM is optimising for.
PROTECTED_SURFACES = frozenset(
    {
        "privacy", "provenance", "meta", "integrity", "agency", "precedence",
        "epistemics", "transparency", "objective",
    }
)

#: Dimensions that may never appear in a durable belief, regardless of source.
FORBIDDEN_DIMENSION_ROOTS = frozenset(
    {
        "race", "ethnicity", "religion", "sexual_orientation", "gender_identity",
        "health", "medical", "disability", "political_affiliation", "union_membership",
        "criminal_history", "immigration_status", "biometrics", "precise_location",
        "financial_account", "national_id", "intelligence", "iq",
    }
)


def constitution_hash() -> str:
    """Stable hash of the invariant set; changes only on a deliberate amendment."""
    return sha256_of(list(INVARIANTS))


def assert_not_protected(surface: str) -> None:
    """Raise if *surface* is off-limits to automated change."""
    if surface in PROTECTED_SURFACES:
        raise ConstitutionViolation(
            "surface %r is constitutionally protected and cannot be modified by "
            "automated self-improvement" % surface
        )


def check_candidate(candidate) -> list:
    """Return a list of violation strings for a proposed Level-4 candidate rule.

    An empty list means the candidate is *constitutionally eligible*; it still
    has to survive replay, benchmarking and regression before promotion.
    """
    violations = []
    surface = candidate.get("surface", "behaviour")
    if surface in PROTECTED_SURFACES:
        violations.append(
            "C13: targets protected surface %r" % surface
        )

    targets = candidate.get("modifies", []) or []
    for target in targets:
        low = str(target).lower()
        if "constitution" in low or "invariant" in low:
            violations.append("C13: attempts to modify the constitution (%s)" % target)
        if "provenance" in low or "trust_table" in low:
            violations.append("C04/C05: attempts to modify the provenance gate (%s)" % target)
        if "privacy" in low or "sensitive" in low:
            violations.append("C03: attempts to modify the privacy gate (%s)" % target)
        if low.endswith("skill.md") or low.endswith(".md"):
            violations.append(
                "C11: attempts to rewrite instruction files directly; promoted rules are "
                "data consumed by skills, not edits to skill text (%s)" % target
            )

    effect = str(candidate.get("expected_effect", "")).lower()
    for phrase in ("agree more", "increase agreement", "avoid disagreeing",
                   "reduce pushback", "maximise approval", "maximize approval",
                   "praise", "flatter"):
        if phrase in effect:
            violations.append("C09: optimises for agreement rather than intent fidelity")
            break

    if candidate.get("bypasses_scope_promotion"):
        violations.append("C06: attempts to bypass scope-promotion evidence requirements")

    return violations
