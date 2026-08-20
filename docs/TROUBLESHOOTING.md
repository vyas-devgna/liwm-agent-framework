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

## "could not acquire lock ... within 10.0s" on Windows

A lock is reclaimed by deleting its file, and Windows will not delete a file
another handle still has open. So where Linux and macOS can force-reclaim a
lock whose owner LIWM believes is gone, Windows waits for the timeout instead.

This is the safer failure, and it is rarely the one you hit: a process that
actually crashed has its handles closed by the OS, leaving a plain file that
reclaims normally. A persistent timeout means something is genuinely still
holding it -- usually a second agent session mid-write.

    liwm doctor            # confirms the home directory and its state
    # then, only if no LIWM process is running:
    del %USERPROFILE%\.liwm\*.lock

Deleting a lock while a writer is live risks a torn write. LIWM will detect and
quarantine the damage on the next read and rebuild from the event log, but the
cheaper move is to close the other session first.
