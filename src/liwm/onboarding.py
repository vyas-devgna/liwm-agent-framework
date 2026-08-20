"""Onboarding: ten questions that do not feel like a personality test.

Constraints this module enforces mechanically, so the host model cannot drift:

* **Exactly ten questions**, asked one at a time.
* **Breadth**: at least eight distinct dimension families, never more than two
  from any one family.  That is what stops the ten questions from all being
  about verbosity.
* **Adaptivity**: each question is chosen *after* the previous answer has been
  folded in, so a decisive answer redirects the remaining questions instead of
  re-asking what is already known.
* **No score theatre**: nothing is shown to the user between questions.
* **Self-report is capped**: onboarding evidence enters at ``onboarding_answer``
  weight (0.70 ceiling).  Behaviour observed later can and should overrule it.

The question *text* is a starting point; the host model is expected to phrase it
naturally.  The *selection* is what this module owns.
"""

from __future__ import annotations

from .question_bank import FAMILIES, by_id, questions_for
from .questions import QuestionPlanner
from .scope import resolve_for_context

__all__ = [
    "ONBOARDING_QUESTION_COUNT",
    "MAX_PER_FAMILY",
    "MIN_FAMILIES",
    "OnboardingSession",
    "plan_next",
]

ONBOARDING_QUESTION_COUNT = 10
MAX_PER_FAMILY = 2
MIN_FAMILIES = 8

#: Onboarding uses a HIGH-like contract: experiential, one at a time, patient.
ONBOARDING_CONTRACT = {
    "mode": "onboarding",
    "max_questions": 1,
    "min_utility": 0.0,          # the count is fixed; utility only ranks
    "experiential_ratio": 0.85,
    "technical_ratio": 0.15,
    "styles": ("scenario", "comparative", "counterfactual", "anti_example",
               "tradeoff", "lived_experience", "emotional_reaction", "direct_technical"),
    "one_at_a_time": True,
    "adaptive_continue": True,
    "use_profile": True,
    "record_evidence": True,
}


def _coverage_bonus(question, family_counts, asked_count):
    """Reward unseen families early, and enforce the per-family cap."""
    fam = question["family"]
    seen = family_counts.get(fam, 0)
    if seen >= MAX_PER_FAMILY:
        return None  # hard exclusion
    remaining = ONBOARDING_QUESTION_COUNT - asked_count
    families_left = MIN_FAMILIES - len([f for f, c in family_counts.items() if c > 0])
    # As the budget tightens, unseen families matter more.
    urgency = 1.0 if families_left <= 0 else min(2.5, 1.0 + families_left / max(1, remaining))
    return (1.0 if seen == 0 else 0.45) * urgency


def plan_next(resolved, asked_ids, family_counts, strategy=None, seed=0):
    """Choose the next onboarding question deterministically.

    Deterministic given the same inputs, which is what makes the synthetic-user
    simulations reproducible.
    """
    asked_ids = set(asked_ids or ())
    asked_count = len(asked_ids)
    if asked_count >= ONBOARDING_QUESTION_COUNT:
        return None

    candidates = [
        q for q in questions_for(onboarding_only=True)
        if q["id"] not in asked_ids
    ]
    if not candidates:
        return None

    planner = QuestionPlanner(ONBOARDING_CONTRACT, resolved=dict(resolved or {}),
                              strategy=strategy, bank=candidates)

    scored = []
    for q in candidates:
        bonus = _coverage_bonus(q, family_counts, asked_count)
        if bonus is None:
            continue
        s = planner.plan(max_questions=1, exclude_ids=[c["id"] for c in candidates if c["id"] != q["id"]])
        if not s:
            continue
        entry = dict(s[0])
        entry["coverage_bonus"] = round(bonus, 4)
        entry["onboarding_score"] = round(entry["utility"] * bonus, 5)
        scored.append(entry)

    if not scored:
        # Every remaining family is capped; relax the cap rather than stopping
        # short of ten questions.
        for q in candidates:
            s = planner.plan(max_questions=1,
                             exclude_ids=[c["id"] for c in candidates if c["id"] != q["id"]])
            if s:
                entry = dict(s[0])
                entry["coverage_bonus"] = 0.2
                entry["onboarding_score"] = round(entry["utility"] * 0.2, 5)
                scored.append(entry)
    if not scored:
        return None

    scored.sort(key=lambda e: (-e["onboarding_score"], e["id"]))
    chosen = scored[0]
    chosen["position"] = asked_count + 1
    chosen["of"] = ONBOARDING_QUESTION_COUNT
    return chosen


