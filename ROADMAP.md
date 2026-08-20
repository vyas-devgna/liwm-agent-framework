# Roadmap

## Shipped in 0.3 — correctness and measurement

0.3 closed the gaps between what the framework documented and what it did:
one tombstone rule shared by every projection, effective confidence that
decays, human outcomes derived from their evidence, an installation journal
that survives process death, a benchmark suite that can fail, shrinkage instead
of a threshold in question learning, and a legitimate way for a candidate rule
to earn human evidence. See [CHANGELOG.md](CHANGELOG.md).

The architecture should now stay still while evidence catches up. Another
thirty modules is not what stands between LIWM and being worth using.

## Next — evidence, not features

The only work that moves the score now is measurement.

- run the 20–40 person falsification alpha in [docs/RESEARCH.md](docs/RESEARCH.md);
- delete whatever the alpha shows is not earning its complexity;
- HumanIntentBench: consented, blinded, anonymised cases with automatic leakage
  checking. Schemas and tooling only until real consented data exists — the
  repository will not ship invented participants;
- host acceptance manifests for each documented adapter, so "documented" and
  "verified on a live host" stay visibly different claims;
- publish a release, and get the framework in front of people who did not write it.

## Then — retrieval and ranking

Kept behind the existing interfaces, and behind evidence that the simple
version is insufficient.

- pluggable local embedding/vector retrieval with lexical fallback;
- pairwise preference ranking and active-learning selection;
- empirically calibrated uncertainty behind the existing interfaces;
- optional OS-keyring-backed profile encryption;
- multi-profile separation.

### On optional dependencies

The core profile engine stays standard-library-only: that is what makes LIWM
installable wherever the host agent runs. Embeddings, signing and ranking will
arrive as **optional extras**, not as a reason to refuse capability the
research needs. A zero-dependency badge is not worth a research result, and
declining to measure something in order to protect it would be the wrong trade.
Development dependencies — ruff, coverage — are already in place and are not
part of that promise.

## World-model research target

Framework 0.x is an evidence-based persistent intent and personalization layer:
a deterministic graph/state engine, not a learned generative world model. The
intent graph is a typed provenance graph with four state-changing edge types;
everything else in it is descriptive by design, because an opaque inference
engine would cost the inspectability that is the point. A
future model may represent intent state `I_t`, action `A_t`, context `C_t`,
response `R_t`, and next intent state `I_{t+1}`, approximating:

```text
P(R_t, I_{t+1} | I_t, A_t, C_t)
```

It must beat the transparent deterministic baselines on held-out prediction,
calibration, transfer, and safety **on real human data** before replacing them.
The symbolic framework is the baseline, not technical debt, and no learned
backend becomes the default by being newer. Current belief
confidence and question utility must not be relabelled as estimates of that
distribution.

## Later research

- multimodal evidence with explicit provenance;
- team intent models with access boundaries;
- external evaluators and reproducible benchmark packs;
- user-authorized fine-tuning or preference-optimization exports.

No roadmap item may weaken guarded-path privacy/provenance policy, make
telemetry default, or require a cloud service for LIWM core.

---

[LIWM](README.md) · [Research](docs/RESEARCH.md) ·
[Host acceptance](docs/HOST_ACCEPTANCE.md) · [Privacy](PRIVACY.md)
