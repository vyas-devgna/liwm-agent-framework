# Privacy

## Defaults

- LIWM core stores and computes profile state locally.
- Telemetry is absent and fixed to `disabled` in configuration.
- No hosted database, account, or proprietary backend is required.
- LIWM performs no automatic upload. Export requires an explicit local command.
- Actual profiles are excluded by `.gitignore` and initialization inside Git is
  refused by default.

## What LIWM stores

LIWM stores intelligible summaries: evidence provenance, scoped preference or
intent values, confidence, decisions, assumptions, predicted outcomes, feedback,
and aggregate metrics. It does not store model hidden reasoning.

With free-text storage disabled, LIWM drops incidental prose fields such as
quotes and notes. Structured semantic strings, including belief values, may
still be stored because they are the model's content. Anonymised export is an
allowlisted, minimized view, not a promise of anonymity: distinctive event or
metric patterns may still permit linkage. Review every export before sharing.

When LIWM is integrated into a hosted agent, the selected runtime projection may
be included in that agent's model context and handled under the host/provider's
privacy policy. “Local-first” describes LIWM core storage and I/O; it does not
override the host's data path. Processes running with the same filesystem
authority can also read the raw LIWM files.

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
- opt-in study view: `liwm study on`, `liwm study export --anonymise`, `liwm study off`
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

Study mode is off by default and derives a minimized view from this same event
log; it creates no second telemetry store. Its retention window controls what a
study export includes, not deletion from the source event history. LIWM never
uploads study exports. Anonymisation pseudonymizes identifiers and coarsens time,
but remains risk reduction rather than an unlinkability guarantee.

## Encryption

v0.1.0 relies on operating-system account and disk protections. The design for
optional at-rest encryption is documented in [docs/ENCRYPTION.md](docs/ENCRYPTION.md);
it is intentionally not marketed as implemented.

---

<div align="center">
<sub>

[LIWM](README.md) · [Docs index](docs/README.md) · [Architecture](ARCHITECTURE.md) · [Privacy](PRIVACY.md) · [Threat model](THREAT_MODEL.md) · [Roadmap](ROADMAP.md)

</sub>
</div>
