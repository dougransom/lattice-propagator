"""Unit tests for BeliefMassValue and DempsterShaferPropagator."""

import pytest

from lattice_propagator import (
    BeliefMassValue,
    Contradiction,
    DempsterShaferPropagator,
    FlatValue,
    PropagatorNetwork,
    SpatialZone,
    merge_lattice,
)


def test_belief_mass_initialization_and_metrics() -> None:
    """Verify belief, plausibility, doubt, and interval metrics."""
    frame = {"B", "K", "L", "A"}
    # Simple support function: 80% belief in {K, L}, 20% ignorance (Θ)
    m = BeliefMassValue.simple(hypothesis={"K", "L"}, confidence=0.8, frame=frame)

    assert m.belief("K") == 0.0
    assert m.plausibility("K") == 1.0
    assert m.plausibility("L") == 1.0
    assert m.plausibility("B") == pytest.approx(0.2, abs=1e-5)
    assert m.doubt("B") == pytest.approx(0.8, abs=1e-5)
    assert m.evidential_interval("K") == (0.0, 1.0)
    assert m.evidential_interval({"K", "L"}) == (0.8, 1.0)


def test_dempster_combination_rule() -> None:
    """Verify orthogonal sum combination of independent evidence."""
    frame = {"B", "K", "L", "A"}
    # Sensor 1 (Proxy 2): Doug in {K, L} with 85% confidence
    m1 = BeliefMassValue.simple({"K", "L"}, 0.85, frame=frame)
    # Sensor 2 (Proxy 1): Doug in {K} with 70% confidence
    m2 = BeliefMassValue.simple("K", 0.70, frame=frame)

    fused = m1.combine(m2)
    assert isinstance(fused, BeliefMassValue)
    # Fused mass should accumulate on {K}
    assert fused.belief("K") == pytest.approx(0.70, abs=1e-3)
    assert fused.plausibility("K") == 1.0
    assert fused.plausibility("L") == pytest.approx(0.255 + 0.045, abs=1e-3)
    assert fused.plausibility("B") == pytest.approx(0.045, abs=1e-3)


def test_conflict_detection_and_contradiction() -> None:
    """Verify orthogonal conflict K calculation and total contradiction."""
    frame = {"B", "K", "L", "A"}
    # Claim A: Doug is strictly in the Bathroom
    m_bath = BeliefMassValue.certain("B", frame=frame)
    # Claim B: Doug is strictly Away
    m_away = BeliefMassValue.certain("A", frame=frame)

    assert m_bath.conflict_with(m_away) == 1.0
    res = m_bath.combine(m_away)
    assert isinstance(res, Contradiction)


def test_lattice_merge_dispatch_for_belief_mass() -> None:
    """Verify BeliefMassValue works via merge_lattice."""
    frame = {"B", "K", "L", "A"}
    m1 = BeliefMassValue.simple("K", 0.6, frame=frame)
    m2 = BeliefMassValue.simple("K", 0.5, frame=frame)

    res = merge_lattice(m1, m2)
    assert isinstance(res, BeliefMassValue)
    assert res.belief("K") > 0.6


def test_dempster_shafer_propagator_in_network() -> None:
    """Verify DempsterShaferPropagator reacts in a PropagatorNetwork."""
    net = PropagatorNetwork("EvidenceNet")
    frame = {"B", "K", "L", "A"}

    cell_p1 = net.add_cell("Proxy1")
    cell_p2 = net.add_cell("Proxy2")
    fused_cell = net.add_cell("FusedLocation")
    conflict_cell = net.add_cell("ConflictMetric")

    prop = DempsterShaferPropagator(
        name="DS_Fusion",
        inputs=[cell_p1, cell_p2],
        output=fused_cell,
        conflict_cell=conflict_cell,
    )
    net.add_propagator(prop)

    # Proxy 1 reports
    cell_p1.set_value(BeliefMassValue.simple({"K", "B"}, 0.75, frame=frame))
    net.run()

    assert isinstance(fused_cell.value, BeliefMassValue)
    assert fused_cell.value.plausibility("K") == 1.0

    # Proxy 2 reports
    cell_p2.set_value(BeliefMassValue.simple({"K", "L"}, 0.80, frame=frame))
    net.run()

    assert isinstance(fused_cell.value, BeliefMassValue)
    # The intersection of {K, B} and {K, L} is {K}
    assert fused_cell.value.belief("K") == pytest.approx(0.75 * 0.80, abs=1e-3)
    assert isinstance(conflict_cell.value, FlatValue)


def test_spatial_zone_geometry() -> None:
    """Verify SpatialZone 2D containment."""
    bath = SpatialZone("Bathroom", x_min=-2.0, x_max=2.0, y_min=10.0, y_max=14.0)
    assert bath.contains(0.0, 12.0)
    assert not bath.contains(0.0, 5.0)
    assert not bath.contains(5.0, 12.0)
