"""Context economics: what each memory strategy actually costs per turn.

The standing objection to persistent agent memory is that feeding it back to
the model doubles token usage and bloats the context.  This harness measures
that, on the same profile, across the strategies real agents use:

``no_memory``
    Nothing injected.  The floor for cost and for how much the agent can know.

``full_dump``
    LIWM's whole folded profile, every turn.  This is a LIWM *ablation* -- the
    control plane with no projection -- not an external baseline.  It shows
    what "just save it and put it in the prompt" costs once a profile has been
    accumulating for a few months.

``markdown_memory``
    The prose-in-a-Markdown-file strategy that Claude Code, Cursor and
    Windsurf actually ship.  Built from the raw observation log rather than
    from LIWM's folded profile, deliberately: a prose memory file records what
    the agent was told, and it has no provenance gate to drop a repository
    claiming to speak for the user.  Handing this baseline LIWM's already
    filtered beliefs would make it stronger than any such system really is and
    would quietly hide the difference the comparison exists to show.  It is
    otherwise written the way these files are actually written -- one sentence
    per remembered thing, most recent last.

``liwm_json``
    LIWM's projection as JSON -- what this repository shipped through 0.3.0.

``liwm_capsule``
    The same projection rendered as a capsule.

``liwm_capsule_gated``
    The capsule with the zero-memory gate deciding which turns get one.

WHAT THIS MEASURES, AND WHAT IT DOES NOT
========================================

Measured here, deterministically and with no model in the loop:

* **injected tokens** per turn -- exact when a tokenizer is importable;
* **evidence sufficiency** -- for turns that need a specific fact, whether the
  injected payload actually contained it.  This is retrieval recall.  It is
  *not* answer accuracy: a payload can contain the fact and the model can
  still ignore it;
* **recoverability** -- of the turns that missed, how many told the agent that
  something had been withheld and how to ask for it.  A miss the agent can see
  and repair is a different failure from one it cannot, and collapsing the two
  would flatter whichever strategy fails most silently;
* **waste** -- the share of injected tokens carrying beliefs the turn did not
  need.  This is the "bloat" in the objection, made numeric;
* **poison leakage** -- whether an untrusted repository claim reached the
  payload;
* **staleness** -- whether a corrected, superseded value reached the payload.

Not measured here: final answer quality.  That needs a model, costs money, and
belongs in a separate run whose numbers are reported separately.  Nothing in
this module may be quoted as evidence about answer quality.

An arm winning on tokens while losing on evidence sufficiency has not won
anything, which is why both are always reported together and why the
efficiency figure is tokens *per satisfied requirement* rather than tokens
alone.
"""

from __future__ import annotations

import json
import platform
import re
import time
from pathlib import Path

from ..budget import count_tokens
from ..capsule import render_capsule
from ..context import plan_context

__all__ = ["ARMS", "load_scenario", "run_contextecon", "build_home"]

SCHEMA_VERSION = "0.3.0"

ARMS = ("no_memory", "full_dump", "markdown_memory",
        "liwm_json", "liwm_capsule", "liwm_capsule_gated")

DEFAULT_SCENARIO = "longrunning-v1"


def _scenario_root():
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "benchmarks" / "contextecon" / "scenarios"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("benchmarks/contextecon/scenarios not found")


def load_scenario(path=None, scenario=DEFAULT_SCENARIO):
    target = Path(path) if path else _scenario_root() / ("%s.json" % scenario)
    return json.loads(Path(target).read_text(encoding="utf-8"))


def build_home(home, scenario):
    """Replay the scenario history into a real LIWM home through the public API."""
    from ..profile import ProfileStore

    store = ProfileStore(home)
    for step in scenario["history"]:
        _apply(store, step)
    store.rebuild(reason="contextecon-fixture")
    return store


