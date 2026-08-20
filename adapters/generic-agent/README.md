# Generic Agent Skills adapter

A compatible host needs four capabilities:

1. load Agent Skills (`<name>/SKILL.md`) progressively;
2. load a compact user-level instruction on every session;
3. execute a local command and parse JSON;
4. allow local files outside repositories.

Install all `skills/liwm*` directories in the host's user skill path, add the
delimited text from `bootstrap.md` to its global instruction file, and make the
`liwm` CLI runnable. Keep private state at the path returned by `liwm init`
(default `~/.liwm`, resolved with the platform home API). Do not copy private
state into a project or plugin directory.

If a host lacks automatic skill invocation, the global bootstrap must direct it
to load `skills/liwm/SKILL.md` for non-trivial tasks. If it lacks global
instructions, true AUTO activation is not available; disclose that limitation.
