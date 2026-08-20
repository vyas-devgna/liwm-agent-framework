#!/usr/bin/env python3
"""Local release benchmark for event-log scale; fixture creation is not timed."""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path

from liwm.compaction import compact
from liwm.context import build_runtime_context
from liwm.events import make_event
from liwm.jsonio import canonical_json, sha256_of
from liwm.profile import ProfileStore
from liwm.traceability import explain_belief


def _timed(call, repeats=1):
    values = []
    result = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = call()
        values.append(time.perf_counter() - started)
    return round(statistics.median(values), 6), result


def _fixture(home, count):
    store = ProfileStore(home)
    shard = Path(home) / "events" / "2026-01"
    shard.mkdir(parents=True, exist_ok=True)
    chain = None
    recent = []
    for sequence in range(1, count + 1):
        event = make_event(
            "observation", "agent_inference", ts="2026-01-01T00:00:00Z",
            session_id="bench-%d" % sequence,
            observation={
                "dimension": "working_style.iteration_style", "value": "iterative",
                "source_type": "single_behavioral", "polarity": "support",
                "scope": "global", "decay_policy": "standard",
            },
        )
        event["sequence"] = sequence
        event["integrity"] = {
            "algo": "sha256",
            "hash": sha256_of({key: value for key, value in event.items() if key != "integrity"}),
        }
        (shard / ("%09d-%s.json" % (sequence, event["event_id"]))).write_text(
            canonical_json(event), encoding="utf-8"
        )
        chain = store.events._chain_step(
            chain, sequence, event["event_id"], event["integrity"]["hash"]
        )
        recent.append(event["event_id"])
    store.events._write_manifest({
        "base_sequence": 0, "event_count": count, "last_sequence": count,
        "chain_head": chain, "recent_event_ids": recent[-256:],
    })
    return store


def run(count):
    with tempfile.TemporaryDirectory(prefix="liwm-bench-") as home:
        store = _fixture(home, count)
        fold_s, profile = _timed(store.fold)
        store.save(profile)
        cold_s, _ = _timed(
            lambda: build_runtime_context(ProfileStore(home), task="iterative implementation")
        )
        warm_s, _ = _timed(
            lambda: build_runtime_context(store, task="iterative implementation"), repeats=3
        )
        verify_s, report = _timed(store.events.verify)
        if not report["ok"]:
            raise RuntimeError(report)
        belief_id = profile["beliefs"][0]["id"]
        explain_s, _ = _timed(lambda: explain_belief(store, belief_id=belief_id))
        compact_s, result = _timed(lambda: compact(store))
        return {
            "events": count, "materialize_s": fold_s, "verify_s": verify_s,
            "context_cold_s": cold_s, "context_warm_median_s": warm_s,
            "explain_s": explain_s, "compact_s": compact_s,
            "archive_retained": result["raw_history_retained"],
        }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1_000, 10_000, 100_000])
    args = parser.parse_args(argv)
    print(json.dumps([run(size) for size in args.sizes], indent=2))


if __name__ == "__main__":
    main()
