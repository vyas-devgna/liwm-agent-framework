"""One tombstone rule, expressed for both projections.

``liwm forget`` writes an append-only tombstone rather than deleting anything.
The profile fold has always honoured it.  The intent graph did not, which meant
a preference the user deleted stayed reachable through a second view of the
same evidence.  Both projections now derive their answer from this module.

The rule is one sentence: *a tombstone reaches evidence recorded before it, and
nothing recorded after it.*  Evidence supplied later can therefore re-establish
what was forgotten, which is what makes forgetting a correction rather than a
permanent hole.

Two expressions of that one rule live here because the two projections are
shaped differently.  :func:`apply_to_fold` drops folded belief state, which is
what ``profile.fold`` accumulates; :func:`invalidated_event_ids` names the
events themselves, which is what the intent graph needs in order to decide
whether an element still has a basis.  ``tests/test_invalidation.py`` asserts
the two agree on every observable outcome.
"""

from __future__ import annotations

from .scope import belief_key

__all__ = ["apply_to_fold", "invalidated_event_ids", "matches_tombstone"]


def apply_to_fold(payload, observations, meta, rejections, projects_seen):
    """Apply one ``forget`` tombstone to the fold's accumulators, in place."""
    if payload.get("dimension"):
        dimension = payload["dimension"]
        for old_key in [k for k, value in meta.items()
                        if value.get("dimension") == dimension]:
            observations.pop(old_key, None)
            meta.pop(old_key, None)
        for rejected_key in [k for k in rejections if k[2] == dimension]:
            rejections.pop(rejected_key, None)
    if payload.get("belief_key"):
        observations.pop(payload["belief_key"], None)
        meta.pop(payload["belief_key"], None)
    if payload.get("project_id"):
        project_id = payload["project_id"]
        for old_key in [k for k, value in meta.items()
                        if value.get("scope") == "project"
                        and value.get("scope_key") == project_id]:
            observations.pop(old_key, None)
            meta.pop(old_key, None)
        for rejected_key in [k for k in rejections
                             if k[0] == "project" and k[1] == project_id]:
            rejections.pop(rejected_key, None)
        projects_seen.discard(project_id)


def matches_tombstone(event, payload):
    """Whether *event* is evidence that the tombstone *payload* removes."""
    observation = event.get("observation") or {}
    dimension = observation.get("dimension")

    if payload.get("dimension"):
        if dimension == payload["dimension"]:
            return True
        if (event.get("kind") == "rejection"
                and (event.get("payload") or {}).get("dimension") == payload["dimension"]):
            return True

    if payload.get("belief_key") and dimension:
        scope = observation.get("scope", "global")
        scope_key = observation.get("scope_key")
        if scope == "project" and not scope_key:
            scope_key = event.get("project_id")
        if scope == "domain" and not scope_key:
            scope_key = event.get("domain")
        if belief_key(scope, scope_key, dimension,
                      observation.get("value")) == payload["belief_key"]:
            return True

    project_id = payload.get("project_id")
    if project_id:
        if event.get("project_id") == project_id:
            return True
        if observation.get("scope") == "project" and observation.get("scope_key") == project_id:
            return True
        element = (event.get("payload") or {}).get("element") or {}
        if element.get("scope") == "project" and element.get("scope_key") == project_id:
            return True

    return False


def invalidated_event_ids(events):
    """Ids of events that a later ``forget`` tombstone removed from active state.

    *events* must already be restricted to the active branch.  A tombstone only
    reaches strictly lower sequence numbers, so the pass is quadratic in the
    number of tombstones rather than in the log.
    """
    tombstones = [
        (int(event.get("sequence") or 0), event.get("payload") or {})
        for event in events
        if event.get("kind") == "forget" and not event.get("quarantined")
    ]
    if not tombstones:
        return frozenset()
    invalidated = set()
    for event in events:
        sequence = int(event.get("sequence") or 0)
        for tombstone_sequence, payload in tombstones:
            if sequence < tombstone_sequence and matches_tombstone(event, payload):
                invalidated.add(event.get("event_id"))
                break
    return frozenset(invalidated)
