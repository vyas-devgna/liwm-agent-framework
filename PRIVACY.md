# Privacy

## Defaults

- All profile learning is local.
- Telemetry is absent and fixed to `disabled` in configuration.
- No hosted database, account, or proprietary backend is required.
- Nothing is exported unless the user explicitly requests a local export.
- Actual profiles are excluded by `.gitignore` and initialization inside Git is
  refused by default.

## What LIWM stores

LIWM stores intelligible summaries: evidence provenance, scoped preference or
intent values, confidence, decisions, assumptions, predicted outcomes, feedback,
and aggregate metrics. It does not store model hidden reasoning.

Free text may be disabled in configuration. Anonymized research export strips
profile IDs, event IDs, paths, quotes, notes, and other free text. It is still a
manual export and should be reviewed before sharing.

## What LIWM refuses

LIWM does not infer or persist race, ethnicity, religion, sexuality, medical or
disability status, political affiliation, criminal history, precise location,
or similarly sensitive identity information as personality features. If such
information is needed for a permitted current task, the host may use it only in
that task according to host policy; durable learning remains refused by default.

## Controls

- inspect: `liwm profile`, `liwm events tail`, `liwm why`
- correct: `liwm reject`, explicit replacement evidence
- selectively forget: `liwm forget`
- delete project: `liwm project delete`
- export: `liwm export` or `liwm export --anonymise`
- rebuild/recover: `liwm rebuild`, `liwm verify`
- rollback: `liwm rollback --as-of <timestamp> --yes`
- backup management: `liwm backup create`, `liwm backup list`
- reset: soft reset preserves audit history; hard reset requires `--yes`
- complete deletion: `liwm delete --yes` removes the validated LIWM home without a backup
- disable: `liwm config set --key enabled --value false`

For full removal, use [UNINSTALL_PROMPT.md](UNINSTALL_PROMPT.md), which asks
whether to retain, export, or delete private data and lists any surviving backup.

## Retention and backups

Materialized files are backed up before risky writes and old backups are pruned
to a bounded count. Event history remains until explicit hard deletion because
it provides audit and reconstruction. Forgetting adds a tombstone: it removes
active influence without falsifying history. Fresh direct evidence after that
tombstone may establish a new belief; old pre-tombstone evidence stays inactive.

## Encryption

v0.1.0 relies on operating-system account and disk protections. The design for
optional at-rest encryption is documented in [docs/ENCRYPTION.md](docs/ENCRYPTION.md);
it is intentionally not marketed as implemented.
