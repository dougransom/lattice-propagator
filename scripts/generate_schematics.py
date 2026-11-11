#!/usr/bin/env python3
"""CLI script to generate circuit schematic SVGs for documentation using schemdraw."""

import sys
from pathlib import Path

# Ensure repo scripts directory is in path
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from schematics import main

if __name__ == "__main__":
    sys.exit(main())
