# Research and evaluation protocol

LIWM's mechanism is tested; its human-effectiveness hypothesis is not. Current
numbers come from deterministic fixtures, replay estimates, or agent-recorded
outcomes. None establishes that LIWM improves work with real people.

## Status and claim boundary

| Evidence | Current status | What it supports |
|---|---|---|
| Unit and adversarial tests | implemented | documented behavior within the threat model |
| `liwm eval modes` and `converge` | synthetic mechanism checks | planner distinction and a closed learning loop |
| `liwm eval intentbench` | synthetic scorer-contract smoke | adapter isolation and probability-scoring plumbing only |
| Counterfactual replay | modelled estimate | whether a policy merits prospective testing |
| Resolved predictions | agent-recorded outcomes | calibration only to the extent labels are valid |
| Controlled human study | not yet run | prospective preference, burden, and transfer effects |

Every published number must carry its evidence label. Synthetic and replay
results must never be presented as observed human effectiveness.

## Hypotheses

- **H1 — intent fit:** full LIWM improves blinded intent-fidelity and paired
  preference over the preregistered comparator.
- **H2 — question economy:** that gain holds while correction burden and
  questions per task do not increase.
- **H3 — transfer:** a profile learned in domains A/B/C predicts choices and
  improves intent fidelity in held-out domain D before D-specific elicitation.
- **H4 — calibration:** committed preference probabilities become better
  calibrated as independently labelled outcomes accumulate.

H1 alone does not distinguish LIWM from simpler memory. Negative and null
results are valid outcomes and should lead to removal or simplification of
unsupported machinery.

## Conditions

Where host capabilities permit, compare:

| | Condition |
|---|---|
| A | base agent, memory disabled |
| B | free-form Markdown memory |
| C | host-native memory |
| D | static LIWM profile, no learning |
| E | LIWM profile and learning with elicitation disabled |
| F | full LIWM |

Condition E needs a real no-question ablation. `liwm mode off` is not that
ablation because OFF also disables profile consultation and learning. If the
host has no native memory, mark C unavailable rather than substituting it after
seeing results.

## Operational definitions

- **Intent fidelity:** blinded rubric score against preregistered hidden
  requirements and anti-goals, separate from style preference.
- **Preference prediction:** probability assigned before output exposure to the
  candidate later chosen; report top-1 accuracy, Brier score, and log loss.
- **First-pass acceptance:** binary approval/use without substantive revision.
- **Correction burden:** correction turns, with edit distance or elapsed time as
  separately defined secondary measures.
- **Question efficiency:** outcome and question count reported together; fewer
  questions with worse outcomes is not improvement.
- **Assumption error:** a consequential recorded assumption later explicitly
  corrected or shown false by registered ground truth.
- **Cross-domain transfer:** held-out-domain gain measured before any
  domain-specific question or observation.
- **Calibration:** reliability bins/ECE plus Brier and log loss for binary or
  categorical probabilistic targets. Continuous acceptance uses MSE/MAE, not a
  Brier label.
- **Technical correctness:** independent executable test or blinded rubric.
- **Satisfaction:** secondary post-task rating, never a synonym for acceptance,
  correctness, or intent fidelity.

Current `liwm stats` exposes metrics such as `rates.first_pass_acceptance`,
`rates.explicit_correction_rate`, `rates.assumption_error_rate`,
`rates.questions_per_accepted_outcome`, and calibration squared error/bias/bins.
It does not yet compute technical correctness, intent fidelity, log loss, ECE,
or every construct above. A study must compute missing registered outcomes in
its analysis rather than claiming they came from `liwm stats`.

## IntentBench

The case contract is in
[`schemas/intentbench-case.schema.json`](../schemas/intentbench-case.schema.json)
and the protocol in
[`benchmarks/intentbench/README.md`](../benchmarks/intentbench/README.md).
Ground truth is stored separately from `exposed_to_liwm`; the runner passes only
the participant view to adapters.

```bash
liwm eval intentbench --json
liwm eval intentbench --adapter static-first --json
```

The shipped cases are `synthetic_scorer_contract_smoke`. Their default adapter
replays participant-visible fixture scores, so they validate only case loading,
adapter isolation, and probability scoring. They do not exercise LIWM learning,
held-out transfer, question selection, traceability, scope filtering, or
poisoning resistance and are not publication-ready results.

