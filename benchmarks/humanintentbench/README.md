# HumanIntentBench

Schemas and tooling. **No data.**

There are no participants here, and there will be none until a consented study
produces some. A benchmark with invented humans in it is worse than no
benchmark, because it looks like evidence.

## What belongs here, when it exists

A case is one task where a real person had a preference LIWM did not already
know, and the record separates five things that must never be mixed:

| Layer | Who sees it |
|---|---|
| participant-visible task | the participant |
| LIWM-visible history | the adapter under test |
| hidden requirements and anti-goals | the scorer, after the prediction |
| candidate artifacts | both, without labels |
| human preference and outcome labels | the scorer only |
| independent evaluator labels | the scorer only |

Cases use [`intentbench-case.schema.json`](../../schemas/intentbench-case.schema.json)
with `dataset_kind: "human_anonymised"`. At that setting the loader refuses any
case whose participant view or candidate metadata contains its own answer — for
synthetic cases the check is skipped, because the smoke suite is deliberately
circular and labelled as such.

## Before collecting anything

1. Preregister the analysis. `docs/RESEARCH.md` lists what has to be fixed in
   advance, including the primary outcome and the stopping rule.
2. Take consent covering the fields collected, the retention period, the export
   procedure, the intended analyses, and the right to withdraw and delete.
   `CONSENT_TEMPLATE.md` is a starting point, not legal advice, and not an
   ethics approval.
3. Decide the held-out domain D *before* collection, and prohibit D-specific
   learning before its transfer measurement.
4. Use `liwm study export --anonymise --longitudinal`, and read the export
   before it goes anywhere.

## Before publishing anything

- Fill in `DATASET_CARD_TEMPLATE.md`. A dataset with no card is a dataset
  nobody can evaluate.
- Report unresolved predictions and evaluator provenance. Resolving only the
  favourable predictions biases every figure downstream, and the only defence
  is making the unresolved ones visible.
- Never commit raw participant exports to this repository. Anonymisation is
  risk reduction; it is not a guarantee, and a small study is small enough to
  re-identify from working patterns alone.

---

[IntentBench](../intentbench/README.md) · [Research protocol](../../docs/RESEARCH.md) ·
[Privacy](../../PRIVACY.md)
