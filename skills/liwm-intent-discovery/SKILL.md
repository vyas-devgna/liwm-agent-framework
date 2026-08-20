---
name: liwm-intent-discovery
description: Elicit what a user actually wants before building, using scenarios and comparisons rather than specification questions. Use in MEDIUM/HIGH mode or when a request is ambitious, novel, or vaguely stated.
license: MIT
metadata:
  version: 0.2.0
  framework: liwm
---

# LIWM — intent discovery

## The problem this solves

A request arrives underspecified. The reflex is to ask the user to specify it.
That reflex is usually wrong, because it asks them to translate something they
can *picture* into vocabulary they may not have — and the translation is where
the intent gets lost.

Discover intent by asking about things people can answer from experience.

## The question to ask yourself first

> What unresolved uncertainty could most change what I am about to make?

Then: what is the **easiest human question** that would resolve it?

If the answer is "nothing would change" — build it. If the answer is "I can pick
a reversible default and find out" — do that, state the assumption, and build it.

## Better and worse forms

| instead of | ask |
|---|---|
| "What error-handling strategy do you want?" | "If this breaks at 3am, which failure would be the bad one?" |
| "Should it be extensible?" | "A year from now, is this the same size or has it grown a lot?" |
| "What's your latency budget?" | "Where would a delay actually annoy you — on open, or on save?" |
| "How much detail in the docs?" | "Who reads this after you — you in six months, or someone new?" |
| "What aesthetic are you going for?" | "Name something you like using even though it does less. What makes it feel right?" |
| "What are the requirements?" | "Imagine this worked perfectly. What are you doing with it that you can't do now?" |

The pattern: concrete situations, comparisons, counterfactuals, anti-examples,
lived experience, forced tradeoffs.

## The highest-yield question types

1. **Anti-examples** — *"What should never happen here?"* Constraints are easier
   to state than goals, and they cut the space faster.
2. **Counterfactual success** — *"Suppose this works better than you expected.
   What does that unlock?"* Reveals the latent objective behind the stated one.
3. **Forced comparison** — *"Which of these two is closer to what you mean?"*
   Recognition is far easier than generation.
4. **Emotional target** — *"What reaction are you hoping for in the first three
   seconds?"* Only when the artifact is something people experience.
5. **Horizon** — *"Throwaway, or something you'll maintain?"* Changes almost
   every engineering judgement downstream.

## Getting the questions

```bash
liwm plan --json --mode <mode> --domain <domain> --project <id> --risk 0.7
```

Each returned question carries `utility`, `why`, and the dimensions it resolves.
Rewrite it to name the actual thing being built. "Two versions of this land on
your desk tomorrow" is a template; "two versions of the migration tool land on
your desk tomorrow" is a question.

## The stopping rule

Stop when the next question's value no longer exceeds its cost. Concretely, stop
when any of these is true:

- the budget from `mode.question_budget` is spent;
- the remaining uncertainty would not change what you build;
- the user has started answering tersely, skipping, or moving on;
- you could pick a reversible default and learn more from their reaction than
  from their answer.

That last one is the most under-used. **Building the wrong thing cheaply and
visibly is often faster than asking.** Do that when the work is reversible.

## Recording what you learn

```bash
liwm project add --project <id> --section objectives --text "<what they said>" --origin USER_SAID
liwm project add --project <id> --section latent_objectives --text "<what you concluded>" --origin AGENT_INFERRED --confidence 0.5
```

Keep `USER_SAID` and `AGENT_INFERRED` honest. An inference that turned out right
is still an inference — that distinction is what makes `LIWM why` trustworthy
later.

## What not to do

- Do not ask a question whose answer you could get from the repository, the
  file you are editing, or the conversation so far.
- Do not ask several questions in one message in HIGH mode.
- Do not ask about preferences the profile already knows with confidence — check
  `applies[]` first.
- Do not run a discovery phase for a one-line change.
