"""Does the projection contain the preference the task actually needs?

Context economics answers what a strategy costs. This answers what it buys.
The two have to be read together, because an arm can always get cheaper by
retrieving less and the only thing stopping that is a measurement of what got
dropped.

THE SETUP
=========

One profile holds a belief on every dimension in the taxonomy, plus forty
undifferentiated `preferences.legacy_choice_*` entries standing in for the
history any long-running profile accumulates. Each case is a request phrased
the way a user would phrase it, turning on exactly one of those beliefs.

Confidence is assigned to the real beliefs pseudo-randomly from a fixed seed,
so it carries **no signal** about whether a given belief is the one this task
needs. A ranker cannot score well here by preferring confident beliefs; it has
to know what the request is about. That is the whole point, and it is why the
confidence-ordered baseline scores where it does.

Cases never name their own dimension or its value. A case whose wording
contains its answer would measure string matching.

DEV AND HOLDOUT
===============

Cases split deterministically by the hash of their id, not by any property
anyone chose. Development reads `dev`. `holdout` is reported once, at the end,
and a ranker tuned against it has stopped being evidence.

METRICS
=======

``recall``
    Share of cases whose required dimension appeared in the projection. The
    headline number.
``precision``
    Required dimensions as a share of everything projected. Low precision is
    wasted tokens, not a wrong answer.
``mrr``
    Mean reciprocal rank of the required belief within the projection, so a
    ranker that includes the right thing fourteenth is distinguishable from one
    that leads with it.
``tokens``
    Mean capsule tokens per case. Recall bought by projecting everything is not
    a result.
"""

from __future__ import annotations

import hashlib
import json
import platform
import random
import statistics
from pathlib import Path

from ..budget import count_tokens
from ..capsule import render_capsule
from ..context import plan_context

__all__ = ["load_suite", "run_retrieval", "build_home", "SPLITS", "wilson_interval"]

SCHEMA_VERSION = "0.4.0"

SPLITS = ("dev", "holdout")

#: Share of cases assigned to development. The rest are the holdout.
DEV_SHARE = 60

#: Fixed, so a profile is the same profile on every run and on every machine.
PROFILE_SEED = 20260821

#: Real source types, spread across the trusted range. The first draft of this
#: fixture used two names that do not exist; LIWM valued them at the guess
#: ceiling and twenty of the forty-seven targets fell below the eligibility
#: floor before any ranker saw them. That is now a quarantine with a reason
#: rather than a silent downgrade -- see events.py -- and the point stands
#: either way: these have to be real.
_SOURCES = ("explicit_statement", "explicit_correction", "repeated_behavioral",
            "comparative_choice", "repeated_selection")


def _suite_root():
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "benchmarks" / "retrieval" / "cases"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("benchmarks/retrieval/cases not found")


def split_of(case_id):
    """Deterministic dev/holdout assignment from the case id alone."""
    digest = hashlib.sha256(case_id.encode("utf-8")).hexdigest()
    return "dev" if int(digest[:8], 16) % 100 < DEV_SHARE else "holdout"


def load_suite(path=None, suite="retrieval-v1"):
    target = Path(path) if path else _suite_root() / ("%s.json" % suite)
    raw = Path(target).read_bytes()
    data = json.loads(raw.decode("utf-8"))
    cases = []
    for dimension, tasks in sorted(data["tasks"].items()):
        for index, task in enumerate(tasks):
            case_id = "%s#%d" % (dimension, index)
            cases.append({"id": case_id, "task": task, "requires": dimension,
                          "split": split_of(case_id)})
    data["cases"] = cases
    data["content_sha256"] = hashlib.sha256(raw).hexdigest()
    return data


def build_home(home, suite):
    """One profile holding a belief on every dimension, plus accumulated noise."""
    from ..profile import ProfileStore
    from ..taxonomy import DIMENSION_INDEX

    store = ProfileStore(home)
    rng = random.Random(PROFILE_SEED)
    for dimension, meta in sorted(DIMENSION_INDEX.items()):
        values = meta.get("values") or ()
        value = values[rng.randrange(len(values))] if values else "recorded_preference"
        store.observe(dimension, value,
                      source_type=_SOURCES[rng.randrange(len(_SOURCES))],
                      provenance="direct_user_message",
                      session_id="s%d" % rng.randrange(1000))
    spec = suite["profile"]
    for index in range(int(spec["noise_beliefs"])):
        store.observe("%s_%d" % (spec["noise_prefix"], index), "value_%d" % index,
                      source_type=spec["noise_source"], provenance="direct_user_message",
                      session_id="noise-%d" % index)
    store.rebuild(reason="retrieval-fixture")
    return store


