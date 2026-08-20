# Research protocol and instrumentation

LIWM's engineering is further along than its evidence. Everything reported so
far comes from a deterministic simulator agreeing with its own model of a
person, which demonstrates that the machinery is coherent and demonstrates
nothing whatsoever about real humans. This document exists so that somebody —
possibly you — can close that gap properly rather than by accumulating
testimonials.

The honest summary of the current state: **the mechanism is tested, the
hypothesis is not.**

---

## The claim under test

> An agent with an evidence-gated, scope-separated model of one person produces
> output that person prefers, using fewer clarifying questions, and that
> advantage transfers to a domain the model has never seen.

Three separable sub-claims, in increasing order of interest and difficulty:

- **H1 (preference fit).** Output produced with the profile is preferred to
  output produced without it, by the person the profile is about.
- **H2 (question economy).** That advantage does not come from asking more. As
  the profile matures, questions per task falls while preference fit holds.
- **H3 (transfer).** A profile learned in domains A, B and C predicts preference
  in an unseen domain D better than chance and better than every baseline.

H3 is the one worth publishing. H1 alone is satisfied by any memory system, and
a result that only shows H1 does not distinguish LIWM from appending notes to a
Markdown file.

## Baselines

A comparison against "no memory" is not informative, because shipped agents
already have memory. The baseline set has to include what people actually use.

| | Condition | Why it is in the set |
|---|---|---|
| **A** | Agent with memory disabled | Floor. Establishes the task difficulty. |
| **B** | Free-form Markdown memory the agent maintains itself | The representation LIWM claims to improve on. |
| **C** | Static hand-written user profile, no learning | Separates *having* a model from *learning* one. |
| **D** | The host's built-in memory (Claude Code auto memory, Cursor Memories, …) | The real competitor. Skipping it makes the study unpublishable. |
| **E** | LIWM with questioning disabled (`liwm mode off` for elicitation, profile still applied) | Isolates the profile from the interviewing. |
| **F** | Full LIWM | The treatment. |

E vs F is the ablation that matters most, because it is the one that says
whether active elicitation earns its cost or whether the profile does all the
work. If E ≈ F, the question planner should be cut, and that is a legitimate
finding rather than a failure.

## Design

Within-subject crossover, because between-subject designs need participant
numbers that a project this size will not get, and inter-person variance in
"what good output looks like" is enormous.

- **Participants.** Working developers, each contributing across ≥4 sessions
  spanning ≥3 weeks. Longitudinal is not optional: the effects under test are
  about accumulation, and a single-session study measures onboarding, not
  learning.
- **Tasks.** Drawn from ≥4 domains, stratified by consequence and reversibility,
  because AUTO's behaviour is defined in terms of those axes and a task set that
  does not vary them cannot exercise the policy.
- **Assignment.** Condition order counterbalanced per participant. The held-out
  domain D is assigned before any data is collected and never trained on.
- **Blinding.** Participants judge paired outputs without knowing which
  condition produced which. This is the whole reason to prefer paired preference
  over Likert satisfaction: people rate a system they know is "the personalised
  one" more highly regardless of what it produced.
- **Washout.** Conditions must not share a profile. Each condition gets its own
  `LIWM_HOME`, and the export from one is never imported into another.

## Primary and secondary measures

**Primary:** blind paired preference rate in the held-out domain D.

**Secondary**, all already instrumented and readable from `liwm stats --json`:

| Measure | Where it comes from | Interpretation risk |
|---|---|---|
| First-pass acceptance | `rates.first_pass_acceptance` | Confounded with task difficulty; only compare within participant. |
| Questions per task | `rates.questions_per_meaningful_interaction` | Must be read *with* preference fit — a system that stops asking and gets worse has not improved. |
| Correction rate | `rates.correction_rate` | Distinguish corrections of *taste* from corrections of *fact*. |
| Assumption error rate | `rates.assumption_error_rate` | The cost side of not asking. |
| Brier score | `calibration.brier_score` | Only meaningful with ≥100 resolved predictions. |
| Calibration bias | `calibration.bias` | Systematic optimism is the expected failure direction. |
| Cross-domain confirmation | `cross_domain.confirmed / tested` | Directly operationalises H3. |

**Guarded, must not regress:** technical correctness, and intent fidelity. These
are tracked separately from acceptance precisely because a system that optimises
for agreement will improve acceptance while getting worse, and that is the most
likely way for this design to fail invisibly.

## Prediction before observation

