---
name: liwm-profile
description: Show the user what LIWM believes about them, with confidence, evidence and gaps. Use for "LIWM profile", "what do you know about me", or before acting on a low-confidence belief.
license: MIT
metadata:
  version: 0.4.0
  framework: liwm
---

# LIWM — profile report

```bash
liwm profile              # readable report
liwm profile --json       # structured
liwm profile --raw --json # the whole materialised profile
liwm profile --section interaction_profile
```

## What to show, and how

Lead with what is **confident and actionable**, then what is **uncertain**, then
what is **missing**. People find the gaps more reassuring than the hits — it
shows the thing knows what it does not know.

The report contains:

- `high_confidence_knowledge` — ≥0.70, acted on silently
- `low_confidence_hypotheses` — <0.40, never acted on without checking
- `cross_domain_hypotheses` — untested guesses that one domain transfers to another
- `contradictions` — where beliefs disagree
- `stale_assumptions` — not reconfirmed in 240+ days
- `coverage_gaps` — high-impact dimensions with no evidence
- `evidence_by_domain` — where the model is thin
- `learning_performance` / `calibration` / `improvement`

## Language

Describe **behaviour you will change**, not who they are.

Good:

> Fairly confident: you want one recommendation rather than a menu (0.88, from
> four corrections), short answers with the reasoning available (0.92, you said
> so), and to be told directly when I think you're wrong (0.75).
>
> Guessing: that you prefer building over planning (0.31 — only inferred, never
> confirmed).
>
> No idea: how much you want documented, or how you feel about irreversible
> changes.

Bad:

> Your profile indicates high openness and low agreeableness.

No archetypes, no personality types, no scores about the person. If a number
appears, it is a confidence in a *hypothesis* — say so.

## Every belief is challengeable

End by making correction easy — correction is the highest-value data LIWM gets:

> Anything there wrong? Say so and I'll drop it.

Then:

```bash
liwm reject --dimension <d> --value <v> --reason "<their words>"
```

Rejection is sticky: weak signals can no longer relearn it, and the inference
method that produced it is recorded so the same mistake is less likely twice.

## Explaining one belief

```bash
liwm why <dimension>
liwm why <belief-id>
```

Shows supporting evidence with timestamps and sources, contradicting evidence,
and **ignored** evidence — including anything quarantined because it came from a
repository or a tool rather than from them. That last part is worth showing; it
demonstrates the boundary is real.

## Confidence, honestly

| range | meaning | behaviour |
|---|---|---|
| ≥0.90 | they told you directly | act on it silently |
| 0.70–0.90 | strong repeated evidence | act on it, mention if surprising |
| 0.40–0.70 | reasonable inference | act on it for reversible things, check for the rest |
| <0.40 | a guess | do not act on it without asking |

If a belief is capped by its source type, the report says so — "capped by weak
source types" means more of the same signal will not raise it, but one sentence
from the user would.
