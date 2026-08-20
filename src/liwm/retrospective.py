"""Session retrospective: turning an episode into learning.

Runs at the end of meaningful work, not after every reply.  It is normally
silent - the output is persisted, not narrated, unless the user asks.

What it produces:

* an **episode record** (what happened, what was predicted, what landed) that
  becomes a replay case for evaluating future strategy changes;
* Level-3 strategy adjustments;
* zero or more Level-4 **candidate rules**, which go into the gated pipeline
  rather than into anyone's instructions.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from .jsonio import utc_now, write_json_atomic
from .selfimprove import CandidateRule, SelfImprovementStore
from .strategy import StrategyStore, update_from_events

__all__ = ["run_retrospective", "build_episode", "propose_candidates"]

SCHEMA_VERSION = "0.1.0"


def build_episode(store, session_id, project_id=None):
    """Condense one session into a replayable episode.

    Stores observable summaries only - questions, decisions, predictions,
    feedback - never model-internal reasoning, so episodes stay useful when the
    underlying model changes (requirement §37).
    """
    events = [
        e for e in store.events.read_all(include_quarantined=True)
        if e.get("session_id") == session_id
    ]
    questions, answers, feedback, predictions, outcomes, assumptions = [], [], [], [], [], []
    modes = []
    corrections = 0
    quarantined = 0

    for e in events:
        payload = e.get("payload") or {}
        kind = e.get("kind")
        if e.get("quarantined"):
            quarantined += 1
            continue
        if kind == "question_asked":
            questions.append({"id": payload.get("question_id"), "style": payload.get("style"),
                              "family": payload.get("family"), "utility": payload.get("utility"),
                              "at": e.get("ts")})
        elif kind == "question_answered":
            answers.append({"id": payload.get("question_id"), "value": payload.get("value"),
                            "changed_plan": payload.get("changed_plan"), "at": e.get("ts")})
        elif kind == "question_skipped":
            answers.append({"id": payload.get("question_id"), "value": "skipped",
                            "reason": payload.get("reason"), "at": e.get("ts")})
        elif kind == "feedback":
            feedback.append({"kind": payload.get("kind"), "channel": payload.get("channel"),
                             "acceptance": payload.get("acceptance"), "at": e.get("ts")})
        elif kind == "prediction":
            predictions.append({"id": payload.get("id"),
                                "predicted_acceptance": payload.get("predicted_acceptance"),
                                "confidence": payload.get("confidence"),
                                "friction": [f.get("issue") for f in payload.get("predicted_friction", [])]})
        elif kind == "outcome" and "predicted_acceptance" in payload:
            outcomes.append(payload)
        elif kind == "assumption_made":
            assumptions.append({"assumption": payload.get("assumption"),
                                "disclosed": payload.get("disclosed"),
                                "reversible": payload.get("reversible"),
                                "impact": payload.get("impact")})
        elif kind == "correction":
            corrections += 1
        elif kind == "mode_selected":
            modes.append(payload.get("mode"))

    accepted = [f["acceptance"] for f in feedback if f.get("acceptance") is not None]
    useful_q = len([a for a in answers if a.get("value") == "useful"])
    wasted_q = len([a for a in answers if a.get("value") in ("redundant", "skipped")])

    return {
        "id": "epi_%s" % uuid.uuid4().hex[:12],
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "session_id": session_id,
        "project_id": project_id,
        "modes_used": sorted(set(m for m in modes if m)),
        "counts": {
            "events": len(events),
            "questions_asked": len(questions),
            "questions_useful": useful_q,
            "questions_wasted": wasted_q,
            "feedback": len(feedback),
            "corrections": corrections,
            "assumptions": len(assumptions),
            "quarantined_events": quarantined,
        },
        "questions": questions,
        "answers": answers,
        "feedback": feedback,
        "predictions": predictions,
        "outcomes": outcomes,
        "assumptions": assumptions,
        "mean_acceptance": round(sum(accepted) / len(accepted), 4) if accepted else None,
        "prediction_error": (
            round(sum(abs(o["error"]) for o in outcomes) / len(outcomes), 4)
            if outcomes else None
        ),
    }


def propose_candidates(episode, metrics=None):
    """Derive Level-4 candidate rules from an episode.

    Conservative by design: a single session is weak evidence about how to
    change behaviour, so these are *proposals* that must survive replay across
    many episodes before they can affect anything.
    """
    candidates = []
    counts = episode["counts"]

    if counts["questions_asked"] >= 3 and counts["questions_wasted"] >= counts["questions_asked"] / 2:
        candidates.append(CandidateRule.create(
            title="Raise the utility threshold before asking",
            statement=(
                "When more than half of the questions in a session are skipped or judged "
                "redundant, raise the minimum question utility by 0.15 for this user until "
                "the answer rate recovers."
            ),
            surface="interaction",
            expected_effect="fewer low-value questions; lower question_ignore_rate",
            primary_metric="question_ignore_rate",
            parameters={"min_utility_delta": 0.15},
            evidence=[{"episode": episode["id"], "asked": counts["questions_asked"],
                       "wasted": counts["questions_wasted"]}],
        ))

    misunderstood = [f for f in episode["feedback"] if f.get("kind") == "misunderstood_intent"]
    if misunderstood and counts["questions_asked"] <= 1:
        candidates.append(CandidateRule.create(
            title="Probe intent before building when consequence is high",
            statement=(
                "When an artifact is non-trivial and no intent question has been asked, ask "
                "one counterfactual probe about the desired outcome before producing it."
            ),
            surface="interaction",
            expected_effect="fewer misunderstood_intent outcomes; higher first_pass_acceptance",
            primary_metric="first_pass_acceptance",
            parameters={"min_probes_before_build": 1},
            evidence=[{"episode": episode["id"], "misunderstood": len(misunderstood)}],
        ))

    undisclosed = [a for a in episode["assumptions"] if not a.get("disclosed")]
    if len(undisclosed) >= 2:
        candidates.append(CandidateRule.create(
            title="Disclose consequential assumptions inline",
            statement=(
                "When two or more irreversible or high-impact assumptions are made without "
                "disclosure, state them in a single line alongside the result."
            ),
            surface="transparency",   # protected: this will be refused, by design
            expected_effect="better assumption visibility",
            primary_metric="assumption_error_rate",
            evidence=[{"episode": episode["id"], "undisclosed": len(undisclosed)}],
        ))

    if episode.get("prediction_error") is not None and episode["prediction_error"] > 0.3:
        candidates.append(CandidateRule.create(
            title="Widen predicted friction when the profile is thin",
            statement=(
                "When mean absolute prediction error exceeds 0.3 over a session, lower "
                "predicted acceptance by the observed bias for domains with fewer than "
                "five high-confidence beliefs."
            ),
            surface="calibration",
            expected_effect="lower calibration error; better-targeted probes",
            primary_metric="first_pass_acceptance",
            parameters={"bias_correction": True},
            evidence=[{"episode": episode["id"], "error": episode["prediction_error"]}],
        ))

    return candidates


def run_retrospective(store, session_id, project_id=None, propose=True, persist=True):
    """Full end-of-session pass: episode, strategy update, candidate proposals."""
    episode = build_episode(store, session_id, project_id=project_id)

    episode_path = None
    if persist:
        episode_path = Path(store.home) / "sessions" / ("%s.json" % episode["id"])
        write_json_atomic(episode_path, episode)

    strategy, applied = update_from_events(store, StrategyStore(store.home))

    proposed = []
    if propose:
        si = SelfImprovementStore(store.home)
        for candidate in propose_candidates(episode):
            proposed.append(si.propose(candidate, store=store))

    lessons = _lessons(episode)
    store.events.record(
        "retrospective", "agent_inference",
        payload={
            "episode_id": episode["id"],
            "session_id": session_id,
            "counts": episode["counts"],
            "mean_acceptance": episode["mean_acceptance"],
            "prediction_error": episode["prediction_error"],
            "strategy_changes": applied,
            "candidates": [c["id"] for c in proposed],
            "lessons": lessons,
        },
        session_id=session_id, project_id=project_id,
    )

    return {
        "episode": episode,
        "episode_path": str(episode_path) if episode_path else None,
        "strategy": strategy,
        "strategy_changes": applied,
        "candidates": [
            {"id": c["id"], "title": c["title"], "state": c["state"],
             "violations": c.get("constitution", {}).get("violations", [])}
            for c in proposed
        ],
        "lessons": lessons,
    }


def _lessons(episode):
    counts = episode["counts"]
    out = []
    if counts["questions_asked"] == 0 and counts["corrections"] > 0:
        out.append("Acted without asking and was corrected; a cheap probe may have been worth it.")
    if counts["questions_wasted"]:
        out.append("%d question(s) produced no usable answer." % counts["questions_wasted"])
    if counts["questions_useful"]:
        out.append("%d question(s) changed the plan." % counts["questions_useful"])
    if episode.get("mean_acceptance") is not None:
        out.append("Mean acceptance %.2f across %d feedback signal(s)."
                   % (episode["mean_acceptance"], counts["feedback"]))
    if episode.get("prediction_error") is not None:
        out.append("Prediction error %.2f - %s."
                   % (episode["prediction_error"],
                      "well calibrated" if episode["prediction_error"] < 0.2
                      else "miscalibrated for this kind of work"))
    if counts["quarantined_events"]:
        out.append("%d event(s) were quarantined and contributed nothing to the profile."
                   % counts["quarantined_events"])
    if not out:
        out.append("Nothing notable; no durable learning recorded.")
    return out
