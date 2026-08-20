"""Enable ``python3 -m liwm`` so the CLI works without an install step."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
