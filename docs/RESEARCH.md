# Research instrumentation

LIWM records local, aggregate measurements for first-pass acceptance,
corrections, revisions, question value, assumption error, prediction
calibration, cross-domain transfer, mode behavior, profile confidence, candidate
promotion, and rolling improvement.

`liwm eval modes` tests behavioral distinguishability. `liwm eval converge`
runs deterministic synthetic archetypes that expose hidden preferences only to
the simulator. These archetypes are fixtures, never labels for real users.
Replay compares current and candidate question policies on recorded episodes.

Interpretation constraints:

- simulated and replay metrics are estimates, not counterfactual ground truth;
- fewer than 20 samples is reported as thin evidence;
- acceptance is distinct from technical correctness and intent fidelity;
- prospective A/B or crossover studies are needed for causal claims;
- raw interactions are never exported automatically.

For a manual research dataset, run `liwm export --anonymise --out <reviewed-path>`.
Inspect the output before sharing. A useful future protocol should compare
personalized vs non-personalized behavior, pre/post onboarding, and all four
modes while stratifying by task consequence and reversibility.
