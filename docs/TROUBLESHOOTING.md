# Troubleshooting

## LIWM command is unavailable

Read `~/.liwm/config.json` for the recorded interpreter and checkout. Run that
absolute interpreter with `-m liwm --version`; do not assume shell activation.
Re-run [INSTALL_PROMPT.md](../INSTALL_PROMPT.md) to repair idempotently.

## Skills are not discovered

Verify complete `liwm*` skill directories at `~/.claude/skills` for Claude Code
or `~/.agents/skills` for Codex. Each requires `SKILL.md`. Restart the host if a
previously nonexistent top-level skills directory was created.

## Automatic activation is absent

Check for exactly one complete LIWM marker block in the active global instruction
file. Codex reads a non-empty `AGENTS.override.md` instead of `AGENTS.md`; the
block must be in the active file. Never duplicate it in both to “fix” discovery.

## Profile is malformed or missing

Run `liwm verify`, then `liwm rebuild`. LIWM quarantines an unreadable materialized
profile and reconstructs from events. If event integrity fails, preserve the
directory and inspect `logs/` before restoring a backup.

## Too many questions

Use `LIWM low` for the current work, or disable persistently with
`liwm config set --key enabled --value false`. Record `too_many_questions`
feedback so bounded strategy adaptation raises the questioning threshold.

## A learned statement is wrong

Say “that is not true about me” or use `liwm reject --dimension …`. LIWM retains
the rejected inference for audit, removes its active confidence, and prevents
weak signals from relearning it.
