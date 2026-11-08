#!/usr/bin/env python3
"""Generate circuit schematic SVGs for documentation using schemdraw.

Generates:
- docs/assets/wheatstone_bridge.svg
"""

from pathlib import Path

import schemdraw
import schemdraw.elements as elm

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = REPO_ROOT / "docs" / "assets"


def generate_wheatstone_bridge_schematic(output_path: Path) -> None:
    """Draw the Wheatstone bridge schematic with standard electrical symbols."""
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(output_path))
    print(f"Generated schematic: {output_path}")


def main() -> None:
    wheatstone_path = ASSETS_DIR / "wheatstone_bridge.svg"
    generate_wheatstone_bridge_schematic(wheatstone_path)


if __name__ == "__main__":
    main()
