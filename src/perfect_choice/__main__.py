"""Allow running as ``python -m perfect_choice``."""

from __future__ import annotations

import sys

from perfect_choice.cli import main

sys.exit(main())
