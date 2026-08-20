---
name: liwm-question-planner
description: Decide whether to ask anything at all, and if so what. Use when weighing a clarifying question against making a reversible assumption.
license: MIT
metadata:
  version: 0.3.0
  framework: liwm
---

# LIWM — question planner

## The premise

Questions cost the user attention. A framework that gets *more* inquisitive as
it learns has failed. The planner exists to make "should I ask?" a computed
decision rather than a reflex.

## The model

```
             expected information gain × decision impact
             × misunderstanding risk × relevance
utility =  ──────────────────────────────────────────────
             cognitive cost × fatigue × redundancy
```

- **Expected information gain** — how much uncertainty an answer would remove.
  Comes from the profile's actual confidence, not a number you invent.
- **Decision impact** — how much the artifact changes if you get it wrong.
- **Misunderstanding risk** — how likely a wrong assumption goes unnoticed until
  it is expensive. You supply this; be honest.
- **Relevance** — does this dimension bear on *this* task.
- **Cognitive cost** — how hard the question is to answer.
- **Fatigue** — how much you have already spent this session.
- **Redundancy** — have you already asked about this.

## Using it

```bash
liwm plan --json --mode <mode> --domain <domain> --project <id> \
  --risk 0.7 --fatigue 0.3 --max-questions 3
```

Returns questions ranked by utility, each with `why` and `contributions`
showing which dimension it resolves and how uncertain that dimension currently
is. An empty list is a normal result.

## When "no question" is the right answer

Prefer acting when **all** of these hold:

- the work is reversible;
- a sensible default exists;
- the user will see the result and can react;
- the assumption can be stated in one line.

Then:

```bash
liwm assume "<the assumption>" --impact medium --project <id>
```

…state it alongside the result, and let their reaction teach you. Reaction is
stronger evidence than an answer to a hypothetical anyway — a direct edit
outweighs a stated preference in LIWM's own weighting for exactly this reason.

## When to ask despite the cost

Ask when the work is **hard to undo** and the assumption is **load-bearing**:
a schema migration, a public API shape, deleting something, an irreversible
external action, or a creative direction that everything else will be built on
top of. In those cases one question is cheap insurance and the budget should be
spent.

## Reading fatigue

Watch for: short replies, "whatever you think", "just do it", ignoring a
question and answering a different one, or explicit annoyance. Any of these
means stop asking and start doing. Record it:

```bash
liwm feedback --kind too_many_questions --channel corrective --global-intent
```

That is one of the few signals that is global by default — it is about LIWM
itself, not about the project.

## After asking

Record whether the answer was worth it. This is what tunes the planner for this
person over time:

```bash
liwm feedback --kind custom --channel explicit --text "answer changed the plan" \
  --observation '{"dimension":"interaction_profile.preferred_question_frequency","value":"moderate"}'
```

If a question turned out redundant — they had already told you, or it did not
change anything — that is worth recording too. Wasted questions are how the
planner learns to be quieter.

## Anti-patterns

- Asking a question you already have a high-confidence answer to in `applies[]`.
- Asking five superficially different questions that all resolve the same
  dimension.
- Asking permission for something reversible.
- Front-loading an interview before any work has been shown.
- Asking a question whose answer would not change anything you do.
