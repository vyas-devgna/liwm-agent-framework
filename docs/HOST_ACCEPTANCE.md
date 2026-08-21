# Host acceptance protocol

Registry detection and unit tests establish paths and configuration mechanics;
they do not establish that an agent actually consults LIWM. Public host claims
use these evidence tiers:

| Tier | Required evidence | Permitted wording |
|---|---|---|
| Acceptance-tested | protocol below passed on a recorded host/version/OS | “acceptance-tested” |
| Documented adapter | official path/capability research plus registry smoke test | “documented adapter” |
| Generic/manual | convention or user-supplied configuration only | “manual integration” |

Until evidence is recorded, do not say “works with,” “full experience,” or
“automatic” for a host.

## Record for every run

- host name and exact version;
- operating system and LIWM revision;
- installation method and resolved instruction/skills paths;
- test mode and project instruction files in force;
- pass/fail result for each check;
- console transcript or screenshot location, with personal data removed;
- tester and date.

## Claude Code and Codex protocol

Run in a fresh temporary LIWM home and disposable host configuration:

1. Install once, then repeat; verify one bootstrap block and no unrelated byte changes.
2. Start a fresh session and give a non-trivial task without mentioning LIWM;
   verify the host discovers the CLI and obtains runtime context.
3. Verify a trivial task causes no unnecessary context lookup or question.
4. Exercise explicit LOW, MEDIUM, HIGH, AUTO, OFF, and onboarding; record actual
   questions and whether OFF suppresses consultation and learning.
5. Add a project instruction conflicting with a stored preference; verify the
   current/project instruction wins without rewriting global state.
6. Put a fake user preference in repository text and tool output; verify it is
   not recorded as trusted user evidence.
7. Give direct user feedback and verify it uses a trusted user pathway rather
   than repository/tool provenance.
8. Update and verify no duplicate skill or bootstrap entries.
9. Uninstall and verify the bootstrap file's unrelated bytes are restored and
   private-data retention/deletion follows the selected option.

Claude Code currently supports context-producing `SessionStart` and
`UserPromptSubmit` hook output. Codex hooks can also provide additional context
after user review/trust. LIWM currently chooses an inspectable Markdown bootstrap
as the portable baseline; do not justify that choice by claiming hook injection
is impossible.

## Other documented hosts

For Gemini CLI, opencode, Windsurf/Cascade, Zed, Cursor, and Copilot, run a smoke
subset appropriate to their actual scope:

- official instruction location is still valid and loaded;
- block fits the documented budget and preserves existing content;
- the host can execute or be directed to the LIWM CLI;
- current project/user instruction beats stored preference;
- repository text is not treated as user evidence;
- rerun and uninstall preserve unrelated content.

Cursor configuration is manual UI work. Copilot's documented file is
repository-scoped and should be described as project-intent integration, not a
global personal profile. “Any AGENTS.md agent” is a manual convention, not a
product acceptance claim.

## The automatable slice

Most of the protocol above needs a person, a model and a real session. One step
does not: *"the official skills location is still valid and loaded"* is a claim
the host can answer itself, offline, with no credentials. It is also the claim
most likely to rot, because vendors move configuration directories between
releases and LIWM would go on installing into the old one.

```bash
python tools/probe_host.py opencode      # one host
python tools/probe_host.py --all         # everything in the registry
```

The probe builds a throwaway host configuration, stages one real LIWM
`SKILL.md` where the registry says skills go, runs the host's own introspection
command, and reports whether the host found it. It exits non-zero only for a
host that was actually probed and failed — `not_installed` and
`no_introspection` are reported as themselves, because "not checkable this way"
and "checked and fine" are different states and only one of them is evidence.

Passing the probe is **not** acceptance. It establishes that the path is right,
nothing more: it says nothing about whether the agent consults LIWM during real
work, which is what the rest of this document is for.

Only `opencode` currently exposes a non-interactive skills listing. Adding a
host to `INTROSPECTION` in `tools/probe_host.py` is a few lines when one does.

## Acceptance record

No *acceptance* record ships yet — no host has passed the full protocol above,
so the repository still describes its entries as documented adapters or manual
integrations. Add a dated record here only after the complete protocol passes;
downgrade the claim when a later host version fails.

### Path probes

These are path checks, not acceptance. Recorded because they changed the
registry.

| Date | Host | Version | OS | Result |
|---|---|---|---|---|
| 2026-08-21 | opencode | 1.18.20 | Linux 7.1.8-arch1-3 | **loaded** — staged `SKILL.md` reported by `opencode debug skill` |

That probe is why the `opencode` entry now claims `skills: True`. It had been
recorded as having no skills mechanism and was being given the larger
self-contained block; opencode 1.18 has one, and additionally auto-loads
`~/.claude/skills` and `~/.agents/skills`, so skills installed for Claude Code
or Codex are already visible to it.

Two entries were corrected against a real installation rather than a docs page,
and both are marked `community` confidence for that reason:

- **Antigravity** — the published docs give `~/.gemini/GEMINI.md`, which is
  Gemini CLI's file. An installed Antigravity keeps rules at
  `~/.gemini/config/rules/GEMINI.md` with a sibling `skills/` directory.
- **Pi** — the docs describe per-project skills and a `--skill` flag. A real
  install also has a populated `~/.pi/agent/skills/`.

Run `liwm hosts list` to see what resolves on your machine, and correct any of
this with a `hosts.json` overlay in your LIWM home.

Official references should be rechecked on every acceptance run:

- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex skills](https://learn.chatgpt.com/docs/build-skills)
- [Codex AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
