"""The profile quality report.

Answers, honestly: what does LIWM actually know, what is it guessing, and where
is it probably wrong?

Deliberately free of personality language.  No archetypes, no types, no scores
about the person.  Every line is either an observation with provenance or an
admission of ignorance (constitution C08).
"""

from __future__ import annotations

from .evidence import age_days
from .taxonomy import DIMENSIONS, decision_impact

__all__ = ["profile_report", "render_text"]

HIGH = 0.70
MEDIUM = 0.40
STALE_DAYS = 240


def profile_report(store, metrics=None, strategy=None, promoted_rules=None):
    """Structured report on the state and quality of the profile."""
    profile = store.load()
    beliefs = [b for b in profile.get("beliefs", []) if b.get("status") == "active"]

    high = [b for b in beliefs if b["confidence"] >= HIGH]
    medium = [b for b in beliefs if MEDIUM <= b["confidence"] < HIGH]
    low = [b for b in beliefs if b["confidence"] < MEDIUM]

    stale = [
        b for b in beliefs
        if age_days(b["last_seen"]) > STALE_DAYS and b["confidence"] >= MEDIUM
    ]

    by_domain = {}
    for b in beliefs:
        key = b.get("domain") or ("global" if b["scope"] == "global" else "unscoped")
        by_domain.setdefault(key, []).append(b)

    covered = {b["dimension"] for b in beliefs}
    known_dims = {d["dimension"] for d in DIMENSIONS}
    gaps = sorted(
        (d for d in known_dims - covered),
        key=lambda d: -decision_impact(d),
    )[:10]

    recent_changes = sorted(beliefs, key=lambda b: b["last_seen"], reverse=True)[:8]

    return {
        "generated_from_revision": profile.get("revision"),
        "onboarding": profile.get("onboarding", {}).get("status"),
        "summary": {
            "beliefs_total": len(beliefs),
            "high_confidence": len(high),
            "medium_confidence": len(medium),
            "low_confidence": len(low),
            "hypotheses": len(profile.get("cross_domain_hypotheses", [])),
            "contradictions_open": len(profile.get("contradictions", [])),
            "rejections_recorded": len(profile.get("rejections", [])),
            "domains_with_evidence": len([d for d in by_domain if d not in ("global", "unscoped")]),
            "quarantined_events": profile.get("statistics_summary", {}).get("quarantined_events", 0),
        },
        "high_confidence_knowledge": [_row(b) for b in
                                      sorted(high, key=lambda b: -b["confidence"])[:15]],
        "low_confidence_hypotheses": [_row(b) for b in
                                      sorted(low, key=lambda b: -decision_impact(b["dimension"]))[:10]],
        "cross_domain_hypotheses": profile.get("cross_domain_hypotheses", [])[:8],
        "contradictions": profile.get("contradictions", [])[:8],
        "stale_assumptions": [
            dict(_row(b), days_since_confirmed=round(age_days(b["last_seen"])))
            for b in sorted(stale, key=lambda b: b["last_seen"])[:8]
        ],
        "evidence_by_domain": {
            domain: {
                "beliefs": len(rows),
                "mean_confidence": round(sum(b["confidence"] for b in rows) / len(rows), 3),
                "well_evidenced": len([b for b in rows if b["confidence"] >= HIGH]),
            }
            for domain, rows in sorted(by_domain.items())
        },
        "coverage_gaps": [
            {"dimension": d, "decision_impact": decision_impact(d),
             "note": "no evidence yet; high impact if it matters to your work"}
            for d in gaps
        ],
        "recently_changed": [_row(b) for b in recent_changes],
        "user_rejections": profile.get("rejections", [])[-6:],
        "current_strategy": strategy or {},
        "active_promoted_rules": promoted_rules or [],
        "learning_performance": (metrics or {}).get("rates", {}),
        "calibration": (metrics or {}).get("calibration", {}),
        "improvement": (metrics or {}).get("improvement", {}),
        "caveats": [
            "Every entry is a hypothesis supported by recorded evidence, not a fact about you.",
            "Confidence reflects evidence strength and provenance, not certainty about a person.",
            "Project-scoped entries apply only to that project.",
            "Anything here can be corrected, forgotten or reset at any time.",
        ],
    }


