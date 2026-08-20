# Roadmap

## 0.2 — research readiness

0.2 is not architecture-frozen. It should make the current representation and
claims adequate for prospective evaluation while preserving the event,
provenance, privacy, and scope contracts.

- explicit intent graph relationships and inspectable retrieval;
- committed preference predictions with evaluator provenance and calibration;
- deterministic install/apply/verify/uninstall plans; repair is idempotent
  re-application and changed preconditions require a regenerated plan;
- bounded compaction and retention without losing audit semantics;
- IntentBench cases, leakage checks, baselines, and run manifests;
- opt-in local study mode with minimized reviewed exports and no upload;
- documented host acceptance protocols and evidence-tiered claims;
- prospective, consented within-subject and longitudinal studies;
- correctness and intent-fidelity outcomes kept separate from acceptance;
- stronger provenance attestation and adversarial/concurrency coverage.

Synthetic benchmark and replay results remain mechanism checks. 0.2 does not
claim human effectiveness until a controlled preregistered study supports it.

## 0.3 — local retrieval and probabilistic ranking

- pluggable local embedding/vector retrieval with lexical fallback;
- pairwise preference ranking and active-learning selection;
- empirically calibrated uncertainty behind the existing interfaces;
- optional OS-keyring-backed profile encryption.

## World-model research target

Framework 0.x is an evidence-based persistent intent and personalization layer:
a deterministic graph/state engine, not a learned generative world model. A
future model may represent intent state `I_t`, action `A_t`, context `C_t`,
response `R_t`, and next intent state `I_{t+1}`, approximating:

```text
P(R_t, I_{t+1} | I_t, A_t, C_t)
```

It must beat the transparent deterministic baselines on held-out prediction,
calibration, transfer, and safety before replacing them. Current belief
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
