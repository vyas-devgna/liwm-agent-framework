"""LIWM - Latent Intent World Model.

A persistent, evidence-based intent-learning layer for coding agents.

LIWM is not a model and not a chatbot persona.  It is a local, file-backed
system that lets an agent progressively understand how one specific human wants
to work, and then act on that understanding without asking them to explain
themselves again.

Quick start (library)::

    from liwm import open_home

    liwm = open_home()                       # ~/.liwm by default
    liwm.store.observe(
        "interaction_profile.preferred_verbosity", "terse",
        source_type="explicit_statement", provenance="direct_user_message",
    )
    ctx = liwm.runtime_context(domain="software", task="refactor the parser")

Quick start (CLI)::

    liwm init
    liwm context --domain software --task "refactor the parser"
    liwm profile
    liwm why interaction_profile.preferred_verbosity
"""

from __future__ import annotations

__version__ = "0.1.0"
__schema_version__ = "0.1.0"
__all__ = [
    "__version__",
    "__schema_version__",
    "Liwm",
    "open_home",
    "ProfileStore",
    "EventStore",
    "ProjectStore",
]

from .events import EventStore  # noqa: E402
from .paths import ensure_layout, liwm_home  # noqa: E402
from .profile import ProfileStore  # noqa: E402
from .projects import ProjectStore  # noqa: E402


class Liwm:
    """Convenience facade binding the stores for one LIWM home directory."""

    def __init__(self, home=None, create=True):
        self.home = ensure_layout(home) if create else (home or liwm_home())
        self.store = ProfileStore(self.home)

    # -- stores ------------------------------------------------------------
    @property
    def events(self):
        return self.store.events

    def project(self, project_id):
        return ProjectStore(self.home, project_id)

    def metrics(self):
        from .metrics import MetricsStore
        return MetricsStore(self.home)

    def strategy(self):
        from .strategy import StrategyStore
        return StrategyStore(self.home)

    def improvement(self):
        from .selfimprove import SelfImprovementStore
        return SelfImprovementStore(self.home)

    # -- common operations -------------------------------------------------
    def profile(self):
        return self.store.load()

    def runtime_context(self, **kwargs):
        from .context import build_runtime_context
        from .config import ConfigStore
        if ConfigStore(self.home).load().get("enabled", True):
            kwargs.setdefault("strategy", self.strategy().load())
            kwargs.setdefault("promoted_rules", self.improvement().active_rules())
        return build_runtime_context(self.store, **kwargs)

    def report(self):
        from .report import profile_report
        return profile_report(
            self.store,
            metrics=self.metrics().load(),
            strategy=self.strategy().load(),
            promoted_rules=self.improvement().active_rules(),
        )

    def why(self, query=None, **kwargs):
        from .traceability import why
        return why(self.store, query, **kwargs)

    def __repr__(self):  # pragma: no cover
        return "<Liwm home=%s>" % self.home


def open_home(home=None, create=True):
    """Open (and by default create) a LIWM home directory."""
    return Liwm(home=home, create=create)
