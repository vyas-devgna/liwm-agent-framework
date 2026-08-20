# LIWM CLI reference

Every command accepts `--json` (machine-readable) and `--home <path>`.
Without `--json` the output is compact human-readable text.

## Session flow

```bash
liwm context --json --domain <d> --project <p> --task "<t>"   # start of task
liwm plan    --json --mode <m> --domain <d> --risk 0.6        # what to ask
liwm assume  "<assumption>" --impact high --project <p>       # before acting
liwm feedback --json --kind <k> --channel <c> --project <p>   # after reacting
liwm retro <session-id> --project <p>                         # end of work
```

### `context` signal flags

`--intent-uncertainty` · `--novelty` · `--consequence` · `--reversibility` ·
`--specification-completeness` · `--recent-correction-rate` · `--fatigue`
(all 0–1), plus `--stage inception|design|build|refine|debug|maintenance`.

Or pass them together: `--signals '{"intent_uncertainty":0.8,"novelty":0.6}'`

## Recording evidence

```bash
liwm observe --dimension <dotted.name> --value <v> \
  --source <source_type> --provenance <provenance> \
  [--scope global|domain|project] [--scope-key <k>] \
  [--polarity support|oppose] [--decay none|slow|standard|volatile] \
  [--note "<why>"] [--session <s>] [--project <p>] [--domain <d>]
```

**Source types** (weight → ceiling): `explicit_statement` 1.00→0.98 ·
`explicit_correction` 1.00→0.98 · `explicit_rejection` 1.00→0.98 ·
`direct_edit` 0.90→0.92 · `repeated_selection` 0.80→0.88 ·
`comparative_choice` 0.75→0.82 · `onboarding_answer` 0.70→0.70 ·
`repeated_behavioral` 0.65→0.78 · `outcome_signal` 0.55→0.72 ·
`single_behavioral` 0.30→0.55 · `agent_inference` 0.15→0.15

**Provenance** — trusted: `direct_user_message`, `direct_user_edit`,
`explicit_user_review`, `onboarding_answer`, `agent_inference`.
Zero-trust (quarantined): `tool_output`, `repository_content`,
`external_document`, `web_content`, `mcp_result`, `subagent_report`,
`synthetic_test`, `other`.

## Projects

```bash
liwm project init     --project <p> --name "<n>" --domain <d>
liwm project add      --project <p> --section <s> --text "<t>" --origin <o> [--confidence 0.4]
liwm project stage    --project <p> --text <stage>
liwm project decision --project <p> --text "<what>" --rationale "<why>" \
                      --evidence <id> --alternative "<other>" [--impact high] [--irreversible]
liwm project show     --project <p> [--raw]
liwm project delete   --project <p>
```

Sections: `objectives` `latent_objectives` `desired_experience` `anti_goals`
`non_negotiables` `preferences` `constraints` `technical_constraints`
`inspirations` `rejected_directions` `emotional_targets` `assumptions`
`open_questions` `implementation_implications`

Origins: `USER_SAID` · `AGENT_INFERRED` · `AGENT_DERIVED`

## Onboarding

```bash
liwm onboarding start
liwm onboarding next --json
liwm onboarding answer --question-id <id> --text "<answer>" \
     --observation '{"dimension":"...","value":"..."}'
liwm onboarding complete --text "<summary>"
liwm onboarding correct --dimension <d> --value <v> --text "<why>"
liwm onboarding status --json
```

## Inspection and control

```bash
liwm profile [--raw] [--section <s>]     liwm why "<query>"
liwm stats                                liwm contradictions
liwm assumptions [--project <p>]          liwm constitution [--full]
liwm reject --dimension <d> --value <v> --reason "<r>"
liwm forget --dimension <d> | --belief <k> | --project <p>
liwm export [--out <path>] [--anonymise] [--include-events]
liwm reset [--hard --yes]
```

## Maintenance

```bash
liwm init [--allow-in-repo]    liwm doctor      liwm verify
liwm hosts [list|detect|plan --host <id> --block <path>]
liwm rebuild [--as-of <ts>]    liwm migrate     liwm schema list
liwm events stats|verify|tail [--limit N] [--include-quarantined]
```

## Self-improvement

```bash
liwm rules list [--state <s>] [--include-rejected]
liwm rules replay  --id cand_<id>
liwm rules promote --id cand_<id>
liwm rules revert  --id cand_<id> --reason "<r>"
liwm eval modes | converge --archetype <a> --rounds N
```

## Exit codes

`0` success · `1` error · `2` usage error
