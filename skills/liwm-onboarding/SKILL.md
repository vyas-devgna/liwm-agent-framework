---
name: liwm-onboarding
description: Run LIWM's ten-question onboarding to bootstrap a new user profile. Use when the user asks for "LIWM onboarding" or accepts the offer to set up their profile.
license: MIT
metadata:
  version: 0.4.0
  framework: liwm
---

# LIWM — onboarding

Ten questions. One at a time. It should feel like a good conversation with
someone curious, not an intake form.

## What you are actually doing

You are collecting **self-report**, which LIWM caps at 0.70 confidence on
purpose. Onboarding is a head start, not the truth. Behaviour observed later
will and should overrule it. So: do not over-interrogate, do not chase precision,
and do not make the user feel tested.

## Flow

```bash
liwm onboarding start --json
```

Then, ten times:

```bash
liwm onboarding next --json
```

This returns `{id, text, style, family, position, of}`. The planner has already
chosen it based on everything answered so far — **do not pick your own
questions and do not reorder them**. The selection enforces breadth (at least
eight distinct dimension families, never more than two from one), which is what
stops ten questions from all being about verbosity.

Ask the question in your own words. Keep the substance; adapt the phrasing to
the conversation. One question per message. No preamble like "Question 3 of 10:"
unless the user asked for progress.

## Interpreting an answer

Read what they actually said, not what the question was fishing for. Extract
zero or more observations. Zero is a legitimate outcome — a vague answer is not
a mandate to invent a preference.

```bash
liwm onboarding answer --json \
  --question-id nov_two_versions \
  --text "<what they said, verbatim>" \
  --observation '{"dimension":"creative_profile.novelty_seeking","value":"novel"}' \
  --observation '{"dimension":"creative_profile.imperfection_tolerance","value":"high"}'
```

Use dimension names from the taxonomy (`references/dimensions.md` in the `liwm`
skill). An unknown dimension is quarantined rather than stored, so check the
name rather than inventing one.

**Never show scores, confidences, or interim conclusions between questions.**
The moment onboarding feels like a test being graded, people start performing
answers instead of giving them.

## Follow-ups

At most one short follow-up when an answer is genuinely ambiguous *and* the
ambiguity matters. It does not count toward the ten. If they gave you a rich
answer, take it and move on — mining one answer for more is how a pleasant
conversation turns into an interrogation.

## Closing

After the tenth answer, write two or three sentences in plain language about how
you will work with them differently. Concrete and behavioural:

> So: short answers with the reasoning available if you want it, one
> recommendation rather than a menu, and I'll say when I think you're wrong
> rather than hinting. I'll ask before anything hard to undo, otherwise just get
> on with it.

Not this:

> You are a high-openness, low-agreeableness systems thinker.

No archetypes. No personality types. No scores. Describe behaviour you will
change, and nothing about who they are as a person.

Then:

```bash
liwm onboarding complete --json --text "<the summary you just gave>"
```

Invite correction, once: *"Anything there you'd change?"*

If they correct something:

```bash
liwm onboarding correct --dimension interaction_profile.preferred_verbosity \
  --value thorough --text "said they actually want full detail"
```

A correction at this point is high-value — it enters as an explicit correction,
which outranks everything else in the session.

## Boundaries

- Never ask about, infer, or record: ethnicity, religion, sexuality, gender
  identity, health, disability, politics, criminal history, immigration status,
  finances, or precise location. The CLI refuses these, but do not put the user
  in the position of declining.
- Never assign or imply an intelligence rating. LIWM models *domain fluency*
  and *preferred explanation granularity*, which are actionable; "how smart
  they are" is neither actionable nor yours to judge.
- If the user wants to stop early, stop immediately. Run
  `liwm onboarding complete` with what you have — a partial profile is fine and
  the rest is learned by working together.

## Afterwards

Say what happens next in one line: they will not need to invoke LIWM again, it
runs automatically, and they can say `LIWM profile` to see what it thinks or
`LIWM off` to stop it.
