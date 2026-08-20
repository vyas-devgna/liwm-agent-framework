"""Level 3: personal strategy adaptation.

Level 2 learns *about the user*.  Level 3 learns *how to work with this
particular user* - which kinds of question actually pay off for them, how hard
to push back, how bold an assumption may be before it should be checked.

These are small, bounded, numeric knobs, updated by exponentially weighted
moving average against observed results.  Bounded because an unbounded feedback
loop on interaction style is how an agent ends up either interrogating someone
forever or never asking anything again.  Every knob has a floor and a ceiling
that no amount of evidence can breach.
"""

from __future__ import annotations

from pathlib import Path

from .jsonio import (
    FileLock, backup_file, lifecycle_lock_path, read_json_resilient, utc_now,
    write_json_atomic,
)

__all__ = ["DEFAULT_STRATEGY", "BOUNDS", "StrategyStore", "update_from_events"]

SCHEMA_VERSION = "0.3.0"

#: Starting point for a brand-new profile: neutral, mildly conservative.
DEFAULT_STRATEGY = {
    "schema_version": SCHEMA_VERSION,
    "revision": 0,
    "updated_at": None,
    "observations": 0,
    "creative_question_weight": 0.50,
    "technical_question_weight": 0.50,
    "preferred_question_length": "short",
    "counterfactual_probe_effectiveness": 0.50,
    "challenge_strength": 0.50,
    "assumption_boldness": 0.45,
    "disclosure_verbosity": 0.50,
    "auto_low_threshold": 0.30,
    "auto_high_threshold": 0.62,
    "style_effectiveness": {
        "scenario": 1.0,
        "comparative": 1.0,
        "counterfactual": 1.0,
        "anti_example": 1.0,
        "tradeoff": 1.0,
        "lived_experience": 1.0,
        "emotional_reaction": 1.0,
        "direct_technical": 1.0,
        "constraint_check": 1.0,
    },
    "notes": [],
}

#: (floor, ceiling) per knob.  Constitutional guardrails in numeric form: e.g.
#: challenge_strength can never reach 0, because an agent that never disagrees
#: is optimising for approval (C09).
BOUNDS = {
    "creative_question_weight": (0.10, 0.90),
    "technical_question_weight": (0.10, 0.90),
    "counterfactual_probe_effectiveness": (0.05, 0.95),
    "challenge_strength": (0.20, 0.90),
    "assumption_boldness": (0.10, 0.85),
    "disclosure_verbosity": (0.15, 0.90),
    "auto_low_threshold": (0.15, 0.45),
    "auto_high_threshold": (0.50, 0.85),
}

STYLE_BOUNDS = (0.35, 1.8)

#: EWMA rate. Deliberately slow: strategy should move over weeks, not turns.
ALPHA = 0.12
#: Hard cap on how far a single update may move any knob.
MAX_STEP = 0.06


def _clamp(name, value):
    lo, hi = BOUNDS.get(name, (0.0, 1.0))
    return max(lo, min(hi, value))


def _ewma(current, target, alpha=ALPHA, max_step=MAX_STEP):
    proposed = current + alpha * (target - current)
    delta = max(-max_step, min(max_step, proposed - current))
    return current + delta


class StrategyStore:
    """Persistence and bounded updates for ``learning/personal-strategy.json``."""

    def __init__(self, home):
        self.home = Path(home)
        self.path = self.home / "learning" / "personal-strategy.json"
        self.backups = self.home / "backups"
        self.logs = self.home / "logs"
        self.lock_path = self.home / "learning" / ".strategy.lock"

    def load(self):
        data, _ = read_json_resilient(
            self.path, backups_dir=self.backups, logs_dir=self.logs, default=None
        )
        if not data:
            data = dict(DEFAULT_STRATEGY)
            data["style_effectiveness"] = dict(DEFAULT_STRATEGY["style_effectiveness"])
        # Forward-compatibility: fill in knobs added by a later version.
        for key, value in DEFAULT_STRATEGY.items():
            data.setdefault(key, value)
        return data

    def save(self, strategy):
        with FileLock(lifecycle_lock_path(self.home)):
            with FileLock(self.lock_path):
                return self._save_locked(strategy)

    def _save_locked(self, strategy):
        backup_file(self.path, self.backups, tag="strategy")
        strategy = dict(strategy)
        strategy["revision"] = int(strategy.get("revision", 0)) + 1
        strategy["updated_at"] = utc_now()
        write_json_atomic(self.path, strategy)
        return strategy

    def apply(self, adjustments, reason=None, store=None):
        """Apply bounded adjustments and record why."""
        with FileLock(lifecycle_lock_path(self.home)):
            with FileLock(self.lock_path):
                strategy = self.load()
                applied = {}
                for key, target in (adjustments or {}).items():
                    if key == "style_effectiveness":
                        for style, t in (target or {}).items():
                            cur = float(strategy["style_effectiveness"].get(style, 1.0))
                            new = max(STYLE_BOUNDS[0], min(STYLE_BOUNDS[1], _ewma(cur, float(t))))
                            if abs(new - cur) > 1e-6:
                                strategy["style_effectiveness"][style] = round(new, 4)
                                applied["style_effectiveness.%s" % style] = [round(cur, 4), round(new, 4)]
                        continue
                    if key not in BOUNDS:
                        continue
                    cur = float(strategy.get(key, DEFAULT_STRATEGY.get(key, 0.5)))
                    new = _clamp(key, _ewma(cur, float(target)))
                    if abs(new - cur) > 1e-6:
                        strategy[key] = round(new, 4)
                        applied[key] = [round(cur, 4), round(new, 4)]

                strategy["technical_question_weight"] = round(
                    _clamp("technical_question_weight", 1.0 - strategy["creative_question_weight"]), 4
                )
                strategy["observations"] = int(strategy.get("observations", 0)) + 1
                if applied:
                    note = {"at": utc_now(), "reason": reason, "changes": applied}
                    strategy["notes"] = ([note] + list(strategy.get("notes", [])))[:40]
                strategy = self._save_locked(strategy)
        if store is not None and applied:
            store.events.record(
                "strategy_update", "agent_inference",
                payload={"reason": reason, "changes": applied,
                         "revision": strategy["revision"]},
            )
        return strategy, applied

    def contract_overrides(self):
        """Strategy knobs expressed as overrides for a mode contract."""
        s = self.load()
        return {
            "experiential_ratio": s.get("creative_question_weight", 0.5),
            "technical_ratio": s.get("technical_question_weight", 0.5),
            "style_effectiveness": s.get("style_effectiveness", {}),
        }

    def auto_thresholds(self):
        s = self.load()
        return (float(s.get("auto_low_threshold", 0.30)),
                float(s.get("auto_high_threshold", 0.62)))


