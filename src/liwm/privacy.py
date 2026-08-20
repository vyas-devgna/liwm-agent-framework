"""The privacy gate.

Constitutional invariant C03 forbids inferring or storing sensitive attributes.
This module is where that becomes mechanical rather than aspirational: every
observation passes through :func:`screen_observation` before it can become an
event, and every event passes through it again before it can become a belief.

Design notes
------------
* The gate is **deny-by-default for dimensions**: a dimension whose path
  contains a forbidden root is refused outright, no matter how the user phrased
  it.  A user is allowed to *tell* an agent anything; LIWM simply refuses to
  turn it into a persistent personality feature.
* Value screening is heuristic and therefore *advisory* for free text: it
  raises the refusal for high-signal matches and flags weaker ones for review.
  Heuristics cannot be complete, so the schema-level dimension allowlist is the
  real guarantee, and this is defence in depth.
* Refusals are themselves recorded, with the offending content **redacted**, so
  that "LIWM ignored something" is auditable without storing the thing ignored.
"""

from __future__ import annotations

import re

from .constitution import FORBIDDEN_DIMENSION_ROOTS

__all__ = [
    "SensitiveAttributeRefused",
    "screen_dimension",
    "screen_value",
    "screen_observation",
    "redact",
    "SENSITIVE_CATEGORIES",
]


class SensitiveAttributeRefused(ValueError):
    """Raised when an observation would store a protected attribute."""

    def __init__(self, category, detail=""):
        self.category = category
        self.detail = detail
        super().__init__("refused: observation touches protected category %r%s"
                         % (category, (" (%s)" % detail) if detail else ""))


#: Category -> compiled patterns.  Deliberately conservative: these fire on
#: assertions *about the person*, which is what C03 protects, not on ordinary
#: technical vocabulary.  Every pattern is unit-tested against false positives
#: drawn from normal software conversation.
SENSITIVE_CATEGORIES = {
    "race_ethnicity": [
        r"\b(?:i am|i'm|user is|they are)\s+(?:black|white|asian|latino|latina|hispanic|arab|jewish|indigenous|native american)\b",
        r"\b(?:race|ethnicity|ethnic background)\s*(?:is|:)\s*\w+",
    ],
    "religion": [
        r"\b(?:i am|i'm|user is)\s+(?:a\s+)?(?:muslim|christian|jewish|hindu|buddhist|sikh|atheist|agnostic|catholic|protestant|mormon)\b",
        r"\b(?:i|user)\s+(?:practice[sd]?|follow(?:s|ed)?|converted to)\s+(?:islam|christianity|judaism|hinduism|buddhism|sikhism)\b",
        r"\b(?:religion|faith|religious belief)\s*(?:is|:)\s*\w+",
    ],
    "sexual_orientation": [
        r"\b(?:i am|i'm|user is)\s+(?:gay|lesbian|bisexual|straight|queer|asexual|heterosexual|homosexual)\b",
        r"\b(?:sexual orientation|sexuality)\s*(?:is|:)\s*\w+",
    ],
    "gender_identity": [
        r"\b(?:i am|i'm|user is)\s+(?:transgender|trans|nonbinary|non-binary|cisgender|intersex)\b",
        r"\bgender identity\s*(?:is|:)\s*\w+",
    ],
    "health": [
        r"\b(?:i (?:have|suffer from|was diagnosed with)|user has|diagnosed with)\s+(?:adhd|autism|depression|anxiety disorder|bipolar|cancer|diabetes|epilepsy|hiv|ptsd|ocd|dyslexia|schizophrenia)\b",
        r"\b(?:medical condition|diagnosis|prescription|medication)\s*(?:is|:)\s*\w+",
        # "blind"/"deaf" are heavily figurative in technical speech ("I am blind
        # to why this fails", "deaf to the warning"), so only the literal sense
        # counts.
        r"\b(?:i am|i'm|user is)\s+(?:disabled|neurodivergent)\b",
        r"\b(?:i am|i'm|user is)\s+(?:blind|deaf)(?!\s+(?:to|about|spot))\b",
    ],
    "political_affiliation": [
        # Allows intervening adjectives ("I am a registered Republican").
        r"\b(?:i am|i'm|user is)\s+(?:an?\s+)?(?:\w+\s+){0,2}(?:republican|democrat|conservative voter|liberal voter|socialist|communist|libertarian|leftist|right-wing|left-wing)\b",
        r"\b(?:i|user)\s+(?:vote[sd]?|voting)\s+(?:for|republican|democrat|labour|tory)\b",
        r"\bpolitical (?:affiliation|party|views)\s*(?:is|:)\s*\w+",
    ],
    "criminal_history": [
        # "convicted by the argument" is a figure of speech, not a record.
        r"\b(?:i was|i've been|user was)\s+(?:arrested|incarcerated|imprisoned|on parole|on probation)\b",
        r"\b(?:i was|i've been|user was)\s+convicted(?!\s+by\s+(?:the\s+)?(?:argument|reasoning|logic|case|point))\b",
        r"\b(?:criminal record|felony conviction)\b",
    ],
    "immigration_status": [
        r"\b(?:i am|i'm|user is)\s+(?:an?\s+)?(?:immigrant|undocumented|asylum seeker|refugee|green card holder|on a visa)\b",
        r"\bimmigration status\s*(?:is|:)\s*\w+",
    ],
    "union_membership": [
        r"\b(?:i am|i'm|user is)\s+(?:a\s+)?union member\b",
    ],
    "biometrics": [
        r"\b(?:fingerprint|retina scan|iris scan|face ?print|voice ?print|dna (?:sample|profile))\b",
    ],
    "financial_account": [
        # Card-shaped and IBAN-shaped strings; SSN-shaped strings.
        r"\b(?:\d[ -]?){13,19}\b",
        r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b",
        r"\b\d{3}-\d{2}-\d{4}\b",
    ],
    "precise_location": [
        # Street addresses and coordinate pairs; city/country alone is not protected.
        r"\b\d{1,5}\s+[A-Z][a-z]+\s+(?:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr)\b",
        r"\b-?\d{1,3}\.\d{4,},\s*-?\d{1,3}\.\d{4,}\b",
    ],
    "intelligence_score": [
        r"\biq\s*(?:score|of|is|:)\s*\d+",
        r"\b(?:iq|intelligence quotient)\s+\d{2,3}\b",
    ],
}

