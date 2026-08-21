# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and semantic versioning.

## [Unreleased]

## [0.4.0] - 2026-08-21

A context-economics release. LIWM could already say what it believed and why;
it could not say what that cost. The most common criticism of persistent agent
memory is that feeding it back to the model doubles token usage and bloats the
context, and until now this repository had no way to answer that except by
asserting the projection was small.

Measured on a ninety-day profile, exact `cl100k_base` counts, twelve turns:

| strategy | tokens/turn | had the needed fact | leaked the README claim |
|---|---:|---:|---:|
| dump the whole profile | 22,266 | 1.00 | 0 |
| prose in a Markdown file | 679 | 1.00 | 12 / 12 |
| LIWM projection as JSON *(0.3.0)* | 620 | 0.88 | 0 |
| LIWM capsule, gate on | **85** | 0.88 | 0 |

### Added

- **Zero-memory gate** (`liwm/gate.py`). A deterministic decision, taken before
  the profile is loaded, about whether a request needs stored memory at all.
  Asking a model this would be a second inference charged against the budget
  the gate protects, and unauditable afterwards. Errors are asymmetric — a
  wrong skip degrades an answer silently, a wrong retrieve costs visible tokens
  — so need signals win ties and anything unrecognised retrieves.
- **Context capsule** (`liwm/capsule.py`, `liwm context --capsule`). The
  projection in the form a model reads: 232 tokens where the same content as
  pretty-printed JSON is 1,402. A rendering choice, not a filtering one.
- **ContextReceipt** (`liwm context --receipt`). Gate decision, candidates
  considered, selected, rejected with the reason the resolver recorded, and the
  cost of each wire format. Not part of the projection, because an audit record
  that inflates what it audits is worse than none.
- **Token accounting** (`liwm/budget.py`). Exact counts where a BPE tokenizer
  is importable, a dependency-free estimator otherwise, and every number
  records which. Estimator error over 75 real payloads: mean -0.2%, 71/75
  within 10%, worst -11.2%/+22.4%.
- **`liwm eval contextecon`** and `benchmarks/contextecon/`. Six strategies over
  one profile. The Markdown baseline is built from the raw observation log, not
  from LIWM's folded profile, so it leaks what such a file really leaks; a test
  asserts it still does, so it cannot quietly become a strawman.
- **Sufficiency loop.** `context --include <dimension>` and `--all`. The capsule
  states how many beliefs it withheld, so a miss is recoverable rather than
  silent.
- **`tools/probe_host.py`.** Stages a real `SKILL.md` where the registry claims
  skills go, runs the host's own introspection, and reports whether it was
  found. No model, no credentials. A path check, not acceptance.
- **Two hosts:** Pi (`~/.pi/agent/AGENTS.md`) and Google Antigravity
  (`~/.gemini/config/rules/GEMINI.md`), both recorded at community confidence
  because both were corrected against an installed copy rather than a docs page.

### Changed

- **Every host block now runs `context --capsule --task "..."`** instead of
  `context --json`. Passing the task is not decoration: without it the gate has
  no hint and retrieves every time.
- **opencode is a skills host.** It was recorded as having none and was being
  given the larger self-contained block and no skills. opencode 1.18 has a
  skills mechanism and also auto-loads `~/.claude/skills` and `~/.agents/skills`.
  Verified with `tools/probe_host.py`.
- `resolve_for_context` records why each belief was excluded, so "why was this
  left out" cannot drift from the filter that left it out.
- `score_beliefs` returns the score that produced the ordering, replacing a
  second copy of the ranking arithmetic that only the receipt used.

### Fixed

- **Fixed top-k filled its last slots from beliefs the ranker could not tell
  apart** — an arbitrary subset presented as a selection, at full token price.
  Selection now drops a tie straddling the cut and reports the count: on the
  benchmark scenario, 620 tokens a turn instead of about 1,620, for strictly more
  information.
