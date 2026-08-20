"""The measurement harness.

Two studies, both fully local and deterministic:

* :func:`run_convergence_study` - drive a synthetic user through onboarding and
  N rounds of work, and measure whether LIWM's beliefs move toward that user's
  hidden preferences, whether artifacts get accepted more often, and whether the
  number of questions needed *falls* as understanding grows.  That last one is
  the claim most personalisation systems quietly fail.

* :func:`run_mode_study` - hold a situation fixed and vary the mode, to check
  that LOW/MEDIUM/HIGH/AUTO are actually different policies rather than the same
  policy with different labels.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ..context import build_runtime_context
from ..feedback import record_feedback
from ..modes import Signals, mode_profile, resolve_auto
from ..onboarding import ONBOARDING_QUESTION_COUNT, OnboardingSession
from ..paths import ensure_layout
from ..profile import ProfileStore
from ..questions import QuestionPlanner
from ..scope import resolve_for_context
from ..strategy import StrategyStore
from .simulators import make_user

__all__ = ["EvaluationResult", "run_convergence_study", "run_mode_study", "belief_accuracy"]


class EvaluationResult(dict):
    """Study output.  Everything here measures the framework, never a person."""


def belief_accuracy(store, user, domain=None, project_id=None):
    """How much of the hidden preference vector LIWM currently has right."""
    profile = store.load()
    resolved = resolve_for_context(profile.get("beliefs", []), domain=domain,
                                   project_id=project_id, min_confidence=0.0)
    correct = wrong = unknown = 0
    weighted = 0.0
    details = []
    for dim in user.hidden_dimensions():
        truth = user.hidden[dim]
        belief = resolved.get(dim)
        if belief is None:
            unknown += 1
            details.append({"dimension": dim, "truth": truth, "believed": None, "state": "unknown"})
            continue
        believed = belief.get("value")
        conf = float(belief.get("confidence", 0.0))
        if str(believed) == str(truth):
            correct += 1
            weighted += conf
            state = "correct"
        else:
            wrong += 1
            weighted -= conf
            state = "wrong"
        details.append({"dimension": dim, "truth": truth, "believed": believed,
                        "confidence": conf, "state": state})
    total = correct + wrong + unknown
    return {
        "correct": correct,
        "wrong": wrong,
        "unknown": unknown,
        "total": total,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "coverage": round((correct + wrong) / total, 4) if total else 0.0,
        "confidence_weighted": round(weighted / total, 4) if total else 0.0,
        "details": details,
    }


def _simulate_onboarding(store, user, session_id="eval-onboarding"):
    ob = OnboardingSession(store, session_id=session_id)
    ob.start()
    asked = ignored = 0
    for _ in range(ONBOARDING_QUESTION_COUNT):
        q = ob.next_question()
        if q is None:
            break
        asked += 1
        answer = user.answer(q["id"])
        if answer is None:
            ignored += 1
            store.events.record(
                "question_skipped", "direct_user_message",
                payload={"question_id": q["id"], "reason": "ignored", "context": "onboarding"},
                session_id=session_id,
            )
            continue
        ob.record_answer(q["id"], "<simulated>", observations=answer["observations"])
    ob.complete(summary="simulated onboarding")
    return {"asked": asked, "ignored": ignored}


def _propose_artifact(store, user, domain, project_id):
    """The agent's best guess at what the user wants, from current beliefs."""
    profile = store.load()
    resolved = resolve_for_context(profile.get("beliefs", []), domain=domain,
                                   project_id=project_id, min_confidence=0.30)
    proposed = {}
    for dim in user.hidden_dimensions():
        belief = resolved.get(dim)
        proposed[dim] = belief.get("value") if belief else "__unknown__"
    return proposed, resolved