This is the part that turns the study from a satisfaction survey into a
measurement, and it is instrumented in the framework rather than in the
protocol:

```bash
liwm predict --acceptance 0.68 --confidence 0.55 --artifact "task-17" --session "$S"
# ... user reacts ...
liwm resolve --prediction prd_… --acceptance 0.30
liwm stats --json | jq .calibration
```

Every prediction is committed *before* the user reacts, so no outcome can be
narrated afterwards as consistent with the profile. Over hundreds of
resolutions this yields Brier score, log loss, reliability bins, and a learning
curve over time — quantities that are meaningful in a way that "users said it
felt more personalised" is not.

`liwm predictions --unresolved` exists because selectively resolving only the
predictions that went well would silently bias every calibration figure in the
study. Report the unresolved count alongside the Brier score, always.

## Power and stopping

Decide these before collecting anything, and write them down:

- the minimum preference-rate difference worth detecting (LIWM's own promotion
  gate uses 4 percentage points as the threshold for "worth acting on", which is
  a defensible starting point);
- the participant and task counts implied by that effect size at the intended
  power;
- a fixed stopping rule.

Interim peeking with an open stopping rule will manufacture a positive result
from noise. Pre-register the analysis, including which measure is primary — the
table above has seven secondary measures, and choosing the primary afterwards
guarantees one of them is significant.

## Data handling

- `liwm export --anonymise --out <path>` produces an allowlisted structural
  export: numbers and controlled vocabulary only, identifiers replaced with
  per-export pseudonyms so two exports cannot be linked. Free text is not in it.
- Inspect every export before it leaves the machine. The anonymiser is an
  allowlist and is meant to be conservative, but the person publishing is
  responsible for what is published.
- Nothing is transmitted automatically. There is no network code in LIWM, and
  adding some for a study would need explicit, informed, revocable consent.
- Participants must be able to read their own profile (`liwm profile --raw`),
  correct it (`liwm reject`), and delete it (`liwm delete`) at any point,
  including after the study, without that being treated as attrition to be
  minimised.

## Interpreting what already exists

`liwm eval modes` shows the modes are behaviourally distinguishable — question
budgets 3 / 6 / 12 and experiential share 0.33 / 0.50 / 0.83, both monotonic.
That is a property of the planner, not a finding about people.

`liwm eval converge` runs deterministic archetypes that expose hidden
preferences only to the simulator. Reported accuracy 0.21 → 1.00 and questions
2.80 → 0.00 mean the fold recovers a preference structure that was designed to
be recoverable. These archetypes are fixtures. They are not labels for real
users and must never be described as user types.

Replay compares a current and a candidate question policy over recorded
episodes. Its acceptance model is explicitly modelled, not observed
(`ACCEPTANCE_MODEL` in `evaluation/replay.py`), so replay can say a candidate
*would likely* have helped and can never establish that it did.

Standing constraints on any reported number:

- fewer than 20 samples is thin evidence and is labelled as such;
- acceptance, technical correctness and intent fidelity are three different
  things and are never collapsed into one score;
- simulation and replay are estimates, not counterfactual ground truth;
- only a prospective, controlled, pre-registered study supports a causal claim.

## Known threats to validity

- **Self-evaluation.** LIWM's self-improvement gates are scored partly by
  replay, which shares assumptions with the system being adapted. This is
  training on your own benchmark, and it is why external outcome signals
  (real choices, real corrections, real task success) have to anchor any
  adaptation claim.
- **The provenance oracle.** LIWM cannot independently verify that the host
  labelled evidence truthfully. A study using a host that mislabels sources
  measures the host, not the framework.
- **Simulator affinity.** The archetypes were written by the same author as the
  fold. Convergence against them is close to a self-consistency check.
- **Novelty effects.** Participants behave differently when they know a system
  is watching them. Longitudinal design and blinding mitigate this; nothing
  eliminates it.

## If you run one

Open an issue with the design before collecting data, and the maintainers will
help pre-register it. A negative result is genuinely welcome and more useful
than another feature: if H2 or H3 does not hold, the parts of this architecture
that exist to serve them should be removed, and that is a better outcome than
carrying them indefinitely on the strength of a simulator.

---

<div align="center">
<sub>

[LIWM](../README.md) · [Docs index](README.md) · [Architecture](../ARCHITECTURE.md) · [Privacy](../PRIVACY.md) · [Threat model](../THREAT_MODEL.md) · [Roadmap](../ROADMAP.md)

</sub>
</div>
