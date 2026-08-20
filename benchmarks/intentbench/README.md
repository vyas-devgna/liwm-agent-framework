# IntentBench

IntentBench is LIWM's benchmark contract. Neither shipped suite is evidence
that personalization works for people, and both say so in their own output.

Every case separates `exposed_to_liwm` from `hidden_ground_truth`. An adapter
receives only the participant view: case id, task type, visible inputs, and
candidate outputs. Ground truth and `observed_choice` stay scorer-only.

## The two suites are not the same kind of thing

| Suite | Adapter | What a pass proves |
|---|---|---|
| `smoke` | reads precomputed scores out of the participant view | the runner loads cases, isolates labels, and scores probabilities |
| `mechanism` | builds a real throwaway LIWM home and asks it | the fold, provenance gate, scope lattice and tombstones behave |

The smoke suite is circular by construction. It exists so a change to the
runner cannot silently break scoring, and it tells you nothing about LIWM.

```bash
python -m liwm --json eval intentbench                                  # smoke
python -m liwm --json eval intentbench --suite mechanism --adapter liwm  # mechanism
```

## The mechanism suite

Each case declares typed evidence as a `setup` list of ordinary LIWM
operations — `observe`, `forget`, `reject` — and a working `context`. The
adapter replays them through the public API into a temporary home, resolves the
context view, and scores each candidate by the confidence of the beliefs its
`traits` match or contradict. Nothing in the participant view names the answer.

Five families, 17 cases:

- **scope_contamination** — a project preference must not answer outside its
  project, a domain preference must not cross domains, and a narrower scope
  must win inside its own.
- **poisoning_resistance** — repository content, tool output, MCP results and
  inferences laundered through `derived_from` all carry trust `0.0`; twelve
  repeated agent inferences stay under the 0.15 ceiling.
- **selective_forget** — a tombstone drops the evidence before it and nothing
  after it; a project tombstone leaves unrelated beliefs standing; a rejection
  holds against the weak signal that produced it.
- **cross_domain_transfer** — a preference learned in three domains answers in
  a fourth, and knowing one thing about someone is not knowing another.
- **preference_prediction** — with no evidence the distribution must be
  uniform. These cases are scored on departure from uniform rather than on
  top-1, because a confident guess from nothing is the failure, not the pass.

The suite has to be able to fail. `tests/test_intentbench.py` asserts that the
fixed-choice baseline scores below 0.5 on it, so a regression in any of those
mechanisms shows up as a benchmark failure rather than as a green number.

## Run manifests

Every run returns a `manifest`: suite id, dataset kind, adapter, case count,
LIWM version, code revision, Python and platform, determinism, whether hidden
labels were exposed, and the exact definition of each metric. A number without
that attached is a number with no claim attached to it.

## Conditions for a human study

Preregister these where the host supports them: base model with no memory (A),
plain Markdown memory (B), host-native memory (C), static LIWM profile (D),
LIWM with learning but elicitation disabled (E), full LIWM (F). Condition E
needs a real no-question ablation; `liwm mode off` is not equivalent, because
it also disables consultation and learning.

Human cases must be consented, minimized, reviewed before sharing, and stored
outside this repository unless explicitly approved for release.

---

[LIWM](../../README.md) · [Research protocol](../../docs/RESEARCH.md) ·
[Privacy](../../PRIVACY.md)
