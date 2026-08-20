"""Safe manipulation of LIWM's delimited host-instruction block.

The prompt installer may use the host's own edit tools, but this pure helper is
the normative behavior and makes idempotence/preservation independently testable.
"""

from __future__ import annotations

import re

BEGIN_PREFIX = "<!-- LIWM:BEGIN"
END_MARKER = "<!-- LIWM:END -->"
_BLOCK_RE = re.compile(r"(?m)^<!-- LIWM:BEGIN[^\n]*-->\n.*?^<!-- LIWM:END -->\n?", re.S)


class MalformedBootstrap(ValueError):
    pass


def _validate_markers(text):
    begins = text.count(BEGIN_PREFIX)
    ends = text.count(END_MARKER)
    if begins != ends or begins > 1:
        raise MalformedBootstrap(
            "expected zero or one complete LIWM block, found %d begin/%d end markers"
            % (begins, ends)
        )
    if begins and not _BLOCK_RE.search(text):
        raise MalformedBootstrap("LIWM markers are not a well-formed standalone block")
    return begins


def upsert_bootstrap(original, block):
    """Insert or replace exactly one block while preserving unrelated text."""
    _validate_markers(original)
    _validate_markers(block)
    if block.count(BEGIN_PREFIX) != 1:
        raise MalformedBootstrap("replacement must contain exactly one LIWM block")
    clean = block.rstrip("\n") + "\n"
    if BEGIN_PREFIX in original:
        return _BLOCK_RE.sub(clean, original, count=1)
    if not original:
        return clean
    # Always add exactly one separator newline. remove_bootstrap removes this
    # same byte, making install -> uninstall lossless even when the source had
    # zero, one, or several trailing newlines.
    return original + "\n" + clean


def remove_bootstrap(original):
    """Remove one complete block; return unchanged text when none exists."""
    _validate_markers(original)
    if BEGIN_PREFIX not in original:
        return original
    match = _BLOCK_RE.search(original)
    start, end = match.span()
    if start > 0 and original[start - 1] == "\n":
        start -= 1
    return original[:start] + original[end:]
