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

1. Make timestamped backups of every configuration file you will edit. In the
   active Claude Code CLAUDE.md, Codex AGENTS.md/AGENTS.override.md, or generic
   host instruction file, remove exactly one complete block beginning with
   `<!-- LIWM:BEGIN` and ending with `<!-- LIWM:END -->`. If the markers are
   absent, leave the file untouched. If malformed, stop and report it. Preserve
   every byte outside the block; do not delete an otherwise empty instruction
   file unless it was created by LIWM and config.json records that fact.

2. Remove only LIWM-managed `liwm` and `liwm-*` skill links/directories whose
   recorded source or manifest identifies this framework. Never remove another
   skill merely because its name contains `liwm`. Remove optional installed LIWM
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
