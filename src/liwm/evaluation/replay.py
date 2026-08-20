"""Replay: would this change actually have helped?

Historical episodes are counterfactually re-run under a candidate strategy and
compared against the incumbent.  This is what stands between "the agent had an
idea about itself" and "the agent's idea survived contact with its own history".

Honesty about what this can and cannot measure
----------------------------------------------
Some quantities are **observed** and replay them exactly:

* which questions were asked, at what computed utility;
* whether each question was answered, skipped, ignored, or judged redundant;
* what feedback the artifact received.

One quantity is **modelled**, because it cannot be observed counterfactually:
the acceptance an artifact would have received had a different question been
asked.  The model is stated explicitly below rather than hidden in a constant,
and every figure derived from it is labelled ``estimated``.  A candidate is
never promoted on a modelled metric alone - the guarded metrics that block
promotion are all observed ones.
"""

from __future__ import annotations

import json
from pathlib import Path

__all__ = ["ReplayResult", "load_episodes", "replay_episodes", "replay_candidate",
           "ACCEPTANCE_MODEL"]

#: Modelled relationship between retaining historically-useful questions and
#: acceptance.  Interpretation: dropping every question that changed the plan
#: costs 15% of observed acceptance; retaining all of them costs nothing.
#: Deliberately conservative - it can never manufacture a large improvement.
ACCEPTANCE_MODEL = {
    "retention_weight": 0.15,
    "base": 0.85,
    "note": "estimated, not observed; see module docstring",
}


class ReplayResult(dict):
    """Replay output, shaped for :meth:`SelfImprovementStore.attach_replay`."""


