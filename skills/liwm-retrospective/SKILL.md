---
name: liwm-retrospective
description: End-of-work review that turns a session into learning - what was predicted, what was misunderstood, which questions paid off. Run after a meaningful unit of work, not after every reply.
license: MIT
metadata:
  version: 0.1.0
  framework: liwm
---

# LIWM — session retrospective

## When

After a **real unit of work**: a feature landed, a document finished, an
investigation concluded, a session ending. Not after every reply, and not after
a one-line answer.

Signals it is worth running: the user gave substantive feedback, you were
corrected, you asked questions, you made a consequential assumption, or the work
took several exchanges.

## Running it

```bash
liwm retro <session-id> --project <id> --json
```

This is **silent by default**. It persists an episode, updates the interaction
strategy, and may propose candidate rules. Report it only if the user asks.

## What it produces

- **An episode** in `~/.liwm/sessions/` — the replayable record of what was
  asked, predicted, decided and how it landed. These become the regression cases
  that any future strategy change has to beat.
- **Strategy adjustments** (Level 3) — bounded EWMA nudges to which question
  styles work for this person, how hard to push back, how bold an assumption may
  be, and where the AUTO thresholds sit.
- **Candidate rules** (Level 4) — proposals only. They enter a gated pipeline;
  a retrospective can never promote anything by itself.

## The questions it answers

- What was predicted correctly, and what was a surprise?
- Which question changed the plan, and which was wasted?
- Which assumption caused rework?
- What preference gained support?
- Was anything project-specific that you were tempted to treat as global?

That last one deserves real attention. The most common way personalisation goes
wrong is a project constraint quietly becoming a personality trait. If a lesson
from this session only makes sense *for this project*, it belongs in project
intent, not in the profile.

## Episodes store observable facts only

Never write model-internal reasoning into an episode. Store what was asked, what
was chosen, what the user did, what the outcome was. Episodes must stay useful
when the underlying model changes — that is why LIWM records evidence and
outcomes rather than chains of thought.

## If the user asks what you learned

Be concrete and short:

> Two things: you cut every hedge out of my draft, so I've recorded that you
> want blunter phrasing. And I assumed you wanted tests alongside — you did, but
> I hadn't checked, which is the sort of thing I should ask about once rather
> than guess repeatedly.

Not a summary of everything that happened. Say what will be different next time.

## What a good retrospective changes

If nothing would change next time, say so — "nothing notable" is a legitimate
outcome and far better than manufacturing a lesson. Inventing learning from a
quiet session is how a profile fills with noise.
