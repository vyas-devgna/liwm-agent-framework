"""The host registry: which agents LIWM can attach to, and how.

LIWM is not a Claude Code plugin that happens to run elsewhere.  The profile is
a plain JSON document produced by a plain Python CLI, and *attaching* it to an
agent means one thing only: putting a short delimited block into whatever file
that agent already reads at the start of a session.  Everything else -- skills,
plugins, hooks -- is an optimisation on top of that single mechanism.

That is why this module is a table rather than a set of classes.  A host is
described by data:

* where its **global** instruction file lives (the one that applies to every
  project, which is what a *user* profile needs);
* where its **project** instruction files live;
* whether it supports a skills directory, and in what layout;
* how many bytes of instruction it will actually read;
* the documentation that says so.

Adding a host is therefore a data change, and users can make it themselves
without touching the code: ``~/.liwm/hosts.json`` is merged over this table at
load time (see :func:`load_registry`).  A host that reads *any* Markdown file at
startup can be supported in about eight lines of JSON.

Honesty about detection
-----------------------
Detection is presence-of-path only.  LIWM never runs a host binary, never reads
a host's internal state, and never phones anywhere to ask what you have
installed.  A ``detected`` result means "this path exists on this machine",
nothing more, and a host being undetected never blocks installation -- you can
always name a target file explicitly.

Byte budgets
------------
Several hosts truncate or refuse oversized instruction files (Codex stops at
``project_doc_max_bytes``, Windsurf's global rules file caps at 6,000
characters).  A profile framework that silently blew that budget would push the
*user's own* instructions out of the context window -- the exact opposite of
what LIWM is for.  So budgets are part of the table, and
:func:`check_budget` is what the installer consults before writing.
"""

from __future__ import annotations

import os
from pathlib import Path

from .jsonio import read_json

__all__ = [
    "BUILTIN_HOSTS",
    "load_registry",
    "get_host",
    "detect_hosts",
    "config_dir_for",
    "instruction_file_for",
    "skills_dir_for",
    "check_budget",
    "installation_plan",
    "USER_REGISTRY_FILENAME",
]

#: A user-supplied overlay in the LIWM home directory.  Same shape as the
#: built-in table; unknown ids are added, known ids are shallow-merged.  A host
#: is a plain dict, so ``liwm hosts --json`` is the table itself.
USER_REGISTRY_FILENAME = "hosts.json"


def _host(**kwargs):
    spec = {
        "id": None,
        "name": None,
        "vendor": None,
        # Environment variable that relocates the host's config directory.
        "home_env": None,
        # Config directory, as a "~"-relative template.
        "config_dir": None,
        # The user-level instruction file: the one LIWM installs into, because
        # a *user* profile must apply to every project, not one repository.
        # Built-ins state ``instruction_rel``, a path relative to ``config_dir``,
        # so that a relocation environment variable moves the file with the
        # directory.  A user overlay may instead give an absolute
        # ``global_instruction_file``, which is then used exactly as written.
        "instruction_rel": None,
        "global_instruction_file": None,
        # Files this host reads inside a repository, nearest-first.
        "project_instruction_files": (),
        # Where user-level skills live.  Two forms, for the same reason the
        # instruction file has two: ``skills_rel`` is relative to the config
        # directory and relocates with it, while ``skills_path`` is a fixed
        # template for a location that is deliberately outside it -- Codex reads
        # user skills from the cross-vendor ~/.agents/skills, so deriving that
        # from CODEX_HOME would point the installer at a directory Codex never
        # looks in.
        "skills_rel": None,
        "skills_path": None,
        # Documented byte budget for the instruction file; None means the host
        # documents no limit, which is reported but never used to refuse a write.
        "instruction_budget_bytes": None,
        # Capability flags that change what the installer can rely on.  Absent
        # means absent: a host only claims what its entry states.
        "capabilities": {},
        "docs": None,
        "notes": "",
        "confidence": "documented",
    }
    spec.update(kwargs)
    return spec


