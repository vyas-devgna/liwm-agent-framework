"""Level 4: gated evolution of LIWM's own behaviour.

The failure mode this module exists to prevent: an agent that appends a lesson
to its own instructions after every conversation, drifts, and cannot be audited
or reverted.

So LIWM does not rewrite its skill files.  Ever.  Instead:

* a retrospective proposes a **candidate rule** - structured data, not prose;
* the candidate is checked against the constitution *before* anything else;
* it is **replayed** against historical episodes and scored;
* it must beat the incumbent on a primary metric **and** avoid regressing any
  guarded metric;
* it must survive the adversarial suite;
* only then is it written to ``learning/promoted-rules.json``, which the skills
  *read* as data at runtime.

The skills' own text is immutable framework code, versioned in git.  What
adapts is the data they consult.  That makes every behavioural change
inspectable (``liwm review``), attributable, and revertible.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from .constitution import check_candidate, constitution_hash
from .evidence import parse_ts
from .jsonio import FileLock, backup_file, read_json_resilient, utc_now, write_json_atomic

__all__ = [
    "CANDIDATE_STATES",
    "GUARDED_METRICS",
    "PROMOTION_GATES",
    "CandidateRule",
    "SelfImprovementStore",
]

SCHEMA_VERSION = "0.4.0"

CANDIDATE_STATES = (
    "proposed",
    "constitution_checked",
    "replayed",
    "benchmarked",
    "adversarial_tested",
    "promoted",
    "rejected",
    "retired",
)

#: Metrics that may not get worse, whatever the primary metric says.  A change
#: that improves acceptance by irritating the user into agreement, or by asking
#: twice as many questions, is not an improvement.
GUARDED_METRICS = {
    "question_ignore_rate": {"direction": "lower_is_better", "tolerance": 0.05},
    "questions_per_accepted_outcome": {"direction": "lower_is_better", "tolerance": 0.15},
    "assumption_error_rate": {"direction": "lower_is_better", "tolerance": 0.03},
    "explicit_correction_rate": {"direction": "lower_is_better", "tolerance": 0.05},
    "global_correction_rate": {"direction": "lower_is_better", "tolerance": 0.03},
}

PROMOTION_GATES = {
    "min_replay_episodes": 12,
    "min_primary_improvement": 0.04,
    "min_distinct_sessions": 3,
    "require_adversarial_pass": True,
    "require_constitution_clean": True,
    "max_guarded_regression": 0.0,   # any breach beyond per-metric tolerance fails
    # Replay scores a candidate against a model of acceptance that LIWM itself
    # authored, so a candidate can win on replay by fitting the evaluator rather
    # than the person -- training on your own benchmark, with the usual result.
    # Promotion therefore also requires outcomes that were *observed*: predictions
    # committed before the user reacted and resolved afterwards against what they
    # actually did.  Without them, replay is the only witness and is not enough.
    "min_resolved_outcomes": 5,
    # Five outcomes from one afternoon is one afternoon, not a longitudinal
    # result.  A behavioural change earns promotion by holding up on separate
    # occasions, which is also what stops a single unusually agreeable session
    # from carrying a candidate through.
    "min_outcome_sessions": 3,
    # ...and those outcomes must come from interactions where the candidate
    # actually produced what the user reacted to.  Replay is a model, shadow
    # evaluation is a model with better manners, and neither is a person
    # responding to the candidate's work.  See :mod:`liwm.experiments`.
    "require_user_facing_exposure": True,
}


class CandidateRule(dict):
    """A proposed behavioural change, with everything needed to judge it."""

    @classmethod
    def create(cls, title, statement, surface="behaviour", expected_effect="",
               evidence=None, modifies=None, applies_to=None, parameters=None,
               primary_metric="first_pass_acceptance", proposed_by="retrospective"):
        return cls(
            {
                "id": "cand_%s" % uuid.uuid4().hex[:12],
                "schema_version": SCHEMA_VERSION,
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "state": "proposed",
                "title": title,
                "statement": statement,
                "surface": surface,
                "expected_effect": expected_effect,
                "primary_metric": primary_metric,
                "evidence": list(evidence or []),
                "modifies": list(modifies or []),
                "applies_to": applies_to or {"modes": ["auto", "low", "medium", "high"]},
                "parameters": dict(parameters or {}),
                "proposed_by": proposed_by,
                "constitution": {"checked": False, "violations": [], "hash": None},
                "replay": None,
                "benchmark": None,
                "adversarial": None,
                "decision": None,
                "history": [],
            }
        )

    def log(self, state, note=None, data=None):
        self["state"] = state
        self["updated_at"] = utc_now()
        self["history"].append(
            {"at": utc_now(), "state": state, "note": note, "data": data}
        )
        return self


class SelfImprovementStore:
    """Manages the candidate-rule lifecycle on disk."""

    def __init__(self, home):
        self.home = Path(home)
        self.learning = self.home / "learning"
        self.candidates = self.learning / "candidate-rules"
        self.rejected = self.learning / "rejected-rules"
        self.promoted_path = self.learning / "promoted-rules.json"
        self.backups = self.home / "backups"
        self.logs = self.home / "logs"
        self.lock_path = self.learning / ".selfimprove.lock"

    # -- storage -----------------------------------------------------------
    def _path(self, candidate_id, rejected=False):
        if not re.fullmatch(r"cand_[0-9a-f]{8,32}", str(candidate_id or "")):
            raise ValueError("invalid candidate id")
        base = self.rejected if rejected else self.candidates
        return base / ("%s.json" % candidate_id)

    def write(self, candidate, rejected=False):
        path = self._path(candidate["id"], rejected=rejected)
        write_json_atomic(path, dict(candidate))
        return path

    def read(self, candidate_id):
        for rejected in (False, True):
            path = self._path(candidate_id, rejected=rejected)
            if path.is_file():
                data, _ = read_json_resilient(path, backups_dir=self.backups, logs_dir=self.logs)
                if data:
                    return CandidateRule(data)
        return None

    def list_candidates(self, state=None, include_rejected=False):
        out = []
        dirs = [self.candidates] + ([self.rejected] if include_rejected else [])
        for d in dirs:
            if not d.is_dir():
                continue
            for path in sorted(d.glob("*.json")):
                data, _ = read_json_resilient(path, backups_dir=self.backups, logs_dir=self.logs)
                if not data:
                    continue
                if state and data.get("state") != state:
                    continue
                out.append(CandidateRule(data))
        return out

    def promoted_rules(self):
        data, _ = read_json_resilient(
            self.promoted_path, backups_dir=self.backups, logs_dir=self.logs,
            default={"schema_version": SCHEMA_VERSION, "rules": [], "updated_at": None},
        )
        return data

    # -- lifecycle ---------------------------------------------------------
    def propose(self, candidate, store=None):
        """Record a candidate and run the constitution check immediately.

        A candidate that fails the constitution is rejected here and never
        reaches replay.  This ordering is deliberate: the cheapest, most
        important gate runs first and cannot be skipped by a later stage.
        """
        candidate = CandidateRule(candidate)
        violations = check_candidate(candidate)
        candidate["constitution"] = {
            "checked": True,
            "violations": violations,
            "hash": constitution_hash(),
            "checked_at": utc_now(),
        }
        if violations:
            candidate.log("rejected", note="constitution violation",
                          data={"violations": violations})
            candidate["decision"] = {
                "outcome": "rejected",
                "reason": "constitution: %s" % "; ".join(violations),
                "at": utc_now(),
            }
            self.write(candidate, rejected=True)
            if store is not None:
                store.events.record(
                    "rule_rejected", "agent_inference",
                    payload={"candidate_id": candidate["id"], "reason": "constitution",
                             "violations": violations, "title": candidate["title"]},
                )
            return candidate

        candidate.log("constitution_checked", note="no violations")
        self.write(candidate)
        if store is not None:
            store.events.record(
                "candidate_rule", "agent_inference",
                payload={"candidate_id": candidate["id"], "title": candidate["title"],
                         "surface": candidate["surface"], "state": candidate["state"]},
            )
        return candidate

    def attach_replay(self, candidate_id, replay_result, store=None):
        candidate = self.read(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        candidate["replay"] = replay_result
        candidate.log("replayed", note="replayed against %d episodes"
                      % replay_result.get("episodes", 0))
        self.write(candidate)
        return candidate

    def attach_benchmark(self, candidate_id, benchmark, store=None):
        candidate = self.read(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        candidate["benchmark"] = benchmark
        candidate.log("benchmarked")
        self.write(candidate)
        return candidate

    def attach_adversarial(self, candidate_id, result, store=None):
        candidate = self.read(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        candidate["adversarial"] = result
        candidate.log("adversarial_tested",
                      note="passed" if result.get("passed") else "failed")
        self.write(candidate)
        return candidate

    # -- the gate ----------------------------------------------------------
    def evaluate_gate(self, candidate, gates=None, store=None):
        """Decide whether *candidate* may be promoted; return a verdict dict.

        Pass *store* to enforce the observed-outcome gate.  It is optional only
        so that the gate arithmetic stays unit-testable in isolation; the CLI
        always supplies it, and a verdict reached without it says so.
        """
        gates = dict(PROMOTION_GATES, **(gates or {}))
        reasons = []
        passed = True

        if gates["require_constitution_clean"]:
            if not candidate.get("constitution", {}).get("checked"):
                passed, _ = False, reasons.append("constitution check not run")
            elif candidate["constitution"].get("violations"):
                passed = False
                reasons.append("constitution violations: %s"
                               % "; ".join(candidate["constitution"]["violations"]))

        replay = candidate.get("replay") or {}
        episodes = int(replay.get("episodes", 0))
        if episodes < gates["min_replay_episodes"]:
            passed = False
            reasons.append("replayed on %d episodes, need %d"
                           % (episodes, gates["min_replay_episodes"]))
        if int(replay.get("distinct_sessions", 0)) < gates["min_distinct_sessions"]:
            passed = False
            reasons.append("evidence spans %d sessions, need %d"
                           % (replay.get("distinct_sessions", 0), gates["min_distinct_sessions"]))

        primary = replay.get("primary_delta")
        if primary is None:
            passed = False
            reasons.append("no primary-metric delta recorded")
        elif primary < gates["min_primary_improvement"]:
            passed = False
            reasons.append("primary improvement %.3f below required %.3f"
                           % (primary, gates["min_primary_improvement"]))

        regressions = []
        guarded = replay.get("guarded_deltas") or {}
        for metric, spec in GUARDED_METRICS.items():
            delta = guarded.get(metric)
            if delta is None:
                passed = False
                reasons.append("guarded metric missing: %s" % metric)
                continue
            worse = delta > spec["tolerance"] if spec["direction"] == "lower_is_better" \
                else -delta > spec["tolerance"]
            if worse:
                regressions.append({"metric": metric, "delta": delta,
                                    "tolerance": spec["tolerance"]})
        if regressions:
            passed = False
            reasons.append("guarded regressions: %s"
                           % ", ".join("%s %+.3f" % (r["metric"], r["delta"]) for r in regressions))

        # Grounding: how many real outcomes stand behind this, as opposed to
        # modelled ones?  Counted from resolved predictions, which are the only
        # record in LIWM of a commitment made before the user reacted.
        required_outcomes = int(gates.get("min_resolved_outcomes", 0) or 0)
        resolved_outcomes = None
        exposure = None
        if required_outcomes:
            if store is None:
                passed = False
                reasons.append("observed-outcome gate could not be evaluated: "
                               "no profile store supplied")
            else:
                if gates.get("require_user_facing_exposure", True):
                    from .experiments import ExperimentStore
                    exposure = ExperimentStore(store.home).exposure_for(
                        store, candidate.get("id"))
                observed = {}
                sessions = set()
                for event in store.events.iter_events(kinds={"outcome"}):
                    payload = event.get("payload") or {}
                    if (payload.get("evaluator_type") == "observed_human_outcome"
                            # Only outcomes whose label was read out of the
                            # evidence count.  A 0.2 outcome predates that rule
                            # and was never checked against anything, so it is
                            # not independent evidence of a human reacting.
                            and payload.get("outcome_binding") == "structured_feedback_event"
                            and event.get("provenance") == "explicit_user_review"
                            and payload.get("candidate_id") == candidate.get("id")
                            and payload.get("evidence_event_id")
                            and payload.get("prediction_id")
                            and parse_ts(event.get("ts"))
                            >= parse_ts(candidate.get("created_at"))):
                        if exposure is not None and payload.get("unit") not in exposure:
                            continue
                        observed[payload["prediction_id"]] = payload
                        sessions.add(event.get("session_id"))
                resolved_outcomes = len(observed)
                required_sessions = int(gates.get("min_outcome_sessions", 0) or 0)
                if resolved_outcomes < required_outcomes:
                    passed = False
                    reasons.append(
                        "only %d evidence-bound outcome(s) from interactions where the "
                        "candidate produced the work; need %d. Replay and shadow "
                        "evaluation do not count: nobody reacted to the candidate."
                        % (resolved_outcomes, required_outcomes))
                elif len({s for s in sessions if s}) < required_sessions:
                    passed = False
                    reasons.append("observed outcomes span %d session(s), need %d"
                                   % (len({s for s in sessions if s}), required_sessions))
                elif sum(int(row.get("actual_first_pass") or 0) for row in observed.values()) \
                        / resolved_outcomes < 0.6:
                    passed = False
                    reasons.append("candidate observed first-pass rate is below 0.60")

        benchmark = candidate.get("benchmark") or {}
        if (not benchmark.get("passed")
                or benchmark.get("candidate_id") != candidate.get("id")
                or benchmark.get("evaluator_type") not in {
                    "external_evaluator", "benchmark_ground_truth"
                }):
            passed = False
            reasons.append("independent benchmark result missing or invalid")

        if gates["require_adversarial_pass"]:
            adv = candidate.get("adversarial") or {}
            if not adv:
                passed = False
                reasons.append("adversarial suite not run")
            elif (not adv.get("passed") or adv.get("candidate_id") != candidate.get("id")
                  or not adv.get("suite_id")):
                passed = False
                reasons.append("adversarial suite result missing identity or failed: %s"
                               % ", ".join(adv.get("failures", [])[:3]))

        return {
            "passed": passed,
            "reasons": reasons,
            "episodes": episodes,
            "resolved_outcomes": resolved_outcomes,
            "user_facing_units": None if exposure is None else len(exposure),
            "primary_delta": primary,
            "regressions": regressions,
            "gates": gates,
            "evaluated_at": utc_now(),
        }

    def promote(self, candidate_id, store=None, gates=None, force_reason=None):
        """Promote a candidate if - and only if - it passes every gate."""
        candidate = self.read(candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        verdict = self.evaluate_gate(candidate, gates=gates, store=store)
        candidate["decision"] = {
            "outcome": "promoted" if verdict["passed"] else "rejected",
            "verdict": verdict,
            "at": utc_now(),
            "note": force_reason,
        }

        if not verdict["passed"]:
            candidate.log("rejected", note="; ".join(verdict["reasons"]))
            self.write(candidate, rejected=True)
            stale = self._path(candidate_id, rejected=False)
            if stale.is_file():
                stale.unlink()
            if store is not None:
                store.events.record(
                    "rule_rejected", "agent_inference",
                    payload={"candidate_id": candidate_id, "reason": "gate",
                             "reasons": verdict["reasons"], "title": candidate.get("title")},
                )
            return candidate, verdict

        with FileLock(self.lock_path):
            backup_file(self.promoted_path, self.backups, tag="promoted-rules")
            promoted = self.promoted_rules()
            promoted["rules"] = [r for r in promoted.get("rules", [])
                                 if r.get("id") != candidate_id]
            promoted["rules"].append(
                {
                    "id": candidate_id,
                    "title": candidate["title"],
                    "statement": candidate["statement"],
                    "surface": candidate["surface"],
                    "applies_to": candidate["applies_to"],
                    "parameters": candidate["parameters"],
                    "promoted_at": utc_now(),
                    "promotion_reason": "primary %+.3f over %d episodes; no guarded regression"
                                        % (verdict["primary_delta"], verdict["episodes"]),
                    "evidence": candidate["evidence"][:10],
                    "constitution_hash": constitution_hash(),
                    "active": True,
                    "revertible": True,
                }
            )
            promoted["updated_at"] = utc_now()
            promoted["schema_version"] = SCHEMA_VERSION
            write_json_atomic(self.promoted_path, promoted)

        candidate.log("promoted", note=candidate["decision"]["verdict"]["reasons"] or "gates passed")
        self.write(candidate)
        if store is not None:
            store.events.record(
                "rule_promoted", "agent_inference",
                payload={"candidate_id": candidate_id, "title": candidate["title"],
                         "primary_delta": verdict["primary_delta"],
                         "episodes": verdict["episodes"]},
            )
        return candidate, verdict

    def revert(self, rule_id, store=None, reason="user requested"):
        """Deactivate a promoted rule.  Always available (constitution C11)."""
        with FileLock(self.lock_path):
            backup_file(self.promoted_path, self.backups, tag="promoted-rules")
            promoted = self.promoted_rules()
            changed = False
            for rule in promoted.get("rules", []):
                if rule.get("id") == rule_id and rule.get("active"):
                    rule["active"] = False
                    rule["reverted_at"] = utc_now()
                    rule["revert_reason"] = reason
                    changed = True
            if changed:
                promoted["updated_at"] = utc_now()
                write_json_atomic(self.promoted_path, promoted)
        if changed and store is not None:
            store.events.record(
                "rule_rejected", "direct_user_message",
                payload={"candidate_id": rule_id, "reason": "reverted", "note": reason},
            )
        return changed

    def active_rules(self):
        return [r for r in self.promoted_rules().get("rules", []) if r.get("active")]
