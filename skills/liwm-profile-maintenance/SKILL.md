---
name: liwm-profile-maintenance
description: Keep the profile healthy - resolve contradictions, retire stale beliefs, handle "that's not true about me", verify integrity, recover from corruption.
license: MIT
metadata:
  version: 0.1.0
  framework: liwm
---

# LIWM — profile maintenance

A profile that only grows becomes wrong slowly and invisibly. Maintenance is
what keeps it honest.

## Health check

```bash
liwm doctor --json     # installation, schema, integrity, host detection
liwm verify --json     # event hashes, schema conformance, materialisation drift
```

`materialisation_drift: true` means `user.json` no longer matches what the event
log would produce — usually a stale write from a parallel session. Fix:

```bash
liwm rebuild
```

Rebuilding is always safe. `user.json` is a cache; the events are the truth.

## Contradictions

```bash
liwm contradictions --json
```

Two kinds:

- **`cross_scope_tension`** — global says one thing, this project says another.
  This is normal and *already resolved* by scope: the narrower one wins in its
  own context. Do not ask about it.
- **`same_scope_conflict`** — two beliefs at the same scope genuinely disagree.
  Worth attention.

Resolve a same-scope conflict by: **recency** → **source strength** →
**repetition** → **consequence**. Ask the user only when it materially changes
what you are about to do:

> You've asked for terse answers before, but on this one you wanted the full
> derivation. Is the compliance work a special case, or has the general
> preference shifted?

That question is doing real work: it distinguishes "project exception" from
"preference changed", and the answer routes to different scopes.

## Stale beliefs

Beliefs not reconfirmed in 240+ days appear in `stale_assumptions`. Do not
delete them — decay already reduces their weight, with a floor so history is
never erased. If a stale belief is about to drive a consequential choice,
reconfirm it in passing rather than with a formal question:

> Still want these short? You said so a while back.

## When the user says the profile is wrong

This is the highest-value correction there is. Do not defend the belief.

```bash
liwm reject --dimension <d> --value <v> \
  --reason "<their words>" --source <the source type that produced it>
```

What this does, and why it matters:

1. zeroes the belief;
2. records **that a previous inference was rejected**, permanently;
3. blocks weak evidence from silently relearning the same wrong thing;
4. only a direct statement or correction from them can revive it.

Pass `--source` when you can tell what produced the bad belief — repeated
rejections of the same inference method are how LIWM learns which of its own
reasoning shortcuts are unreliable for this person.

## Forgetting

```bash
liwm forget --dimension <d>              # a topic
liwm forget --belief <belief-key>        # one specific belief
liwm project delete --project <id>       # a whole project
```

These write **tombstones**. The effect is removed; the audit trail survives, so
"why did you stop thinking that?" remains answerable. Confirm first and report
exactly what went.

## Resetting

```bash
liwm reset              # soft: clean active branch; prior events stay auditable
liwm reset --hard --yes # reset events/projects/learning; snapshot kept in backups/
```

Always confirm `--hard` explicitly and tell them where the snapshot went.
For complete, non-recoverable deletion use `liwm delete --yes` only after an
explicit confirmation; it removes backups, exports, logs, configuration, and
all other LIWM private state together.

For a durable return to an earlier active state, use an exact timestamp and
confirm it:

```bash
liwm rollback --as-of <ISO-8601 timestamp> --yes
```

The rollback is an append-only branch marker: skipped history remains available
for audit, and subsequent events form the new branch. Use `liwm backup create`
for a full private snapshot and `liwm backup list` to inspect snapshots and
automatic pre-write backups.

## Corruption

LIWM recovers automatically: a corrupt `user.json` is quarantined to
`logs/corrupt/` (never deleted) and the profile is re-folded from events. If the
event log itself is damaged, `liwm doctor` will say so and the newest backup in
`backups/` is the fallback.

Never hand-edit files under `~/.liwm`. Editing bypasses the provenance gate, the
privacy gate and the audit log — the three things that make the profile
trustworthy. Everything you need is a CLI command.

## Migration

```bash
liwm migrate --json
```

Idempotent, backs up first, refuses to touch data written by a *newer* LIWM
rather than guessing at it.

## A periodic sanity question

Every so often, look at the profile as a stranger would and ask: **would this
person recognise themselves here?** If it reads like a personality assessment
rather than a set of working preferences, something has drifted and the
over-reaching beliefs should be challenged or dropped.
