#!/usr/bin/env python3
"""Run the LIWM test suite with no third-party dependencies.

    python3 tests/run_tests.py            # everything
    python3 tests/run_tests.py -v         # verbose
    python3 tests/run_tests.py test_scope # one module
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
for path in (str(HERE), str(REPO_ROOT / "src")):
    if path not in sys.path:
        sys.path.insert(0, path)


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    verbosity = 2 if ("-v" in argv or "--verbose" in argv) else 1
    modules = [a for a in argv if not a.startswith("-")]

    loader = unittest.TestLoader()
    if modules:
        suite = unittest.TestSuite()
        for name in modules:
            suite.addTests(loader.loadTestsFromName(name))
    else:
        suite = loader.discover(str(HERE), top_level_dir=str(HERE))

    runner = unittest.TextTestRunner(verbosity=verbosity, buffer=False)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
