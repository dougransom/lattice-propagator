"""Schematic and electrical circuit diagram generation using schemdraw.

Provides programmatic and CLI generation of vector circuit schematics for
documentation, tutorials, and reports.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "docs" / "assets"


def generate_wheatstone_bridge(output_path: Path | None = None) -> Path:
    """Draw the Wheatstone bridge circuit schematic with standard electrical symbols."""
    try:
        import schemdraw
        import schemdraw.elements as elm
    except ImportError as err:
        raise ImportError(
            "schemdraw is required to generate electrical schematics. "
            "Install with: pip install 'lattice-propagator[visualize]'"
        ) from err

    d = schemdraw.Drawing(fontsize=13)

    # Wheatstone diamond bridge compound element
    bridge = d.add(
        elm.Wheatstone(
            labels=[
                "R₁ = 1000 Ω ± 1%",
                "R₃ = 1000 Ω ± 1%",
                "R_x (Unknown)",
                "R₂ = 2000 Ω ± 1%",
            ]
        )
    )

    # Galvanometer across Node B (left / W) and Node D (right / E)
    d.add(elm.Dot().at(bridge.W).label("Node B (V_b)", loc="left"))
    d.add(elm.Dot().at(bridge.E).label("Node D (V_d)", loc="right"))
    d.add(
        elm.MeterV()
        .endpoints(bridge.W, bridge.E)
        .label("Galvanometer: V_g = 0.0 V (Null)", loc="top")
    )

    # Node A at top (N)
    d.add(elm.Dot().at(bridge.N).label("Node A (V_s)", loc="top"))

    # Ground at bottom (S)
    d.add(elm.Dot().at(bridge.S).label("Ground: 0.0 V", loc="bottom"))
    d.add(elm.Ground().at(bridge.S))

    # Power supply on the left
    x_src = bridge.W.x - 3.2
    d.add(elm.Line().endpoints(bridge.N, (x_src, bridge.N.y)))
    d.add(
        elm.SourceV()
        .endpoints((x_src, bridge.S.y), (x_src, bridge.N.y))
        .label("V_s = 10.0 V ± 0.5%", loc="top")
    )
    d.add(elm.Line().endpoints((x_src, bridge.S.y), bridge.S))

    dest = output_path or (ASSETS_DIR / "wheatstone_bridge.svg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(dest))
    return dest


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for generating circuit schematics."""
    parser = argparse.ArgumentParser(
        prog="generate-schematics",
        description="Generate circuit schematic SVGs for documentation using schemdraw.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ASSETS_DIR,
        help="Target directory for generated SVG schematics (default: docs/assets).",
    )
    args = parser.parse_args(argv)

    wheatstone_svg = args.output_dir / "wheatstone_bridge.svg"
    out = generate_wheatstone_bridge(wheatstone_svg)
    print(f"Generated schematic: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

