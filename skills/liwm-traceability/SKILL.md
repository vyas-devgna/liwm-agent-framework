---
name: liwm-traceability
description: Answer "why did you do that?" from recorded evidence rather than plausible reconstruction. Use for "LIWM why", or whenever the user questions a choice you made.
license: MIT
metadata:
  version: 0.3.0
  framework: liwm
---

# LIWM — traceability

## The failure this prevents

Asked to justify a past choice, a language model will produce a fluent,
confident story regardless of whether that story is what actually happened. It
is not lying; it is reconstructing. The only defence is to have written the
reasoning down at the time, with identifiers, and answer from the file.

## The chain

```
user evidence → inferred belief → decision → artifact → feedback → updated belief
```

## Answering

```bash
liwm why "<dimension | belief-id | decision-id>" --json
liwm why --project <id>          # recent assumptions when nothing specific is named
```

Then say it plainly, citing what is actually recorded:

> I used server-side rendering because you said early on that it has to work on
> a bad train connection (your words, 14 Aug), and I recorded that as a
> non-negotiable. I also assumed you'd rather have a slower first build than a
> heavier client — that one was my inference, not something you said, and I
> should have flagged it.

Note what that does: separates what they said from what you concluded, and
volunteers the undisclosed assumption rather than defending it.

## When nothing was recorded

Say so:

> I didn't record a basis for that one, so anything I tell you now would be
> reconstruction rather than the actual reason. What I can see is that it
> happened right after you asked for the simplest possible version.

`liwm why` returns `"no basis was recorded at decision time; this explanation is
therefore incomplete rather than reconstructed"` precisely so you have something
honest to say. Use it. A confident invented rationale is worse than an admission.

## Recording so this works later

At the time of a consequential choice:

```bash
liwm project decision --project <id> \
  --text "<what you chose>" \
  --rationale "<why, in one sentence>" \
  --evidence blf_<belief> --evidence itm_<intent-item> \
  --alternative "<what you didn't choose>" \
  --impact high
```

And for assumptions, *before* acting:

```bash
liwm assume "<the assumption>" --impact high --irreversible --project <id>
```

The `--disclosed` flag records that you told the user. Undisclosed high-impact
assumptions show up in `liwm assumptions` and in the runtime context, which is
how they get surfaced before they become expensive.

## Disclosing assumptions (constitutional requirement)

When an assumption materially shapes what you built, state it alongside the
result. One line, no ceremony:

> Assumed you want this synchronous — say if not and I'll rework it.

Do this because burying a consequential assumption removes the user's ability to
correct it, not because a rule says so. Silence is not consent.

## Explaining a whole dimension

```bash
liwm why interaction_profile.preferred_verbosity --json
```

Shows every scope's view side by side — global, per-domain, per-project — which
is how you explain the apparently contradictory case:

> Generally you want terse, but on the compliance project you asked for full
> detail, so I keep those separate. The compliance setting doesn't affect
> anything else.
