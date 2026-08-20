# Architecture

## Design constraints

LIWM is a local, model-independent framework. The host model supplies language
understanding; LIWM supplies durable semantics, provenance, scope, consistency,
controls, and measurement. No daemon, database, SaaS service, telemetry, hidden
chain of thought, or host-specific profile format is required.

## Layers

| Layer | Responsibility | Principal modules |
|---|---|---|
| Invariants | Guarded agency/privacy/integrity rules | `constitution.py`, `privacy.py` |
| Evidence | Provenance trust, source ceilings, decay, combination | `events.py`, `evidence.py` |
| State | Fold events into profile and project views | `profile.py`, `projects.py`, `scope.py` |
| Adaptation | Context, modes, fatigue, active question selection | `context.py`, `modes.py`, `questions.py` |
| Learning | Feedback, prediction, bounded strategy | `feedback.py`, `prediction.py`, `strategy.py` |
| Evolution | Retrospective, replay, candidate promotion | `retrospective.py`, `evaluation/`, `selfimprove.py` |
| Interface | CLI, skills, host adapters | `cli.py`, `skills/`, `adapters/` |

## Event source and materialized views

Each event is a standalone JSON file named with a UTC timestamp and UUID. This
avoids a shared append file: two agents create different paths and cannot
overwrite each other. Events include canonical content hashes for tamper-evident
integrity checks. Untrusted events may remain in the log for audit but the fold
excludes them. The hashes detect accidental or isolated modification; they are
not a signed chain and cannot defeat an account-level attacker rewriting all state.

`user.json` is a disposable materialized view. A deterministic fold groups
trusted observations by scope/dimension/value, applies source trust and temporal
decay, handles scoped rejection and ordered forget tombstones, evaluates promotions, detects
contradictions, and emits compact profile sections. Recovery prefers re-folding
the event source over restoring an older cache.

Reset and rollback are append-only branch markers. A reset starts a clean active
branch; a rollback admits events through an explicit cutoff plus events written
after its marker. Skipped events remain available for inspection and a later
rollback. Manual full snapshots complement automatic pre-write backups.

Atomic replace, fsync, timestamped backups, advisory `O_EXCL` locks, stale-lock
handling, revision checks, and rebuild-on-conflict protect mutable views. Project
intent has an independent lock and revision.

## Scope lattice

```text
session (ephemeral) → project → domain → global
```

The arrows are not automatic inheritance. Promotion policy requires independent
sessions/contexts, sufficient source confidence, no strong conflict, and a
discount. Cross-domain transfer is first represented as a hypothesis. At read
time, the resolver selects the most specific applicable belief; an explicit
current instruction remains outside and above this lattice.

## Confidence

Weights are auditable heuristics, not pretend posterior probabilities. LIWM uses
a noisy-OR style aggregation with correlation and same-session discounts,
source-specific ceilings, opposition, recency decay, and a persistent floor.
Confidence means “strength of evidence for using this interaction hypothesis,”
not confidence in a personality diagnosis.

## Question utility

The planner implements a provisional, interpretable heuristic corresponding to:

```text
information gain × decision impact × misunderstanding risk × relevance
-----------------------------------------------------------------------
       cognitive cost × fatigue × redundancy
```

Question templates encode which latent dimension they isolate, style, cost, and
expected power. The host rewrites the selected probe into current context. Modes
alter allowed styles, utility threshold, budget, and sequential behavior—not
just the number of questions.

## Self-improvement gates

Project and personal learning can be immediate because they are reversible data
updates. Personal-strategy parameters are bounded and move at most 0.06 per
update. Core rules are immutable candidates until they have:

1. passed the constitution check;
2. replayed on enough distinct historical episodes;
3. improved a declared primary metric;
4. avoided guarded-metric regressions;
5. passed an adversarial evaluation;
6. recorded a promotion decision and reason.

Promoted rules remain data, not rewritten source prompts, and are revertible.

## Extension points

Interfaces deliberately permit future retrieval backends, local embeddings,
Bayesian preference inference, ranking models, multimodal evidence, shared/team
models, external evaluators, and fine-tuning exports. Compliant extensions must
preserve the event/provenance/scope contract. LIWM cannot stop code with the
same filesystem authority from replacing the extension or the constitution.

## Host independence

Every adapter installs against the same LIWM home and drives the same CLI.
Host-specific files contain only discovery and automatic-activation mechanics,
and the JSON schemas contain no Claude- or OpenAI-specific fields.

The knowledge of *which* hosts exist is data, not code paths:
[`src/liwm/hosts.py`](src/liwm/hosts.py) is a table of config directories,
user-level instruction files, skills layouts, capability flags, instruction byte
budgets and the documentation each claim comes from. Three things follow.

**Attachment has exactly one mechanism.** A delimited Markdown block in a file
the host already reads at session start. Skills, plugins and hooks are
optimisations layered on top of that, never prerequisites — which is why a host
with no skills mechanism still works, using a standalone block that carries the
routing rules inline.

**Adding a host requires no release.** `~/.liwm/hosts.json` is merged over the
built-in table, so a user can teach LIWM a new agent, or correct a path a vendor
moved, in about eight lines of JSON. An entry that matches a built-in id merges
over it field by field; unstated fields survive. A user-supplied entry is
recorded with `confidence: user-supplied` rather than inheriting the built-in
`documented`, on the same principle as the provenance gate: LIWM does not claim
a source it does not have.

**Budgets are honoured before writing, not discovered afterwards.** Hosts
truncate oversized instruction files (Codex at `project_doc_max_bytes`, Windsurf
at 6,000 characters). `check_budget` counts the user's existing content against
the limit, and the installer downgrades to the compact block rather than letting
LIWM be the reason someone else's rules fall off the end.

Detection is presence-of-path only. LIWM never executes a host binary, reads a
host's internal state, or asks a network what you have installed, and
`liwm hosts` reports the evidence behind every `detected: true` so the answer can
be checked rather than trusted.

Platform differences that usually break portability are *probed* rather than
inferred from `sys.platform`: `liwm doctor` tests whether the filesystem
actually supports symlinks (Windows permits them only under Developer Mode) and
whether it is case-sensitive (which decides whether two skill directory names
can collide). Locking is one `O_CREAT|O_EXCL` implementation with stale
detection, atomic on POSIX and Windows alike, so there is no `fcntl`/`msvcrt`
divergence to keep in sync.

---

<div align="center">
<sub>

[LIWM](README.md) · [Docs index](docs/README.md) · [Architecture](ARCHITECTURE.md) · [Privacy](PRIVACY.md) · [Threat model](THREAT_MODEL.md) · [Roadmap](ROADMAP.md)

</sub>
</div>
