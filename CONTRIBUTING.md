# Contributing

LIWM welcomes issues and pull requests that improve observable user intent
fidelity without weakening agency, privacy, provenance, or scope separation.

## Development

Python 3.9+ is required; there are no runtime or test dependencies.

```bash
python tests/run_tests.py -v
PYTHONPATH=src python -m liwm eval modes
PYTHONPATH=src python -m liwm eval converge --rounds 10
```

Before a pull request, also run `python tools/validate_repo.py` and build both
sdist and wheel when the `build` package is available. Never add real LIWM
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
