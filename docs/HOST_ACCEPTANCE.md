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

## Acceptance record

No host acceptance record ships yet. The repository therefore describes its
current host entries as documented adapters or manual integrations. Add a dated
record here only after the complete protocol passes; downgrade the claim when a
later host version fails.

Official references should be rechecked on every acceptance run:

- [Claude Code hooks](https://code.claude.com/docs/en/hooks)
- [Codex hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex skills](https://learn.chatgpt.com/docs/build-skills)
- [Codex AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