- **The runtime-context schema rejected two of its own projections.**
  `mode.resolved_from` allowed only `auto`, `explicit` and `config`, while the
  integrity path has emitted `integrity_gate` since 0.3.0. The schema test only
  ever built the ordinary projection; it now walks all six.
- **The gate sent "compare the three options" to the model with no memory.**
  Presenting a comparison is a formatting and decision-style question before it
  is a factual one.
- **The gate treated situated questions as general knowledge.** "What is wrong
  with this function" parses exactly like "what is a monad", and the first
  version skipped memory for both -- the expensive direction to be wrong in,
  because the answer quietly gets worse and nothing says why. A reference to a
  local artifact is now a need signal. The benchmark could not see this,
  because every self-contained turn in it was genuinely general; two turns of
  that shape were added so it can.

### Known limits

- Evidence sufficiency is 0.88, not 1.00. A genuinely relevant belief held at
  confidence 0.53 is outranked by forty accumulated preferences at 0.55 — a real
  limit of confidence-ordered retrieval without semantics. Every such miss is
  signalled and recoverable, and a test holds it that way.
- `eval contextecon` measures retrieval and cost. It does not measure answer
  quality; no model runs, and nothing from it may be quoted as evidence about
  accuracy.
- No host has passed the full acceptance protocol. The opencode record in
  `docs/HOST_ACCEPTANCE.md` is paths, bytes and idempotence.


## [0.3.0] - 2026-08-21

A correctness and measurement release. No new surface area to speak of; what
changed is that several things which were documented as true became true.

### Fixed

- **Forgetting reached only one projection.** The profile fold honoured
  `liwm forget`; the intent graph did not. A node standing on evidence the
  user deleted stayed active, so a forgotten preference was still readable
  through a second view of the same log. Both projections now derive their
  answer from one rule in `invalidation.py`. Elements whose whole basis was
  forgotten go inactive, edges die with their endpoints, and a new element
  cannot be built on forgotten evidence. `liwm intent explain|trace` refuse an
  inactive element without `--history`; `intent-graph.json` records inactive
  elements by id and reason only, never their labels.
- **`liwm forget --belief` never worked.** A belief key is pipe-separated, the
  free-text screen classifies prose by shape, and the tombstone reached disk
  with its subject stripped to null.
- **`decay_policy` was decorative in the intent graph.** The materialiser
  validated the field and left confidence alone, so the graph could hold 0.8
  indefinitely while the same belief had decayed in `user.json`. Recorded and
  effective confidence are now separate; effective confidence uses the
  profile's own `recency_factor`, bounded by the effective confidence of the
  evidence beneath it, and evidence ages on its own clock.
- **An "observed human outcome" did not have to match its evidence.**
  `resolve_prediction` checked that some later trusted user event existed while
  the caller supplied the label separately, so a prediction of option A could
  be resolved as "the user chose B, observed" because the user had said
  "thanks". The label is now read out of a feedback event carrying that
  prediction's id, and a contradicting argument is an error rather than an
  override.
- **The promotion gate was unsatisfiable.** It demanded observed outcomes from
  a candidate that never ran. See `liwm.experiments` below.
- **Question effectiveness switched on at a threshold.** Four observations were
  ignored and the fifth took full control of a question family's utility.
- Seven defects found by linting: dead locals in the install planner and the
  fold, a swallowed exception chain, a nested `max`, an unused loop variable,
  an unchecked subprocess in a test.

### Added

- `liwm.experiments` — shadow, canary and A/B evaluation for candidate rules.
  Shadow computes without shipping and its outcomes are never counted as human
  exposure. Canary and A/B put candidate output in front of the user for a
  registered fraction of interactions, capped at 0.25, with the assignment
  committed as an event before the output exists and derived from
  `sha256(seed, experiment, unit)` so it cannot be re-rolled. All three require
  `learning.experiments_enabled`, which is off.
