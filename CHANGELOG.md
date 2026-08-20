# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and semantic versioning.

## [Unreleased]

## [0.2.0] - 2026-08-20

### Added

- A persisted append sequence and bounded event-chain manifest, fail-closed
  integrity checks, checkpoint/archive compaction, and crash-recovery journals.
  Existing 0.1 event files are verified with their original hashes before the
  migration assigns sequence numbers, so their evidence remains usable.
- An event-derived Intent State Graph with typed nodes, edges, provenance,
  confidence ceilings, trace/explain commands, and quarantine for invalid or
  untrusted ancestry.
- Typed provenance-aware observation paths, unique prediction outcomes,
  evaluator/evidence linkage, binary and categorical proper scores, and a
  durable Question Outcome Store.
- A synthetic IntentBench runner/scorer contract smoke suite and local,
  explicitly opt-in study export. Study export begins at the consent event
  sequence, excludes quarantined records, bounds measurements, and never
  uploads data.
- Deterministic `install` and `uninstall` plan/apply/verify flows with exact
  input/output hashes, precondition checks, backups, atomic writes, rollback,
  idempotent re-apply, malformed-marker refusal, and disposable round-trip tests.
- Complete wheel/sdist runtime assets, byte-reproducible wheel and normalized
  sdist content-equivalence checks, and a
  maintainer release checklist. Release publishing remains intentionally manual.

- `liwm predict`, `liwm resolve` and `liwm predictions`. The Brier score and
  calibration bins in `liwm stats` were computed from prediction and outcome
  events that nothing outside the test suite could create, so calibration was
  guaranteed to read zero samples for every real user while the documentation
  claimed the framework measured itself. The loop is now reachable, the skills
  give the commands, and `--unresolved` surfaces predictions made and never
  scored, since resolving only the favourable ones would bias every figure.

- A promotion gate requiring candidate-specific, evidence-linked observed
  outcomes. Replay scores a candidate
  against an acceptance model LIWM authored, so a candidate could win by fitting
  the evaluator rather than the person — training on your own benchmark, with
  the usual result. `min_resolved_outcomes` now requires five distinct
  predictions committed before trusted evidence and resolution. The gate fails
  closed when it cannot be evaluated.

### Changed

- The README no longer claims the gates "cannot be bypassed by a model that
  decides to edit `user.json` directly". An agent runs with the user's
  filesystem authority; the defensible claim is that normal compliant framework
  use is guarded. Isolated hash mismatches are detected, but coherent rewriting
  by a same-authority process need not leave evidence. It is a self-hash, not a
  signed chain.
- Project IDs and self-improvement candidate IDs are validated against path
  traversal; project mutations are privacy-screened and preserve provenance,
  confidence, and evidence instead of promoting inferred text to hard
  constraints. Hard reset now keeps a complete recoverable snapshot, while
  full deletion uses a shared lifecycle lock.
- The README states plainly that 0.2.0 contains no world model in the sense an
  ML researcher means: no learned latent representation, no generative
  transition model, no counterfactual simulator over real trajectories. The
  accurate description is an evidence-sourced, uncertainty-aware persistent user
  model with active intent elicitation. The name is the destination.
- `docs/RESEARCH.md` is a study protocol rather than a note: hypotheses,
  a six-condition baseline set including the host's own built-in memory,
  crossover design, primary and guarded measures, power and pre-registration,
  and threats to validity.
- Python 3.14 added to the package classifiers; CI already tested it.

### Migration and compatibility

- Opening a 0.1 home creates the sequence manifest without rewriting or
  invalidating legacy event evidence; migration and rebuild are covered by an
  end-to-end regression test. The manifest is then mandatory—removing it or a
  sequenced event makes rebuild fail closed instead of silently weakening
  rejection, reset, forget, or rollback controls.
- Persisted schemas add event `sequence`, install-plan receipts, intent-graph
  materializations, compaction checkpoints, question outcomes, and study
  consent state. These are backward-readable through the tested 0.1→0.2 path;
  0.1 clients are not expected to understand the new 0.2 records.
- IntentBench is a deterministic runner/scorer contract smoke suite, not
  evidence that LIWM learns a latent world model or resists poisoning. Study
  export remains local and opt-in; historical pre-consent events are excluded.

## [0.1.0] - 2026-08-20

### Added

- Event-sourced, revisioned, atomic local profile with recovery and backups.
- Evidence weighting, source ceilings, temporal decay, contradiction handling,
  scope promotion, cross-domain hypotheses, and human rejection memory.
- AUTO/LOW/MEDIUM/HIGH/OFF modes with fatigue-aware active questioning.
- Adaptive onboarding targeting ten questions, with early stop, and a synthetic user evaluation harness.
- Project intent, traceable assumptions/decisions, predictions, feedback,
  rolling metrics, retrospective, replay, and gated candidate rules.
- Prompt-poisoning and sensitive-attribute defenses.
- Portable 15-skill bundle, Claude Code/Codex/generic adapters, and optional
  Claude/Codex plugin manifests.
- Declarative host registry (`liwm hosts`) covering Claude Code, Codex CLI,
  Gemini CLI, opencode, Windsurf, Cursor, Zed, GitHub Copilot and any AGENTS.md
  agent, extensible without a code change via `~/.liwm/hosts.json`, with
  per-host instruction byte budgets and a non-destructive `hosts plan`.
- Platform probing in `liwm doctor`: symlink support and filesystem case
  sensitivity are tested rather than inferred from the OS name.
- Free-text retention is deny-by-default by value shape rather than by a list of
  field names, so an unanticipated prose field is dropped instead of stored.
- Prompt-only install, update, and uninstall workflows.
- Cross-platform CI, repository validation, documentation, and MIT license.

### Notes

Released after an over-engineering audit. Cuts made before shipping: an unused
`append_jsonl` helper, an unused `INTERACTION_META_DIMENSIONS` constant, an
empty `dict` subclass, a `None` alias, a single-caller path resolver, a
duplicated `_clamp`, all-false capability boilerplate, and a
`retention.episode_retention_days` setting that nothing read. Four bugs found before release were fixed rather than documented. `FileLock.acquire`
retried its stale-reclaim path without consulting the deadline or sleeping; on
POSIX that path is unreachable because an open file can still be unlinked, but
Windows refuses to delete a file another handle holds open, so the failure was
swallowed and the loop spun a CPU core until something killed it. The deadline
is now checked on every exit from a failed attempt. Also: on Windows,
the POSIX `os.kill(pid, 0)` liveness idiom maps onto `TerminateProcess`, so a
second thread probing a lock would have terminated its own agent -- Windows now
uses a non-destructive `OpenProcess`/`GetExitCodeProcess` probe. The audit
surfaced the other two: a user override of a host's
instruction file was silently ignored in favour of the built-in path, and the
Codex skills directory resolved to `$CODEX_HOME/skills` instead of the
cross-vendor `~/.agents/skills`. Episode pruning is on the roadmap rather than a
knob that does nothing.

[Unreleased]: https://github.com/vyas-devgna/liwm-agent-framework/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/vyas-devgna/liwm-agent-framework/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/vyas-devgna/liwm-agent-framework/releases/tag/v0.1.0
