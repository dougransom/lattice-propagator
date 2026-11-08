"""Test suite for circuit schematic generation using schemdraw."""

from pathlib import Path

from lattice_propagator.schematics import generate_wheatstone_bridge, main


def test_generate_wheatstone_bridge_svg(tmp_path: Path) -> None:
    output_svg = tmp_path / "test_wheatstone.svg"
    out = generate_wheatstone_bridge(output_svg)
    assert out.is_file()
    content = out.read_text(encoding="utf-8")
    assert "<svg" in content
    assert "R₁ = 1000 Ω ± 1%" in content
    assert "R₂ = 2000 Ω ± 1%" in content
    assert "R₃ = 1000 Ω ± 1%" in content
    assert "R_x (Unknown)" in content
    assert "V_s = 10.0 V ± 0.5%" in content
    assert "Galvanometer: V_g = 0.0 V (Null)" in content


def test_schematics_cli_main(tmp_path: Path) -> None:
    code = main(["--output-dir", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "wheatstone_bridge.svg").is_file()
