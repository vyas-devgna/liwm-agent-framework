"""Minimal IntentBench scorer-contract runner.

Cases keep participant-visible inputs separate from scorer-only ground truth.
Adapters receive a deep copy of :func:`participant_view`, never the source case.
The shipped projection adapter consumes visible fixture scores, so its synthetic
suite validates adapter/scorer plumbing only, not LIWM learning or retrieval.
"""

from __future__ import annotations

import json
import math
import sys
from copy import deepcopy
from pathlib import Path

from ..schema import SchemaStore, validate_or_raise

__all__ = [
    "BUILTIN_ADAPTERS",
    "default_suite_path",
    "load_suite",
    "participant_view",
    "run_intentbench",
]


def default_suite_path():
    """Return the repository's shipped synthetic smoke suite."""
    relative = Path("benchmarks") / "intentbench" / "cases" / "synthetic-smoke.json"
    candidates = [Path(__file__).resolve().parents[3] / relative, Path(sys.prefix) / "share" / "liwm" / relative]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def load_suite(path=None):
    target = Path(path) if path else default_suite_path()
    suite = json.loads(target.read_text(encoding="utf-8"))
    validate_or_raise(suite, SchemaStore().load("intentbench-case"), str(target))
    seen = set()
    for case in suite["cases"]:
        if case["case_id"] in seen:
            raise ValueError("duplicate IntentBench case_id %r" % case["case_id"])
        seen.add(case["case_id"])
        candidates = {row["id"] for row in case["candidate_outputs"]}
        if len(candidates) != len(case["candidate_outputs"]):
            raise ValueError("duplicate candidate id in case %r" % case["case_id"])
        if case["observed_choice"] not in candidates:
            raise ValueError("observed_choice is not a candidate in case %r" % case["case_id"])
        if case["hidden_ground_truth"]["preferred_candidate"] != case["observed_choice"]:
            raise ValueError("ground truth and observed choice disagree in case %r" % case["case_id"])
    return suite


def participant_view(case):
    """Return the only data an adapter is allowed to inspect."""
    return deepcopy({
        "case_id": case["case_id"],
        "task_type": case["task_type"],
        "exposed_to_liwm": case["exposed_to_liwm"],
        "candidate_outputs": case["candidate_outputs"],
    })


def _static_first(view):
    ids = [row["id"] for row in view["candidate_outputs"]]
    return {"probabilities": {candidate_id: float(i == 0) for i, candidate_id in enumerate(ids)}}


def _liwm_projection(view):
    """Use precomputed, participant-visible LIWM projection scores."""
    ids = [row["id"] for row in view["candidate_outputs"]]
    scores = view["exposed_to_liwm"].get("candidate_scores", {})
    return {"probabilities": {candidate_id: float(scores.get(candidate_id, 0.0)) for candidate_id in ids}}


BUILTIN_ADAPTERS = {"static-first": _static_first, "liwm-projection": _liwm_projection}


def _normalise_prediction(view, prediction):
    ids = [row["id"] for row in view["candidate_outputs"]]
    raw = prediction.get("probabilities") if isinstance(prediction, dict) else None
    if not isinstance(raw, dict):
        raise ValueError("adapter must return {'probabilities': {candidate_id: number}}")
    unknown = set(raw) - set(ids)
    if unknown:
        raise ValueError("adapter returned unknown candidates: %s" % ", ".join(sorted(unknown)))
    probabilities = {}
    for candidate_id in ids:
        value = raw.get(candidate_id, 0.0)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            raise ValueError("candidate probabilities must be non-negative numbers")
        probabilities[candidate_id] = float(value)
    total = sum(probabilities.values())
    if total <= 0:
        raise ValueError("adapter probabilities must have a positive sum")
    return {key: value / total for key, value in probabilities.items()}


def run_intentbench(suite, adapter="liwm-projection"):
    """Run a suite and return aggregate probability and top-choice scores."""
    if isinstance(adapter, str):
        try:
            adapter_name, adapter_fn = adapter, BUILTIN_ADAPTERS[adapter]
        except KeyError as exc:
            raise ValueError("unknown adapter %r" % adapter) from exc
    else:
        adapter_name, adapter_fn = getattr(adapter, "__name__", "callable"), adapter

    rows = []
    for case in suite["cases"]:
        view = participant_view(case)
        probabilities = _normalise_prediction(view, adapter_fn(view))
        target = case["observed_choice"]
        selected = max(probabilities, key=probabilities.get)
        target_probability = max(probabilities[target], 1e-15)
        brier = sum((probability - float(candidate_id == target)) ** 2
                    for candidate_id, probability in probabilities.items())
        rows.append({
            "case_id": case["case_id"],
            "task_type": case["task_type"],
            "selected_candidate": selected,
            "correct": selected == target,
            "target_probability": round(probabilities[target], 6),
            "brier_score": round(brier, 6),
            "log_loss": round(-math.log(target_probability), 6),
        })

    count = len(rows)
    by_task = {}
    for task_type in sorted({row["task_type"] for row in rows}):
        task_rows = [row for row in rows if row["task_type"] == task_type]
        by_task[task_type] = {
            "cases": len(task_rows),
            "top1_accuracy": round(sum(row["correct"] for row in task_rows) / len(task_rows), 6),
        }
    return {
        "benchmark": "IntentBench",
        "suite_id": suite["suite_id"],
        "dataset_kind": suite["dataset_kind"],
        "result_label": (
            "synthetic_scorer_contract_smoke"
            if suite["dataset_kind"] == "synthetic"
            else "human_evaluation_data"
        ),
        "adapter": adapter_name,
        "cases": count,
        "metrics": {
            "top1_accuracy": round(sum(row["correct"] for row in rows) / count, 6) if count else 0.0,
            "mean_brier_score": round(sum(row["brier_score"] for row in rows) / count, 6) if count else None,
            "mean_log_loss": round(sum(row["log_loss"] for row in rows) / count, 6) if count else None,
        },
        "by_task": by_task,
        "results": rows,
        "caveat": (
            "The shipped synthetic adapter replays visible fixture scores and validates only "
            "the runner/scorer contract; it does not test LIWM learning, retrieval, transfer, "
            "traceability, poisoning resistance, or human effectiveness. Output is not "
            "publication-ready without a preregistered adapter and run manifest."
        ) if suite["dataset_kind"] == "synthetic" else
                  "Human-data interpretation depends on the registered protocol and consent scope.",
    }
