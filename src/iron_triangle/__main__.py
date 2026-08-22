"""Module entry: ``python3 -m iron_triangle --config <private-config> <command>``."""

import pathlib
import sys

# When run from a source checkout without installation, put src/ on sys.path.
_SRC = pathlib.Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from iron_triangle.cli import main

raise SystemExit(main())