def update_from_events(store, strategy_store=None, window=60):
    """Derive strategy targets from recent interaction outcomes.

    The signals used, and what they mean:

    * question *usefulness* per style -> that style's effectiveness weight;
    * ignored / skipped questions -> raise the AUTO thresholds (ask less);
    * ``should_have_asked`` feedback -> lower them (ask more);
    * assumption error rate -> assumption boldness;
    * how corrections land -> challenge strength.
    """
    strategy_store = strategy_store or StrategyStore(store.home)
    events = store.events.read_all()[-window * 6:]

    style_useful, style_total = {}, {}
    asked = ignored = skipped = 0
    should_have_asked = too_many_questions = 0
    assumption_wrong = assumption_total = 0
    corrections = 0
    accepted = 0
    feedback_total = 0

    for e in events:
        payload = e.get("payload") or {}
        kind = e.get("kind")
        if kind == "question_asked":
            asked += 1
            style = payload.get("style")
            if style:
                style_total[style] = style_total.get(style, 0) + 1
        elif kind == "question_answered":
            style = payload.get("style")
            if style and payload.get("value") == "useful":
                style_useful[style] = style_useful.get(style, 0) + 1
        elif kind == "question_skipped":
            if payload.get("reason") == "ignored":
                ignored += 1
            else:
                skipped += 1
        elif kind == "assumption_made":
            assumption_total += 1
        elif kind == "correction":
            corrections += 1
        elif kind == "feedback":
            feedback_total += 1
            fk = payload.get("kind")
            if fk == "should_have_asked":
                should_have_asked += 1
                assumption_wrong += 1
            elif fk == "too_many_questions":
                too_many_questions += 1
            elif fk == "misunderstood_intent":
                assumption_wrong += 1
            if (payload.get("acceptance") or 0) >= 0.8:
                accepted += 1

    adjustments = {}

    styles = {}
    for style, total in style_total.items():
        if total < 3:
            continue
        rate = style_useful.get(style, 0) / total
        # A style that pays off half the time holds at 1.0; better raises it.
        styles[style] = max(STYLE_BOUNDS[0], min(STYLE_BOUNDS[1], 0.5 + rate * 1.2))
    if styles:
        adjustments["style_effectiveness"] = styles
        experiential = [s for s in styles if s not in ("direct_technical", "constraint_check")]
        technical = [s for s in styles if s in ("direct_technical", "constraint_check")]
        if experiential and technical:
            e_mean = sum(styles[s] for s in experiential) / len(experiential)
            t_mean = sum(styles[s] for s in technical) / len(technical)
            total = e_mean + t_mean
            if total > 0:
                adjustments["creative_question_weight"] = e_mean / total

    if asked >= 5:
        ignore_rate = (ignored + skipped) / asked
        if ignore_rate > 0.3 or too_many_questions:
            adjustments["auto_low_threshold"] = 0.45
            adjustments["auto_high_threshold"] = 0.80
        elif should_have_asked:
            adjustments["auto_low_threshold"] = 0.22
            adjustments["auto_high_threshold"] = 0.52

    if assumption_total >= 3 or assumption_wrong:
        error_rate = assumption_wrong / max(1, assumption_total, feedback_total)
        adjustments["assumption_boldness"] = max(0.1, 0.85 - 1.4 * error_rate)

    if feedback_total >= 5:
        # Frequent correction means the agent should surface its reasoning and
        # disagree earlier - not that it should become more agreeable (C09).
        correction_rate = corrections / max(1, feedback_total)
        adjustments["challenge_strength"] = 0.45 + 0.5 * correction_rate
        adjustments["disclosure_verbosity"] = 0.4 + 0.5 * correction_rate

    return strategy_store.apply(
        adjustments,
        reason="derived from last %d events (%d questions, %d feedback)"
               % (len(events), asked, feedback_total),
        store=store,
    )
