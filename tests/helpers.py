"""Shared test scaffolding."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from liwm.paths import ensure_layout  # noqa: E402
from liwm.profile import ProfileStore  # noqa: E402


def days_ago(n, base=None):
    """ISO timestamp *n* days in the past, for decay tests."""
    ref = base or datetime.now(timezone.utc)
    return (ref - timedelta(days=n)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class LiwmTestCase(unittest.TestCase):
    """Base case giving each test an isolated LIWM home."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="liwm-test-")
        self.home = ensure_layout(Path(self._tmp) / "home")
        self._old_env = os.environ.get("LIWM_HOME")
        os.environ["LIWM_HOME"] = str(self.home)
        self.store = ProfileStore(self.home)
        self.store.rebuild(reason="test-setup")

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("LIWM_HOME", None)
        else:
            os.environ["LIWM_HOME"] = self._old_env
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- convenience -------------------------------------------------------
    def observe(self, dimension, value, source_type="explicit_statement",
                provenance="direct_user_message", **kwargs):
        return self.store.observe(dimension, value, source_type=source_type,
                                  provenance=provenance, **kwargs)

    def belief(self, dimension, value=None, scope=None, scope_key=None, profile=None):
        profile = profile or self.store.load()
        rows = [b for b in profile["beliefs"] if b["dimension"] == dimension]
        if value is not None:
            rows = [b for b in rows if str(b["value"]) == str(value)]
        if scope is not None:
            rows = [b for b in rows if b["scope"] == scope]
        if scope_key is not None:
            rows = [b for b in rows if b.get("scope_key") == scope_key]
        rows.sort(key=lambda b: -b["confidence"])
        return rows[0] if rows else None

    def confidence(self, dimension, value=None, scope=None):
        b = self.belief(dimension, value=value, scope=scope)
        return b["confidence"] if b else 0.0

    def record_event(self, kind, provenance, **kwargs):
        event = self.store.events.record(kind, provenance, **kwargs)
        self.store.rebuild(reason="test")
        return event
