"""Scope: the firewall between "true for this project" and "true about you".

The single most common way a personalisation system becomes actively harmful is
scope leakage.  A user says *"this banking app must be extremely conservative"*
and three weeks later the agent is refusing to suggest anything adventurous for
their art project, because a project constraint was quietly promoted into a
personality trait.

LIWM therefore keeps four scopes and makes upward movement expensive:

    session  ->  project  ->  domain  ->  global
    (hours)      (weeks)      (months)    (years)

Promotion is never automatic on repetition alone.  It requires *independent*
evidence: distinct projects for a domain claim, distinct domains for a global
claim, spread across distinct sessions and across time.  Every promotion is
confidence-discounted, recorded as an event, and reversible.
"""

from __future__ import annotations

from .evidence import age_days

__all__ = [
    "SCOPES",
    "SCOPE_ORDER",
    "PromotionPolicy",
    "DEFAULT_POLICY",
    "evaluate_promotions",
    "cross_domain_hypotheses",
    "belief_key",
    "resolve_for_context",
]

SCOPES = ("session", "project", "domain", "global")
SCOPE_ORDER = {name: i for i, name in enumerate(SCOPES)}


def belief_key(scope, scope_key, dimension, value):
    """Stable identity for a belief: one (scope, key, dimension, value) claim."""
    return "%s|%s|%s|%s" % (scope, scope_key or "-", dimension, _norm(value))


def _norm(value):
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ",".join(sorted(_norm(v) for v in value))
    return str(value)


class PromotionPolicy:
    """Thresholds governing scope promotion.

    These are configuration, not constants of nature - ``liwm.evaluation`` can
    sweep them - but they are deliberately strict by default.  Being slow to
    generalise is a much cheaper failure than being wrong about a person.
    """

    def __init__(
        self,
        min_projects_for_domain=2,
        min_domains_for_global=2,
        min_sessions_for_domain=2,
        min_sessions_for_global=3,
        min_source_confidence=0.50,
        min_global_source_confidence=0.55,
        max_opposing_confidence=0.35,
        min_span_days_domain=0.0,
        min_span_days_global=1.0,
        domain_discount=0.75,
        global_discount=0.60,
        cross_domain_discount=0.35,
        cross_domain_max_confidence=0.35,
    ):
        self.min_projects_for_domain = min_projects_for_domain
        self.min_domains_for_global = min_domains_for_global
        self.min_sessions_for_domain = min_sessions_for_domain
        self.min_sessions_for_global = min_sessions_for_global
        self.min_source_confidence = min_source_confidence
        self.min_global_source_confidence = min_global_source_confidence
        self.max_opposing_confidence = max_opposing_confidence
        self.min_span_days_domain = min_span_days_domain
        self.min_span_days_global = min_span_days_global
        self.domain_discount = domain_discount
        self.global_discount = global_discount
        self.cross_domain_discount = cross_domain_discount
        self.cross_domain_max_confidence = cross_domain_max_confidence

    def to_dict(self):
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data):
        return cls(**{k: v for k, v in (data or {}).items() if k in cls().__dict__})


DEFAULT_POLICY = PromotionPolicy()


def _sessions(belief):
    return {s for s in (belief.get("session_ids") or []) if s}


def _span_days(beliefs):
    firsts = [b.get("first_seen") for b in beliefs if b.get("first_seen")]
    lasts = [b.get("last_seen") for b in beliefs if b.get("last_seen")]
    if not firsts or not lasts:
        return 0.0
    return max(0.0, age_days(min(firsts), now=max(lasts)))


