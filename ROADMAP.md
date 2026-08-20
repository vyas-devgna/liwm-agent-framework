# Roadmap

## 0.2 — hardening and longitudinal evidence

- prospective, consented personalized-vs-baseline study protocol;
- richer episode capture and correctness/intent-fidelity outcome separation;
- guided selective snapshot restoration with conflict previews;
- stronger provenance attestation between host adapters and CLI;
- property-based and network-filesystem concurrency testing;
- migration fixtures from real prior releases;
- event and episode retention policy (the log is append-only and currently
  unbounded; pruning must preserve deterministic re-folding).

## 0.3 — local retrieval and ranking

- pluggable local embedding/vector retrieval with a lexical fallback;
- pairwise preference-ranking interface;
- active-learning question selector with calibrated uncertainty;
- improved Bayesian or probabilistic evidence backend behind the same schema;
- optional OS-keyring-backed profile encryption.

## Later research

- multimodal evidence with explicit provenance;
- multi-profile and team intent models with access boundaries;
- shared preference policies that never expose private individual evidence;
- external evaluation models and reproducible benchmark packs;
- export formats for user-authorized fine-tuning or preference optimization.

No roadmap item may weaken the immutable constitution, make telemetry default,
or require a cloud service for the core framework.
