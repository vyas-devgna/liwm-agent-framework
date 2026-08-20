# Roadmap

## 0.2 — hardening and longitudinal evidence

The architecture is deliberately frozen for 0.2. The highest-return work is no
longer scaffolding; it is evidence. See [docs/RESEARCH.md](docs/RESEARCH.md) for
the protocol, baselines and pre-registration expectations.

- the prospective crossover study itself, against built-in host memory as the
  live baseline rather than against "no memory";

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

## 0.4 — from preference state to intent model

Present LIWM models attributes and preferences. The next structural step is an
explicit intent state graph, making the relationships first class rather than
implicit in the taxonomy: goal *conflicts with* anti-goal, preference
*conditional on* context, outcome *implies* constraint, belief *supported by*
evidence, hypothesis *predicts* choice, choice *falsifies* hypothesis, decision
*derived from* intent, dimension *transfers to* domain with probability.

That is what would make the "world model" in the name accurate rather than
aspirational, and the prediction loop shipped in 0.1.0 is the yardstick a
learned model would have to beat.

## Later research

- multimodal evidence with explicit provenance;
- multi-profile and team intent models with access boundaries;
- shared preference policies that never expose private individual evidence;
- external evaluation models and reproducible benchmark packs;
- export formats for user-authorized fine-tuning or preference optimization.

No roadmap item may weaken the immutable constitution, make telemetry default,
or require a cloud service for the core framework.
