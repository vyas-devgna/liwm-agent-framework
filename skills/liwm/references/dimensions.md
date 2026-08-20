# LIWM dimension taxonomy

Use stable, actionable dimensions. Never create intelligence scores, personality
types, diagnoses, or protected-attribute fields.

## Global interaction dimensions

- `interaction_profile.preferred_verbosity`
- `interaction_profile.preferred_directness`
- `interaction_profile.preferred_question_frequency`
- `interaction_profile.technical_language_preference`
- `interaction_profile.explanation_depth`
- `interaction_profile.examples_vs_first_principles`
- `interaction_profile.pace`
- `interaction_profile.challenge_level`
- `interaction_profile.autonomy_preference`
- `interaction_profile.confirmation_preference`

## Reasoning and creative dimensions

- `reasoning_profile.abstraction_comfort`
- `reasoning_profile.systems_thinking_preference`
- `reasoning_profile.exploration_vs_execution`
- `reasoning_profile.ambiguity_tolerance`
- `reasoning_profile.evidence_preference`
- `reasoning_profile.tradeoff_style`
- `creative_profile.novelty_seeking`
- `creative_profile.conventionality_tolerance`
- `creative_profile.aesthetic_direction`

## Domain-specific dimensions

Use a domain scope and key, for example `domain_fluency.programming` with
`--scope domain --scope-key software`. Keep mathematical, programming,
vocabulary, and conceptual-uptake observations domain-specific unless the user
explicitly generalizes them.

## Scope test

Before recording, ask: would this still be true if the current project changed?
If uncertain, use project scope. Project-to-domain and domain-to-global transfer
must start as a reduced-confidence hypothesis and requires independent evidence.

## Values

Prefer compact semantic values (`terse`, `direct`, `examples_first`) over prose.
Put necessary context in the evidence note. Do not invent precision: ordinal or
categorical values are usually more honest than decimals produced by an LLM.