A benchmark run manifest should record dataset kind, seed, code revision,
host/model/version, adapter, timestamp, and exact metric definitions. For
held-out transfer, learn only from A/B/C, commit D-domain probabilities before
any D-specific elicitation, then compare conditions on the same D tasks.

## Within-subject experiment

Use a randomized, counterbalanced crossover when short-term paired comparisons
are the target:

1. preregister F-versus-D in held-out domain D as the primary contrast;
2. randomize condition and task order, using an incomplete block or Latin square
   if six conditions create excessive burden;
3. isolate condition state with separate LIWM homes and no cross-condition imports;
4. collect probabilities before showing outputs;
5. present paired outputs under concealed condition labels;
6. use independent blinded assessment for intent fidelity and correctness;
7. model participant and task as random effects.

Report paired effect size and 95% confidence interval. Treat the six-condition
omnibus analysis and additional pairwise contrasts as secondary.

## Longitudinal experiment

Learning and transfer require a separate longitudinal protocol. Use parallel or
staggered randomized groups over a preregistered period (for example 6–8 weeks)
so treatment profiles do not carry into control conditions. Assign held-out
domain D before collection and prohibit D-specific learning before its transfer
measurement. Record repeated tasks, corrections, questions, committed
predictions, unresolved predictions, attrition, and environment failures.

Estimate power by simulation under the intended mixed logistic/ordinal model,
using a minimum important effect, expected participant/task variation, ICC, and
attrition. Fix sample size and stopping before collection; do not stop after an
encouraging interim result.

## Analysis registration

Before collection, register:

- hypotheses and one primary outcome/contrast;
- primary model formula, effect-size scale, and 95% interval;
- task and participant eligibility;
- outcome-blind exclusion rules and adjudication;
- randomization and counterbalancing procedure/seed;
- missing-data handling and intention-to-treat analysis;
- sensitivity analysis for attrition/missingness;
- Holm correction for the secondary comparison family;
- fixed stopping rule and any allowed interim safety review.

Do not choose the primary outcome after inspecting results. Report unresolved
predictions and label evaluator provenance so selective outcome resolution is
visible.

## Study mode and consent

Study mode is opt-in, local-only, and derived from the existing event log:

```bash
liwm study status
liwm study on
liwm study export --anonymise --out <path>
liwm study off
```

It creates no second telemetry log and performs no upload. Export includes only
event metadata and allowlisted numeric/boolean measurements within the configured
retention window. Anonymisation replaces identifiers and coarsens timestamps,
but unique patterns may remain linkable or identifying. Inspect every export
before sharing.

Consent must name the local fields collected, retention period, host/provider
data path, export procedure, intended analyses, right to inspect/correct, and
right to withdraw and delete. Withdrawing or deleting data must not be treated
as misconduct or silently converted into an outcome-dependent exclusion. Never
commit raw participant exports to this repository.

## Interpreting existing outputs

- `liwm eval modes` checks deterministic mode policy differences.
- `liwm eval converge` checks that recoverable synthetic preferences are
  recovered and questions can fall. Its acceptance series is synthetic observed
  acceptance, not a committed preference prediction.
- Replay applies an explicit acceptance model to historical episodes. Its
  counterfactual outcomes are estimates, not observations.
- A resolved outcome may have been entered by an agent. Until evaluator type and
  candidate/run linkage are recorded, describe it as agent-recorded rather than
  independently observed.

Only a prospective, controlled, preregistered study supports a causal human-
effectiveness claim.

## Threats to validity

- **Simulator affinity:** the fixtures and fold share authorship and assumptions.
- **Evaluator dependence:** agent-entered labels are not independent evidence.
- **Provenance oracle:** LIWM cannot prove a host labelled evidence truthfully.
- **Carryover:** shared profiles invalidate crossover comparisons.
- **Novelty and demand effects:** longitudinal collection and blinding reduce but
  do not eliminate them.
- **Multiplicity and attrition:** unregistered choices can manufacture a result.

---

[LIWM](../README.md) · [IntentBench](../benchmarks/intentbench/README.md) ·
[Host acceptance](HOST_ACCEPTANCE.md) · [Privacy](../PRIVACY.md) ·
[Threat model](../THREAT_MODEL.md)