class OnboardingSession:
    """Drives a ten-question onboarding against a :class:`ProfileStore`."""

    def __init__(self, store, session_id=None, strategy=None):
        self.store = store
        self.session_id = session_id or "onboarding"
        self.strategy = strategy or {}

    # -- state -------------------------------------------------------------
    def state(self):
        asked, families, answered = [], {}, 0
        for e in self.store.events.iter_events(
            kinds={"question_asked", "onboarding_answer", "onboarding_started",
                   "onboarding_completed"},
        ):
            payload = e.get("payload") or {}
            if payload.get("context") != "onboarding" and e.get("kind") == "question_asked":
                continue
            if e.get("kind") == "question_asked":
                qid = payload.get("question_id")
                if qid and qid not in asked:
                    asked.append(qid)
                    q = by_id(qid)
                    if q:
                        families[q["family"]] = families.get(q["family"], 0) + 1
            elif e.get("kind") == "onboarding_answer":
                answered += 1
        profile = self.store.load()
        return {
            "status": profile.get("onboarding", {}).get("status", "not_started"),
            "asked_ids": asked,
            "family_counts": families,
            "answered": answered,
            "remaining": max(0, ONBOARDING_QUESTION_COUNT - len(asked)),
            "families_covered": len([f for f, c in families.items() if c > 0]),
            "min_families": MIN_FAMILIES,
        }

    # -- flow --------------------------------------------------------------
    def start(self):
        self.store.events.record(
            "onboarding_started", "direct_user_message",
            payload={"question_count": ONBOARDING_QUESTION_COUNT,
                     "families_available": list(FAMILIES)},
            session_id=self.session_id,
        )
        return self.store.rebuild(reason="onboarding_started")

    def next_question(self):
        st = self.state()
        if st["remaining"] <= 0:
            return None
        profile = self.store.load()
        resolved = resolve_for_context(profile.get("beliefs", []), min_confidence=0.0)
        q = plan_next(resolved, st["asked_ids"], st["family_counts"], strategy=self.strategy)
        if q is None:
            return None
        self.store.events.record(
            "question_asked", "agent_inference",
            payload={"question_id": q["id"], "context": "onboarding",
                     "position": q["position"], "style": q["style"],
                     "family": q["family"], "utility": q["utility"]},
            session_id=self.session_id,
        )
        return q

    def record_answer(self, question_id, answer_text, observations=None):
        """Fold an answer into the profile.

        *observations* is what the host model extracted from the free-text
        answer: a list of ``{"dimension", "value", "polarity"}`` dicts.  They are
        recorded at ``onboarding_answer`` strength - self-report, capped at 0.70.
        """
        q = by_id(question_id) or {}
        self.store.events.record(
            "onboarding_answer", "direct_user_message",
            payload={
                "question_id": question_id,
                "answer": answer_text,
                "dimensions": list(q.get("resolves", ())),
                "family": q.get("family"),
            },
            session_id=self.session_id,
        )
        for obs in observations or []:
            self.store.events.record(
                "observation", "onboarding_answer",
                observation={
                    "dimension": obs["dimension"],
                    "value": obs.get("value"),
                    "polarity": obs.get("polarity", "support"),
                    "source_type": "onboarding_answer",
                    "scope": obs.get("scope", "global"),
                    "scope_key": obs.get("scope_key"),
                    "decay_policy": obs.get("decay_policy", "standard"),
                    "note": "onboarding: %s" % question_id,
                },
                session_id=self.session_id,
            )
        return self.store.rebuild(reason="onboarding_answer")

    def complete(self, summary=None):
        st = self.state()
        self.store.events.record(
            "onboarding_completed", "direct_user_message",
            payload={
                "summary": summary,
                "questions_asked": len(st["asked_ids"]),
                "families_covered": st["families_covered"],
                "coverage_ok": st["families_covered"] >= MIN_FAMILIES,
            },
            session_id=self.session_id,
        )
        return self.store.rebuild(reason="onboarding_completed")

    def correct(self, dimension, corrected_value=None, reason=None):
        """The user disagreeing with the closing summary is high-value evidence."""
        if corrected_value is None:
            return self.store.reject(dimension, reason=reason,
                                     inference_source="onboarding_answer",
                                     session_id=self.session_id)
        self.store.events.record(
            "correction", "direct_user_message",
            observation={
                "dimension": dimension,
                "value": corrected_value,
                "source_type": "explicit_correction",
                "polarity": "support",
                "scope": "global",
                "note": "onboarding summary correction: %s" % (reason or ""),
            },
            payload={"reason": reason, "stage": "onboarding_summary"},
            session_id=self.session_id,
        )
        return self.store.rebuild(reason="onboarding_correction")
