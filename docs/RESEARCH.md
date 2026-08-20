# Research and evaluation protocol

LIWM's mechanism is tested; its human-effectiveness hypothesis is not. Current
numbers come from deterministic fixtures, replay estimates, or agent-recorded
outcomes. None establishes that LIWM improves work with real people.

## Status and claim boundary

| Evidence | Current status | What it supports |
|---|---|---|
| Unit, property and adversarial tests | implemented | documented behavior within the threat model |
| `liwm eval modes` and `converge` | synthetic mechanism checks | planner distinction and a closed learning loop |
| `liwm eval intentbench --suite smoke` | synthetic scorer-contract smoke | runner and probability-scoring plumbing only |
| `liwm eval intentbench --suite mechanism` | synthetic mechanism result | scope isolation, poisoning resistance, forgetting, transfer and calibration behave as specified |
| Counterfactual replay | modelled estimate | whether a policy merits prospective testing |
| Shadow evaluation | modelled estimate | what a candidate would have done; no human was exposed |
| Outcomes without `outcome_binding` | agent-recorded, unverified | nothing independent; retained for audit only |
| Outcomes with `outcome_binding` | evidence-bound human outcome | calibration, and promotion when the user was exposed to the candidate |
| Controlled human study | **not yet run** | prospective preference, burden, and transfer effects |

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

Condition E is `liwm mode silent`: profile consultation and learning stay on,
elicitation is off. `liwm mode off` is not that ablation, because OFF disables
all three and would attribute the effect of three changes to elicitation alone.
If the host has no native memory, mark C unavailable rather than substituting
it after seeing results.

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

The `smoke` suite is `synthetic_scorer_contract_smoke`: its adapter replays
participant-visible fixture scores, so it validates case loading, adapter
isolation and probability scoring and nothing else.

The `mechanism` suite runs a real, throwaway LIWM home built from each case's
typed evidence, so the fold, provenance gate, scope lattice and tombstone logic
answer for themselves. Seventeen cases across five families. Real LIWM passes
all seventeen; the fixed-choice baseline scores 0.29 with a log loss of 22.3,
and a test asserts that gap so the suite cannot degrade into one every adapter
passes. Cases asserting the absence of an opinion are scored on departure from
uniform rather than on top-1, because a confident guess from no evidence is the
failure the case exists to catch.

Neither suite is human evidence. A mechanism pass says LIWM does what it says
it does, not that doing so helps anyone.

Every run returns a manifest recording suite, dataset kind, adapter, case
count, LIWM version, code revision, Python and platform, determinism, whether
hidden labels were exposed, and the exact definition of each metric.

## Belief confidence is not prediction probability

Three quantities in LIWM are easy to conflate and mean different things:

- **Belief confidence** — an evidence-strength heuristic on [0, 1], computed by
  noisy-OR over weighted observations and clamped to a per-source ceiling. It
  is not a calibrated probability and is not claimed to be one.
- **Prediction probability** — a forecast committed before an outcome, scored
  by Brier and log loss. This one is meant to be calibrated, and `liwm
  calibration` is where you find out whether it is.
- **Prediction confidence** — meta-confidence in that forecast. It is not a
  second probability of the same event.

A prediction may be labelled `locally_calibrated_candidate` only when it was
built from a recorded basis. It should not be described as *calibrated* in a
write-up until reliability bins over at least 30 evidence-bound outcomes support
the claim; `liwm stats` reports `expected_calibration_error_reliable` for
exactly this reason.

## Cross-domain transfer is the flagship measurement

H3 is the hypothesis that separates LIWM from a better notes file. The protocol
is fixed and the contamination rule is not negotiable:

1. assign held-out domain D before any collection;
2. learn only in A, B and C;
3. freeze the profile;
4. commit D-domain preference probabilities *before* any D-specific question,
   observation or output is shown;
5. only then reveal the D outcome and score it.

If D-specific evidence exists in the log before the prediction, the trial is
invalid. Mark it invalid and report the count. Do not quietly include it,
and do not decide after seeing the results which trials were contaminated.

Compare against every baseline on the same D tasks, not against LIWM's own
earlier self.

## How a candidate rule earns human evidence

Replay scores a candidate against an acceptance model LIWM wrote, so a
candidate can win by fitting the evaluator rather than the person. Promotion
therefore requires outcomes from interactions where the candidate produced the
work. `liwm.experiments` provides three modes:

| Mode | User-facing | Counts toward promotion |
|---|---|---|
| `shadow` | no | no — nobody was exposed to anything |
| `canary` | a registered fraction, capped at 0.25 | yes |
| `ab` | registered random assignment | yes |

Assignment is `sha256(seed, experiment, unit)`, committed as an event before
the output exists, so it cannot be re-rolled or chosen after seeing how things
went. All three require explicit opt-in via `learning.experiments_enabled`.
A study that changes participant-facing behaviour must say so in its consent.

## First alpha, before any large study

Do not attempt a full crossover as the first contact with real people. Run a
falsification-oriented alpha and use it to delete machinery that does not earn
its place.

- **Primary question:** does LIWM reduce correction burden or improve blinded
  intent fit compared with a static profile or plain Markdown memory?
- 20–40 participants, several sessions each, at least two domains.
- Conditions: F versus D, and F versus B. Skip the full six-condition matrix.
- Precommitted preference predictions; blinded paired output selection.
- Measure correction burden, questions asked, first-pass acceptance, technical
  correctness, and an intent-fidelity rubric — reported together, never singly.
- Treat the result as pilot evidence. It is not causal proof, and a null result
  is a useful finding that should shrink the framework.

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
liwm study export --anonymise --out <path>                  # one-off
liwm study export --anonymise --longitudinal --out <path>   # repeated measures
liwm study rotate-key      # sever linkage to earlier exports
liwm study forget-key      # make existing exports permanently unjoinable
liwm study off
```

A one-off export salts freshly, so two exports of the same session cannot be
linked by anyone, including you. That is correct for a single hand-off and
useless for a six-week study. A longitudinal export uses a local study key so
pseudonyms are stable within one study and unrelated across studies, and
reports `relative_day`, `event_sequence_offset`, `session_ordinal` and
`task_ordinal` rather than wall-clock stamps — enough for a mixed-effects
model, not enough to identify someone by their working hours.

Stable pseudonyms are pseudonymity, not anonymity. Anyone holding two exports
can link them and the local key can re-identify every row. Rotate or delete the
key when the study ends, and say so in the consent.

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
  This applies to the mechanism suite too: it was written by the same people who
  wrote the mechanisms, and a passing case means the implementation matches the
  specification, not that the specification is right.
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