def _row(belief):
    return {
        "dimension": belief["dimension"],
        "value": belief["value"],
        "confidence": belief["confidence"],
        "scope": belief["scope"],
        "scope_key": belief.get("scope_key"),
        "origin": belief.get("origin", "observed"),
        "evidence_count": belief.get("evidence_count", 0),
        "source_types": belief.get("source_types", []),
        "last_seen": belief.get("last_seen"),
        "belief_id": belief["id"],
        "limiting_factor": belief.get("limiting_factor"),
    }


def render_text(report, width=88):
    """Human-readable rendering for the terminal."""
    lines = []

    def head(title):
        lines.append("")
        lines.append(title)
        lines.append("-" * min(width, max(12, len(title))))

    s = report["summary"]
    lines.append("LIWM profile report  (revision %s, onboarding: %s)"
                 % (report.get("generated_from_revision"), report.get("onboarding")))
    lines.append("%d beliefs: %d high / %d medium / %d low confidence, %d open contradictions"
                 % (s["beliefs_total"], s["high_confidence"], s["medium_confidence"],
                    s["low_confidence"], s["contradictions_open"]))

    if report["high_confidence_knowledge"]:
        head("What LIWM is fairly confident about")
        for row in report["high_confidence_knowledge"]:
            lines.append("  %-46s %-20s %.2f  [%s%s]"
                         % (row["dimension"], _short(row["value"]), row["confidence"],
                            row["scope"],
                            "/" + str(row["scope_key"]) if row["scope_key"] else ""))

    if report["low_confidence_hypotheses"]:
        head("Guesses LIWM would not act on without checking")
        for row in report["low_confidence_hypotheses"]:
            lines.append("  %-46s %-20s %.2f  (%s)"
                         % (row["dimension"], _short(row["value"]), row["confidence"],
                            row.get("limiting_factor") or "thin evidence"))

    if report["contradictions"]:
        head("Contradictions")
        for c in report["contradictions"]:
            vals = " vs ".join("%s (%s %.2f)"
                               % (_short(k["value"]), k["scope"], k["confidence"])
                               for k in c["candidates"])
            lines.append("  %-40s %s" % (c["dimension"], vals))
            lines.append("      %s" % c["suggested_resolution"])

    if report["stale_assumptions"]:
        head("Stale - not reconfirmed recently")
        for row in report["stale_assumptions"]:
            lines.append("  %-46s %-18s last seen %d days ago"
                         % (row["dimension"], _short(row["value"]),
                            row["days_since_confirmed"]))

    if report["cross_domain_hypotheses"]:
        head("Cross-domain guesses (untested)")
        for h in report["cross_domain_hypotheses"]:
            lines.append("  %s -> %s: %s = %s (%.2f, needs independent evidence)"
                         % (h["source_domain"], h["target_domain"], h["dimension"],
                            _short(h["value"]), h["confidence"]))

    if report["coverage_gaps"]:
        head("Highest-impact things LIWM does not know")
        for gap in report["coverage_gaps"][:6]:
            lines.append("  %-46s impact %.2f" % (gap["dimension"], gap["decision_impact"]))

    if report.get("evidence_by_domain"):
        head("Evidence by domain")
        for domain, info in report["evidence_by_domain"].items():
            lines.append("  %-24s %3d beliefs, mean confidence %.2f, %d well-evidenced"
                         % (domain, info["beliefs"], info["mean_confidence"],
                            info["well_evidenced"]))

    perf = report.get("learning_performance") or {}
    if perf:
        head("Learning performance")
        for key in ("first_pass_acceptance", "rolling_first_pass_acceptance",
                    "explicit_correction_rate", "question_ignore_rate",
                    "questions_per_accepted_outcome", "assumption_error_rate"):
            if perf.get(key) is not None:
                lines.append("  %-38s %s" % (key, perf[key]))
        imp = report.get("improvement") or {}
        if imp.get("verdict"):
            lines.append("  %-38s %s (delta %s)" % ("trend", imp["verdict"], imp.get("delta")))

    if report.get("active_promoted_rules"):
        head("Active learned rules")
        for rule in report["active_promoted_rules"]:
            lines.append("  %s: %s" % (rule.get("id", "?")[:16], rule.get("statement", "")))

    head("Caveats")
    for caveat in report["caveats"]:
        lines.append("  - %s" % caveat)
    return "\n".join(lines)


def _short(value, limit=18):
    s = str(value)
    return s if len(s) <= limit else s[: limit - 1] + "…"