def evaluate_promotions(beliefs, policy=None, now=None):
    """Return promotion proposals derived from *beliefs*.

    *beliefs* is the flat list from a materialised profile.  The return value is
    a list of dicts describing proposed higher-scope beliefs, each carrying the
    reason it qualified so ``liwm why`` can explain it later.
    """
    policy = policy or DEFAULT_POLICY
    proposals = []

    active = [
        b for b in beliefs
        if b.get("status", "active") == "active" and not b.get("rejected_by_user")
    ]

    # --- project -> domain -------------------------------------------------
    by_domain_dim_value = {}
    for b in active:
        if b.get("scope") != "project":
            continue
        domain = b.get("domain")
        if not domain:
            continue
        key = (domain, b.get("dimension"), _norm(b.get("value")))
        by_domain_dim_value.setdefault(key, []).append(b)

    for (domain, dimension, value_norm), group in sorted(by_domain_dim_value.items()):
        projects = {b.get("scope_key") for b in group if b.get("scope_key")}
        sessions = set().union(*[_sessions(b) for b in group]) if group else set()
        qualifying = [b for b in group if b.get("confidence", 0.0) >= policy.min_source_confidence]
        if len(projects) < policy.min_projects_for_domain:
            continue
        if len(sessions) < policy.min_sessions_for_domain:
            continue
        if len({b.get("scope_key") for b in qualifying}) < policy.min_projects_for_domain:
            continue
        if _span_days(group) < policy.min_span_days_domain:
            continue
        opposing = _opposing(active, "domain", domain, dimension, value_norm)
        if opposing >= policy.max_opposing_confidence:
            continue

        base = max(b.get("confidence", 0.0) for b in qualifying)
        proposals.append(
            {
                "target_scope": "domain",
                "scope_key": domain,
                "domain": domain,
                "dimension": dimension,
                "value": qualifying[0].get("value"),
                "confidence": round(base * policy.domain_discount, 4),
                "origin": "promoted",
                "promoted_from": sorted(b["id"] for b in qualifying if b.get("id")),
                "reason": (
                    "observed in %d distinct projects (%s) across %d sessions within domain %r"
                    % (len(projects), ", ".join(sorted(str(p) for p in projects)[:5]),
                       len(sessions), domain)
                ),
                "policy": "project->domain",
                "first_seen": min(b.get("first_seen") for b in qualifying),
                "last_seen": max(b.get("last_seen") for b in qualifying),
            }
        )

    # --- domain -> global --------------------------------------------------
    by_dim_value = {}
    for b in active:
        if b.get("scope") != "domain":
            continue
        key = (b.get("dimension"), _norm(b.get("value")))
        by_dim_value.setdefault(key, []).append(b)

    for (dimension, value_norm), group in sorted(by_dim_value.items()):
        domains = {b.get("scope_key") for b in group if b.get("scope_key")}
        sessions = set().union(*[_sessions(b) for b in group]) if group else set()
        qualifying = [
            b for b in group
            if b.get("confidence", 0.0) >= policy.min_global_source_confidence
        ]
        if len(domains) < policy.min_domains_for_global:
            continue
        if len({b.get("scope_key") for b in qualifying}) < policy.min_domains_for_global:
            continue
        if len(sessions) < policy.min_sessions_for_global:
            continue
        if _span_days(group) < policy.min_span_days_global:
            continue
        opposing = _opposing(active, "global", None, dimension, value_norm)
        if opposing >= policy.max_opposing_confidence:
            continue

        base = min(b.get("confidence", 0.0) for b in qualifying)  # weakest link
        proposals.append(
            {
                "target_scope": "global",
                "scope_key": None,
                "domain": None,
                "dimension": dimension,
                "value": qualifying[0].get("value"),
                "confidence": round(base * policy.global_discount, 4),
                "origin": "promoted",
                "promoted_from": sorted(b["id"] for b in qualifying if b.get("id")),
                "reason": (
                    "independently supported in %d distinct domains (%s) across %d sessions"
                    % (len(domains), ", ".join(sorted(str(d) for d in domains)[:5]), len(sessions))
                ),
                "policy": "domain->global",
                "first_seen": min(b.get("first_seen") for b in qualifying),
                "last_seen": max(b.get("last_seen") for b in qualifying),
            }
        )

    return proposals


def _opposing(beliefs, scope, scope_key, dimension, value_norm):
    """Highest confidence held by a *conflicting* belief at the target scope."""
    worst = 0.0
    for b in beliefs:
        if b.get("scope") != scope or b.get("dimension") != dimension:
            continue
        if scope_key is not None and b.get("scope_key") != scope_key:
            continue
        if _norm(b.get("value")) == value_norm:
            continue
        worst = max(worst, float(b.get("confidence", 0.0)))
    return worst


def cross_domain_hypotheses(beliefs, known_domains, policy=None):
    """Propose - never assert - that a domain preference might transfer.

    "They like minimal UIs" is not evidence that they like minimal prose.  These
    are generated as explicit hypotheses with heavily discounted confidence and
    a hard ceiling; they only become beliefs if independently observed in the
    target domain.
    """
    policy = policy or DEFAULT_POLICY
    out = []
    domain_beliefs = [
        b for b in beliefs
        if b.get("scope") == "domain"
        and b.get("status", "active") == "active"
        and b.get("confidence", 0.0) >= 0.6
        and not b.get("rejected_by_user")
    ]
    existing = {
        (b.get("scope_key"), b.get("dimension"))
        for b in beliefs if b.get("scope") == "domain"
    }
    for b in domain_beliefs:
        source_domain = b.get("scope_key")
        for target in sorted(known_domains):
            if target == source_domain:
                continue
            if (target, b.get("dimension")) in existing:
                continue  # already have real evidence there; no need to guess
            out.append(
                {
                    "kind": "cross_domain_hypothesis",
                    "source_domain": source_domain,
                    "target_domain": target,
                    "dimension": b.get("dimension"),
                    "value": b.get("value"),
                    "confidence": round(
                        min(
                            b.get("confidence", 0.0) * policy.cross_domain_discount,
                            policy.cross_domain_max_confidence,
                        ),
                        4,
                    ),
                    "status": "hypothesis",
                    "requires": "independent observation in target domain before use",
                    "source_belief_id": b.get("id"),
                }
            )
    return out


def resolve_for_context(beliefs, domain=None, project_id=None, min_confidence=0.0):
    """Pick the winning belief per dimension for a given working context.

    Narrower scope wins over broader scope at equal-or-better confidence, which
    is what makes "for this project, do the opposite" work without rewriting the
    global model.
    """
    best = {}
    for b in beliefs:
        if b.get("status", "active") != "active" or b.get("rejected_by_user"):
            continue
        scope = b.get("scope", "global")
        if scope == "project" and b.get("scope_key") != project_id:
            continue
        if scope == "domain" and (domain is None or b.get("scope_key") != domain):
            continue
        if scope == "session":
            continue
        conf = float(b.get("confidence", 0.0))
        if conf < min_confidence:
            continue
        dim = b.get("dimension")
        incumbent = best.get(dim)
        if incumbent is None:
            best[dim] = b
            continue
        # Specificity first, then confidence.
        if SCOPE_ORDER[scope] < SCOPE_ORDER[incumbent.get("scope", "global")]:
            best[dim] = b
        elif scope == incumbent.get("scope") and conf > float(incumbent.get("confidence", 0.0)):
            best[dim] = b
    return best
