"""Unit tests for TMS Dependency-Directed Backtracking, ChoiceEngine, and Lattice Combinators."""

import math

from lattice_propagator.lattice import (
    BOTTOM,
    Contradiction,
    DiscreteDomain,
    FlatValue,
    IntervalValue,
    MapLattice,
    SetLattice,
    merge_lattice,
)
from lattice_propagator.primitives import (
    AllDifferentPropagator,
    ChoiceEngine,
    PropagatorNetwork,
)
from lattice_propagator.tms import (
    Assumption,
    NetworkTMS,
    TruthMaintenanceSystem,
)


def test_set_lattice_combinator():
    """Verify monotonic set accumulation under union."""
    s1 = SetLattice.from_iterable(["lamp_living_room", "thermostat"])
    s2 = SetLattice.from_iterable(["motion_hallway", "thermostat"])

    merged = merge_lattice(s1, s2)
    assert isinstance(merged, SetLattice)
    assert len(merged) == 3
    assert "lamp_living_room" in merged
    assert "motion_hallway" in merged
    assert "thermostat" in merged

    # Merging with BOTTOM is identity
    assert merge_lattice(s1, BOTTOM) == s1
    assert merge_lattice(BOTTOM, s2) == s2


def test_map_lattice_combinator():
    """Verify monotonic key-wise mapping lattice merge."""
    m1 = MapLattice(
        {
            "temp": IntervalValue(18.0, 24.0),
            "mode": FlatValue("eco"),
        }
    )
    m2 = MapLattice(
        {
            "temp": IntervalValue(20.0, 26.0),
            "humidity": IntervalValue(40.0, 60.0),
        }
    )

    merged = merge_lattice(m1, m2)
    assert isinstance(merged, MapLattice)
    assert set(merged.mapping.keys()) == {"temp", "mode", "humidity"}

    # Overlapping key "temp" is merged: [18, 24] ⊔ [20, 26] = [20, 24]
    temp_val = merged.mapping["temp"]
    assert isinstance(temp_val, IntervalValue)
    assert math.isclose(temp_val.min_val, 20.0)
    assert math.isclose(temp_val.max_val, 24.0)

    # Disjoint keys are preserved
    assert merged.mapping["mode"] == FlatValue("eco")
    assert merged.mapping["humidity"] == IntervalValue(40.0, 60.0)

    # Conflict on a key results in overall Contradiction
    m_conflict = MapLattice({"mode": FlatValue("boost")})
    conflict_res = merge_lattice(merged, m_conflict)
    assert isinstance(conflict_res, Contradiction)


def test_tms_assumptions_and_nogood_recording():
    """Verify assumption tracking, nogood recording, and support sets in TMS."""
    asm = Assumption("speculative_mode", FlatValue("comfort"), confidence=0.8)
    assert asm.is_assumption is True
    assert asm.confidence == 0.8
    assert "speculative_mode" in asm.support

    tms = TruthMaintenanceSystem("ClimateTarget")
    tms.assert_evidence("user_schedule", IntervalValue(20.0, 22.0), is_assumption=False)
    tms.assert_evidence(
        "weather_adaptation",
        IntervalValue(21.0, 23.0),
        is_assumption=True,
        confidence=0.5,
    )

    fused = tms.compute_fused_value()
    assert isinstance(fused, IntervalValue)
    assert math.isclose(fused.min_val, 21.0)
    assert math.isclose(fused.max_val, 22.0)

    # Record a nogood
    ng = tms.record_nogood(["weather_adaptation", "grid_curtailment"])
    assert ng == frozenset(["weather_adaptation", "grid_curtailment"])
    assert ng in tms.nogoods


