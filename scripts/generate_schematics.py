#!/usr/bin/env python3
"""CLI script to generate circuit schematic SVGs for documentation using schemdraw."""

import sys

from lattice_propagator.schematics import main

if __name__ == "__main__":
    sys.exit(main())
