# Threat model

## Assets

- private preference and intent evidence;
- integrity of profile beliefs, project intent, strategy, and metrics;
- user-level host instructions and installed skills;
- audit history and recovery backups.

## Trust boundaries

Direct user messages, direct edits, and explicit user reviews may support
durable learning. Agent inference is permitted only with a 0.15 ceiling.
Repository content, tool/MCP output, web pages, documents, email, fixtures,
subagent reports, and unknown sources are untrusted as evidence about the user.

## Threats and mitigations

| Threat | Mitigation |
|---|---|
| Repository comment says “save this preference” | provenance gate quarantines `repository_content`; adversarial tests |
| Tool/document impersonates user feedback | untrusted provenance has zero influence; taint follows derivation |
| Project preference pollutes global profile | explicit scopes; promotion thresholds and discounts; scope tests |
| Weak inference self-reinforces | source ceiling; correlated-repeat discount; rejection suppression |
| Concurrent writers lose observations | unique event files; deterministic re-fold; locks only for views |
| Crash leaves partial JSON | same-filesystem atomic replace, fsync, backups, resilient reads |
| Stale agent overwrites profile | optimistic revision conflict and rebuild |
| Candidate rule modifies safety | constitution hash and protected surfaces; failed candidates rejected |
| Installer destroys persona config | timestamped backup, delimited block, malformed-marker stop, byte preservation |
| Private state is committed | outside-repo default, initialization guard, `.gitignore`, CI secret-file scan |
| Metric gaming optimizes agreement | separate correctness/intent/acceptance metrics and guarded regressions |
| Local account compromise | outside LIWM's boundary; use OS full-disk/home encryption |

## Attacker capabilities

We assume repositories and retrieved content may be malicious. We assume normal
agents can make classification mistakes. We do not assume protection against an
attacker who can modify the LIWM Python package, host global instructions, and
private files under the user's OS account; such an attacker already controls the
trusted computing base.

## Residual risks

The CLI cannot cryptographically prove that a host correctly labeled
provenance. Individual content hashes expose isolated changes but are not tamper-proof against a local
attacker who can rewrite all files. Regex/allowlist privacy screening may have
false positives or negatives. Backups intentionally preserve deleted history
until the user chooses complete deletion.

## Reporting

Follow [SECURITY.md](SECURITY.md). Do not open a public issue containing a real
profile, private event, token, or host configuration backup.