_COMPILED = {
    cat: [re.compile(p, re.IGNORECASE) for p in pats]
    for cat, pats in SENSITIVE_CATEGORIES.items()
}

_REDACTION = "[redacted-by-liwm-privacy-gate]"


def screen_dimension(dimension):
    """Return the offending category when *dimension* is forbidden, else ``None``.

    Dimension screening is exact and structural: it looks at whole dotted path
    segments rather than substrings, so ``domain_fluency.political_science``
    (a legitimate field of expertise) and ``domain_fluency.health_informatics``
    (a legitimate technical domain) are not confused with
    ``political_affiliation`` or a medical condition.

    Matching is therefore exact-segment or ``*_<root>`` suffix only.  Prefix
    matching was tried and removed: it blocked real domains of expertise, and
    the genuine guarantee here is the taxonomy allowlist in
    :func:`liwm.taxonomy.is_known_dimension`, which this backstops.
    """
    if not dimension:
        return None
    segments = re.split(r"[.\[\]/]+", str(dimension).lower())
    for seg in segments:
        seg = seg.strip("_ ")
        if not seg:
            continue
        if seg in FORBIDDEN_DIMENSION_ROOTS:
            return seg
        # Catch compound leaf names such as "user_religion" or "self_reported_iq".
        for root in FORBIDDEN_DIMENSION_ROOTS:
            if seg.endswith("_" + root):
                return root
    return None


def screen_value(value):
    """Return ``(category, matched_pattern)`` for a sensitive value, else ``(None, None)``."""
    if value is None:
        return None, None
    if isinstance(value, (list, tuple, set)):
        for item in value:
            cat, pat = screen_value(item)
            if cat:
                return cat, pat
        return None, None
    if isinstance(value, dict):
        for k, v in value.items():
            cat, pat = screen_value(k)
            if cat:
                return cat, pat
            cat, pat = screen_value(v)
            if cat:
                return cat, pat
        return None, None
    if not isinstance(value, str):
        return None, None
    for cat, patterns in _COMPILED.items():
        for pat in patterns:
            if pat.search(value):
                return cat, pat.pattern
    return None, None


def screen_observation(dimension=None, value=None, text=None, strict=True):
    """Screen a candidate observation.

    Returns a dict describing the verdict.  With ``strict=True`` (the default,
    and what the event writer uses) a hit raises
    :class:`SensitiveAttributeRefused` instead of returning.
    """
    cat = screen_dimension(dimension)
    if cat:
        if strict:
            raise SensitiveAttributeRefused(cat, "dimension %r" % dimension)
        return {"allowed": False, "category": cat, "where": "dimension"}

    for label, candidate in (("value", value), ("text", text)):
        cat, pattern = screen_value(candidate)
        if cat:
            if strict:
                raise SensitiveAttributeRefused(cat, "%s matched /%s/" % (label, pattern))
            return {"allowed": False, "category": cat, "where": label, "pattern": pattern}

    return {"allowed": True, "category": None, "where": None}


def redact(text, max_len=280):
    """Return a length-capped copy of *text* with sensitive spans removed.

    Used when LIWM must record *that* something was refused without recording
    *what* it was.
    """
    if text is None:
        return None
    if max_len <= 0:
        return ""
    s = str(text)
    for patterns in _COMPILED.values():
        for pat in patterns:
            s = pat.sub(_REDACTION, s)
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s
