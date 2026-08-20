# Security policy

## Supported versions

The latest tagged 0.x release receives security fixes. During alpha, fixes may
require a schema migration and will be documented in the changelog.

## Report a vulnerability

Do not open a public issue containing a real profile, event, export, credential,
or host configuration. Use GitHub's private vulnerability reporting for
`vyas-devgna/liwm-agent-framework`. Include affected version, reproduction with
synthetic data, impact, and suggested mitigation if known.

You should receive acknowledgment within seven days. Please allow a reasonable
remediation window before disclosure. This project does not offer a bug bounty.

## In scope

Profile poisoning, provenance bypass, sensitive-attribute persistence, scope
contamination, destructive prompt installation/uninstallation, unsafe path
handling, concurrency data loss, integrity/recovery defects, export leakage,
and candidate-rule bypasses are security-relevant.

## Safe testing

Use a temporary `LIWM_HOME` and synthetic data. Do not test against another
person's profile or modify their agent configuration without permission.

---

<div align="center">
<sub>

[LIWM](README.md) · [Docs index](docs/README.md) · [Architecture](ARCHITECTURE.md) · [Privacy](PRIVACY.md) · [Threat model](THREAT_MODEL.md) · [Roadmap](ROADMAP.md)

</sub>
</div>
