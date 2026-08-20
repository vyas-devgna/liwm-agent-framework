# Host adapters

LIWM attaches to an agent by one mechanism: **one delimited Markdown block in a
file the agent already reads at the start of a session.** Everything else —
skills, plugins, hooks — is an optimisation layered on top of that.

That is the whole portability story, and it is why LIWM works on hosts nobody
has written an adapter for. If your agent reads *any* Markdown file at startup
and can run a local command, it can use LIWM.

```
   ~/.liwm/                    one private profile, host-independent
        │
        │  liwm context --json
        ▼
   ┌─────────────┬──────────────┬──────────────┬──────────────┐
   │ Claude Code │  Codex CLI   │  Gemini CLI  │  anything    │
   │ CLAUDE.md   │  AGENTS.md   │  GEMINI.md   │  AGENTS.md   │
   │ + 15 skills │  + 15 skills │  block only  │  block only  │
   └─────────────┴──────────────┴──────────────┴──────────────┘
```

## Which block goes where

`liwm hosts list` prints this table for *your* machine, with detection results
and the resolved paths. The registry behind it is
[`src/liwm/hosts.py`](../src/liwm/hosts.py).

| Host | User-level file LIWM installs into | Block | Skills |
|---|---|---|---|
| Claude Code | `~/.claude/CLAUDE.md` | [`claude-code/bootstrap.md`](claude-code/bootstrap.md) | yes |
| Codex CLI | `$CODEX_HOME/AGENTS.md` (default `~/.codex/AGENTS.md`) | [`codex/bootstrap.md`](codex/bootstrap.md) | yes |
| Gemini CLI | `~/.gemini/GEMINI.md` | [`blocks/standalone.md`](blocks/standalone.md) | no |
| opencode | `~/.config/opencode/AGENTS.md` | [`blocks/standalone.md`](blocks/standalone.md) | no |
| Windsurf / Cascade | `~/.codeium/windsurf/memories/global_rules.md` | [`blocks/compact.md`](blocks/compact.md) | no |
| Zed agent | `~/.config/zed/rules` | [`blocks/standalone.md`](blocks/standalone.md) | no |
| Cursor | *(User Rules live in the settings UI)* | [`blocks/standalone.md`](blocks/standalone.md), pasted | no |
| GitHub Copilot coding agent | `.github/copilot-instructions.md` *(repo-scoped)* | project intent only | no |
| Any AGENTS.md agent | nearest `AGENTS.md` | [`blocks/generic-agent`](generic-agent/bootstrap.md) | depends |

Three blocks, because hosts differ in exactly two ways that matter:

- **`bootstrap.md` (per host, ~730 bytes)** — the host loads skills, so the block
  only has to *route*. The reasoning lives in skill bodies that load on demand,
  which keeps the always-on context cost near zero.
- **`blocks/standalone.md` (~1.1 KB)** — no skills mechanism, so the rules that
  would live in a skill body are inline: what counts as evidence, what never
  does, and which CLI command to run.
- **`blocks/compact.md` (~450 bytes)** — for hosts with a hard instruction
  budget. Windsurf caps its global rules file at 6,000 characters, and LIWM
  will not be the thing that pushes a user's own rules out of that budget.

`{{LIWM_COMMAND}}` is substituted at install time with whatever actually runs on
that machine (`liwm`, `python3 -m liwm`, `py -m liwm`, or an absolute path into
a virtualenv). The installer resolves it and records the answer in
`~/.liwm/config.json`, so `liwm doctor` can tell you later when it stops working.

## Why a block and not a hook

Hooks look like the obvious mechanism and are, for this purpose, the wrong one.

In Claude Code, `SessionStart` hook output is **shown to the user**, not added to
the model's prompt — a hook cannot inject context. Codex hooks *can* return
`additionalContext`, but only for users who have trusted hooks via `/hooks`, so
LIWM offers that as an enhancement and never depends on it. A design that
required hooks would work for a minority of users and silently do nothing for
everyone else.

The delimited block, by contrast, is universal, inspectable (`cat ~/.claude/CLAUDE.md`),
diffable, and removable with a text editor if LIWM ever misbehaves.

## Adding a host without writing code

`~/.liwm/hosts.json` is merged over the built-in registry:

```json
{
  "hosts": [
    {
      "id": "my-agent",
      "name": "My Agent",
      "config_dir": "~/.myagent",
      "global_instruction_file": "~/.myagent/INSTRUCTIONS.md",
      "project_instruction_files": ["AGENTS.md"],
      "instruction_budget_bytes": 8192
    }
  ]
}
```

`liwm hosts list` picks it up immediately, `liwm hosts plan --host my-agent`
shows exactly which files would be touched, and an entry whose `id` matches a
built-in *corrects* that built-in rather than replacing it — so if a vendor moves
a path, you can fix it locally without waiting for a release.

## The installation contract, on every host

Whatever the host, an installer following [`INSTALL_PROMPT.md`](../INSTALL_PROMPT.md)
must:

1. **back up** any file it is about to modify, with a timestamp, into `~/.liwm/backups/`;
2. **preserve** every byte outside the `<!-- LIWM:BEGIN … -->` / `<!-- LIWM:END -->`
   markers — your existing persona and instructions are not LIWM's to edit;
3. be **idempotent** — re-running replaces the one block instead of appending a second;
4. **verify** afterwards (`liwm doctor`) and **report** precisely what changed;
5. be **reversible** — [`UNINSTALL_PROMPT.md`](../UNINSTALL_PROMPT.md) removes the
   block and leaves the file byte-identical to what preceded installation.

`liwm hosts plan --host <id> --block <path>` prints that plan without performing
it, including the byte budget arithmetic. Run it first if you would rather see
the diff before an agent edits your assistant's instructions — which is a
reasonable thing to want, and the reason the command exists.

## Per-host notes

- [Claude Code](claude-code/README.md) — skills, plugin manifest, why not a hook.
- [Codex CLI](codex/README.md) — `AGENTS.override.md` precedence, `~/.agents/skills`, the 32 KiB budget.
- [Generic Agent Skills host](generic-agent/README.md) — the four capabilities a host needs, and how to degrade when it lacks one.