def wilson_interval(successes, total, z=1.96):
    """95% Wilson score interval. Normal approximation lies near 0 and 1."""
    if not total:
        return (None, None)
    phat = successes / total
    denominator = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denominator
    margin = (z / denominator) * ((phat * (1 - phat) / total
                                   + z * z / (4 * total * total)) ** 0.5)
    return (round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4))


def run_retrieval(suite=None, home=None, splits=SPLITS, **context_kwargs):
    """Score the projection's required-fact recall over the suite."""
    import shutil
    import tempfile

    suite = suite or load_suite()
    owns_home = home is None
    home = home or Path(tempfile.mkdtemp(prefix="liwm-retrieval-"))
    try:
        from ..paths import ensure_layout
        store = build_home(ensure_layout(Path(home) / "home"), suite)

        rows = []
        for case in suite["cases"]:
            if case["split"] not in splits:
                continue
            context, receipt = plan_context(store, task=case["task"], **context_kwargs)
            applied = [item["dimension"] for item in context.get("applies") or []]
            rank = applied.index(case["requires"]) + 1 if case["requires"] in applied else None
            tokens, method = count_tokens(render_capsule(context))
            rows.append({
                "id": case["id"],
                "split": case["split"],
                "task": case["task"],
                "requires": case["requires"],
                "found": rank is not None,
                "rank": rank,
                "projected": len(applied),
                "tokens": tokens,
                "method": method,
                "gate_skipped": receipt.get("outcome") == "zero_memory",
            })
        return {
            "schema_version": SCHEMA_VERSION,
            "suite_id": suite["suite_id"],
            "manifest": _manifest(suite, rows, context_kwargs),
            "rows": rows,
            "splits": {name: _aggregate([r for r in rows if r["split"] == name])
                       for name in splits},
            "overall": _aggregate(rows),
        }
    finally:
        if owns_home:
            shutil.rmtree(home, ignore_errors=True)


def _aggregate(rows):
    if not rows:
        return {}
    found = [r for r in rows if r["found"]]
    ranks = [r["rank"] for r in found]
    projected = sum(r["projected"] for r in rows)
    return {
        "cases": len(rows),
        "recall": round(len(found) / len(rows), 4),
        "recall_ci95": wilson_interval(len(found), len(rows)),
        "precision": round(len(found) / projected, 4) if projected else None,
        "mrr": round(sum(1.0 / rank for rank in ranks) / len(rows), 4) if rows else None,
        "mean_rank_when_found": round(statistics.fmean(ranks), 2) if ranks else None,
        "mean_tokens": round(statistics.fmean(r["tokens"] for r in rows), 1),
        "mean_projected": round(statistics.fmean(r["projected"] for r in rows), 2),
        "gate_skipped": sum(1 for r in rows if r["gate_skipped"]),
    }


def _manifest(suite, rows, context_kwargs):
    from .. import __version__
    from .intentbench import _code_revision
    methods = {row["method"] for row in rows}
    return {
        "suite_id": suite["suite_id"],
        "content_sha256": suite["content_sha256"],
        "cases_scored": len(rows),
        "cases_total": len(suite["cases"]),
        "dev_share_percent": DEV_SHARE,
        "profile_seed": PROFILE_SEED,
        "context_kwargs": {k: v for k, v in sorted(context_kwargs.items())},
        "liwm_version": __version__,
        "code_revision": _code_revision(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "deterministic": True,
        "model_in_the_loop": False,
        "token_counting": "exact" if methods == {"exact"} else sorted(methods),
        "metric_definitions": {
            "recall": "share of cases whose required dimension appeared in the "
                      "projection; this is retrieval recall, not answer accuracy",
            "precision": "required dimensions as a share of all projected beliefs",
            "mrr": "mean reciprocal rank of the required belief in the projection",
            "recall_ci95": "Wilson score interval, which unlike the normal "
                           "approximation stays inside [0,1] near the extremes",
        },
        "evidence_label": "synthetic mechanism result: deterministic, no human involved",
    }
