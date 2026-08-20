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

## Mapping to OWASP ASI06

The [OWASP Top 10 for Agentic Applications](https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications-the-benchmark-for-agentic-security-in-the-age-of-autonomous-ai/)
names memory and context poisoning as ASI06, distinguishing it from ordinary
prompt injection by two structural properties. LIWM is designed against both.

**Persistence** — poisoned content survives the session that planted it. A
[University of Washington study](https://arxiv.org/html/2607.14611v1) found that
agents correctly refuse a malicious instruction in the moment and then retain it
in their memory file, where it influences later sessions. LIWM's answer is that
refusal is a *storage* decision, not a conversational one: an observation whose
provenance is untrusted is written as a quarantined event and can never be
folded into a belief, so "the agent declined but wrote it down anyway" is not a
reachable state.

**Temporal decoupling** — the write and the effect are separated by weeks, so
the harm surfaces far from its cause. LIWM keeps the two connected: every belief
carries `evidence_refs` back to the events that produced it, and `liwm why`
prints them. A belief that appeared without a legitimate source is visible as
such rather than indistinguishable from a legitimate one.

The defences the ASI06 literature converges on — trust scoring, provenance
tracking at write time, and trust-aware retrieval — correspond to
`PROVENANCE_TRUST`, the gate in `make_event`, and scope-resolved context
projection respectively.

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
