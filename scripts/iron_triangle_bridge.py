#!/usr/bin/env python3
"""Backward-compatible entry point for the Iron Triangle bridge.

The implementation lives in ``src/iron_triangle``; this shim keeps the
documented invocation stable:

    python3 scripts/iron_triangle_bridge.py --config <private-config> <command>
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from iron_triangle.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