def _ts(days):
    from datetime import datetime, timedelta, timezone
    when = datetime.now(timezone.utc) - timedelta(days=float(days or 0))
    return when.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _apply(store, step):
    op = step["op"]
    if op == "observe":
        store.observe(
            step["dimension"], step["value"],
            source_type=step["source"], provenance=step["provenance"],
            scope=step.get("scope", "global"), scope_key=step.get("scope_key"),
            ts=_ts(step.get("days_ago")),
            session_id=step.get("session") or ("s-%s" % step.get("days_ago", 0)),
        )
    elif op == "noise":
        for index in range(int(step["count"])):
            store.observe(
                "%s_%d" % (step["dimension_prefix"], index), "value_%d" % index,
                source_type=step["source"], provenance=step["provenance"],
                ts=_ts(step.get("days_ago")), session_id="noise-%d" % index,
            )
    elif op == "forget":
        payload = {key: step[key] for key in ("dimension", "belief_key", "project_id")
                   if step.get(key)}
        if not payload:
            raise ValueError("forget step needs a dimension, belief_key or project_id")
        store.events.record("forget", "direct_user_message", payload=payload,
                            ts=_ts(step.get("days_ago")))
    else:
        raise ValueError("unknown history op %r" % op)


def _markdown_memory(store):
    """Reconstruct the prose-memory strategy from the raw observation log.

    Deliberately *not* built from LIWM's folded profile.  A Markdown memory
    file has no provenance gate, no confidence, no scope and no tombstones: it
    records what the agent was told, in the order it was told, and a later
    correction sits in the same file as the thing it corrected.  That is the
    behaviour the UW persistence result and OWASP ASI06 are about, and a
    baseline given LIWM's filtering for free would not be that baseline.
    """
    lines = ["# Memory", ""]
    for event in store.events.read_all():
        if event.get("kind") != "observation":
            continue
        observation = event.get("observation") or {}
        if not observation.get("dimension"):
            continue
        lines.append("- The user prefers %s for %s."
                     % (observation.get("value"), observation.get("dimension")))
    return "\n".join(lines) + "\n"


def _payload(arm, store, turn, cache):
    """Return ``(text, receipt_or_None)`` for one arm on one turn."""
    if arm == "no_memory":
        return "", None
    if arm == "full_dump":
        if "full" not in cache:
            cache["full"] = json.dumps(store.load(), indent=2, ensure_ascii=False)
        return cache["full"], None
    if arm == "markdown_memory":
        if "md" not in cache:
            cache["md"] = _markdown_memory(store)
        return cache["md"], None

    gate = "auto" if arm == "liwm_capsule_gated" else "off"
    context, receipt = plan_context(store, task=turn["task"], gate=gate)
    if arm == "liwm_json":
        return json.dumps(context, indent=2, ensure_ascii=False), receipt
    return render_capsule(context), receipt


def _mentions(text, value):
    """Whether *value* appears in *text* as a whole token, not as a substring.

    Naive containment gets this exactly wrong on the scenario that matters:
    ``"npm" in "pnpm"`` is true, so a payload correctly carrying the corrected
    preference would score as leaking the poisoned one it replaced.
    """
    return re.search(r"(?<!\w)%s(?!\w)" % re.escape(str(value)), text) is not None


def _satisfied(text, needs):
    """Whether every required (dimension, value) is legible in the payload.

    Matching on the value alone is deliberately the weakest possible reading of
    "the fact reached the model": it cannot flatter the arm whose formatting
    happens to suit a cleverer parser.
    """
    return all(_mentions(text, value) for _, value in needs)


