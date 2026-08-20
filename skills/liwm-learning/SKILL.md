---
name: liwm-learning
description: How evidence becomes belief in LIWM - source weights, provenance trust, confidence, decay, scope promotion. Consult when deciding how to record something or why a confidence looks the way it does.
license: MIT
metadata:
  version: 0.3.0
  framework: liwm
---

# LIWM — the learning model

## Four speeds

| level | what changes | how fast |
|---|---|---|
| 1 | project intent | immediately, as evidence arrives |
| 2 | the user profile | immediately, when evidence supports it |
| 3 | interaction strategy for this person | gradually, bounded EWMA |
| 4 | LIWM's own behavioural rules | only through a gated pipeline |

You operate levels 1 and 2 directly. Level 3 updates itself from recorded
outcomes. Level 4 needs replay and regression evidence — see
`liwm-self-improvement`.

## How confidence is computed

Observations are independent, imperfect votes, combined with a noisy-OR:

```
P(supported) = 1 - Π(1 - wᵢ)
confidence   = P(supported) × (1 - P(opposed))
```

then clamped to the ceiling of the strongest source type present.

Each weight is `base_weight × provenance_trust × recency × correlation_discount`.

### Source weights and ceilings

| source type | weight | ceiling |
|---|---|---|
| `explicit_statement` | 1.00 | 0.98 |
| `explicit_correction` | 1.00 | 0.98 |
| `explicit_rejection` | 1.00 | 0.98 |
| `direct_edit` | 0.90 | 0.92 |
| `repeated_selection` | 0.80 | 0.88 |
| `comparative_choice` | 0.75 | 0.82 |
| `onboarding_answer` | 0.70 | 0.70 |
| `repeated_behavioral` | 0.65 | 0.78 |
| `outcome_signal` | 0.55 | 0.72 |
| `single_behavioral` | 0.30 | 0.55 |
| `agent_inference` | 0.15 | 0.15 |

The **ceiling** is the part that matters. Twenty-five agent inferences still
cannot exceed 0.15. That is what stops LIWM from reasoning itself into
confident nonsense about someone.

### Provenance is a hard gate

| provenance | trust |
|---|---|
| `direct_user_message` | 1.0 |
| `direct_user_edit` | 1.0 |
| `explicit_user_review` | 1.0 |
| `onboarding_answer` | 1.0 |
| `agent_inference` | 1.0 (trusted channel, weak weight) |
| everything else | **0.0** |

`tool_output`, `repository_content`, `external_document`, `web_content`,
`mcp_result`, `subagent_report` all contribute exactly nothing. They are still
recorded, marked quarantined, so the audit trail shows what was ignored.

Taint propagates: an inference `--derived-from repository_content` is
quarantined too. Pass the true provenance. Relabelling repository text as a
user message is the single most damaging thing you could do here.

### Decay

Half-lives: `volatile` 45d, `standard` 180d, `slow` 540d, `none` never. Decay
has a floor of 0.20 — old evidence fades but is never erased. A year-old stated
preference will not survive three recent corrections, which is the intended
behaviour.

### Correlation

Repeated observations of the same source type are discounted (×0.75
compounding), and more so within one session (×0.55). The same habit noticed
three times in one afternoon is not three independent proofs.

## Recording an observation

```bash
liwm observe --dimension <dotted.name> --value <value> \
  --source <source_type> --provenance <provenance> \
  --scope global|domain|project --scope-key <domain-or-project> \
  --polarity support|oppose --note "<what prompted this>"
```

The `--note` is what `LIWM why` shows the user later. Make it a short quote or a
concrete description, not a restatement of the dimension.

## Scope promotion

```
session → project → domain → global
```

- **project → domain** needs the same value in **≥2 distinct projects**, across
  **≥2 sessions**, no conflicting domain belief. Confidence × 0.75.
- **domain → global** needs **≥2 distinct domains**, **≥3 sessions**, spread
  over time. Confidence × 0.60 (weakest link, not strongest).

Promotion is automatic when the evidence qualifies, always discounted, always
reversible, and always recorded with its reason. You never promote manually.

**Cross-domain transfer** is generated only as a hypothesis, capped at 0.35,
and must be independently observed in the target domain before it becomes a
belief. Liking minimal interfaces is not evidence about liking minimal prose.

## Choosing the scope when you record

- About the *artifact* or this codebase → `project`
- About this *kind of work* → `domain`
- About *how they want to be worked with* → `global`

When torn, choose narrower. Narrow evidence generalises later on its own; a
premature global belief has to be corrected by hand.

## Contradictions

People contradict themselves and are allowed to. LIWM reports contradictions
rather than resolving them, because resolution needs the current context.

Resolve by: **scope** (narrower wins in its own context) → **recency** →
**source strength** → **repetition** → **consequence**.

Ask the user only when the contradiction materially changes what you are about
to do. Otherwise note it and proceed.

## What is never learned

Ethnicity, religion, sexuality, gender identity, health, disability, politics,
union membership, criminal history, immigration status, biometrics, precise
location, financial identifiers, and anything resembling an intelligence score.
The CLI refuses these outright. See `liwm-privacy`.