#: Hosts LIWM knows about out of the box.
#:
#: Ordering is by how much of LIWM the host can use, not by popularity: hosts
#: with a real skills mechanism come first, because they get progressive
#: disclosure (a small router plus on-demand skills) instead of one flat block.
BUILTIN_HOSTS = (
    _host(
        id="claude-code",
        name="Claude Code",
        vendor="Anthropic",
        home_env="CLAUDE_CONFIG_DIR",
        config_dir="~/.claude",
        instruction_rel="CLAUDE.md",
        project_instruction_files=("CLAUDE.md", ".claude/CLAUDE.md", "AGENTS.md"),
        skills_rel="skills",
        capabilities={
            "skills": True,
            "plugins": True,
            "subagents": True,
            # Checked and false, not merely unlisted: hooks fire, but
            # SessionStart output is shown to the user rather than added to the
            # model's prompt, so LIWM cannot depend on it for context.
            "hook_injects_context": False,
            "progressive_disclosure": True,
        },
        docs="https://docs.claude.com/en/docs/claude-code/skills",
        notes=(
            "Full LIWM: a ~40-line router block in CLAUDE.md plus 15 skills under "
            "~/.claude/skills/. Skill bodies are loaded on demand, so the always-on "
            "cost stays small."
        ),
    ),
    _host(
        id="codex",
        name="Codex CLI",
        vendor="OpenAI",
        home_env="CODEX_HOME",
        config_dir="~/.codex",
        instruction_rel="AGENTS.md",
        project_instruction_files=("AGENTS.md",),
        skills_path="~/.agents/skills",
        instruction_budget_bytes=32 * 1024,
        capabilities={
            "skills": True,
            "plugins": True,
            "hook_injects_context": True,
            "progressive_disclosure": True,
        },
        docs="https://developers.openai.com/codex/local-config",
        notes=(
            "AGENTS.md is truncated at project_doc_max_bytes (32 KiB by default), "
            "which the LIWM block stays far inside. A SessionStart hook can inject "
            "additionalContext, but it requires the user to trust hooks, so it is "
            "offered and never assumed."
        ),
    ),
    _host(
        id="gemini-cli",
        name="Gemini CLI",
        vendor="Google",
        home_env="GEMINI_CONFIG_DIR",
        config_dir="~/.gemini",
        instruction_rel="GEMINI.md",
        project_instruction_files=("GEMINI.md", "AGENTS.md"),
        docs="https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html",
        notes=(
            "The global ~/.gemini/GEMINI.md is read first and concatenated with "
            "project files into 'memory'. No skills mechanism, so LIWM installs the "
            "self-contained block, which carries the routing rules inline."
        ),
    ),
    _host(
        id="opencode",
        name="opencode",
        vendor="opencode",
        home_env="OPENCODE_CONFIG_DIR",
        config_dir="~/.config/opencode",
        instruction_rel="AGENTS.md",
        project_instruction_files=("AGENTS.md", "CLAUDE.md", "CONTEXT.md"),
        capabilities={
            "plugins": True,
            "subagents": True,
        },
        docs="https://opencode.ai/docs/rules/",
        notes=(
            "Global rules are merged with the project file rather than overridden, "
            "with project rules winning on conflict -- which matches LIWM's own "
            "precedence rule (explicit project instructions beat the profile)."
        ),
    ),
    _host(
        id="windsurf",
        name="Windsurf / Cascade",
        vendor="Cognition",
        home_env=None,
        config_dir="~/.codeium/windsurf",
        instruction_rel="memories/global_rules.md",
        project_instruction_files=(".windsurf/rules", ".devin/rules", "AGENTS.md",
                                   ".windsurfrules"),
        instruction_budget_bytes=6000,
        docs="https://docs.windsurf.com/windsurf/cascade/memories",
        notes=(
            "The global rules file is capped at 6,000 characters, so LIWM installs "
            "its compact block here and relies on the CLI for detail."
        ),
    ),
    _host(
        id="cursor",
        name="Cursor",
        vendor="Anysphere",
        home_env=None,
        config_dir="~/.cursor",
        global_instruction_file=None,
        project_instruction_files=(".cursor/rules", "AGENTS.md", ".cursorrules"),
        docs="https://cursor.com/docs/context/rules",
        notes=(
            "User Rules are stored in Cursor's settings UI, not in a file LIWM can "
            "edit safely. INSTALL_PROMPT.md therefore prints the block for you to "
            "paste, and installs the project-level path automatically."
        ),
    ),
    _host(
        id="github-copilot",
        name="GitHub Copilot coding agent",
        vendor="GitHub",
        home_env=None,
        config_dir=None,
        global_instruction_file=None,
        project_instruction_files=(".github/copilot-instructions.md", "AGENTS.md"),
        docs="https://docs.github.com/en/copilot/customizing-copilot",
        notes=(
            "Repository-scoped only. A shared repository is not the place for one "
            "person's profile, so LIWM installs the *project intent* block here and "
            "leaves the user profile to a personal host."
        ),
    ),
    _host(
        id="zed",
        name="Zed agent",
        vendor="Zed Industries",
        home_env=None,
        config_dir="~/.config/zed",
        instruction_rel="rules",
        project_instruction_files=("AGENTS.md", ".rules"),
        docs="https://zed.dev/docs/ai/rules",
        notes="Reads AGENTS.md in a project; global rules live in the Zed config dir.",
        confidence="community",
    ),
    _host(
        id="agents-md",
        name="Any AGENTS.md agent",
        vendor="open convention",
        home_env=None,
        config_dir=None,
        global_instruction_file=None,
        project_instruction_files=("AGENTS.md",),
        docs="https://agents.md/",
        notes=(
            "The fallback that makes LIWM universal: ~25 agents read AGENTS.md from "
            "the nearest directory. Anything on that list can consume the LIWM block "
            "even if it has no entry of its own here."
        ),
    ),
)

