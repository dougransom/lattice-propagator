"""Test suite for degenerate computation, multi-pathway redundancy, and fault tolerance."""

from __future__ import annotations

from lattice_propagator.degenerate import (
    DegenerateBranch,
    DegeneratePipeline,
    add_degenerate_pipeline,
)
from lattice_propagator.lattice import (
    Contradiction,
    IntervalValue,
)
from lattice_propagator.primitives import PropagatorNetwork
from lattice_propagator.tms import NetworkTMS


def test_degenerate_branch_creation() -> None:
    net = PropagatorNetwork("BranchTest")
    c = net.add_cell("c1")
    b = DegenerateBranch("sensor", c, priority=0.9, description="High precision sensor")
    assert b.name == "sensor"
    assert b.cell is c
    assert b.priority == 0.9
    assert b.assumption_id == "branch_sensor"
    assert b.description == "High precision sensor"


def test_degenerate_pipeline_consensus_fusion() -> None:
    """Branches agree and monotonically refine interval uncertainty."""
    net = PropagatorNetwork("ConsensusTest")
    target = net.add_cell("room_temp")

    c_sensor = net.add_cell("c_sensor")
    c_model = net.add_cell("c_model")
    c_sched = net.add_cell("c_sched")

    b_sensor = DegenerateBranch("sensor", c_sensor, priority=1.0)
    b_model = DegenerateBranch("model", c_model, priority=0.7)
    b_sched = DegenerateBranch("sched", c_sched, priority=0.3)

    pipeline = add_degenerate_pipeline(
        net,
        target,
        [b_sensor, b_model, b_sched],
        mode="consensus",
    )

    assert pipeline.status == "idle"
    assert pipeline.is_degraded is False

    # 1. Supply schedule fallback
    c_sched.set_value(IntervalValue(18.0, 26.0))
    net.run()

    assert target.value == IntervalValue(18.0, 26.0)
    assert pipeline.is_degraded is True  # primary sensor is still Bottom!
    assert pipeline.status == "degraded"

    # 2. Supply physical model
    c_model.set_value(IntervalValue(20.0, 24.0))
    net.run()

    assert target.value == IntervalValue(20.0, 24.0)

    # 3. Supply primary sensor
    c_sensor.set_value(IntervalValue(21.0, 22.5))
    net.run()

    # Monotonic intersection across all three
    assert target.value == IntervalValue(21.0, 22.5)
    assert pipeline.is_degraded is False
    assert pipeline.status == "consensus"

    diag = pipeline.diagnostics()
    assert diag["status"] == "consensus"
    assert diag["primary_branch"] == "sensor"
    assert len(diag["active_branches"]) == 3


def test_degenerate_pipeline_manual_retraction_and_restoration() -> None:
    """Primary sensor drops offline or is retracted, falling back to auxiliary model."""
    net = PropagatorNetwork("RetractTest")
    target = net.add_cell("room_temp")

    c_sensor = net.add_cell("c_sensor", IntervalValue(21.0, 22.0))
    c_model = net.add_cell("c_model", IntervalValue(20.0, 24.0))

    b_sensor = DegenerateBranch("sensor", c_sensor, priority=1.0)
    b_model = DegenerateBranch("model", c_model, priority=0.5)

    pipeline = DegeneratePipeline("deg_pipe", target, [b_sensor, b_model])
    net.add_propagator(pipeline)
    net.run()

    assert target.value == IntervalValue(21.0, 22.0)
    assert pipeline.is_degraded is False

    # Retract sensor
    ok = pipeline.retract_branch("sensor", reason="sensor_offline")
    assert ok is True
    net.run()

    # Gracefully degraded to model: [20.0, 24.0]
    assert target.value == IntervalValue(20.0, 24.0)
    assert pipeline.is_degraded is True
    assert pipeline.status == "degraded"

    # Restore sensor
    ok_restore = pipeline.restore_branch("sensor")
    assert ok_restore is True
    net.run()

    assert target.value == IntervalValue(21.0, 22.0)
    assert pipeline.is_degraded is False
    assert pipeline.status == "consensus"


def test_degenerate_pipeline_contradiction_resolution_ddb() -> None:
    """When a branch asserts contradictory evidence, DDB retracts the culprit."""
    net = PropagatorNetwork("ConflictTest")
    NetworkTMS(net)
    target = net.add_cell("room_temp")

    c_sensor = net.add_cell("c_sensor", IntervalValue(80.0, 85.0))  # Glitched sensor!
    c_model = net.add_cell("c_model", IntervalValue(20.0, 23.0))

    # Give the glitched sensor lower priority/confidence (e.g. 0.4 vs model 0.8)
    b_sensor = DegenerateBranch("sensor", c_sensor, priority=0.4)
    b_model = DegenerateBranch("model", c_model, priority=0.8)

    pipeline = add_degenerate_pipeline(net, target, [b_sensor, b_model])
    net.run()

    # Contradiction: [80, 85] ∩ [20, 23] = ∅
    assert isinstance(target.value, Contradiction)
    assert pipeline.status == "contradiction"

    # Resolve conflict via DDB
    culprit = pipeline.resolve_conflict()
    assert culprit == "branch_sensor"

    # Target successfully recovered to the consistent model
    assert target.value == IntervalValue(20.0, 23.0)
    assert pipeline.status == "degraded"  # sensor retracted, model remains


def test_degenerate_pipeline_tiered_mode() -> None:
    """Tiered mode strictly selects the highest-priority non-empty tier."""
    net = PropagatorNetwork("TieredTest")
    target = net.add_cell("target")

    c_high = net.add_cell("c_high")
    c_med = net.add_cell("c_med", IntervalValue(20.0, 24.0))
    c_low = net.add_cell("c_low", IntervalValue(15.0, 30.0))

    b_high = DegenerateBranch("high", c_high, priority=1.0)
    b_med = DegenerateBranch("med", c_med, priority=0.6)
    b_low = DegenerateBranch("low", c_low, priority=0.2)

    pipeline = DegeneratePipeline("tiered_pipe", target, [b_high, b_med, b_low], mode="tiered")
    net.add_propagator(pipeline)
    net.run()

    # High is Bottom, so med is selected
    assert target.value == IntervalValue(20.0, 24.0)

    # Now high produces a value
    c_high.set_value(IntervalValue(21.5, 22.5))
    net.run()

    assert target.value == IntervalValue(21.5, 22.5)

    # Retract high
    pipeline.retract_branch("high", reason="offline")
    net.run()

    # Tiered fallback selects med
    assert target.value == IntervalValue(20.0, 24.0)
