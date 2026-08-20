---
name: liwm-evaluation
description: Measure whether personalisation is actually working - acceptance, calibration, question efficiency, improvement over time. Use for "LIWM stats" or when asked whether LIWM is helping.
license: MIT
metadata:
  version: 0.2.0
  framework: liwm
---

# LIWM — evaluation

## The question

Is this actually helping, or does it just feel like it is? Without measurement,
"the agent is learning" is a claim nobody can check — including the agent.

```bash
liwm stats --json
```

Everything is computed from the local event log. LIWM performs no telemetry or
automatic upload; a host provider may still process runtime context under its
own policy.

## Metrics worth reporting

| metric | reads as |
|---|---|
| `first_pass_acceptance` | share of artifacts accepted without rework |
| `rolling_first_pass_acceptance` | the same, recent window only |
| `explicit_correction_rate` | how often the user has to correct you |
| `assumption_error_rate` | how often an assumption caused rework |
| `question_ignore_rate` | share of questions skipped or ignored |
| `questions_per_accepted_outcome` | **the headline efficiency number** |
| `revisions_per_artifact` | how many passes to get there |
| `calibration.brier_score` | squared prediction error (lower is better; use the Brier label for binary/categorical outcomes) |
| `calibration.bias` | negative = systematically overconfident |
| `improvement.verdict` | improving / flat / regressing / insufficient data |

## The number that matters most

**`questions_per_accepted_outcome` should fall over time.**

Rising acceptance while asking more questions is not personalisation working —
it is an interrogation that happens to produce good results. The claim LIWM
makes is that understanding converts into *fewer* interruptions for the same or
better outcomes. That is the number that tests it.

## Calibration

`calibration.bias` is the gap between predicted and actual acceptance. A
persistently negative bias means LIWM systematically overrates how well its
output will land — worth surfacing, because it means confident wrong
assumptions are going unchallenged.

Calibration only exists if predictions were recorded *before* feedback arrived,
with `liwm predict` and then `liwm resolve`. If `calibration.samples` is 0, say
so plainly rather than implying the framework is measuring itself when it is
not — and check `liwm predictions --unresolved`, because predictions made and
never scored are the usual reason the number stays at zero.

## Sample sizes

Treat any rate with fewer than ~20 samples as indicative only. `liwm stats`
carries this caveat in `interpretation_note`; repeat it rather than quoting a
first-pass acceptance of "1.00" from three data points.

Early on, the honest answer to "is it working?" is *"too early to tell — here's
what it has learned so far and how it will be measured."*

## Framework studies

```bash
liwm eval modes --json
liwm eval converge --archetype detail_oriented_researcher --rounds 10 --json
liwm eval intentbench --json
```

These are deterministic synthetic mechanism checks. IntentBench additionally
enforces that scorer-only ground truth is not passed to an adapter.

Two honesty requirements when reporting these:

1. They measure **the framework**, not any person.
2. The synthetic user answers and reacts by construction, so convergence
   demonstrates that the learning loop *closes* — not that real-world accuracy
   will match. Say that plainly.

## Research export

```bash
liwm study on
liwm study export --anonymise --out <path>
```

Study mode is opt-in and derives a minimized allowlisted view from existing
events. It never uploads. Pseudonymisation is risk reduction, not an anonymity
or unlinkability guarantee; inspect the file before sharing.

## Reporting to the user

Short, honest, with the caveat attached:

> Over 23 exchanges: first-pass acceptance 0.74 (up from 0.52 in the first
> half), and I'm asking about a third as many questions to get there. My
> predictions run slightly optimistic — I expect things to land better than they
> do by about 0.08. Small sample, so treat it as a direction rather than a
> measurement.

Never present LIWM as more effective than the numbers support. Overclaiming here
is the failure mode that makes the whole framework untrustworthy.
