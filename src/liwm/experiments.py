"""How a candidate rule earns human evidence without being sprung on anyone.

The promotion gate demands outcomes that were observed, not modelled.  That
demand was unsatisfiable in practice: an unpromoted candidate never runs, so it
never produces outcomes of its own, so the strictest gate in the framework was
also the one nothing could legitimately pass.

This closes the loop with three evaluation modes, in ascending order of what
they cost the user:

``shadow``
    The candidate computes what it would have done.  The incumbent stays
    user-facing.  Nothing the user sees changes, and shadow outcomes are
    labelled as such - they are never counted as human exposure, because no
    human was exposed to anything.

``canary``
    The candidate genuinely produces the output, for a small registered
    fraction of eligible interactions.  The assignment is committed *before*
    the output exists, so it cannot be chosen after seeing how things went.

``ab``
    Registered random assignment against the incumbent, with a fixed seed and
    an explicit condition on every event.

Assignment is a pure function of (seed, experiment, unit), so the same
interaction always lands in the same arm.  Re-rolling until a candidate looks
good is not available.  All three require the user to have turned experiments
on; LIWM does not quietly change how it behaves toward someone in order to
gather evidence about itself.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from .config import ConfigStore
from .jsonio import FileLock, read_json_resilient, utc_now, write_json_atomic

__all__ = ["EXPERIMENT_MODES", "ExperimentStore"]

SCHEMA_VERSION = "0.2.0"

#: ``exposure`` records whether a human saw candidate output.  It is the field
#: the promotion gate reads, and the reason shadow evidence cannot masquerade
#: as a user outcome.
EXPERIMENT_MODES = {
    "shadow": {"user_facing": False,
               "note": "candidate computes, incumbent ships; no human exposure"},
    "canary": {"user_facing": True,
               "note": "candidate ships to a registered fraction of interactions"},
    "ab": {"user_facing": True,
           "note": "registered random assignment against the incumbent"},
}
MAX_CANARY_EXPOSURE = 0.25


class ExperimentStore:
    """Registered candidate experiments and their pre-committed assignments."""

    def __init__(self, home):
        self.home = Path(home)
        self.path = self.home / "learning" / "experiments.json"
        self.lock_path = self.home / "learning" / ".experiments.lock"

    def load(self):
        data, _ = read_json_resilient(
            self.path, backups_dir=self.home / "backups", logs_dir=self.home / "logs",
            default={"schema_version": SCHEMA_VERSION, "experiments": []})
        return data

    def _save(self, data):
        data["schema_version"] = SCHEMA_VERSION
        data["updated_at"] = utc_now()
        write_json_atomic(self.path, data)
        return data

    def enrolled(self, candidate_id):
        return next((row for row in self.load()["experiments"]
                     if row["candidate_id"] == candidate_id and row["state"] == "running"),
                    None)

    def enroll(self, candidate_id, mode, store=None, exposure=0.1, seed=None):
        """Register a candidate for evaluation.  Requires explicit consent."""
        if mode not in EXPERIMENT_MODES:
            raise ValueError("unknown experiment mode %r" % mode)
        config = ConfigStore(self.home).load()
        if not config.get("learning", {}).get("experiments_enabled", False):
            raise ValueError(
                "experiments are off; run 'liwm config set learning.experiments_enabled "
                "true' to allow LIWM to evaluate its own candidate rules on your work")
        exposure = float(exposure)
        if EXPERIMENT_MODES[mode]["user_facing"]:
            if not 0.0 < exposure <= MAX_CANARY_EXPOSURE:
                raise ValueError("user-facing exposure must be in (0, %.2f]"
                                 % MAX_CANARY_EXPOSURE)
        else:
            exposure = 0.0
        if self.enrolled(candidate_id):
            raise ValueError("candidate %s is already enrolled" % candidate_id)

        row = {
            "experiment_id": "exp_%s" % uuid.uuid4().hex[:12],
            "candidate_id": candidate_id,
            "mode": mode,
            "user_facing": EXPERIMENT_MODES[mode]["user_facing"],
            "exposure": exposure,
            "seed": seed or uuid.uuid4().hex[:16],
            "state": "running",
            "started_at": utc_now(),
            "stopped_at": None,
            "stop_reason": None,
        }
        with FileLock(self.lock_path):
            data = self.load()
            data["experiments"].append(row)
            self._save(data)
        if store is not None:
            store.events.record("experiment_started", "direct_user_message", payload={
                "experiment_id": row["experiment_id"], "candidate_id": candidate_id,
                "mode": mode, "exposure": exposure, "user_facing": row["user_facing"],
            })
        return row

    def stop(self, candidate_id, store=None, reason="completed"):
        with FileLock(self.lock_path):
            data = self.load()
            stopped = False
            for row in data["experiments"]:
                if row["candidate_id"] == candidate_id and row["state"] == "running":
                    row.update(state="stopped", stopped_at=utc_now(), stop_reason=reason)
                    stopped = True
            if stopped:
                self._save(data)
        if stopped and store is not None:
            store.events.record("experiment_stopped", "direct_user_message", payload={
                "candidate_id": candidate_id, "reason": reason})
        return stopped

    def assign(self, candidate_id, unit, store=None, session_id=None, project_id=None,
               domain=None):
        """Decide the arm for one interaction and commit it before any output.

        *unit* is whatever the caller considers one interaction - a task id, a
        turn id.  The same unit always lands in the same arm, so the assignment
        cannot be re-rolled after seeing the result, and a caller cannot walk
        the boundary looking for a favourable draw.
        """
        row = self.enrolled(candidate_id)
        if row is None:
            raise KeyError("no running experiment for candidate %s" % candidate_id)
        digest = hashlib.sha256(
            ("%s\0%s\0%s" % (row["seed"], row["experiment_id"], unit)).encode("utf-8"))
        draw = int.from_bytes(digest.digest()[:8], "big") / float(1 << 64)
        chosen = draw < row["exposure"]
        assignment = {
            "experiment_id": row["experiment_id"],
            "candidate_id": candidate_id,
            "mode": row["mode"],
            "unit": unit,
            "draw": round(draw, 6),
            "condition": "candidate" if (chosen or not row["user_facing"]) else "incumbent",
            # The distinction the gate turns on. Shadow always computes the
            # candidate and always ships the incumbent, so nobody was exposed
            # to anything and no outcome from it is human evidence.
            "exposure": ("shadow" if not row["user_facing"]
                         else "user_facing" if chosen else "incumbent"),
            "assigned_at": utc_now(),
        }
        if store is not None:
            store.events.record(
                "experiment_assignment", "agent_inference", payload=assignment,
                session_id=session_id, project_id=project_id, domain=domain)
        return assignment

    def exposure_for(self, store, candidate_id):
        """Units where the user actually saw this candidate's output."""
        return {
            (event.get("payload") or {}).get("unit")
            for event in store.events.iter_events(kinds={"experiment_assignment"})
            if (event.get("payload") or {}).get("candidate_id") == candidate_id
            and (event.get("payload") or {}).get("exposure") == "user_facing"
        }
