# Codex adapter

LIWM uses the current cross-vendor Agent Skills location and Codex global
instruction chain:

```text
~/.agents/skills/liwm*/SKILL.md   # or symlinks into this checkout
$CODEX_HOME/AGENTS.md            # defaults to ~/.codex/AGENTS.md
~/.liwm/                         # private, host-independent state
```

The installer adds only the delimited block in `bootstrap.md`. If
`AGENTS.override.md` is the active non-empty global instruction file, it updates
that file instead because Codex reads only the first non-empty global candidate.
It preserves all text outside the LIWM markers.

Codex discovers user skills at `$HOME/.agents/skills`, follows symlinks, and
loads only skill names/descriptions until invocation. This makes the same skill
directories usable by Claude Code and Codex without duplicating private data.

The root `.codex-plugin/plugin.json` is an optional distribution wrapper. It is
not required for prompt-based installation, and the bootstrap remains necessary
for automatic consultation on tasks that do not explicitly mention LIWM.

Sources:

- https://developers.openai.com/codex/skills
- https://developers.openai.com/codex/guides/agents-md
- https://developers.openai.com/codex/plugins
