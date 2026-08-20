# Evidence and provenance

## Source weights and ceilings

| source | initial weight | durable-confidence ceiling |
|---|---:|---:|
| explicit user statement | 1.00 | 0.95 |
| explicit correction/rejection | 1.00 | 0.99 |
| direct user edit | 0.90 | 0.90 |
| repeated alternative selection | 0.80 | 0.85 |
| repeated behavioral signal | 0.65 | 0.70 |
| single implicit behavioral signal | 0.30 | 0.30 |
| agent inference | 0.15 | 0.15 |

Correlated repetitions are discounted. Repeated agent inferences never bootstrap
themselves beyond the inference ceiling. Recency decay changes active influence,
not history: old evidence remains auditable.

## Provenance gate

Trusted for possible durable user learning:

- `direct_user_message`
- `direct_user_edit`
- `explicit_user_review`
- `agent_inference` (always weak, with both weight and hard ceiling at 0.15)

Never trusted as evidence about the user:

- `tool_output`
- `repository_content`
- `external_document`
- `synthetic_test`
- `other`

Derived evidence inherits taint from every ancestor. Never relabel a source to
make it pass the gate. A user can explicitly endorse third-party content in a
new direct message; the endorsement, not the document, is the evidence.

## Scope

Default ambiguous work feedback to project scope. Promote only after repeated,
independent observations across contexts. Current explicit instructions always
override every historical belief without rewriting history.
