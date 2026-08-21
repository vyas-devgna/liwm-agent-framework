---
name: liwm-counterfactual
description: Resolve a stubborn ambiguity by offering alternatives that differ along one meaningful dimension and asking which feels closest. Use when direct questions have not settled an important choice.
license: MIT
metadata:
  version: 0.4.0
  framework: liwm
---

# LIWM — counterfactual probes

## When to use this

Ordinary questioning has not resolved something that materially changes the
work, and asking again in a different tone will not help. Recognition is easier
than generation: people who cannot describe what they want can reliably pick it
out of a lineup.

## The rule that makes it work

**Vary exactly one latent dimension.** Three options that differ along one axis
tell you where they sit on that axis. Three options that differ along five axes
tell you nothing you can act on — you learn they liked B, not why.

Good — one axis (control vs automation):

> **A.** It just does it.
> **B.** It shows you exactly what it will do and waits.
> **C.** It does it, and leaves an obvious undo.

Bad — five axes at once:

> **A.** Fast, minimal, CLI-only, no config, opinionated.
> **B.** Thorough, GUI, configurable, careful, general.

## Construction

1. Name the dimension you are actually uncertain about (from
   `open_uncertainties[]` in `liwm context`, or the planner's `contributions`).
2. Write two or three options that sit at genuinely different points on it.
3. Hold everything else constant — same scope, same quality, same domain.
4. Make each option concrete enough to picture. Not "more flexible" but "you
   pass a config file and it does what the file says".
5. Ask which feels **closest**, not which is best. And ask *why* — the
   reasoning usually carries more signal than the choice.

## A useful third option

When two options feel like a false binary, the reconciling third often wins and
tells you the most:

> **C.** Automatic by default, but obvious how to take over.

If they pick the reconciler, you have learned they want the capability without
the ceremony — which is a different thing from wanting either extreme.

## Recording the outcome

A single choice between offered alternatives is `comparative_choice`. The same
choice made repeatedly is `repeated_selection` and is much stronger:

```bash
liwm feedback --kind custom --channel comparative --project <id> \
  --text "picked C: automatic with an escape hatch" \
  --observation '{"dimension":"interaction_profile.autonomy_preference","value":"act_then_report"}'
```

Also record what they rejected — a rejected direction is a real constraint:

```bash
liwm project add --project <id> --section rejected_directions \
  --text "full manual confirmation on every step" --origin USER_SAID
```

## Escalation: build the counterfactual

When the ambiguity is aesthetic or experiential and words keep failing, stop
describing and make two small versions. A thirty-second look at two real things
resolves more than ten minutes of discussion. Only do this when both are cheap —
otherwise you have spent the budget you were trying to protect.

## Do not

- Offer options you would not actually build.
- Offer five variants that test nothing.
- Use this for something a default would settle.
- Present a fake choice where you have already decided — that is manipulation,
  and it poisons the evidence you record.