_BUILTIN_INDEX = {h["id"]: h for h in BUILTIN_HOSTS}


def config_dir_for(spec):
    """Absolute config directory for *spec*, honouring its relocation variable.

    ``CODEX_HOME`` and ``CLAUDE_CONFIG_DIR`` are handled here and nowhere else,
    so no host needs special-casing.  Returns ``None`` for hosts that have no
    config directory at all (repository-scoped ones such as Copilot).
    """
    env_name = spec.get("home_env")
    if env_name:
        raw = (os.environ.get(env_name) or "").strip()
        if raw:
            return Path(raw).expanduser().absolute()
    template = spec.get("config_dir")
    if template is None:
        return None
    return Path(template).expanduser().absolute()


def skills_dir_for(spec):
    """Absolute user-level skills directory for *spec*, or ``None``."""
    rel = spec.get("skills_rel")
    if rel:
        base = config_dir_for(spec)
        if base is not None:
            return base.joinpath(*str(rel).replace("\\", "/").split("/"))
    template = spec.get("skills_path")
    if template is None:
        return None
    return Path(template).expanduser().absolute()


def instruction_file_for(spec):
    """Absolute user-level instruction file for *spec*, or ``None``.

    Built-ins declare ``instruction_rel``, a path *relative to the config
    directory*, so that relocating the config directory relocates the file with
    it.  Deriving the tail from the displayed template instead was tried and
    removed: it had to guess how many leading segments the environment variable
    replaced, and guessed wrong for any host whose config directory is nested
    (``~/.config/opencode`` became ``$OPENCODE_CONFIG_DIR/opencode``).

    A user overlay that supplies an absolute ``global_instruction_file`` and no
    ``instruction_rel`` is taken at its word -- it named a specific file, and
    LIWM has no business relocating it.
    """
    rel = spec.get("instruction_rel")
    if rel:
        base = config_dir_for(spec)
        if base is not None:
            return base.joinpath(*str(rel).replace("\\", "/").split("/"))
    template = spec.get("global_instruction_file")
    if template is None:
        return None
    return Path(template).expanduser().absolute()


def load_registry(home=None):
    """Return the effective host table: built-ins overlaid with the user's own.

    The overlay lives at ``<liwm home>/hosts.json`` and has the same shape as
    :data:`BUILTIN_HOSTS`::

        {"hosts": [{"id": "my-agent",
                    "name": "My Agent",
                    "global_instruction_file": "~/.myagent/INSTRUCTIONS.md"}]}

    An entry whose ``id`` matches a built-in is merged over it, so a user can
    correct one path without restating the whole record.  A malformed overlay is
    ignored rather than fatal: a typo in an optional file must not stop LIWM from
    reporting on the hosts it does know.
    """
    hosts = {hid: dict(spec) for hid, spec in _BUILTIN_INDEX.items()}
    order = [h["id"] for h in BUILTIN_HOSTS]

    if home is None:
        return [hosts[hid] for hid in order]

    overlay_path = Path(home) / USER_REGISTRY_FILENAME
    try:
        overlay = read_json(overlay_path, default=None)
    except Exception:  # noqa: BLE001 - an unreadable overlay must not be fatal
        return [hosts[hid] for hid in order]
    if not isinstance(overlay, dict):
        return [hosts[hid] for hid in order]

    for entry in overlay.get("hosts") or ():
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        hid = str(entry["id"])
        if hid in hosts:
            merged = dict(hosts[hid])
            # Naming an absolute file overrides the built-in's derived path.
            # Without this the relative path would keep winning and the user's
            # correction would be silently ignored - the worst kind of override.
            if entry.get("global_instruction_file") and not entry.get("instruction_rel"):
                merged["instruction_rel"] = None
            merged.update(entry)
            merged["source"] = "user-override"
            hosts[hid] = merged
        else:
            base = dict(_host(id=hid, name=entry.get("name") or hid))
            # A user-supplied entry must not inherit the built-in default of
            # "documented": LIWM has not read a vendor doc for this host, and
            # saying otherwise would be the same dishonesty the provenance gate
            # exists to prevent.
            base["confidence"] = "user-supplied"
            base.update(entry)
            base["source"] = "user-defined"
            hosts[hid] = base
            order.append(hid)

    return [hosts[hid] for hid in order]


