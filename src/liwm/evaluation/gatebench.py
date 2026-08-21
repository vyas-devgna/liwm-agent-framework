"""Should this request read the profile at all, and how wrong does it get it?

The zero-memory gate saves the most tokens of anything in LIWM, and it is the
component whose errors are hardest to notice. A request wrongly sent without
memory still produces an answer -- a slightly worse one, for reasons nothing in
the transcript records. A request wrongly sent with memory costs a few hundred
tokens that appear in the receipt.

So accuracy is the wrong headline. This reports both error rates separately and
a weighted loss that prices a false skip at ten times a false retrieve. A gate
tuned to maximise token savings would score well on accuracy and badly here,
which is the point.
"""

from __future__ import annotations

import json
import platform
from pathlib import Path

from ..gate import gate_decision

__all__ = ["load_suite", "run_gatebench"]

SCHEMA_VERSION = "0.4.0"


def _suite_root():
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "benchmarks" / "gate" / "cases"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("benchmarks/gate/cases not found")


def load_suite(path=None, suite="gate-v1"):
    target = Path(path) if path else _suite_root() / ("%s.json" % suite)
    return json.loads(Path(target).read_text(encoding="utf-8"))


def run_gatebench(suite=None):
    suite = suite or load_suite()
    weights = suite["loss"]
    rows = []
    for case in suite["cases"]:
        decision = gate_decision(case["task"])
        predicted = decision["needs_memory"]
        expected = bool(case["needs_memory"])
        rows.append({
            "task": case["task"],
            "family": case["family"],
            "expected": expected,
            "predicted": predicted,
            "correct": predicted == expected,
            # The dangerous error: memory was needed and the gate said no.
            "false_skip": expected and not predicted,
            "false_retrieve": (not expected) and predicted,
            "reason": decision["reason"],
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "suite_id": suite["suite_id"],
        "manifest": _manifest(suite, rows),
        "rows": rows,
        "overall": _aggregate(rows, weights),
        "families": {family: _aggregate([r for r in rows if r["family"] == family],
                                        weights)
                     for family in sorted({r["family"] for r in rows})},
    }


def _aggregate(rows, weights):
    if not rows:
        return {}
    from .retrieval import wilson_interval
    needed = [r for r in rows if r["expected"]]
    not_needed = [r for r in rows if not r["expected"]]
    false_skips = sum(1 for r in rows if r["false_skip"])
    false_retrieves = sum(1 for r in rows if r["false_retrieve"])
    correct = sum(1 for r in rows if r["correct"])
    loss = (false_skips * float(weights["false_skip_weight"])
            + false_retrieves * float(weights["false_retrieve_weight"]))
    return {
        "cases": len(rows),
        "accuracy": round(correct / len(rows), 4),
        "accuracy_ci95": wilson_interval(correct, len(rows)),
        "false_skips": false_skips,
        "false_skip_rate": round(false_skips / len(needed), 4) if needed else None,
        "false_skip_rate_ci95": wilson_interval(false_skips, len(needed)) if needed
        else (None, None),
        "false_retrieves": false_retrieves,
        "false_retrieve_rate": (round(false_retrieves / len(not_needed), 4)
                                if not_needed else None),
        "weighted_loss": round(loss, 2),
        "weighted_loss_per_case": round(loss / len(rows), 4),
        "failing": [{"task": r["task"], "kind": "false_skip" if r["false_skip"]
                     else "false_retrieve", "reason": r["reason"]}
                    for r in rows if not r["correct"]],
    }


def _manifest(suite, rows):
    from .. import __version__
    from .intentbench import _code_revision
    return {
        "suite_id": suite["suite_id"],
        "cases": len(rows),
        "loss_weights": suite["loss"],
        "liwm_version": __version__,
        "code_revision": _code_revision(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "deterministic": True,
        "model_in_the_loop": False,
        "metric_definitions": {
            "false_skip_rate": "share of requests that needed memory and were sent "
                               "without it; the error the user cannot see",
            "false_retrieve_rate": "share of self-contained requests that read the "
                                   "profile anyway; costs tokens, visible in the receipt",
            "weighted_loss": "false_skips x %.0f + false_retrieves x %.0f"
                             % (suite["loss"]["false_skip_weight"],
                                suite["loss"]["false_retrieve_weight"]),
        },
        "evidence_label": "synthetic mechanism result: deterministic, no human involved",
    }
