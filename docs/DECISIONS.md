# Architecture decisions and host research

Research was refreshed on 2026-08-20 from official documentation.

## ADR-001: portable Agent Skills

Both Claude Code and Codex support the open Agent Skills directory format and
progressive loading. LIWM therefore keeps one portable `skills/` tree and avoids
host-only frontmatter. Claude Code user skills install at `~/.claude/skills`;
Codex user skills install at `~/.agents/skills`.

## ADR-002: compact global bootstrap

AUTO must work when users do not mention LIWM. Claude Code loads user-level
`~/.claude/CLAUDE.md`; Codex reads the first non-empty global
`$CODEX_HOME/AGENTS.override.md` or `AGENTS.md`. A short, delimited block routes
to skills and the context CLI. Full framework instructions do not live there.

## ADR-003: plugin manifests are optional distribution wrappers

Claude Code and Codex/ChatGPT plugin catalogs package skills, but a plugin alone
does not establish LIWM's private data directory or guaranteed AUTO routing.
Prompt installation remains normative; manifests support future distribution.

## ADR-004: Markdown bootstrap is the portable baseline, not the only context path

Claude Code `SessionStart`/`UserPromptSubmit` hooks and reviewed Codex hooks can
provide context. LIWM uses an inspectable instruction block because it is the
common documented mechanism, not because hook context injection is impossible.
Host behavior remains a claim to verify with the acceptance protocol.

## ADR-005: final public name

The product remains **LIWM** and the repository is **liwm-agent-framework**.
Checks found no PyPI or npm packages named `liwm` on 2026-08-20, but GitHub had
multiple unrelated `liwm*` repositories and a `liwm` account. The descriptive
repository name avoids implying ownership of that namespace.

## Official sources

- https://code.claude.com/docs/en/slash-commands
- https://code.claude.com/docs/en/memory
- https://code.claude.com/docs/en/plugins
- https://code.claude.com/docs/en/plugins-reference
- https://learn.chatgpt.com/docs/build-skills
- https://learn.chatgpt.com/docs/agent-configuration/agents-md
- https://learn.chatgpt.com/docs/hooks
- https://code.claude.com/docs/en/hooks

---

<div align="center">
<sub>

[LIWM](../README.md) · [Docs index](README.md) · [Architecture](../ARCHITECTURE.md) · [Privacy](../PRIVACY.md) · [Threat model](../THREAT_MODEL.md) · [Roadmap](../ROADMAP.md)

</sub>
</div>