def run_convergence_study(archetype, rounds=8, seed=1337, home=None, domain="software",
                          project_id="eval-project", mode="auto", do_onboarding=True,
                          project_overrides=None):
    """Drive a synthetic user through onboarding plus *rounds* of work."""
    tmp = None
    if home is None:
        # mkdtemp rather than TemporaryDirectory: the caller decides when to
        # remove it, and an implicit finalizer would emit ResourceWarnings
        # under the test runner.
        tmp = tempfile.mkdtemp(prefix="liwm-eval-")
        home = tmp
    home = ensure_layout(home)
    store = ProfileStore(home)
    strategy_store = StrategyStore(home)
    user = make_user(archetype, seed=seed, project_overrides=project_overrides)

    onboarding_stats = None
    if do_onboarding:
        onboarding_stats = _simulate_onboarding(store, user)

    series = []
    for round_index in range(rounds):
        session_id = "eval-s%02d" % round_index
        proposed, resolved = _propose_artifact(store, user, domain, project_id)

        contract = _contract_for(store, mode, resolved, round_index, strategy_store)
        planner = QuestionPlanner(contract, resolved=dict(resolved),
                                  strategy=strategy_store.load())
        plan = planner.plan(
            misunderstanding_risk=0.6,
            fatigue=min(0.8, 0.06 * round_index),
            max_questions=contract.get("max_questions"),
        )

        asked = answered = 0
        for planned in plan:
            asked += 1
            store.events.record(
                "question_asked", "agent_inference",
                payload={"question_id": planned["id"], "style": planned["style"],
                         "family": planned["family"], "utility": planned["utility"],
                         "threshold": contract.get("min_utility"),
                         "mode": contract["mode"]},
                session_id=session_id, project_id=project_id, domain=domain,
            )
            answer = user.answer(planned["id"])
            if answer is None:
                store.events.record(
                    "question_skipped", "direct_user_message",
                    payload={"question_id": planned["id"], "reason": "ignored"},
                    session_id=session_id, project_id=project_id, domain=domain,
                )
                continue
            answered += 1
            store.events.record(
                "question_answered", "direct_user_message",
                payload={"question_id": planned["id"], "style": planned["style"],
                         "value": "useful" if answer["useful"] else "redundant",
                         "changed_plan": answer["useful"]},
                session_id=session_id, project_id=project_id, domain=domain,
            )
            for obs in answer["observations"]:
                store.events.record(
                    "observation", "direct_user_message",
                    observation={
                        "dimension": obs["dimension"],
                        "value": obs["value"],
                        "polarity": "support",
                        "source_type": "explicit_statement",
                        "scope": "global",
                        "note": "simulated answer",
                    },
                    session_id=session_id, project_id=project_id, domain=domain,
                )
        if asked:
            store.rebuild(reason="eval-questions")
            proposed, resolved = _propose_artifact(store, user, domain, project_id)

        store.events.record(
            "artifact", "agent_inference",
            payload={"round": round_index, "mode": contract["mode"],
                     "dimensions": len(proposed)},
            session_id=session_id, project_id=project_id, domain=domain,
        )
        reaction = user.react(proposed)
        record_feedback(
            store, reaction["kind"], channel="explicit",
            text="<simulated reaction>", project_id=project_id, domain=domain,
            session_id=session_id, custom_acceptance=reaction["acceptance"],
            # Deliberately no explicit scope: corrections about *this artifact*
            # must inherit feedback.py's project-scoped default. Forcing them
            # global here would simulate the exact contamination the framework
            # exists to prevent, and would make the study flatter the design.
            extra_observations=[
                {"dimension": m["dimension"], "value": m["wanted"],
                 "source_type": "explicit_correction"}
                for m in reaction["mismatches"][:3]
            ],
        )

        accuracy = belief_accuracy(store, user, domain=domain, project_id=project_id)
        series.append({
            "round": round_index,
            "mode": contract["mode"],
            "investigation_need": contract.get("investigation_need"),
            "questions_asked": asked,
            "questions_answered": answered,
            "acceptance": reaction["acceptance"],
            "feedback_kind": reaction["kind"],
            "accuracy": accuracy["accuracy"],
            "coverage": accuracy["coverage"],
            "confidence_weighted": accuracy["confidence_weighted"],
        })

    final_accuracy = belief_accuracy(store, user, domain=domain, project_id=project_id)
    # The same measurement from outside the project, which is what reveals
    # whether project-only requirements have leaked into the person's model.
    final_accuracy_global = belief_accuracy(store, user, domain=None, project_id=None)
    result = EvaluationResult({
        "archetype": archetype,
        "seed": seed,
        "rounds": rounds,
        "mode": mode,
        "home": str(home),
        "onboarding": onboarding_stats,
        "series": series,
        "final_accuracy": final_accuracy,
        "final_accuracy_global": final_accuracy_global,
        "summary": _summarise(series, final_accuracy),
        "note": "Simulated study of the framework. These are estimates about LIWM, "
                "not measurements of any person.",
    })
    if tmp is not None:
        result["temp_home"] = str(tmp)
    return result


