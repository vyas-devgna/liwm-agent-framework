# Profile schema guide

`schemas/user.schema.json` is normative. `user.json` is a compact materialized
view, not an event transcript.

Top-level metadata identifies the schema/profile, revision, fold source, and
constitution. `beliefs[]` is the normalized evidence-backed representation.
Convenience sections (`interaction_profile`, `reasoning_profile`,
`creative_profile`, `domain_fluency`, working/decision style, goals,
preferences, and anti-preferences) are projections for agents and humans.

Every belief includes:

- stable ID and canonical key;
- scope (`global`, `domain`, or `project`) and optional scope key;
- dimension and JSON value;
- confidence and its source ceiling/limiting factor; this is heuristic evidence
  strength, not the probability of a future choice;
- support/opposition, evidence and contradiction counts;
- first/last seen timestamps and decay policy;
- source and provenance types;
- bounded evidence references;
- observed/promoted origin, status, rejection, and notes.

Outcome probabilities are separate prediction records committed before an
outcome. Question utility is a separate provisional prioritization heuristic.
Neither should be inferred from a belief confidence field.

Unknown fields are preserved for forward compatibility, while the materializer
only acts on recognized fields. Migration code must explicitly adopt new fields
into active semantics. This prevents an older host from deleting newer data
without allowing unknown fields to silently influence behavior.

---

<div align="center">
<sub>

[LIWM](../README.md) · [Docs index](README.md) · [Architecture](../ARCHITECTURE.md) · [Privacy](../PRIVACY.md) · [Threat model](../THREAT_MODEL.md) · [Roadmap](../ROADMAP.md)

</sub>
</div>
