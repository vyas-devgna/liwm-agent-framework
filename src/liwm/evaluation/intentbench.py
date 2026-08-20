"""IntentBench: adapters answer, the scorer holds the labels.

Cases keep participant-visible inputs separate from scorer-only ground truth,
and adapters receive a deep copy of :func:`participant_view`, never the source
case.  Two very different things live behind that one contract:

* the **scorer-contract smoke** suite, whose adapter reads precomputed scores
  out of the participant view.  It is circular by construction and exists to
  test loading, isolation and probability scoring.  It says nothing about LIWM.
* the **mechanism** suite, whose adapter builds a real, throwaway LIWM home
  from the case's typed evidence and asks the actual fold, provenance gate,
  scope lattice and tombstone logic what they conclude.  A case passes only if
  those mechanisms behave, so a regression in any of them shows up as a
  benchmark failure rather than as a green number.

Neither is human evidence.  Both are deterministic, and the mechanism suite at
least measures the thing whose name is on the box.
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


SUITES = {"smoke": "synthetic-smoke.json", "mechanism": "mechanism-v1.json"}

#: How far a distribution may drift from uniform and still count as "no
#: opinion".  Tight, because the whole point of the case is that a system with
#: no evidence should not be producing a preference.
UNIFORM_TOLERANCE = 0.02


def default_suite_path(suite="smoke"):
    """Locate a shipped suite by name, in the repo or in an installed share/."""
    relative = Path("benchmarks") / "intentbench" / "cases" / SUITES[suite]
    candidates = [Path(__file__).resolve().parents[3] / relative,
                  Path(sys.prefix) / "share" / "liwm" / relative]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def load_suite(path=None, suite="smoke"):
    target = Path(path) if path else default_suite_path(suite)
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


def _liwm(view):
    """Answer from a real LIWM home built out of the case's own evidence.

    Every operation in ``setup`` goes through the ordinary public API, so the
    provenance gate, the scope lattice, decay and the forget tombstones all run
    for real.  Nothing in the participant view names the right answer.
    """
    import tempfile
    import shutil
    from ..paths import ensure_layout
    from ..profile import ProfileStore

    root = tempfile.mkdtemp(prefix="intentbench-")
    try:
        store = ProfileStore(ensure_layout(Path(root) / "home"))
        store.rebuild(reason="intentbench")
        for step in view["exposed_to_liwm"].get("setup") or []:
            _apply_setup(store, step)
        context = view["exposed_to_liwm"].get("context") or {}
        resolved = store.context_view(domain=context.get("domain"),
                                      project_id=context.get("project_id"),
                                      min_confidence=0.0)
        return {"probabilities": _score_candidates(view["candidate_outputs"], resolved)}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _apply_setup(store, step):
    op = step.get("op")
    if op == "observe":
        store.observe(
            step["dimension"], step["value"],
            source_type=step.get("source_type", "explicit_statement"),
            provenance=step.get("provenance", "direct_user_message"),
            scope=step.get("scope", "global"), scope_key=step.get("scope_key"),
            session_id=step.get("session_id"), project_id=step.get("project_id"),
            domain=step.get("domain"), derived_from=step.get("derived_from"),
        )
    elif op == "forget":
        store.forget(dimension=step.get("dimension"),
                     belief_key_=step.get("belief_key"),
                     project_id=step.get("project_id"))
    elif op == "reject":
        store.reject(step["dimension"], value=step.get("value"),
                     scope=step.get("scope", "global"), scope_key=step.get("scope_key"))
    else:
        raise ValueError("unknown IntentBench setup op %r" % op)


def _score_candidates(candidates, resolved):
    """Confidence for the traits a candidate has, against those it contradicts.

    A candidate whose traits LIWM believes scores its confidence; one whose
    traits contradict a held belief is penalised by that confidence.  With no
    belief either way every candidate scores zero and the result is a uniform
    distribution, which is the correct answer to "you have no idea".
    """
    scores = {}
    for candidate in candidates:
        total = 0.0
        for dimension, value in (candidate.get("traits") or {}).items():
            belief = resolved.get(dimension)
            if belief is None:
                continue
            confidence = float(belief.get("confidence", 0.0))
            total += confidence if str(belief.get("value")) == str(value) else -confidence
        scores[candidate["id"]] = total
    shifted = {key: math.exp(2.5 * value) for key, value in scores.items()}
    total = sum(shifted.values())
    return {key: value / total for key, value in shifted.items()}


BUILTIN_ADAPTERS = {"static-first": _static_first,
                    "liwm-projection": _liwm_projection,
                    "liwm": _liwm}


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


def _code_revision():
    """The commit this ran against, when there is one to name."""
    import subprocess
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(Path(__file__).resolve().parents[3]),
            capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _manifest(suite, adapter_name, count):
    """Everything needed to say what a number means and reproduce it.

    A benchmark result without its suite, adapter, code revision and metric
    definitions is a number without a claim attached to it.
    """
    from .. import __version__
    import platform
    return {
        "suite_id": suite["suite_id"],
        "dataset_kind": suite["dataset_kind"],
        "adapter": adapter_name,
        "cases": count,
        "liwm_version": __version__,
        "code_revision": _code_revision(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "seed": None,
        "deterministic": True,
        "hidden_labels_exposed": False,
        "metric_definitions": {
            "top1_accuracy": "fraction of cases whose argmax is the observed choice, "
                             "or whose distribution is uniform where the case asserts "
                             "no opinion",
            "mean_brier_score": "mean over cases of the multiclass Brier score against "
                                "a one-hot observed choice",
            "mean_log_loss": "mean over cases of -ln P(observed choice)",
            "uniform_tolerance": UNIFORM_TOLERANCE,
        },
        "evidence_label": (
            "synthetic mechanism result: deterministic, no human involved"
            if suite["dataset_kind"] == "synthetic" else "human_anonymised"),
    }


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
        # Some cases assert the absence of an opinion.  Scoring those on top-1
        # is meaningless -- a uniform distribution has an arbitrary argmax --
        # and rewarding a confident guess is the overconfidence the case exists
        # to catch.  They are scored on departure from uniform instead.
        uniform = case["hidden_ground_truth"].get("expected_uniform", False)
        even = 1.0 / len(probabilities)
        deviation = max(abs(value - even) for value in probabilities.values())
        rows.append({
            "case_id": case["case_id"],
            "task_type": case["task_type"],
            "scored_as": "uniformity" if uniform else "top1",
            "selected_candidate": selected,
            "correct": deviation <= UNIFORM_TOLERANCE if uniform else selected == target,
            "max_deviation_from_uniform": round(deviation, 6),
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
        "manifest": _manifest(suite, adapter_name, count),
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