def test_network_tms_dependency_directed_backtracking():
    """Verify DDB automatically resolves contradictions by retracting the weakest assumption."""
    net = PropagatorNetwork("BeliefRevisionNet")
    tms = NetworkTMS(net)

    # Cell: target temperature
    cell = net.add_cell("TargetTemp")

    # Hard premise: Comfort policy specifies [20.0, 22.0]
    ctms = tms.get_or_create_cell_tms("TargetTemp")
    ctms.assert_evidence("policy_comfort", IntervalValue(20.0, 22.0), is_assumption=False)
    cell.set_value(ctms.compute_fused_value())

    # Defeasible Assumption 1: Solar boost assumes [23.0, 25.0] (confidence 0.6)
    tms.assume("TargetTemp", "solar_boost", IntervalValue(23.0, 25.0), confidence=0.6)

    # Merging comfort [20, 22] and solar boost [23, 25] creates a contradiction!
    fused_val = ctms.compute_fused_value()
    assert isinstance(fused_val, Contradiction)

    # Trigger DDB: conflict involves policy_comfort and solar_boost
    retracted = tms.resolve_contradiction(["policy_comfort", "solar_boost"])

    # solar_boost should be retracted because policy_comfort is a hard premise
    assert retracted == "solar_boost"
    assert tms.is_nogood(["policy_comfort", "solar_boost"])

    # Cell now reverts to consistent state [20, 22]
    new_val = ctms.compute_fused_value()
    assert isinstance(new_val, IntervalValue)
    assert math.isclose(new_val.min_val, 20.0)
    assert math.isclose(new_val.max_val, 22.0)


def test_choice_engine_interleaved_search():
    """Verify ChoiceEngine branches and backtracks to solve an undetermined constraint problem."""
    net = PropagatorNetwork("ChoiceNet")

    # 4 variables with discrete domains {1, 2, 3, 4}
    x1 = net.add_cell("X1", DiscreteDomain.range(1, 5))
    x2 = net.add_cell("X2", DiscreteDomain.range(1, 5))
    x3 = net.add_cell("X3", DiscreteDomain.range(1, 5))
    x4 = net.add_cell("X4", DiscreteDomain.range(1, 5))

    # All-different constraint across all 4
    net.add_propagator(AllDifferentPropagator("AllDiff", [x1, x2, x3, x4]))

    # Partial clues: X1 in {1, 2}, X2 in {2, 3}, X3 in {1, 3}, X4 = 4
    x1.set_value(DiscreteDomain({1, 2}), overwrite=True)
    x2.set_value(DiscreteDomain({2, 3}), overwrite=True)
    x3.set_value(DiscreteDomain({1, 3}), overwrite=True)
    x4.set_value(DiscreteDomain.single(4), overwrite=True)

    engine = ChoiceEngine(net)
    success = engine.first_solution()

    assert success is True
    assert engine.is_solved()

    # Solution must be a valid permutation of {1, 2, 3, 4}
    vals = [x1.value.value, x2.value.value, x3.value.value, x4.value.value]
    assert set(vals) == {1, 2, 3, 4}
    assert vals[3] == 4


def test_choice_engine_enumerates_multiple_solutions():
    """Verify iter_solutions and all_solutions find all distinct valid assignments."""
    net = PropagatorNetwork("MultiChoiceNet")
    x1 = net.add_cell("X1", DiscreteDomain({1, 2}))
    x2 = net.add_cell("X2", DiscreteDomain({1, 2}))
    x3 = net.add_cell("X3", DiscreteDomain({1, 2, 3}))
    net.add_propagator(AllDifferentPropagator("AllDiff", [x1, x2, x3]))

    engine = ChoiceEngine(net, variables=[x1, x2, x3])
    solutions = engine.all_solutions()

    # X1 in {1,2}, X2 in {1,2} -> 2 permutations; X3 is forced to 3 in both
    assert len(solutions) == 2
    tuples = {(s["X1"].value, s["X2"].value, s["X3"].value) for s in solutions}
    assert tuples == {(1, 2, 3), (2, 1, 3)}

    # Limited enumeration stops lazily
    limited = engine.all_solutions(limit=1)
    assert len(limited) == 1
    assert engine.all_solutions(limit=0) == []


def test_choice_engine_detects_unsolvable():
    """Verify ChoiceEngine returns False when no consistent branch exists."""
    net = PropagatorNetwork("UnsolvableNet")
    a = net.add_cell("A", DiscreteDomain({1, 2}))
    b = net.add_cell("B", DiscreteDomain({1, 2}))
    c = net.add_cell("C", DiscreteDomain({1, 2}))

    # 3 cells restricted to 2 values with all-different -> Pigeonhole contradiction!
    net.add_propagator(AllDifferentPropagator("Pigeonhole", [a, b, c]))

    engine = ChoiceEngine(net)
    success = engine.first_solution()
    assert success is False
    assert engine.all_solutions() == []
