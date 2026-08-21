"""Token accounting: what LIWM actually costs the context window.

The central objection to persistent agent memory is that feeding it back into
the model doubles token usage and bloats the context.  That is an empirical
claim, and answering it requires counting, not asserting.  This module is the
counter.

Two counters, and which one produced a number is always recorded:

``exact``
    A real BPE tokenizer, used when one is importable.  LIWM never depends on
    one; benchmarks that publish absolute numbers install it deliberately.

``estimated``
    A dependency-free approximation.  It applies the GPT-family pre-tokenizer
    split, then charges extra for the boundaries BPE is forced to break on
    inside an identifier -- underscores, digits, and camelCase humps -- because
    profile payloads are dense in ``interaction_profile.preferred_verbosity``
    and a flat bytes-per-token ratio underestimates them badly.

Measured against ``cl100k_base`` over 75 real payloads from this repository
(Markdown, Python, JSON schemas, a full ``user.json`` and a runtime context
projection): mean error -0.2%, 71/75 within 10%, worst case -11.2% / +22.4%.
A flat bytes/4 scores 36/75 within 10% and -23.0% / +34.1% worst case.

Estimator error is a *shared* bias: every arm of a comparison is counted the
same way, so ratios between arms survive it even where absolutes do not.  Any
claim about absolute token cost should carry ``method == "exact"``.
"""

from __future__ import annotations

import re

__all__ = [
    "count_tokens", "estimate_tokens", "exact_tokens", "tokenizer_available",
    "account", "ESTIMATOR_ERROR", "PIECE_SCALE",
]

SCHEMA_VERSION = "0.4.0"

#: GPT-family pre-tokenizer split, in the subset of the pattern that Python's
#: ``re`` accepts.  Each piece it yields costs at least one token.
_PRETOKEN = re.compile(
    r"""'(?:[sdmt]|ll|ve|re)|[^\r\n\w]?\w+|\d{1,3}| ?[^\s\w]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+"""
)

#: Boundaries BPE cannot merge across inside one pre-token.
_SPLIT = re.compile(r"[_\d]|(?<=[a-z])(?=[A-Z])")

#: Median tokens-per-piece over the calibration corpus.  See the module
#: docstring for how it was measured and how wrong it gets.
PIECE_SCALE = 1.068

#: Worst observed signed error, as fractions.  Reported alongside estimates so
#: a consumer can widen a budget rather than discover the shortfall at runtime.
ESTIMATOR_ERROR = {"mean": -0.002, "low": -0.112, "high": 0.224, "samples": 75,
                   "reference": "cl100k_base"}


def _pieces(text):
    total = 0
    for piece in _PRETOKEN.findall(text):
        total += 1 + len(_SPLIT.findall(piece))
    return total


def estimate_tokens(text):
    """Approximate BPE token count with no dependency.  Never raises."""
    if not text:
        return 0
    return max(1, int(round(_pieces(text) * PIECE_SCALE)))


def _encoder():
    try:  # pragma: no cover - depends on an optional dev extra
        import tiktoken
    except Exception:
        return None
    try:  # pragma: no cover
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return None


def tokenizer_available():
    """Whether an exact tokenizer can be used for this process."""
    return _encoder() is not None


def exact_tokens(text):
    """Exact BPE token count, or ``None`` when no tokenizer is importable."""
    encoder = _encoder()
    if encoder is None:
        return None
    return len(encoder.encode(text or ""))


def count_tokens(text, prefer_exact=True):
    """Return ``(tokens, method)`` where method is ``"exact"`` or ``"estimated"``."""
    if prefer_exact:
        exact = exact_tokens(text)
        if exact is not None:
            return exact, "exact"
    return estimate_tokens(text), "estimated"


def account(payloads, prefer_exact=True):
    """Token account for a mapping of ``{label: text}``.

    Returns per-label counts, the total, and the counting method -- so a report
    can never quote a number without saying how it was obtained.
    """
    parts = {}
    method = "estimated"
    for label, text in (payloads or {}).items():
        body = text if isinstance(text, str) else str(text)
        tokens, method = count_tokens(body, prefer_exact=prefer_exact)
        parts[label] = {"tokens": tokens, "bytes": len(body.encode("utf-8"))}
    total = sum(row["tokens"] for row in parts.values())
    result = {"parts": parts, "total_tokens": total,
              "total_bytes": sum(row["bytes"] for row in parts.values()),
              "method": method}
    if method == "estimated":
        result["error_bounds"] = dict(ESTIMATOR_ERROR)
    return result