def get_host(host_id, home=None):
    """Return one host spec by id, or ``None``."""
    for spec in load_registry(home):
        if spec["id"] == host_id:
            return spec
    return None


def detect_hosts(home=None):
    """Report which known hosts appear to be present on this machine.

    Presence is inferred from paths alone (see the module docstring).  Each row
    reports what was checked so the answer is auditable rather than magic.
    """
    rows = []
    for spec in load_registry(home):
        config_dir = config_dir_for(spec)
        global_file = instruction_file_for(spec)
        skills_root = skills_dir_for(spec)

        evidence = []
        if config_dir is not None and config_dir.is_dir():
            evidence.append("config dir %s exists" % config_dir)
        if global_file is not None and global_file.is_file():
            evidence.append("instruction file %s exists" % global_file)
        if skills_root is not None and skills_root.is_dir():
            evidence.append("skills dir %s exists" % skills_root)

        rows.append({
            "id": spec["id"],
            "name": spec["name"],
            "vendor": spec.get("vendor"),
            "detected": bool(evidence),
            "evidence": evidence,
            "config_dir": str(config_dir) if config_dir else None,
            "global_instruction_file": str(global_file) if global_file else None,
            "skills_path": str(skills_root) if skills_root else None,
            "project_instruction_files": list(spec.get("project_instruction_files") or ()),
            "supports_skills": bool((spec.get("capabilities") or {}).get("skills")),
            "instruction_budget_bytes": spec.get("instruction_budget_bytes"),
            "liwm_installed": _block_present(global_file),
            "docs": spec.get("docs"),
            "notes": spec.get("notes"),
            "confidence": spec.get("confidence"),
            "source": spec.get("source", "builtin"),
        })
    return rows


def _block_present(path):
    """True when a LIWM bootstrap block is already in *path*."""
    from .integration import BEGIN_PREFIX

    if path is None or not Path(path).is_file():
        return False
    try:
        return BEGIN_PREFIX in Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:  # pragma: no cover
        return False


def check_budget(spec, block_text, existing_text=""):
    """Would installing *block_text* exceed what this host will actually read?

    Returns a dict rather than raising: the installer reports the number and
    picks the compact block, and the *user's* existing content is never the
    thing that gets dropped to make room.
    """
    budget = spec.get("instruction_budget_bytes")
    block_bytes = len(block_text.encode("utf-8"))
    existing_bytes = len((existing_text or "").encode("utf-8"))
    total = block_bytes + existing_bytes + 1
    return {
        "budget_bytes": budget,
        "block_bytes": block_bytes,
        "existing_bytes": existing_bytes,
        "total_bytes": total,
        "within_budget": budget is None or total <= budget,
        "headroom_bytes": None if budget is None else budget - total,
    }


def installation_plan(host_id, home=None, block_text=""):
    """Describe -- without performing -- what installing into *host_id* means.

    This is what ``liwm hosts plan`` prints and what INSTALL_PROMPT.md tells the
    agent to show the user before touching anything.  Every write is named, and
    every write to a pre-existing file is paired with the backup that precedes
    it, because a framework that edits your assistant's instructions has to show
    its work first.
    """
    spec = get_host(host_id, home)
    if spec is None:
        return None

    config_dir = config_dir_for(spec)
    global_file = instruction_file_for(spec)
    steps = []

    if global_file is not None:
        existing = ""
        if global_file.is_file():
            try:
                existing = global_file.read_text(encoding="utf-8", errors="replace")
            except OSError:  # pragma: no cover
                existing = ""
            steps.append({
                "action": "backup",
                "path": str(global_file),
                "detail": "timestamped copy into <liwm home>/backups/ before any edit",
            })
        steps.append({
            "action": "upsert_block",
            "path": str(global_file),
            "detail": ("replace the existing LIWM block" if _block_present(global_file)
                       else "append one delimited LIWM block, preserving all other text"),
        })
        budget = check_budget(spec, block_text, existing)
    else:
        budget = check_budget(spec, block_text, "")
        steps.append({
            "action": "manual",
            "path": None,
            "detail": ("this host has no user-level instruction file LIWM can edit; "
                       "the block is printed for you to paste into its settings UI"),
        })

    skills_root = skills_dir_for(spec)
    if skills_root is not None and (spec.get("capabilities") or {}).get("skills"):
        steps.append({
            "action": "link_skills",
            "path": str(skills_root),
            "detail": "symlink (or copy, on filesystems without symlinks) the 15 LIWM skills",
        })

    return {
        "host": spec["id"],
        "name": spec["name"],
        "steps": steps,
        "budget": budget,
        "reversible": True,
        "uninstall": "liwm uninstall guidance lives in UNINSTALL_PROMPT.md; "
                     "removing the delimited block restores the file exactly",
        "docs": spec.get("docs"),
    }
