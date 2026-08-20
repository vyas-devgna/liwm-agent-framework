"""Runtime context projection: the small thing the agent actually reads.

Loading a full profile into every turn would be self-defeating - it costs the
context budget that the actual work needs, and buries the three facts that
matter under forty that do not.

So LIWM derives ``runtime_context.json``: a task-shaped, size-capped view
containing only what could change *this* piece of work.  Relevance is computed
from domain match, project match, confidence, decision impact and recency.  The
full evidence history stays on disk and is consulted only when asked.
"""

from __future__ import annotations

from pathlib import Path

from .evidence import age_days
from .config import ConfigStore
from .fatigue import profile_maturity
from .jsonio import utc_now, write_json_atomic
from .modes import Signals, mode_profile, resolve_auto
from .scope import resolve_for_context
from .taxonomy import decision_impact

__all__ = ["build_runtime_context", "write_runtime_context", "DEFAULT_MAX_BELIEFS"]

SCHEMA_VERSION = "0.1.0"

DEFAULT_MAX_BELIEFS = 14
#: Hard cap on the serialised projection.  If it does not fit, it is trimmed,
#: because an unbounded "compact" context is not compact.
MAX_BYTES = 6000


def _relevance(belief, domain, project_id, task_terms):
    conf = float(belief.get("confidence", 0.0))
    impact = decision_impact(belief.get("dimension", ""))

    scope = belief.get("scope", "global")
    if scope == "project":
        scope_score = 1.0 if belief.get("scope_key") == project_id else 0.0
    elif scope == "domain":
        scope_score = 1.0 if (domain and belief.get("scope_key") == domain) else 0.35
    else:
        scope_score = 0.75

    days = age_days(belief.get("last_seen"))
    recency = 1.0 if days < 45 else (0.85 if days < 180 else 0.65)

    term_bonus = 0.0
    if task_terms:
        haystack = ("%s %s" % (belief.get("dimension", ""), belief.get("value", ""))).lower()
        hits = sum(1 for t in task_terms if t and t in haystack)
        term_bonus = min(0.25, 0.08 * hits)

    return round(conf * impact * scope_score * recency + term_bonus, 5)


