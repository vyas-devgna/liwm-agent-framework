# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and semantic versioning.

## [Unreleased]

## [0.1.0] - 2026-08-20

### Added

- Event-sourced, revisioned, atomic local profile with recovery and backups.
- Evidence weighting, source ceilings, temporal decay, contradiction handling,
  scope promotion, cross-domain hypotheses, and human rejection memory.
- AUTO/LOW/MEDIUM/HIGH/OFF modes with fatigue-aware active questioning.
- Exactly-ten adaptive onboarding and synthetic user evaluation harness.
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

[Unreleased]: https://github.com/vyas-devgna/liwm-agent-framework/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/vyas-devgna/liwm-agent-framework/releases/tag/v0.1.0
