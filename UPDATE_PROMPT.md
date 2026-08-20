# Update LIWM

```text
Update my existing LIWM installation to the latest compatible version from its
recorded framework checkout or from:
https://github.com/vyas-devgna/liwm-agent-framework

Treat this as a prompt-driven update. Do not create or run an installation shell
script. Preserve all private profile data and unrelated host configuration.

1. Locate ~/.liwm/config.json through platform home resolution and inspect the
   recorded checkout, CLI command, host, skill destination, install method, and
   global instruction file. If metadata is missing, safely rediscover it using
   the current official/local host conventions. Verify the repository identity
   before fetching. Stop rather than replacing an unrelated checkout.

2. Before changing anything, make timestamped backups of config.json, user.json,
   metrics.json, learning state, project state, the global instruction file, and
   any copied LIWM skill directories. Never back up or copy unrelated skills.

3. Fetch the remote and fast-forward to the requested/latest stable release. Do
   not discard local modifications: if the checkout is dirty or cannot
   fast-forward, stop and report the exact conflict. Update the private virtual
   environment's editable package without installing optional dependencies.

4. Run the new CLI's migration dry checks, then `liwm migrate`, `liwm rebuild`,
   and `liwm verify`. Migrations must be forward-only, schema-validated, atomic,
   and recoverable from the backups. Do not delete historical events.

5. Refresh only LIWM-managed skill links/copies from `skills/liwm*`. Leave every
   unrelated skill untouched. Read the current matching adapter bootstrap,
   substitute the absolute CLI command, and replace exactly the complete
   `<!-- LIWM:BEGIN ... -->` through `<!-- LIWM:END -->` block. If markers are
   malformed, stop. Never alter text outside the block or create a duplicate.

6. Update only LIWM-owned installation fields in config.json while preserving
   unknown/user fields. Run `liwm doctor --json`, schema validation, the full
   repository test suite, skill validation, and adapter fixture checks. Confirm
   private data remains outside Git and no telemetry or network service was
   enabled.

7. Report old/new versions, commit/tag, every path changed or backed up,
   migrations applied, test results, and any action I need to take. Do not rerun
   onboarding or reset learned data during an update.
```
