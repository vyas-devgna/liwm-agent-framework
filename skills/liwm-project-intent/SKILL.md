---
name: liwm-project-intent
description: Maintain what a specific project is for - objectives, anti-goals, non-negotiables, constraints, assumptions - kept separate from the user's personal profile.
license: MIT
metadata:
  version: 0.3.0
  framework: liwm
---

# LIWM — project intent

## Why this is separate from the profile

*"This banking app must be extremely conservative"* is a fact about the banking
app. If it becomes a fact about the person, their art project suffers six weeks
later and nobody can work out why.

Project intent lives in `~/.liwm/projects/<id>/intent.json` and only becomes
personal when the same pattern shows up **independently across several
projects** — which LIWM's promotion rules handle, not you.

## Setting up

```bash
liwm project init --project <id> --name "<human name>" --domain software
```

The project id defaults to the current directory name. Domains:
`software`, `systems_infrastructure`, `data_ml`, `research`, `writing`,
`visual_design`, `product`, `business`, `hardware`, `operations`, `education`,
`personal`.

## Recording intent

```bash
liwm project add --project <id> --section <section> --text "<text>" --origin <origin>
```

Sections: `objectives`, `latent_objectives`, `desired_experience`, `anti_goals`,
`non_negotiables`, `preferences`, `constraints`, `technical_constraints`,
`inspirations`, `rejected_directions`, `emotional_targets`, `assumptions`,
`open_questions`, `implementation_implications`.

## The origin field is the important one

| origin | means |
|---|---|
| `USER_SAID` | they said it, in their words |
| `AGENT_INFERRED` | you concluded it from what they said or chose |
| `AGENT_DERIVED` | you computed it from the code, environment, or an earlier decision |

This never collapses. An inference does not graduate to a statement because it
turned out to be right. Everything `LIWM why` can honestly tell the user later
depends on this staying accurate, so resist the urge to record your own good
guess as `USER_SAID`.

Confidence defaults to 1.0 for `USER_SAID` and 0.4 for the others. Lower it when
you are genuinely unsure:

```bash
liwm project add --project api-v2 --section latent_objectives \
  --text "wants to stop hand-maintaining the client SDK" \
  --origin AGENT_INFERRED --confidence 0.35
```

## The two sections people skip and shouldn't

**`anti_goals`** — what this must *not* become. Far more actionable than
objectives, and users find them easier to state. Ask "what should never happen
here?" early.

**`non_negotiables`** — the constraints that override everything, including
your judgement and the personal profile. If a non-negotiable and a learned
preference conflict, the non-negotiable wins and you say so.

## Stage

```bash
liwm project stage --project <id> --text design
```

Stages: `inception`, `design`, `build`, `refine`, `debug`, `maintenance`.
This feeds AUTO — inception warrants investigation, debug does not. Update it
when the work genuinely moves on; a project stuck at `inception` will make LIWM
ask far more than it should.

## Decisions

Record anything you would want to explain later:

```bash
liwm project decision --project <id> \
  --text "chose server-side rendering" \
  --rationale "their 'works on a bad connection' anti-goal rules out a heavy client" \
  --evidence itm_abc123 --evidence blf_def456 \
  --alternative "SPA with a service worker" \
  --impact high --irreversible
```

`--evidence` takes intent item ids (`itm_`), belief ids (`blf_`) and event ids
(`evt_`). Without them, `LIWM why` can only say "no basis was recorded", which
is honest but useless.

## Superseding rather than deleting

When intent changes, supersede — history matters for understanding how the
project got here. The CLI's `add` plus a superseded predecessor keeps both. Never
silently drop an objective the user stated.

## Reviewing

```bash
liwm project show --project <id> --json
```

Watch `confidence.overall_intent`. Low with many `AGENT_INFERRED` items means
you are building on guesses — that is the moment to ask something, not later.

`contradictions` flags objectives that overlap anti-goals and non-negotiables
that overlap rejected directions. Surface these **only if they affect the
current work**; otherwise note them and carry on.

## Ending a project

```bash
liwm project delete --project <id>
```

Removes intent, decisions and feedback, and tombstones its evidence so it stops
influencing the personal profile. The audit log is retained. Confirm with the
user first, and tell them exactly what was removed.
