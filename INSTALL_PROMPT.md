# Install LIWM

Copy and paste the single prompt below into Claude Code, Codex, Gemini CLI,
Cursor, opencode, Windsurf, or any other capable coding agent. If you are not
already inside the repository checkout, append the repository URL to the prompt.

Nothing here is a script. The installer is an agent following instructions,
because only your agent knows how your agent is configured — and because a
framework that edits your assistant's instructions should have to show its work.
See [adapters/README.md](adapters/README.md) for the per-host details, and run
`liwm hosts plan --host <id>` if you want the diff before anything is written.

```text
Install LIWM (Latent Intent World Model Framework) for me from the current
checkout or from this repository URL if supplied:
https://github.com/vyas-devgna/liwm-agent-framework

This is an agent-performed, prompt-based installation. Do not look for or create
install.sh, install.ps1, an installer executable, or a persona installer. Work
autonomously, but stop on permission failures or if an existing LIWM block is
malformed. Preserve all unrelated user configuration.

1. Detect the host you are actually running under. The supported hosts, their
   user-level instruction files and their byte budgets are tabulated in
   adapters/README.md and in src/liwm/hosts.py; after step 3 you can query the
   same table with `liwm hosts --json`. If your host is not listed, it is still
   supported: any agent that reads a Markdown file at session start can use the
   self-contained block, and you should add an entry for it to ~/.liwm/hosts.json
   so later runs recognise it -- that overlay has the same shape as the built-in
   table and shallow-merges over it, so it can also correct a built-in entry that
   is wrong for your version. Inspect current local conventions and, when
   uncertain, current official host documentation. Do not guess a config path.
   Use platform home/config APIs rather than hard-coding /home or C:\Users.

   Prefer what is on disk to what is on a documentation page. Two shipped
   entries were wrong because the docs described a different product's file:
   Antigravity's published path is Gemini CLI's, and Pi's user-level skills
   directory is undocumented but real. If the host's config directory contains a
   populated `skills/` or `rules/` directory, that is stronger evidence than the
   docs, and the entry you write should record `"confidence": "community"` to
   say where it came from.

   Verify rather than assume. `python tools/probe_host.py <id>` stages a real
   LIWM skill where your entry claims skills go, runs the host's own
   introspection command, and reports whether the host actually found it; it
   needs no model and no credentials. If your host has a comparable command,
   add it to `INTROSPECTION` in that file. A host with no such command is not a
   failure, only unverifiable this way -- confirm it by hand instead, and do not
   describe it as tested.

2. Resolve a stable framework checkout outside project repositories:
   - macOS/Linux: prefer $XDG_DATA_HOME/liwm/framework when XDG_DATA_HOME is set,
     otherwise ~/.local/share/liwm/framework.
   - Windows: prefer %LOCALAPPDATA%\LIWM\framework.
   If the current checkout is already a stable user-owned location, it may be
   used in place. Otherwise clone the URL there. If it already exists, verify
   the remote is the expected LIWM repository and fetch fast-forward updates;
   never replace unrelated content.

3. Make LIWM runnable without changing system Python. Create or reuse a private
   virtual environment beside the framework checkout, install this package in
   editable mode with no optional dependencies, and determine the absolute
   command that successfully runs `python -m liwm --version`. Record that exact
   interpreter-based command; do not rely on shell activation or PATH state.

4. Resolve the private data directory with LIWM itself (normally ~/.liwm on all
   platforms via the platform home API). Refuse to place it inside any Git
   repository. Run `liwm init`, then `liwm migrate`, `liwm rebuild`, and
   `liwm doctor --json` using the exact command from step 3. This must initialize
   config.json, user.json, metrics.json, the append-only events directory,
   project/session/learning directories, backups, and logs. Do not seed personal
   preferences or copy example profiles.

5. If the host supports Agent Skills, resolve its user-scoped skills directory:
   - Claude Code: the resolved user config directory's `skills/` directory,
     normally ~/.claude/skills/.
   - Codex: ~/.agents/skills/ (not ~/.codex/skills).
   - Generic host: its documented user-level Agent Skills directory.
   The lifecycle plan copies each complete LIWM skill with an input/output hash
   and restores a pre-existing same-path file on uninstall. It never enumerates
   or deletes unrelated skills. If the host has no skills mechanism, pass
   `--no-skills` and use the standalone block in step 6.

6. Add a consultation request through the host's documented global instruction file:
   - Claude Code: ~/.claude/CLAUDE.md (respect CLAUDE_CONFIG_DIR).
   - Codex: $CODEX_HOME/AGENTS.override.md if it is the active non-empty global
     file; otherwise $CODEX_HOME/AGENTS.md (CODEX_HOME defaults to ~/.codex).
   - Generic host: its documented global user instruction file.
   Choose the block: `adapters/<host>/bootstrap.md` for a skills-capable host,
   `adapters/blocks/standalone.md` for a host without skills, and
   `adapters/blocks/compact.md` where the host has a tight instruction budget.
   Substitute `{{LIWM_COMMAND}}` in a temporary copy of the block. Run
   `liwm install plan --host <id> --block <path> --output <plan.json>` first.
   Inspect the serialized plan: it names every target, exact hash precondition,
   backup, and expected output. If the resulting instruction file would exceed
   the host's documented budget, use the
   compact block; never truncate the user's own instructions to make room.
   Apply only the approved file with `liwm install apply --plan <plan.json>` and
   then run `liwm install verify --plan <plan.json>`. The CLI refuses malformed
   markers or changed preconditions, backs up every overwritten file, performs
   atomic writes, rolls back a partial failure, and is idempotent.

7. Keep the receipt written under ~/.liwm/installations/ and record non-personal
   installation metadata in ~/.liwm/config.json: host, plan ID, and ownership.
   Preserve unknown existing config fields.

8. Validate idempotence and safety:
   - rerun `install apply` and confirm it reports zero file changes;
   - verify all skill SKILL.md files are present;
   - run `liwm doctor --json`, `liwm schema list`, and the repository test runner;
   - confirm user.json and metrics.json are outside Git and no private state was
     copied into the framework checkout;
   - confirm text before and after the bootstrap markers is byte-for-byte
     unchanged from the pre-edit file;
   - run the exact command the installed block tells the agent to run --
     `<liwm> context --capsule --task "<something>"` -- and confirm it returns a
     capsule rather than an error. A block naming a command that does not work
     is worse than no block, because the failure is silent and lands in a
     session months from now;
   - report every created, modified, backed-up, linked, or copied path and the
     validation results.

9. If onboarding is not complete, offer to begin LIWM onboarding now. If I
   accept, load the liwm-onboarding skill and ask exactly ten adaptive questions,
   one at a time. If I decline, remember only that onboarding was offered and
   proceed in AUTO; do not nag. The installed block requests AUTO consultation;
   call it automatic only after that host passes the dated acceptance protocol.
```
