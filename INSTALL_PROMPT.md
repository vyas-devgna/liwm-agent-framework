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
   so later runs recognise it. Inspect current local conventions and, when
   uncertain, current official host documentation. Do not guess a config path.
   Use platform home/config APIs rather than hard-coding /home or C:\Users.

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

5. If the host supports Agent Skills, install every `skills/liwm*` directory at
   user scope:
   - Claude Code: the resolved user config directory's `skills/` directory,
     normally ~/.claude/skills/.
   - Codex: ~/.agents/skills/ (not ~/.codex/skills).
   - Generic host: its documented user-level Agent Skills directory.
   Test whether the filesystem actually supports symlinks rather than inferring
   it from the OS name (`liwm doctor --json` reports platform.supports_symlinks
   and platform.filesystem_case_sensitive). Prefer per-skill directory symlinks;
   otherwise copy each complete skill directory. On Windows, use directory
   junctions or copies according to available privileges. On a case-insensitive
   filesystem, treat skill names as case-insensitive so you never clobber one
   directory with another. Never delete unrelated skills. Replace only an
   existing LIWM-managed link/copy after backing it up. If the host has no skills
   mechanism, skip this step and use the standalone block in step 6, which
   carries the routing rules inline.

6. Add automatic activation through the host's active global instruction file:
   - Claude Code: ~/.claude/CLAUDE.md (respect CLAUDE_CONFIG_DIR).
   - Codex: $CODEX_HOME/AGENTS.override.md if it is the active non-empty global
     file; otherwise $CODEX_HOME/AGENTS.md (CODEX_HOME defaults to ~/.codex).
   - Generic host: its documented global user instruction file.
   Choose the block: `adapters/<host>/bootstrap.md` for a skills-capable host,
   `adapters/blocks/standalone.md` for a host without skills, and
   `adapters/blocks/compact.md` where the host has a tight instruction budget.
   Run `liwm hosts plan --host <id> --block <path>` first: it prints every file
   that would be touched and the byte-budget arithmetic. If the block plus the
   file's existing content would exceed the host's documented budget, use the
   compact block; never truncate the user's own instructions to make room.
   Replace `{{LIWM_COMMAND}}` with the absolute command from step 3, and insert
   exactly one block delimited by `<!-- LIWM:BEGIN ... -->` and
   `<!-- LIWM:END -->`.
   Before any edit, make a timestamped sibling backup. If a complete LIWM block
   already exists, replace only that block; do not append a duplicate. If only
   one marker exists or markers are nested, stop and report the malformed file.
   If no instruction file exists, create it. Never overwrite, reorder, reformat,
   or remove text outside the markers.

7. Record non-personal installation metadata in ~/.liwm/config.json: framework
   version/checkout, exact CLI command, host, skill destination, install method
   (symlink/junction/copy), instruction file, bootstrap version, and install time.
   Preserve unknown existing config fields.

8. Validate idempotence and safety:
   - rerun the installation checks without creating another bootstrap block;
   - verify all skill SKILL.md files are present;
   - run `liwm doctor --json`, `liwm schema list`, and the repository test runner;
   - confirm user.json and metrics.json are outside Git and no private state was
     copied into the framework checkout;
   - confirm text before and after the bootstrap markers is byte-for-byte
     unchanged from the pre-edit file;
   - report every created, modified, backed-up, linked, or copied path and the
     validation results.

9. If onboarding is not complete, offer to begin LIWM onboarding now. If I
   accept, load the liwm-onboarding skill and ask exactly ten adaptive questions,
   one at a time. If I decline, remember only that onboarding was offered and
   proceed in AUTO; do not nag. Future sessions must use AUTO automatically
   without requiring me to mention LIWM.
```
