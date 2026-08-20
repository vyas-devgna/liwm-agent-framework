"""Feedback interpretation.

Users are not going to fill in rating forms, so LIWM learns from what they
already do: correcting, rewriting, choosing, accepting, abandoning, and
occasionally saying something plainly.

The important decisions in this module:

* **Scope defaults to the project.**  "Too complex" said about one artifact is
  evidence about that artifact.  It becomes evidence about the person only via
  the promotion rules in :mod:`liwm.scope`, which need it to recur across
  projects.  This is the single biggest guard against a personalisation system
  turning one bad afternoon into a personality.
* **Channel determines strength.**  A typed sentence outranks a behavioural
  inference by design, and behavioural signals are explicitly marked as weak.
* **Acceptance is separated from correctness.**  ``accepted`` feeds
  satisfaction metrics; it is never treated as proof that the work was right
  (constitution C09).
"""

from __future__ import annotations

import uuid

from .jsonio import utc_now

__all__ = [
    "FEEDBACK_KINDS",
    "CHANNELS",
    "interpret",
    "record_feedback",
    "acceptance_score",
]

#: The lightweight review vocabulary from the milestone review loop.  Natural
#: language is always sufficient; these are the shorthands, not a required UI.
FEEDBACK_KINDS = {
    "exactly_right": {
        "acceptance": 1.0,
        "revision_expected": False,
        "nudges": (),
        "note": "full acceptance",
    },
    "mostly_right": {
        "acceptance": 0.8,
        "revision_expected": True,
        "nudges": (),
        "note": "accepted with minor edits",
    },
    "direction_right_execution_wrong": {
        "acceptance": 0.45,
        "revision_expected": True,
        "nudges": (),
        "note": "intent understood, craft missed - do not update intent beliefs",
    },
    "misunderstood_intent": {
        "acceptance": 0.1,
        "revision_expected": True,
        "nudges": (),
        "note": "intent model was wrong - highest-value learning signal",
    },
    "technically_wrong": {
        "acceptance": 0.0,
        "revision_expected": True,
        "nudges": (),
        "note": "correctness failure; never excused by taste alignment",
    },
    "too_conventional": {
        "acceptance": 0.35,
        "revision_expected": True,
        "nudges": (
            ("creative_profile.novelty_seeking", "novel"),
            ("creative_profile.conventionality_tolerance", "low"),
        ),
        "note": "wanted something less expected",
    },
    "too_ambitious": {
        "acceptance": 0.35,
        "revision_expected": True,
        "nudges": (
            ("creative_profile.creative_risk_appetite", "safe"),
            ("working_style.scope_discipline", "tight_scope"),
        ),
        "note": "overreached relative to what was wanted",
    },
    "too_complex": {
        "acceptance": 0.4,
        "revision_expected": True,
        "nudges": (
            ("creative_profile.simplicity_vs_richness", "minimal"),
            ("interaction_profile.preferred_verbosity", "terse"),
        ),
        "note": "wanted less",
    },
    "too_simple": {
        "acceptance": 0.4,
        "revision_expected": True,
        "nudges": (
            ("creative_profile.simplicity_vs_richness", "feature_rich"),
            ("interaction_profile.explanation_depth", "full_derivation"),
        ),
        "note": "wanted more",
    },
    "too_technical": {
        "acceptance": 0.45,
        "revision_expected": True,
        "nudges": (
            ("interaction_profile.technical_language_preference", "plain"),
            ("communication_profile.vocabulary_register", "plain"),
        ),
        "note": "register mismatch",
    },
    "too_verbose": {
        "acceptance": 0.5,
        "revision_expected": True,
        "nudges": (
            ("interaction_profile.preferred_verbosity", "terse"),
            ("interaction_profile.explanation_depth", "conclusion_plus_why"),
        ),
        "note": "length mismatch",
    },
    "too_terse": {
        "acceptance": 0.5,
        "revision_expected": True,
        "nudges": (
            ("interaction_profile.preferred_verbosity", "thorough"),
            ("interaction_profile.explanation_depth", "full_derivation"),
        ),
        "note": "length mismatch",
    },
    "too_many_questions": {
        "acceptance": 0.5,
        "revision_expected": False,
        "nudges": (
            ("interaction_profile.preferred_question_frequency", "minimal"),
            ("interaction_profile.autonomy_preference", "act_then_report"),
        ),
        "note": "interaction cost too high - always global-eligible, it is about LIWM itself",
    },
    "should_have_asked": {
        "acceptance": 0.3,
        "revision_expected": True,
        "nudges": (
            ("interaction_profile.preferred_question_frequency", "moderate"),
            ("interaction_profile.confirmation_preference", "confirm_risky"),
        ),
        "note": "acted on an assumption that should have been checked",
    },
    "custom": {
        "acceptance": None,
        "revision_expected": None,
        "nudges": (),
        "note": "free-text; the host model extracts observations",
    },
}

