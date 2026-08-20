---
name: liwm-feedback
description: Turn user reactions - corrections, edits, choices, acceptance, silence - into correctly scoped evidence. Use whenever the user reacts to something you produced.
license: MIT
metadata:
  version: 0.1.0
  framework: liwm
---

# LIWM — feedback

Nobody fills in rating forms. Learn from what they already do.

## Channels, from strongest to weakest

| channel | what it is | strength |
|---|---|---|
| `explicit` | they said it | highest |
| `corrective` | they corrected an output or an assumption | highest |
| `edit` | they rewrote what you produced | very high |
| `repeated_comparative` | same choice, several times | high |
| `comparative` | chose between offered options once | high |
| `outcome` | accepted / shipped / abandoned / reworked | medium |
| `repeated_behavioral` | same implicit signal several times | medium |
| `behavioral` | one implicit signal | low, by design |

Use the *true* channel. Recording a guess as `explicit` inflates confidence in
something nobody said, and the whole model degrades from there.

## Recording

```bash
liwm feedback --json --kind <kind> --channel <channel> --project <id> --text "<their words>"
```

Kinds and what they mean:

| kind | signal |
|---|---|
| `exactly_right` | full acceptance |
| `mostly_right` | accepted with minor edits |
| `direction_right_execution_wrong` | intent understood, craft missed — **do not** update intent beliefs |
| `misunderstood_intent` | the intent model was wrong — highest-value signal there is |
| `technically_wrong` | correctness failure — never excused by taste alignment |
| `too_conventional` / `too_ambitious` | novelty mismatch |
| `too_complex` / `too_simple` | scope mismatch |
| `too_technical` / `too_verbose` / `too_terse` | register mismatch |
| `too_many_questions` | interaction cost too high |
| `should_have_asked` | you assumed something you should have checked |
| `custom` | free text; you extract the observations |

The distinction between `direction_right_execution_wrong` and
`misunderstood_intent` is the one that matters most. The first means keep the
intent model and fix the work. The second means the intent model is wrong and
should change. Conflating them is how a framework learns the wrong lesson
confidently.

## Scope: the decision you make every time

Feedback is recorded **against the project by default**. That is deliberate.
"Too complex" about one artifact is evidence about that artifact.

Add `--global-intent` only when they are plainly describing how they want to be
worked with in general:

- *"This is too long"* → project scope.
- *"I always want the short version"* → `--global-intent`.
- *"Stop asking me so much"* → already global; it is about LIWM itself.

When unsure, leave it project-scoped. If the pattern is real it will recur, and
the promotion rules will generalise it with evidence. Guessing global is not
recoverable in the same cheap way.

## Learning from an edit

When the user rewrites your output, the diff is the message. Compare, identify
what systematically changed, and record the *pattern*, not the instance:

```bash
liwm feedback --kind custom --channel edit --project <id> \
  --text "removed every hedge and cut the intro paragraph" \
  --observation '{"dimension":"interaction_profile.preferred_verbosity","value":"terse"}' \
  --observation '{"dimension":"interaction_profile.preferred_directness","value":"blunt"}'
```

Do this only when you can actually see both versions. Do not reconstruct an
imagined edit.

## Silence

Silence is weak evidence and usually means nothing. Do not record acceptance
because nobody complained. If the work was clearly used or shipped, that is an
`outcome` signal — which is medium strength, not high.

## When they say the profile itself is wrong

> *"I don't know why you think I like minimal interfaces."*

That is not feedback about an artifact. It is a rejection of a belief:

```bash
liwm reject --dimension creative_profile.simplicity_vs_richness --value minimal \
  --reason "user says this was never true" --source single_behavioral
```

This zeroes the belief, records that it was rejected, and blocks weak signals
from silently relearning it. Only a direct statement from them can revive it.

## Predicting first

Before producing something substantial, commit to how you expect it to land.
Without a prediction recorded beforehand, "the framework is learning" is
unfalsifiable: any reaction can be narrated afterwards as consistent with the
profile. Keep it internal — never narrate probabilities at the user.

```bash
liwm predict --acceptance 0.7 --confidence 0.55 \
  --friction "too terse:0.4" --artifact "auth refactor" \
  --uncertain interaction_profile.preferred_verbosity --session "$SESSION"
```

It prints a `prd_…` id. After their reaction, resolve it with what actually
happened:

```bash
liwm resolve --prediction prd_0659864f2919 --acceptance 0.3 --friction "too terse"
```

The gap between predicted and actual is what `liwm stats` calibrates on, and it
is the difference between a framework that measures itself and one that assumes
it is working. `liwm predictions --unresolved` lists commitments you made and
never checked; those are not neutral gaps, because a pile of them means the
calibration figures describe only the cases you chose to score.

Predict when the work is substantial enough that being wrong would matter. A
one-line answer does not need a prediction, and recording one for every reply
turns calibration into noise.

## Never

- Fish for positive feedback, or phrase a question so agreement is easiest.
- Record acceptance you did not observe.
- Treat "fine" or "ok" as enthusiasm.
- Let taste alignment excuse a technical error — a wrong answer that matches
  their preferences is still wrong, and should be recorded as
  `technically_wrong`.
