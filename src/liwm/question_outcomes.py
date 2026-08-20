"""Event-derived empirical question usefulness with sparse-data fallbacks."""

from __future__ import annotations

from .evidence import clamp
from .jsonio import utc_now

MIN_SAMPLES = 5


class QuestionOutcomeStore:
    def __init__(self, store):
        self.store = store

    def record(self, question_id, family, dimensions, pre_uncertainty,
               predicted_information_gain, post_uncertainty, changed_decision=False,
               later_correction_useful=None, answer_evidence=None, cognitive_cost=None,
               elapsed_seconds=None, turn_burden=None, scope="global", domain=None,
               project_id=None, session_id=None):
        prior = [event for event in self.store.events.iter_events(
            kinds={"question_asked", "question_answered"}, session_id=session_id
        ) if (event.get("payload") or {}).get("question_id") == question_id]
        if not any(event.get("kind") == "question_asked" for event in prior):
            raise ValueError("question outcome requires a linked question_asked event")
        if any(event.get("kind") == "question_answered" for event in prior):
            raise ValueError("question outcome was already recorded")
        payload = {
            "question_id": question_id, "family": family,
            "dimensions": list(dimensions or []),
            "pre_uncertainty": clamp(pre_uncertainty),
            "predicted_information_gain": clamp(predicted_information_gain),
            "post_uncertainty": clamp(post_uncertainty),
            "observed_information_gain": round(
                max(0.0, clamp(pre_uncertainty) - clamp(post_uncertainty)), 4
            ),
            "changed_decision": bool(changed_decision),
            "later_correction_useful": later_correction_useful,
            "answer_evidence": list(answer_evidence or []),
            "cognitive_cost": clamp(cognitive_cost) if cognitive_cost is not None else None,
            "elapsed_seconds": max(0.0, float(elapsed_seconds)) if elapsed_seconds is not None else None,
            "turn_burden": turn_burden, "scope": scope, "recorded_at": utc_now(),
        }
        return self.store.events.record(
            "question_answered", "agent_inference", payload=payload,
            domain=domain, project_id=project_id, session_id=session_id,
        )

    def rows(self):
        return [
            {"domain": event.get("domain"), "project_id": event.get("project_id"),
             **(event.get("payload") or {})}
            for event in self.store.events.iter_events(kinds={"question_answered"})
            if (event.get("payload") or {}).get("observed_information_gain") is not None
        ]

    def effectiveness(self, family, dimension=None, domain=None, min_samples=MIN_SAMPLES):
        rows = self.rows()
        fallbacks = [
            [row for row in rows if row.get("family") == family and domain
             and row.get("domain") == domain and dimension in row.get("dimensions", [])],
            [row for row in rows if row.get("family") == family
             and dimension in row.get("dimensions", [])],
            [row for row in rows if row.get("family") == family],
        ]
        for level, candidates in zip(("family_dimension_domain", "family_dimension", "family"),
                                     fallbacks):
            if len(candidates) < min_samples:
                continue
            values = [float(row["observed_information_gain"])
                      + (0.25 if row.get("changed_decision") else 0.0)
                      + (0.15 if row.get("later_correction_useful") is True else 0.0)
                      - 0.15 * float(row.get("cognitive_cost") or 0.0)
                      - min(0.15, float(row.get("turn_burden") or 0.0) * 0.03)
                      for row in candidates]
            return {"estimate": round(sum(values) / len(values), 4),
                    "samples": len(values), "level": level, "empirical": True}
        return {"estimate": None, "samples": max((len(group) for group in fallbacks), default=0),
                "level": "heuristic", "empirical": False}