#: Feedback channel -> (source_type, confidence character).
CHANNELS = {
    "explicit": {
        "source_type": "explicit_statement",
        "provenance": "direct_user_message",
        "note": "the user said it",
    },
    "corrective": {
        "source_type": "explicit_correction",
        "provenance": "direct_user_message",
        "note": "the user corrected an output or an assumption",
    },
    "comparative": {
        "source_type": "comparative_choice",
        "provenance": "direct_user_message",
        "note": "the user picked between offered alternatives",
    },
    "repeated_comparative": {
        "source_type": "repeated_selection",
        "provenance": "direct_user_message",
        "note": "the same choice, repeatedly",
    },
    "edit": {
        "source_type": "direct_edit",
        "provenance": "direct_user_edit",
        "note": "the user rewrote the artifact, revealing a preference",
    },
    "outcome": {
        "source_type": "outcome_signal",
        "provenance": "agent_inference",
        "note": "accepted / shipped / abandoned / reworked",
    },
    "behavioral": {
        "source_type": "single_behavioral",
        "provenance": "agent_inference",
        "note": "one implicit signal - weak by construction",
    },
    "repeated_behavioral": {
        "source_type": "repeated_behavioral",
        "provenance": "agent_inference",
        "note": "the same implicit signal several times",
    },
}

#: Dimensions that are about LIWM's own interaction style rather than about the
#: work.  These may enter at global scope directly, because "stop asking me so
#: much" is not project-specific.
def acceptance_score(kind, custom=None):
    """Numeric acceptance in [0, 1], or ``None`` when it must be supplied."""
    if kind in FEEDBACK_KINDS and FEEDBACK_KINDS[kind]["acceptance"] is not None:
        return FEEDBACK_KINDS[kind]["acceptance"]
    return custom


def interpret(kind, channel="explicit", text=None, project_id=None, domain=None,
              global_intent=False, extra_observations=None):
    """Turn a feedback event into observations, correctly scoped.

    ``global_intent`` should be set only when the user is plainly speaking about
    how they want to be worked with in general ("I always want the short
    version"), not about this artifact.  When in doubt, leave it false: the
    promotion machinery will generalise later if the pattern is real.
    """
    spec = FEEDBACK_KINDS.get(kind, FEEDBACK_KINDS["custom"])
    chan = CHANNELS.get(channel, CHANNELS["explicit"])

    observations = []
    for dimension, value in spec["nudges"]:
        if global_intent:
            scope, scope_key = "global", None
        elif project_id:
            scope, scope_key = "project", project_id
        elif domain:
            scope, scope_key = "domain", domain
        else:
            scope, scope_key = "session", None
        observations.append(
            {
                "dimension": dimension,
                "value": value,
                "polarity": "support",
                "source_type": chan["source_type"],
                "scope": scope,
                "scope_key": scope_key,
                "decay_policy": "standard",
                "note": "feedback:%s via %s" % (kind, channel),
            }
        )

    for obs in extra_observations or []:
        obs = dict(obs)
        obs.setdefault("source_type", chan["source_type"])
        obs.setdefault("polarity", "support")
        if "scope" not in obs:
            if global_intent:
                obs["scope"], obs["scope_key"] = "global", None
            elif project_id:
                obs["scope"], obs["scope_key"] = "project", project_id
            elif domain:
                obs["scope"], obs["scope_key"] = "domain", domain
            else:
                obs["scope"], obs["scope_key"] = "session", None
        observations.append(obs)

    return {
        "kind": kind,
        "channel": channel,
        "provenance": chan["provenance"],
        "source_type": chan["source_type"],
        "acceptance": spec["acceptance"],
        "revision_expected": spec["revision_expected"],
        "scope_note": (
            "global (the user explicitly spoke generally)"
            if global_intent else (
                "project-scoped by default" if project_id
                else "domain-scoped by default" if domain
                else "session-only (no durable scope supplied)"
            )
        ),
        "observations": observations,
        "text": text,
    }