def build_runtime_context(
    store,
    domain=None,
    project_id=None,
    task=None,
    mode="auto",
    signals=None,
    max_beliefs=DEFAULT_MAX_BELIEFS,
    strategy=None,
    promoted_rules=None,
):
    """Assemble the compact projection for the current task."""
    config = ConfigStore(store.home).load()
    requested_mode = (mode or "auto").lower()
    if not config.get("enabled", True):
        contract = mode_profile("off")
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": utc_now(),
            "profile_revision": None,
            "onboarding_status": "not_consulted",
            "context": {"domain": domain, "project_id": project_id,
                        "task_hint": (task or "")[:160]},
            "mode": {
                "effective": "off", "requested": requested_mode,
                "resolved_from": "config", "question_budget": 0,
                "one_at_a_time": False, "experiential_ratio": 0.0,
                "investigation_need": None,
                "rationale": "LIWM is persistently disabled",
            },
            "profile_maturity": 0.0,
            "applies": [], "avoid": [], "open_uncertainties": [],
            "contradictions": [], "project": None, "active_rules": [],
            "strategy": {}, "learning_enabled": False,
            "reminders": ["LIWM is off; no profile or learning state was consulted."],
        }
    elif requested_mode == "auto" and config.get("default_mode", "auto") != "auto":
        mode = config["default_mode"]
    profile = store.load()
    beliefs = profile.get("beliefs", [])
    task_terms = [t.lower() for t in (task or "").split() if len(t) > 3][:12]

    resolved = resolve_for_context(beliefs, domain=domain, project_id=project_id,
                                   min_confidence=0.30)

    ranked = sorted(
        resolved.values(),
        key=lambda b: -_relevance(b, domain, project_id, task_terms),
    )[:max_beliefs]

    maturity = profile_maturity(profile, domain=domain)

    sig = signals if isinstance(signals, Signals) else Signals(**(signals or {}))
    sig.profile_maturity = maturity
    if not (signals or {}).get("domain_evidence"):
        sig.domain_evidence = min(
            1.0, len([b for b in beliefs if b.get("domain") == domain]) / 8.0
        ) if domain else 0.0

    if (mode or "auto").lower() == "auto":
        contract = resolve_auto(sig)
    else:
        contract = mode_profile(mode)
        contract["resolved_from"] = "explicit"
        contract["investigation_need"] = None
        contract["rationale"] = "mode set explicitly by the user"
    contract["max_questions"] = min(
        int(contract.get("max_questions", 0)),
        int(config.get("questioning", {}).get("max_questions_per_session", 12)),
    )

    project_summary = None
    if project_id:
        from .projects import ProjectStore
        ps = ProjectStore(store.home, project_id)
        if ps.exists():
            intent = ps.load_intent()
            project_summary = {
                "project_id": project_id,
                "stage": intent.get("stage"),
                "confidence": intent.get("confidence", {}).get("overall_intent"),
                "non_negotiables": [i["text"] for i in intent.get("non_negotiables", [])
                                    if i.get("status") == "active"][:5],
                "anti_goals": [i["text"] for i in intent.get("anti_goals", [])
                               if i.get("status") == "active"][:5],
                "open_questions": [i["text"] for i in intent.get("open_questions", [])
                                   if i.get("status") == "active"][:4],
                "undisclosed_assumptions": [
                    i["text"] for i in intent.get("assumptions", [])
                    if i.get("status") == "active" and not i.get("disclosed")
                ][:4],
            }

    relevant_contradictions = [
        c for c in profile.get("contradictions", [])
        if any(cand["scope_key"] in (None, domain, project_id) for cand in c["candidates"])
    ][:3]

    anti = [
        {"name": b.get("dimension", "").partition(".")[2],
         "value": b.get("value"), "confidence": b.get("confidence"),
         "scope": b.get("scope"), "scope_key": b.get("scope_key")}
        for b in resolved.values()
        if b.get("dimension", "").startswith("anti_preferences.")
    ][:5]

    profile_enabled = contract.get("use_profile", True)
    context = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "profile_revision": profile.get("revision"),
        "onboarding_status": profile.get("onboarding", {}).get("status", "not_started"),
        # Declining onboarding leaves the status at "not_started" forever, so
        # status alone cannot distinguish "never asked" from "asked, said no".
        # Without this flag the agent re-offers every session, which is exactly
        # the nagging the install prompt promises not to do.
        "onboarding_already_offered": bool(config.get("onboarding_offered", False)),
        "context": {"domain": domain, "project_id": project_id, "task_hint": (task or "")[:160]},
        "mode": {
            "effective": contract["mode"],
            "requested": requested_mode,
            "resolved_from": contract.get("resolved_from"),
            "question_budget": contract.get("max_questions"),
            "one_at_a_time": contract.get("one_at_a_time"),
            "experiential_ratio": contract.get("experiential_ratio"),
            "investigation_need": contract.get("investigation_need"),
            "rationale": contract.get("rationale"),
        },
        "profile_maturity": round(maturity, 4),
        "applies": [
            {
                "dimension": b["dimension"],
                "value": b["value"],
                "confidence": b["confidence"],
                "scope": b["scope"],
                "scope_key": b.get("scope_key"),
                "origin": b.get("origin", "observed"),
                "belief_id": b["id"],
            }
            for b in ranked
        ] if profile_enabled else [],
        "avoid": anti if profile_enabled else [],
        "open_uncertainties": [
            {"dimension": u["dimension"], "confidence": u["confidence"],
             "why": u["why_uncertain"]}
            for u in profile.get("uncertainties", [])[:5]
        ],
        "contradictions": relevant_contradictions if profile_enabled else [],
        "project": project_summary if profile_enabled else None,
        "active_rules": [
            {"id": r["id"], "statement": r["statement"], "parameters": r.get("parameters", {})}
            for r in (promoted_rules or [])
        ][:6],
        "strategy": {
            k: v for k, v in (strategy or {}).items()
            if k in ("creative_question_weight", "technical_question_weight",
                     "challenge_strength", "assumption_boldness", "disclosure_verbosity")
        } if profile_enabled else {},
        "learning_enabled": bool(config.get("learning_enabled", True) and
                                  contract.get("record_evidence", True)),
        "reminders": [
            "Explicit instructions in this conversation override everything below.",
            "These are hypotheses with confidence, not facts about the person.",
            "Project-scoped entries must not be generalised to the person.",
        ],
    }

    return _trim(context)


def _trim(context, max_bytes=MAX_BYTES):
    """Shrink the projection until it fits, dropping the least useful parts first."""
    import json

    order = ["contradictions", "open_uncertainties", "active_rules", "avoid"]
    while len(json.dumps(context, ensure_ascii=False).encode("utf-8")) > max_bytes:
        trimmed = False
        for key in order:
            if context.get(key):
                context[key] = context[key][:-1]
                trimmed = True
                break
        if not trimmed and len(context.get("applies", [])) > 4:
            context["applies"] = context["applies"][:-1]
            trimmed = True
        if not trimmed:
            context["truncated"] = True
            break
    return context


def write_runtime_context(store, path=None, **kwargs):
    """Build and persist the projection; returns ``(context, path)``."""
    context = build_runtime_context(store, **kwargs)
    target = Path(path) if path else (Path(store.home) / "runtime_context.json")
    write_json_atomic(target, context)
    return context, target
