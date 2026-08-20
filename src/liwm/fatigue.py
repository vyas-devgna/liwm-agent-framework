"""Question budget and interaction fatigue.

An intent framework that constantly interviews the user has failed, no matter
how good its model becomes.  This module makes "the best question is sometimes
no question" a computed quantity rather than a slogan.

Fatigue is deliberately *asymmetric*: it rises quickly on ignored and skipped
questions (the user is telling you something) and decays slowly within a
session, then resets between sessions.
"""

from __future__ import annotations

from .evidence import age_days

__all__ = ["FatigueTracker", "estimate_fatigue", "profile_maturity",
           "SATURATION_MASS", "TARGET_DIMENSIONS"]

#: Impact-weighted evidence mass at which maturity reaches 0.5 on the depth
#: term.  Roughly "a dozen well-supported beliefs on dimensions that matter".
SATURATION_MASS = 6.0

#: Dimensional breadth considered full coverage for maturity purposes.
TARGET_DIMENSIONS = 18.0


class FatigueTracker:
    """Session-scoped accounting of how much of the user's attention was spent."""

    def __init__(self, asked=0, answered=0, skipped=0, ignored=0,
                 turns=0, corrections=0, session_id=None):
        self.session_id = session_id
        self.asked = asked
        self.answered = answered
        self.skipped = skipped
        self.ignored = ignored
        self.turns = turns
        self.corrections = corrections

    @classmethod
    def from_events(cls, events, session_id=None):
        """Reconstruct fatigue for a session from its event stream."""
        t = cls(session_id=session_id)
        for e in events:
            if session_id and e.get("session_id") != session_id:
                continue
            kind = e.get("kind")
            if kind == "question_asked":
                t.asked += 1
            elif kind == "question_answered":
                t.answered += 1
            elif kind == "question_skipped":
                reason = (e.get("payload") or {}).get("reason", "skipped")
                if reason == "ignored":
                    t.ignored += 1
                else:
                    t.skipped += 1
            elif kind == "correction":
                t.corrections += 1
        return t

    def score(self):
        """Fatigue in [0, 1]."""
        return estimate_fatigue(
            asked=self.asked,
            skipped=self.skipped,
            ignored=self.ignored,
            answered=self.answered,
            turns=self.turns,
        )

    def to_dict(self):
        d = {k: v for k, v in self.__dict__.items()}
        d["fatigue"] = round(self.score(), 4)
        d["answer_rate"] = round(self.answered / self.asked, 4) if self.asked else None
        return d


def estimate_fatigue(asked=0, skipped=0, ignored=0, answered=0, turns=0):
    """Combine interaction signals into a single fatigue score.

    Weights, in order of how loudly the signal speaks:

    * an **ignored** question (asked, user moved on) is the strongest signal;
    * an explicitly **skipped** question is nearly as strong;
    * sheer **volume** of questions asked accumulates with diminishing effect;
    * a long conversation adds a small baseline.
    """
    asked = max(0, int(asked))
    skipped = max(0, int(skipped))
    ignored = max(0, int(ignored))
    turns = max(0, int(turns))

    volume = 1.0 - (0.75 ** asked)          # 1 -> .25, 3 -> .58, 6 -> .82
    ignore_pressure = min(1.0, 0.45 * ignored)
    skip_pressure = min(1.0, 0.30 * skipped)
    length = min(0.25, 0.012 * turns)

    raw = 0.42 * volume + 0.30 * ignore_pressure + 0.20 * skip_pressure + length
    return max(0.0, min(1.0, raw))


def profile_maturity(profile, domain=None):
    """How much accumulated understanding LIWM can actually exploit, in [0, 1].

    This feeds AUTO's damping term, so it must reflect *usable* knowledge:
    high-confidence beliefs on high-impact dimensions, recently confirmed, with
    onboarding counted but not overweighted (self-report is capped at 0.70
    confidence for a reason).

    Deliberately **not** a mean confidence.  A mean saturates after a single
    observation, which would let one lucky guess convince LIWM it understands
    someone.  Instead maturity accumulates *evidence mass* with diminishing
    returns and multiplies in dimensional breadth, so knowing one thing very
    well still counts as knowing almost nothing about the person.
    """
    from .taxonomy import decision_impact

    beliefs = [
        b for b in (profile or {}).get("beliefs", [])
        if b.get("status") == "active" and not b.get("rejected_by_user")
    ]
    if not beliefs:
        return 0.0

    mass = 0.0
    dimensions = set()
    for b in beliefs:
        if domain and b.get("domain") and b["domain"] != domain and b.get("scope") == "domain":
            continue
        impact = decision_impact(b.get("dimension", ""))
        conf = float(b.get("confidence", 0.0))
        recency = 1.0 if age_days(b.get("last_seen")) < 120 else 0.6
        mass += impact * conf * recency
        dimensions.add(b.get("dimension"))

    if mass <= 0:
        return 0.0

    # Saturating: ~0.10 for one strong belief, ~0.40 after a dozen, never 1.0.
    depth = mass / (mass + SATURATION_MASS)
    coverage = min(1.0, len(dimensions) / TARGET_DIMENSIONS)
    onboarding_bonus = (
        0.05 if (profile or {}).get("onboarding", {}).get("status") == "completed" else 0.0
    )
    return max(0.0, min(1.0, 0.70 * depth + 0.25 * coverage + onboarding_bonus))
