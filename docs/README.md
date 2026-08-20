<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../assets/mark-dark.png">
  <img src="../assets/mark.png" width="72" alt="LIWM">
</picture>

# LIWM documentation

</div>

---

## Start here

| | |
|---|---|
| **[Main README](../README.md)** | What LIWM is, what it is not, and why the representation matters more than the memory |
| **[INSTALL_PROMPT.md](../INSTALL_PROMPT.md)** | The prompt you paste into your agent. There is no install script, on purpose |
| **[Troubleshooting](TROUBLESHOOTING.md)** | When something looks wrong |

## Understanding it

| | |
|---|---|
| **[Architecture](../ARCHITECTURE.md)** | Event sourcing, the scope lattice, confidence, question utility, and the self-improvement gates |
| **[Design decisions](DECISIONS.md)** | What was chosen, and what was rejected to choose it |
| **[Profile schema](PROFILE_SCHEMA.md)** | Field-by-field reference for `user.json` |
| **[Versioning](VERSIONING.md)** | What a version number promises and what it does not |

## Trusting it

| | |
|---|---|
| **[Privacy](../PRIVACY.md)** | What is stored, what is refused, what never leaves the machine |
| **[Threat model](../THREAT_MODEL.md)** | Attacker capabilities, mitigations, mapping to OWASP ASI06, and the residual risks |
| **[Security policy](../SECURITY.md)** | How to report something |
| **[Encryption design](ENCRYPTION.md)** | Designed, not shipped. Read this before assuming otherwise |

## Extending it

| | |
|---|---|
| **[Host adapters](../adapters/README.md)** | Every supported agent, and how to add one in eight lines of JSON |
| **[Research protocol](RESEARCH.md)** | The study that would actually establish whether this works |
| **[Roadmap](../ROADMAP.md)** | Where it is going, and what is deliberately not in 0.1.0 |
| **[Contributing](../CONTRIBUTING.md)** | How to help |
| **[Brand assets](../assets/README.md)** | The elephant, and the rules it lives by |

---

## The short version

LIWM keeps an append-only log of *typed evidence* about how one person works.
`user.json` is a cache folded deterministically from that log, never the source
of truth. Every belief carries where it came from, how strong that source is
allowed to make it, how fast it decays, and which projects it applies to.

Four ideas do most of the work:

**Provenance decides trust, not the caller.** Repository text, web pages, tool
output, MCP results and subagent reports carry trust `0.0`. Claiming a strong
source type for a `README` does not help.

**Ceilings stop self-reinforcement.** `agent_inference` caps at 0.15 however
often it recurs. An agent cannot cite its own guess into a fact.

**Scope does not leak upward.** A preference learned on one project stays there
until evidence from several projects promotes it, at a discount.

**Predictions come before outcomes.** `liwm predict` commits to a number before
you react; `liwm resolve` scores it. Without that, "it is learning" is a claim
nobody can check.

---

<div align="center">
<sub>

[← Back to the main README](../README.md)

</sub>
</div>