- Four intent-graph edge types now change state instead of describing it:
  `falsified_by`, `validated_by`, `supersedes`, `rejects`. An edge may not
  overrule an element it is weaker than, so an agent inference capped at 0.15
  cannot retire something the user said. Every other edge stays descriptive.
- A durable installation journal, `liwm install status` and `liwm install
  repair [--rollback]`. In-process rollback covers a bad plan; it does nothing
  if the machine dies between file three and file four. A target found in
  neither its original nor its planned state is refused rather than guessed at.
  Tested by killing a real child process after each individual mutation.
- The IntentBench `mechanism` suite: 17 cases across scope contamination,
  poisoning resistance, selective forgetting, cross-domain transfer and
  calibration, run against a real throwaway LIWM home. Real LIWM passes all 17;
  the fixed-choice baseline scores 0.29, which is asserted, so the suite can
  fail. Cases asserting the *absence* of an opinion are scored on departure
  from uniform. Every run returns a manifest naming suite, adapter, version,
  revision, determinism and metric definitions.
- `liwm study export --longitudinal` — stable within-study pseudonyms from a
  local key, and `relative_day` / `event_sequence_offset` / `session_ordinal` /
  `task_ordinal` instead of wall-clock stamps. `liwm study rotate-key` severs
  linkage; `liwm study forget-key` makes existing exports permanently
  unjoinable. The notice says plainly that this is pseudonymity, not anonymity.
- SILENT mode: profile and learning on, questions off. `liwm mode off` disables
  all three, so a study using OFF as its no-elicitation arm changes three
  things and blames elicitation for all of them. This is research condition E.
- `docs/STATE_INVALIDATION.md` and `tests/test_state_invalidation.py`, naming
  every projection and asserting what forget, reject, rollback, reset and
  compaction do to each — including per-consumer compaction equivalence rather
  than the single `user.json` check that was there before.
- Development tooling: ruff, coverage at 79% overall and 82% for the modules
  that decide what to trust, forget or install, and sixteen invariant tests
  over randomised histories. Runtime dependencies remain zero.

### Changed

- Question effectiveness is hierarchical empirical-Bayes shrinkage toward a
  prior worth six pseudo-observations, weighted down for evaluator quality and
  same-session correlation. The planner multiplier is bounded to [0.70, 1.40]:
  history tilts a question's utility, it never vetoes one.
- `observed_information_gain` is now `estimated_uncertainty_reduction`. It was
  the difference between two numbers LIWM produced about its own uncertainty;
  nothing about the person was observed. Explicit user usefulness and trusted
  answer evidence are tracked separately and weighted higher. 0.2 rows are
  still read under the old name, as agent estimates, which is what they were.
- Answer evidence on a question outcome is resolved rather than stored, so an
  outcome cannot claim user evidence that does not exist or was quarantined.
- The promotion gate counts only outcomes bound to their evidence, from
  interactions the user was actually exposed to, spanning at least three
  sessions.
- `liwm stats` keeps unverified historical outcomes in
  `observed_human_outcome_unverified`, reports resolution rate and unresolved
  count, and flags an ECE computed on fewer than 30 samples.
- The batch question planner's 0.55 constant is named `BATCH_RESOLUTION` and
  documented as an assumed answer. `next_question` is stated as the canonical
  path, because there the real answer arrives between picks.

### Migration and compatibility

- 0.2 to 0.3 is additive for `user.json`; the profile is stamped, not
  rewritten. The intent graph is rebuilt from the log, because a 0.2 file has
  no effective confidence and because rebuilding is also what applies the new
  forget semantics to existing state.
- Install plans are written at 0.3.0 and 0.2.0 receipts are still accepted. A
  receipt is the only record of what an earlier release changed; refusing to
  read one would strand the user with an installation they cannot remove.
- Outcomes resolved before this release carry no `outcome_binding`. They are
  retained, reported separately, and not counted as independent human evidence,
  because they were never checked against anything.

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
