"""Cross-platform location of the LIWM data directory and host config dirs.

LIWM keeps *all* personal data in a user-level directory that is deliberately
outside any git repository.  Resolution order (first match wins):

1. ``$LIWM_HOME``                        - explicit override, used by tests
2. ``$XDG_DATA_HOME/liwm``               - only when ``LIWM_USE_XDG`` is truthy
3. ``<home>/.liwm``                      - the default on every platform

``Path.home()`` resolves to ``C:\\Users\\<name>`` on Windows, ``/Users/<name>``
on macOS and ``/home/<name>`` on Linux, so ``~/.liwm`` is a genuine
cross-platform default rather than a POSIX-ism.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = [
    "liwm_home",
    "ensure_layout",
    "claude_config_dir",
    "codex_config_dir",
    "LAYOUT_DIRS",
    "is_inside_git_repo",
]

#: Directories created by :func:`ensure_layout`.
LAYOUT_DIRS = (
    "events",
    "sessions",
    "projects",
    "learning",
    "learning/candidate-rules",
    "learning/rejected-rules",
    "learning/promoted-rules",
    "backups",
    "logs",
    "exports",
)

_TRUTHY = {"1", "true", "yes", "on"}


def _env_path(name: str):
    raw = os.environ.get(name)
    if not raw:
        return None
    raw = raw.strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def liwm_home() -> Path:
    """Return the absolute path of the LIWM data directory (not created)."""
    explicit = _env_path("LIWM_HOME")
    if explicit is not None:
        return explicit.absolute()

    if os.environ.get("LIWM_USE_XDG", "").lower() in _TRUTHY:
        xdg = _env_path("XDG_DATA_HOME")
        if xdg is not None:
            return (xdg / "liwm").absolute()

    return (Path.home() / ".liwm").absolute()


def ensure_layout(home=None) -> Path:
    """Create the LIWM directory layout if missing and return its root."""
    root = Path(home) if home is not None else liwm_home()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        root.chmod(0o700)
    except OSError:  # pragma: no cover - ACL semantics vary on Windows
        pass
    for rel in LAYOUT_DIRS:
        path = root / rel
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            path.chmod(0o700)
        except OSError:  # pragma: no cover
            pass
    # A README inside the data dir helps a human who stumbles on it later.
    readme = root / "README.txt"
    if not readme.exists():
        readme.write_text(
            "This directory holds your private LIWM (Latent Intent World Model) profile.\n"
            "It is local-only. LIWM never uploads it anywhere.\n\n"
            "  user.json      - materialised model of you (derived from events/)\n"
            "  events/        - append-only evidence log; the source of truth\n"
            "  projects/      - per-project intent, decisions and feedback\n"
            "  learning/      - adaptive strategy and candidate/promoted rules\n"
            "  metrics.json   - local, non-telemetric performance measurements\n"
            "  backups/       - timestamped snapshots taken before risky writes\n\n"
            "Inspect it with:  liwm profile   |   liwm export   |   liwm stats\n"
            "Delete it with:   liwm reset --hard   (or just remove this directory)\n",
            encoding="utf-8",
        )
        try:
            readme.chmod(0o600)
        except OSError:  # pragma: no cover
            pass
    return root


def claude_config_dir() -> Path:
    """Best-effort location of the Claude Code user-level config directory."""
    explicit = _env_path("CLAUDE_CONFIG_DIR")
    if explicit is not None:
        return explicit.absolute()
    return (Path.home() / ".claude").absolute()


def codex_config_dir() -> Path:
    """Best-effort location of the OpenAI Codex user-level config directory."""
    explicit = _env_path("CODEX_HOME")
    if explicit is not None:
        return explicit.absolute()
    return (Path.home() / ".codex").absolute()


def is_inside_git_repo(path) -> bool:
    """True when *path* (or an ancestor) contains a ``.git`` entry.

    Used as a guard: LIWM refuses to initialise a profile inside a repository
    unless the user explicitly forces it, because personal data must not be
    one ``git add -A`` away from publication.
    """
    p = Path(path).absolute()
    for candidate in (p,) + tuple(p.parents):
        if (candidate / ".git").exists():
            return True
    return False