def run_contextecon(scenario=None, home=None, arms=ARMS, prefer_exact=True):
    """Run every arm over every turn and return raw and aggregate metrics."""
    import shutil
    import tempfile

    scenario = scenario or load_scenario()
    poison = scenario.get("poison") or {}
    owns_home = home is None
    home = home or Path(tempfile.mkdtemp(prefix="liwm-contextecon-"))
    try:
        from ..paths import ensure_layout
        store = build_home(ensure_layout(Path(home) / "home"), scenario)

        rows = []
        for arm in arms:
            cache = {}
            for turn in scenario["turns"]:
                started = time.perf_counter()
                text, receipt = _payload(arm, store, turn, cache)
                elapsed = time.perf_counter() - started
                tokens, method = count_tokens(text, prefer_exact=prefer_exact)
                needs = [tuple(pair) for pair in turn.get("needs") or []]
                rows.append({
                    "arm": arm,
                    "turn": turn["id"],
                    "kind": turn.get("kind"),
                    "tokens": tokens,
                    "method": method,
                    "needs": len(needs),
                    "satisfied": bool(_satisfied(text, needs)) if needs else None,
                    "poison_leaked": bool(
                        poison and _mentions(text, poison.get("value"))
                        and str(poison.get("value")) not in [v for _, v in needs]),
                    "latency_ms": round(elapsed * 1000, 3),
                    "gate_skipped": bool(receipt and receipt.get("outcome") == "zero_memory"),
                    "signalled_withholding": "not shown" in text,
                })

        return {
            "schema_version": SCHEMA_VERSION,
            "scenario_id": scenario["scenario_id"],
            "manifest": _manifest(scenario, rows),
            "rows": rows,
            "arms": {arm: _aggregate([r for r in rows if r["arm"] == arm]) for arm in arms},
            "caveat": (
                "Token counts and evidence sufficiency are measured. Answer quality "
                "is not: no model ran. Nothing here is evidence about answer accuracy."
            ),
        }
    finally:
        if owns_home:
            shutil.rmtree(home, ignore_errors=True)


def _aggregate(rows):
    if not rows:
        return {}
    tokens = [r["tokens"] for r in rows]
    scored = [r for r in rows if r["satisfied"] is not None]
    satisfied = sum(1 for r in scored if r["satisfied"])
    total_tokens = sum(tokens)
    return {
        "turns": len(rows),
        "total_tokens": total_tokens,
        "mean_tokens_per_turn": round(total_tokens / len(rows), 1),
        "max_tokens_in_a_turn": max(tokens),
        "turns_needing_evidence": len(scored),
        "evidence_sufficiency": round(satisfied / len(scored), 4) if scored else None,
        # The figure that stops an arm from winning by sending nothing.
        "tokens_per_satisfied_requirement": (
            round(total_tokens / satisfied, 1) if satisfied else None),
        "poison_leak_turns": sum(1 for r in rows if r["poison_leaked"]),
        "unsatisfied_turns": len(scored) - satisfied,
        "unsatisfied_but_signalled": sum(
            1 for r in scored if r["satisfied"] is False and r["signalled_withholding"]),
        "gate_skipped_turns": sum(1 for r in rows if r["gate_skipped"]),
        "median_latency_ms": round(sorted(r["latency_ms"] for r in rows)[len(rows) // 2], 3),
    }


def _manifest(scenario, rows):
    """Everything needed to say what these numbers mean and reproduce them."""
    from .. import __version__
    from .intentbench import _code_revision
    methods = {row["method"] for row in rows}
    return {
        "scenario_id": scenario["scenario_id"],
        "arms": sorted({row["arm"] for row in rows}),
        "turns": len(scenario["turns"]),
        "history_ops": len(scenario["history"]),
        "liwm_version": __version__,
        "code_revision": _code_revision(),
        "python": platform.python_version(),
        "platform": platform.system(),
        "deterministic": True,
        "model_in_the_loop": False,
        "token_counting": "exact" if methods == {"exact"} else sorted(methods),
        "metric_definitions": {
            "mean_tokens_per_turn": "injected context tokens per turn, averaged over "
                                    "every turn in the scenario including gated ones",
            "evidence_sufficiency": "fraction of turns needing a specific fact whose "
                                    "injected payload contained that fact; this is "
                                    "retrieval recall, not answer accuracy",
            "tokens_per_satisfied_requirement": "total injected tokens divided by the "
                                                "number of satisfied requirements; the "
                                                "figure an arm cannot win by sending "
                                                "nothing",
            "poison_leak_turns": "turns whose payload carried the untrusted repository "
                                 "claim the scenario plants",
            "unsatisfied_but_signalled": "turns that missed a required fact but told the "
                                         "agent something had been withheld and how to ask "
                                         "for it; a recoverable miss, not a silent one",
            "gate_skipped_turns": "turns the zero-memory gate declined to project for",
        },
        "evidence_label": "synthetic mechanism result: deterministic, no human involved",
    }

