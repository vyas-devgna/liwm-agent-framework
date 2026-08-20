---
name: liwm-self-improvement
description: Review, replay and gate LIWM's own behavioural rule changes. Use for "LIWM review", or when deciding whether a proposed lesson should change future behaviour.
license: MIT
metadata:
  version: 0.2.0
  framework: liwm
---

# LIWM — gated self-improvement

## The thing this refuses to do

Append a lesson to its own instructions after every conversation. That is how an
agent drifts somewhere nobody chose, with no way to audit or revert it.

**LIWM never rewrites its skill files.** Skill text is framework code, versioned
in git. What adapts is *data the skills read*. Every behavioural change is
therefore inspectable, attributable and revertible.

## The pipeline

```
retrospective → candidate rule → constitution check → replay over history
   → benchmark → adversarial suite → gate → promoted | rejected
```

A candidate that fails any stage is rejected and archived with the reason.

## Reviewing

```bash
liwm rules list --json                    # active rules and pending candidates
liwm rules list --include-rejected --json # including what was refused, and why
```

Show the user in plain language:

> Two rules are active: ask one intent question before non-trivial builds
> (promoted after it improved first-pass acceptance across 18 past sessions),
> and default to one recommendation rather than options.
>
> One was rejected: a proposal to relax the rule about only counting you as
> evidence about you. That one is constitutionally blocked and always will be.

## Advancing a candidate

```bash
liwm rules replay --id cand_<id> --json    # score it against real past episodes
liwm rules promote --id cand_<id> --json   # attempt the gate
liwm rules revert --id cand_<id>           # always available
```

## The gate

Promotion requires **all** of:

- constitution check clean;
- replayed over ≥12 episodes spanning ≥3 distinct sessions;
- primary metric improved by ≥0.04;
- **no guarded metric regressed** beyond tolerance;
- adversarial suite passed.

Guarded metrics: `question_ignore_rate`, `questions_per_accepted_outcome`,
`assumption_error_rate`, `explicit_correction_rate`, `global_correction_rate`.

The guarded set exists because a change can improve the headline number by doing
something bad — raising acceptance by asking twice as many questions, or by
being agreeable. Those show up here and block promotion.

## What can never be promoted

Anything touching a protected surface: `privacy`, `provenance`, `meta`,
`integrity`, `agency`, `precedence`, `epistemics`, `transparency`, `objective`.

Concretely, a candidate is auto-rejected if it tries to relax the provenance
gate, weaken the privacy gate, bypass scope-promotion evidence rules, edit
instruction files directly, or optimise for agreement. `interaction` and
`calibration` remain tunable — adapting how LIWM asks and how well it predicts
is the whole point.

## Honesty about replay

Replay reproduces **observed** facts exactly: which questions were asked, at
what utility, whether they were answered, ignored or judged redundant, and what
feedback followed.

One quantity is **modelled**: what acceptance an artifact *would* have received
under a different question set. That cannot be observed counterfactually. The
model is stated explicitly in the code, deliberately conservative, and every
figure derived from it is labelled `estimated`. No candidate is promoted on a
modelled metric alone — every guarded metric is an observed one.

When reporting replay results, carry that distinction. "Would probably have
helped, estimated" is honest; "improves acceptance by 6%" is not.

## Running the studies

```bash
liwm eval modes --json                                    # are the modes actually distinct?
liwm eval converge --archetype impatient_technical_expert # does it learn a synthetic user?
```

These measure **the framework**, using deterministic synthetic fixtures. They
are never measurements of a real person, and the archetypes are not categories
anyone gets sorted into.

## Proposing well

A good candidate names a specific trigger, a specific change, a measurable
expected effect, and the episodes that motivated it. A bad one is a vibe:

- Good: *"When more than half a session's questions are skipped, raise the
  minimum question utility by 0.15 until the answer rate recovers."*
- Bad: *"Be more attentive to what the user wants."*

The second cannot be replayed, cannot be measured, and cannot be reverted —
which means it cannot be promoted, and should not be proposed.