def record_feedback(store, kind, channel="explicit", text=None, project_id=None,
                    domain=None, session_id=None, artifact=None, decision_id=None,
                    prediction_id=None, global_intent=False, extra_observations=None,
                    custom_acceptance=None, provenance=None, derived_from=None,
                    selected_option=None):
    """Record feedback as events and fold the result into the profile.

    Returns the feedback record, which is also appended to the project's
    ``feedback.json`` when a project is in play.
    """
    parsed = interpret(
        kind, channel=channel, text=text, project_id=project_id, domain=domain,
        global_intent=global_intent, extra_observations=extra_observations,
    )
    allowed_provenance = {
        "explicit": {"direct_user_message", "explicit_user_review"},
        "corrective": {"direct_user_message", "explicit_user_review"},
        "comparative": {"direct_user_message", "explicit_user_review"},
        "repeated_comparative": {"direct_user_message", "explicit_user_review"},
        "edit": {"direct_user_edit"},
        "outcome": {"agent_inference"},
        "behavioral": {"agent_inference"},
        "repeated_behavioral": {"agent_inference"},
    }
    actual_provenance = provenance or parsed["provenance"]
    if actual_provenance not in allowed_provenance.get(channel, set()):
        raise ValueError(
            "provenance %r is incompatible with feedback channel %r" %
            (actual_provenance, channel)
        )
    record = {
        "id": "fbk_%s" % uuid.uuid4().hex[:12],
        "at": utc_now(),
        "kind": kind,
        "channel": channel,
        "text": text,
        "artifact": artifact,
        "decision_id": decision_id,
        "prediction_id": prediction_id,
        # Which candidate the user actually picked, when the feedback is a
        # choice.  A preference prediction can only be scored against an
        # observed human outcome if the choice itself is on the record.
        "selected_option": str(selected_option) if selected_option is not None else None,
        "acceptance": acceptance_score(kind, custom_acceptance),
        "project_id": project_id,
        "domain": domain,
        "session_id": session_id,
        "observation_count": len(parsed["observations"]),
        "scope_note": parsed["scope_note"],
    }

    store.events.record(
        "feedback", actual_provenance,
        payload=record,
        derived_from=derived_from,
        session_id=session_id, project_id=project_id, domain=domain,
    )
    for obs in parsed["observations"]:
        store.events.record(
            "observation", actual_provenance,
            observation=obs,
            derived_from=derived_from,
            session_id=session_id, project_id=project_id, domain=domain,
        )
    store.rebuild(reason="feedback")

    if project_id:
        from .projects import ProjectStore
        from .config import ConfigStore
        project_record = dict(record)
        if not ConfigStore(store.home).load().get("privacy", {}).get("store_free_text", False):
            project_record.pop("text", None)
        ProjectStore(store.home, project_id).record_feedback(project_record)
        if decision_id:
            ProjectStore(store.home, project_id).attach_outcome(
                decision_id, {"acceptance": record["acceptance"], "kind": kind},
                feedback_ref=record["id"],
            )
    return record
