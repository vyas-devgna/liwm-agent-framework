# Uninstall LIWM

```text
Uninstall LIWM integration from this machine without damaging unrelated agent
configuration. This is a prompt-driven uninstall; do not create or run an
uninstaller script.

First locate ~/.liwm/config.json using platform home resolution, identify the
recorded host integration, skill destination, framework checkout, and exact
global instruction file, and show me those targets. Then ask one concise
question: should the private LIWM data be (a) retained, (b) exported then
retained, or (c) permanently deleted after export is offered? Do not proceed
with private-data deletion without my explicit answer in this conversation.

After I answer:

1. Run `liwm uninstall plan --host <id> --output <plan.json>` and show me every
   target, precondition, backup source, and expected result. After approval, run
   `liwm uninstall apply --plan <plan.json>` and `liwm uninstall verify --plan
   <plan.json>`. The CLI removes exactly one complete LIWM block, restores
   overwritten LIWM skill files, refuses malformed markers or changed hashes,
   and preserves every byte of unrelated instruction text.

2. The serialized receipt, not a name pattern, identifies LIWM-managed skill
   files. Never remove another skill merely because its name contains `liwm`.
   Remove optional installed LIWM
   plugin entries only if config.json records that LIWM installed them. Leave
   unrelated plugins, marketplaces, settings, and persona instructions intact.

3. Remove the private virtual environment/framework checkout only if config.json
   records them as LIWM-created and they contain no unrelated or uncommitted
   work. Otherwise report and retain them.

4. Handle ~/.liwm according to my choice:
   - retain: leave it unchanged;
   - export then retain: run `liwm export` to a path I approve and leave it;
   - delete: offer a local JSON export first, verify it if accepted, make the
     deletion target resolve exactly to the LIWM data root (never home, a repo,
     or a broad parent), then delete it and state whether recovery is possible.

5. Validate that no LIWM bootstrap block remains, LIWM skills are no longer
   discoverable, unrelated instruction text is unchanged, and retained/exported
   data is readable. Report exactly what was removed, retained, exported, and
   backed up. Do not claim personal data was deleted if any backup or export
   remains; list those paths explicitly.
```
