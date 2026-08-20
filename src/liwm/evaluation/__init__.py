"""Local evaluation: simulators, replay and the measurement harness.

Nothing here talks to a network or a model provider.  Synthetic users are
deterministic finite-state fixtures with a hidden preference vector; the harness
measures whether LIWM's beliefs converge toward that hidden vector, whether
questioning becomes cheaper as it does, and whether a proposed strategy change
would actually have helped on real past episodes.

Simulated numbers are labelled as estimates everywhere they surface.  They are
evidence about the *framework*, never about the user.
"""

from __future__ import annotations

from .harness import EvaluationResult, run_convergence_study, run_mode_study
from .replay import ReplayResult, replay_candidate, replay_episodes
from .simulators import ARCHETYPES, SyntheticUser, make_user

__all__ = [
    "ARCHETYPES",
    "SyntheticUser",
    "make_user",
    "replay_episodes",
    "replay_candidate",
    "ReplayResult",
    "run_convergence_study",
    "run_mode_study",
    "EvaluationResult",
]
