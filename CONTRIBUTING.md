# Contributing

LIWM welcomes issues and pull requests that improve observable user intent
fidelity without weakening agency, privacy, provenance, or scope separation.

## Where to start

The most useful contributions right now are not features. The architecture is
deliberately frozen for 0.2 while the evidence catches up with it, so a pull
request that adds a subsystem is likely to be declined on those grounds alone.

These are wanted:

| | |
|---|---|
| **Run the study** | [docs/RESEARCH.md](docs/RESEARCH.md) has the protocol. A negative result is genuinely welcome and more useful than another feature — if H2 or H3 does not hold, parts of this design should be deleted. Open an issue with your design before collecting data and we will help pre-register it. |
| **Break the provenance gate** | `tests/test_security.py` is an adversarial suite. If you find an injection path that reaches a belief, that is the highest-value bug report this project can receive. Report it [privately](SECURITY.md) first. |
| **Correct a host path** | Vendors move their config files. `src/liwm/hosts.py` is a table; a corrected path is a two-line change, and users can already fix it locally via `~/.liwm/hosts.json` while the PR lands. |
| **Add a host** | Any agent that reads a Markdown file at startup can be supported. See [adapters/README.md](adapters/README.md). |
| **Falsify a claim in the docs** | If something in the README is not true of the code, that is a bug and will be treated as one. This has already happened more than once. |

## Development

Python 3.9+ is required; there are no runtime or test dependencies.

```bash
python tests/run_tests.py -v
PYTHONPATH=src python -m liwm eval modes
PYTHONPATH=src python -m liwm eval converge --rounds 10
```

Before a pull request, also run `python tools/validate_repo.py` and build both
sdist and wheel when the `build` package is available. CI runs the suite on
Ubuntu, macOS and Windows across Python 3.9 to 3.14; POSIX-only assumptions are
the most common cause of a red build, and locking, path handling and process
probing are where they hide. Never add real LIWM
profiles, event logs, host instruction files, or exports as fixtures. Synthetic
fixtures must say so in their metadata.

## Design rules

- Current explicit instructions outrank learned hypotheses.
- Default ambiguous evidence to the narrowest scope.
- Preserve truthful provenance; tainted input stays tainted.
- Add confidence ceilings for any new evidence source.
- Store observable summaries, not hidden reasoning.
- Core strategy changes need a candidate and evaluation; do not rewrite skills
  from ordinary feedback.
- New metrics must distinguish estimates from ground truth and must not reward
  agreement at the expense of correctness.
- Keep the zero-cloud, zero-telemetry core and Python standard-library runtime.

## Changes

Add or update tests for behavior, security, migrations, and cross-platform I/O.
Update schemas and migration code together. Update `CHANGELOG.md` under
`Unreleased`. Public APIs follow semantic versioning; schema compatibility is
called out separately because pre-1.0 changes may still require migration.

## Pull requests

Explain the user-visible behavior, evidence model impact, scope/provenance
impact, risks, and validation. Small focused pull requests are easier to audit.
By contributing, you agree to the [Code of Conduct](CODE_OF_CONDUCT.md) and
license your contribution under MIT.

---

<div align="center">
<sub>

[LIWM](README.md) · [Docs index](docs/README.md) · [Architecture](ARCHITECTURE.md) · [Privacy](PRIVACY.md) · [Threat model](THREAT_MODEL.md) · [Roadmap](ROADMAP.md)

</sub>
</div>
