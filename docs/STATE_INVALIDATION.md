# What a user control actually invalidates

LIWM has one source of truth and many projections of it. That is a good design
until two projections disagree about whether something was deleted, at which
point the framework is telling the user one thing and the agent another.

This page names every layer and states what each user control does to it. It is
not documentation of an intention: `tests/test_state_invalidation.py` asserts
every row, and `tests/test_invalidation.py` asserts the tombstone rule the
profile and the intent graph both derive from.

## The layers

| Layer | Kind | Rebuildable? |
|---|---|---|
| `events/`, `archives/` | immutable historical evidence | no — this *is* the record |
| `user.json` | active materialization | yes, from the log |
| `intent-graph.json` | active materialization | yes, from the log |
| `runtime_context.json` | cached projection of `user.json` | yes |
| `projects/*/intent.json` | active materialization, project-scoped | yes |
| `metrics.json` | derived measurement | yes, from the log |
| question outcome history | derived measurement | yes, from the log |
| `learning/personal-strategy.json` | derived measurement | yes |
| `learning/promoted-rules.json` | governed state, not belief | no — gated, reverted explicitly |
| `exports/` | research artifacts, already left the system | no |

The distinction that matters is **belief versus measurement**. A belief is a
claim about the person. A measurement is a record of how LIWM performed. They
respond to user controls differently, and conflating them would be a serious
mistake in the other direction: if deleting a belief also deleted the record of
how badly LIWM predicted it, the calibration figures would improve every time
someone removed an inconvenient conclusion.

## What each control does

### `liwm forget --dimension` / `--belief` / `--project`

Writes an append-only tombstone. It reaches evidence recorded **before** it and
nothing recorded after, so evidence supplied later can re-establish what was
forgotten. Forgetting is a correction, not a permanent hole.

| Layer | Effect |
|---|---|
| event log | untouched; the tombstone is appended |
| `user.json` | matching beliefs stop being folded |
| `intent-graph.json` | elements whose whole basis was invalidated go inactive; edges die with their endpoints; new elements may not cite forgotten evidence |
| `runtime_context.json` | rebuilt from `user.json`, so the belief is gone |
| project intent | project tombstone drops project-scoped state |
| `metrics.json` | unchanged — measurement, not belief |
| question outcomes | unchanged — measurement, not belief |

`liwm intent explain` and `liwm intent trace` refuse an inactive element unless
given `--history`. The audit record survives; the normal command honours the
tombstone rather than reading around it. `intent-graph.json` lists inactive
elements by id and reason only — never their labels or values.

### `liwm reject`

Records that a belief is *wrong about the user*, not merely stale. The belief is
held at confidence `0.0` and stays there: the same class of weak signal that
produced it cannot relearn it. Only a direct statement from the user can.
`liwm endorse` lifts a rejection.

### `liwm rollback <cutoff>`

Appends a branch marker. Events between the cutoff and the marker stop being
active; events after the marker form the new branch. Every projection reads the
same marker, so `user.json` and `intent-graph.json` move together. Nothing is
deleted, and a later rollback can reach any of it.

### `liwm reset` (soft)

A branch marker that makes the active history start at the marker. Every
derived layer empties. The log is intact and inspectable.

### `liwm reset --hard --yes`

The only destructive control. Takes a complete recoverable snapshot into
`backups/` first, then removes the live state. The snapshot deliberately does
not include the study key, so a hard reset does not preserve the ability to
re-identify old exports.

### `liwm compact`

Moves live event files into a verified gzip archive and writes a checkpoint. It
is not deletion: `EventStore` reads archives transparently, and every consumer
sees the same events before and after. `tests/test_state_invalidation.py`
checks equivalence per consumer rather than only for `user.json`, because each
one folds the log for itself.

Archive growth is unbounded by design. Compaction bounds the *live* set, not the
history. Retention of the archive is a separate decision and LIWM does not make
it for you.

### `liwm study forget-key`

Destroys the local longitudinal pseudonym key. Exports already written can never
again be joined to each other or re-identified from this machine. It does not
reach exports that have already been shared, because nothing can.

## Adding a projection

A new layer derived from the event log must answer this page before it ships:

1. Is it belief or measurement? Belief must honour forget and reject.
2. Does it call `invalidation.invalidated_event_ids` or fold through something
   that does?
3. Does it apply the same reset/rollback branch markers?
4. Does it survive compaction unchanged?
5. Does its serialized form leak anything the user asked to forget?

Add it to `_layers()` in `tests/test_state_invalidation.py`. The suite is the
enforcement; this page is only the explanation.

---

[LIWM](../README.md) · [Architecture](../ARCHITECTURE.md) ·
[Privacy](../PRIVACY.md) · [Threat model](../THREAT_MODEL.md)
