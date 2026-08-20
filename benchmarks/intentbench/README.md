# IntentBench

IntentBench is LIWM's benchmark contract, not evidence that personalization
works for people. The shipped smoke suite is synthetic and tests only adapter,
runner, and scoring plumbing. Its projection adapter replays visible fixture
scores; it does not exercise LIWM state, scope, traceability, or quarantine.

Every case separates `exposed_to_liwm` from `hidden_ground_truth`. An adapter
receives only the participant view: case ID, task type, visible inputs, and
candidate outputs. Ground truth and `observed_choice` remain scorer-only.

## Conditions

Human studies should preregister these comparisons where the host supports
them: base model with no memory (A), plain Markdown memory (B), host-native
memory (C), static LIWM profile (D), LIWM without elicitation (E), and full LIWM
(F). Condition E requires a real no-question ablation; `liwm mode off` is not
equivalent because it also disables consultation and learning.

Record dataset kind, seed, code revision, host/model/version, adapter, metric
definitions, and run time. Synthetic results must retain the label
`synthetic_scorer_contract_smoke`. Human cases must be consented, minimized,
reviewed before sharing, and stored outside the repository unless explicitly
approved for release.

Run the smoke suite with:

```bash
python -m liwm --json eval intentbench
```