def _contract_for(store, mode, resolved, round_index, strategy_store):
    if (mode or "auto").lower() != "auto":
        return mode_profile(mode)
    profile = store.load()
    from ..fatigue import profile_maturity
    signals = Signals(
        intent_uncertainty=max(0.15, 0.85 - 0.08 * round_index),
        novelty=0.4,
        consequence=0.5,
        reversibility=0.8,
        specification_completeness=0.4,
        profile_maturity=profile_maturity(profile),
        recent_correction_rate=0.2,
        fatigue=min(0.7, 0.06 * round_index),
        project_stage="design" if round_index < 2 else "build",
        question_preference=(
            (profile.get("interaction_profile", {}).get("preferred_question_frequency") or {})
            .get("value") or "moderate"
        ),
    )
    low, high = strategy_store.auto_thresholds()
    return resolve_auto(signals, thresholds=(low, high))


def _summarise(series, final_accuracy):
    if not series:
        return {}
    first_half = series[: max(1, len(series) // 2)]
    second_half = series[len(series) // 2:]

    def _mean(rows, key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    return {
        "accuracy_first_round": series[0]["accuracy"],
        "accuracy_final_round": series[-1]["accuracy"],
        "accuracy_gain": round(series[-1]["accuracy"] - series[0]["accuracy"], 4),
        "acceptance_early": _mean(first_half, "acceptance"),
        "acceptance_late": _mean(second_half, "acceptance"),
        "acceptance_gain": (
            round((_mean(second_half, "acceptance") or 0) - (_mean(first_half, "acceptance") or 0), 4)
        ),
        "questions_early": _mean(first_half, "questions_asked"),
        "questions_late": _mean(second_half, "questions_asked"),
        "questions_reduction": (
            round((_mean(first_half, "questions_asked") or 0)
                  - (_mean(second_half, "questions_asked") or 0), 4)
        ),
        "final_confidence_weighted_accuracy": final_accuracy["confidence_weighted"],
        "total_questions": sum(r["questions_asked"] for r in series),
    }


def run_mode_study(store=None, home=None, signals=None, domain="software",
                   project_id=None, task="build a thing"):
    """Compare the four modes on one fixed situation."""
    tmp = None
    if store is None:
        if home is None:
            tmp = tempfile.mkdtemp(prefix="liwm-modes-")
            home = tmp
        store = ProfileStore(ensure_layout(home))

    base_signals = signals or {
        "intent_uncertainty": 0.75,
        "novelty": 0.6,
        "consequence": 0.7,
        "reversibility": 0.4,
        "specification_completeness": 0.3,
        "project_stage": "inception",
    }

    rows = {}
    for mode in ("low", "medium", "high", "auto"):
        ctx = build_runtime_context(store, domain=domain, project_id=project_id,
                                    task=task, mode=mode, signals=dict(base_signals))
        contract = (mode_profile(ctx["mode"]["effective"]))
        contract["max_questions"] = ctx["mode"]["question_budget"]
        planner = QuestionPlanner(contract, resolved={})
        plan = planner.plan(misunderstanding_risk=0.6, fatigue=0.0,
                            max_questions=contract["max_questions"])
        experiential = len([p for p in plan if p["class"] == "experiential"])
        rows[mode] = {
            "effective_mode": ctx["mode"]["effective"],
            "question_budget": ctx["mode"]["question_budget"],
            "planned": len(plan),
            "experiential": experiential,
            "technical": len(plan) - experiential,
            "experiential_share": round(experiential / len(plan), 3) if plan else None,
            "styles": sorted({p["style"] for p in plan}),
            "first_question": plan[0]["text"] if plan else None,
            "investigation_need": ctx["mode"].get("investigation_need"),
            "one_at_a_time": contract.get("one_at_a_time"),
        }

    result = EvaluationResult({
        "signals": base_signals,
        "modes": rows,
        "distinguishable": _distinguishable(rows),
    })
    if tmp is not None:
        result["temp_home"] = str(tmp)
    return result


def _distinguishable(rows):
    counts = [rows[m]["planned"] for m in ("low", "medium", "high")]
    shares = [rows[m]["experiential_share"] for m in ("low", "medium", "high")
              if rows[m]["experiential_share"] is not None]
    return {
        "question_counts_increase": counts == sorted(counts) and counts[0] < counts[-1],
        "experiential_share_increases": (
            len(shares) >= 2 and shares == sorted(shares) and shares[0] < shares[-1]
        ),
        "counts": counts,
        "experiential_shares": shares,
    }