def load_episodes(home):
    """Load every persisted episode from ``<home>/sessions``."""
    sessions = Path(home) / "sessions"
    episodes = []
    if not sessions.is_dir():
        return episodes
    for path in sorted(sessions.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                episodes.append(json.load(fh))
        except (OSError, ValueError):
            continue
    return episodes


def _answer_index(episode):
    index = {}
    for answer in episode.get("answers", []):
        qid = answer.get("id")
        if qid:
            index[qid] = answer
    return index


def _classify(answer):
    """useful | wasted | unknown, from what the user actually did."""
    if answer is None:
        return "unknown"
    value = answer.get("value")
    if value == "useful":
        return "useful"
    if value in ("redundant", "skipped"):
        return "wasted"
    if answer.get("changed_plan"):
        return "useful"
    return "unknown"


def _episode_metrics(episode, asked_ids):
    """Observed metrics for a chosen counterfactual question set."""
    answers = _answer_index(episode)
    asked = [q for q in episode.get("questions", []) if q.get("id") in asked_ids]

    useful = wasted = unknown = 0
    for q in asked:
        klass = _classify(answers.get(q.get("id")))
        if klass == "useful":
            useful += 1
        elif klass == "wasted":
            wasted += 1
        else:
            unknown += 1

    total_useful = sum(
        1 for q in episode.get("questions", [])
        if _classify(answers.get(q.get("id"))) == "useful"
    )
    retention = (useful / total_useful) if total_useful else 1.0

    accepted = len([f for f in episode.get("feedback", [])
                    if (f.get("acceptance") or 0) >= 0.8])
    observed_acceptance = episode.get("mean_acceptance")

    estimated_acceptance = None
    if observed_acceptance is not None:
        estimated_acceptance = round(
            observed_acceptance
            * (ACCEPTANCE_MODEL["base"] + ACCEPTANCE_MODEL["retention_weight"] * retention),
            4,
        )

    assumptions = episode.get("assumptions", [])
    wrong = len([f for f in episode.get("feedback", [])
                 if f.get("kind") in ("misunderstood_intent", "should_have_asked")])

    return {
        "asked": len(asked),
        "useful": useful,
        "wasted": wasted,
        "unknown": unknown,
        "useful_retention": round(retention, 4),
        "accepted_outputs": accepted,
        "observed_acceptance": observed_acceptance,
        "estimated_acceptance": estimated_acceptance,
        "assumptions": len(assumptions),
        "assumption_errors": wrong,
    }


def _aggregate(per_episode):
    total_asked = sum(m["asked"] for m in per_episode)
    total_wasted = sum(m["wasted"] for m in per_episode)
    total_useful = sum(m["useful"] for m in per_episode)
    total_accepted = sum(m["accepted_outputs"] for m in per_episode)
    total_assumptions = sum(m["assumptions"] for m in per_episode)
    total_errors = sum(m["assumption_errors"] for m in per_episode)
    est = [m["estimated_acceptance"] for m in per_episode if m["estimated_acceptance"] is not None]
    retention = [m["useful_retention"] for m in per_episode]

    def _rate(n, d):
        return round(n / d, 4) if d else None

    return {
        "questions_asked": total_asked,
        "question_ignore_rate": _rate(total_wasted, total_asked),
        "useful_question_rate": _rate(total_useful, total_asked),
        "useful_question_retention": round(sum(retention) / len(retention), 4) if retention else None,
        "questions_per_accepted_outcome": _rate(total_asked, total_accepted),
        "assumption_error_rate": _rate(total_errors, max(total_assumptions, len(per_episode))),
        "first_pass_acceptance": round(sum(est) / len(est), 4) if est else None,
        "first_pass_acceptance_is_estimated": True,
    }


def replay_episodes(episodes, utility_threshold_delta=0.0, force_min_questions=0,
                    style_filter=None):
    """Replay a question policy across episodes.

    The policy is expressed as a delta on the utility threshold plus optional
    floors and style restrictions - which is exactly the shape of the parameters
    a Level-4 candidate is allowed to carry.
    """
    per_episode = []
    for episode in episodes:
        chosen = set()
        ranked = sorted(
            episode.get("questions", []),
            key=lambda q: -(q.get("utility") or 0.0),
        )
        for q in ranked:
            utility = q.get("utility")
            if utility is None:
                continue
            if style_filter and q.get("style") not in style_filter:
                continue
            # The historical utility was computed against the incumbent
            # threshold; a candidate shifts that bar.
            if utility >= max(0.0, (q.get("threshold") or 0.0) + utility_threshold_delta):
                chosen.add(q.get("id"))
        while len(chosen) < force_min_questions and ranked:
            for q in ranked:
                if q.get("id") not in chosen:
                    chosen.add(q.get("id"))
                    break
            else:
                break
        per_episode.append(_episode_metrics(episode, chosen))

    return {"per_episode": per_episode, "aggregate": _aggregate(per_episode)}


def replay_candidate(home_or_episodes, candidate, primary_metric=None):
    """Score a candidate rule against history.

    Returns the structure :mod:`liwm.selfimprove` expects, including
    ``primary_delta`` and ``guarded_deltas`` (incumbent minus candidate, in the
    direction where positive means *worse* for lower-is-better metrics).
    """
    if isinstance(home_or_episodes, (str, Path)):
        episodes = load_episodes(home_or_episodes)
    else:
        episodes = list(home_or_episodes)

    params = candidate.get("parameters", {}) or {}
    delta = float(params.get("min_utility_delta", 0.0))
    floor = int(params.get("min_probes_before_build", 0))
    styles = params.get("styles")

    incumbent = replay_episodes(episodes)
    variant = replay_episodes(
        episodes, utility_threshold_delta=delta, force_min_questions=floor,
        style_filter=styles,
    )

    primary = primary_metric or candidate.get("primary_metric") or "first_pass_acceptance"
    lower_is_better = primary in (
        "question_ignore_rate", "questions_per_accepted_outcome", "assumption_error_rate",
        "explicit_correction_rate", "global_correction_rate",
    )

    a = incumbent["aggregate"].get(primary)
    b = variant["aggregate"].get(primary)
    primary_delta = None
    if a is not None and b is not None:
        primary_delta = round((a - b) if lower_is_better else (b - a), 4)

    guarded = {}
    for metric in ("question_ignore_rate", "questions_per_accepted_outcome",
                   "assumption_error_rate"):
        x, y = incumbent["aggregate"].get(metric), variant["aggregate"].get(metric)
        if x is not None and y is not None:
            guarded[metric] = round(y - x, 4)   # positive = worse

    retention_before = incumbent["aggregate"].get("useful_question_retention")
    retention_after = variant["aggregate"].get("useful_question_retention")

    return ReplayResult(
        {
            "episodes": len(episodes),
            "distinct_sessions": len({e.get("session_id") for e in episodes if e.get("session_id")}),
            "primary_metric": primary,
            "primary_delta": primary_delta,
            "primary_is_estimated": primary == "first_pass_acceptance",
            "incumbent": incumbent["aggregate"],
            "candidate": variant["aggregate"],
            "guarded_deltas": guarded,
            "useful_question_retention": {"incumbent": retention_before, "candidate": retention_after},
            "parameters_applied": {"min_utility_delta": delta, "min_probes_before_build": floor,
                                   "styles": styles},
            "caveat": (
                "Question selection and outcomes are replayed from recorded events. "
                "Acceptance under a different question set is modelled, not observed; "
                "see liwm.evaluation.replay.ACCEPTANCE_MODEL."
            ),
        }
    )
