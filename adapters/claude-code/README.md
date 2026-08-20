# Claude Code adapter

LIWM installs into Claude Code as **user-level Agent Skills** plus a small
delimited block in the global instruction file. No hooks, no background process,
no daemon.

## Why this shape

Claude Code hooks (`SessionStart`, `UserPromptSubmit`) **cannot inject text into
the model's context** — `systemMessage` is informational output shown to the
user, not added to the prompt. The two mechanisms that genuinely reach the model
every session are:

1. `~/.claude/CLAUDE.md` — always loaded;
2. skill `name` + `description` — always loaded; the body loads on invocation.

So LIWM uses a compact bootstrap block in (1) that routes to (2). The bulk of
the framework never touches the context window until it is needed.

## Layout after installation

```
~/.claude/
├── CLAUDE.md              # + one delimited LIWM block (everything else untouched)
└── skills/
    ├── liwm/              # router — the only rich description
    │   ├── SKILL.md
    │   └── references/
    ├── liwm-onboarding/
    ├── liwm-profile/
    ├── liwm-intent-discovery/
    ├── liwm-question-planner/
    ├── liwm-project-intent/
    ├── liwm-counterfactual/
    ├── liwm-feedback/
    ├── liwm-learning/
    ├── liwm-retrospective/
    ├── liwm-profile-maintenance/
    ├── liwm-traceability/
    ├── liwm-evaluation/
    ├── liwm-privacy/
    └── liwm-self-improvement/

~/.liwm/                   # private data — never in a repository
```

Skills may be **symlinks** to a single checkout (preferred on macOS/Linux, so
`liwm update` is a `git pull`) or **copies** (Windows without Developer Mode).
The installer decides and records which in `~/.liwm/config.json`.

## The bootstrap block

Delimited by the markers in `bootstrap.md`, so update and uninstall can find and
replace exactly their own block and nothing else. Under 1.5 KB, because it is
paid for on every single turn.

## Frontmatter portability

LIWM skills use only `name`, `description`, `license`, `metadata` — the
intersection of what Claude Code and Codex both accept. Claude Code additionally
supports `allowed-tools`, `argument-hint`, `model`, `context: fork` and more;
LIWM deliberately uses none of them so one skill directory serves both hosts.

## Optional: install as a plugin

`.claude-plugin/plugin.json` at the repository root lets the whole bundle be
added via Claude Code's plugin system instead of copied skill directories. The
bootstrap block is still needed for automatic activation.

## Verifying

```bash
liwm doctor          # reports claude_code_present and the config dir it found
ls ~/.claude/skills  # should list liwm and liwm-*
```

In a fresh Claude Code session, `/liwm` should be available, and asking
"what does LIWM know about me?" should trigger the router without an explicit
invocation.

## Sources

- Skills: https://code.claude.com/docs/en/slash-commands
- Memory / CLAUDE.md precedence and `@` imports: https://code.claude.com/docs/en/memory.md
- Settings and `CLAUDE_CONFIG_DIR`: https://code.claude.com/docs/en/settings.md
- Plugins: https://code.claude.com/docs/en/plugins-reference.md
- Hooks (and why they are not used here): https://code.claude.com/docs/en/hooks.md
