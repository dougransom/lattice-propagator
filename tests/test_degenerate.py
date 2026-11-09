"""Test suite for degenerate computation, multi-pathway redundancy, and fault tolerance."""

from __future__ import annotations

import math
from typing import Any

from lattice_propagator.degenerate import (
    DegenerateBranch,
    DegeneratePipeline,
    add_degenerate_pipeline,
)
from lattice_propagator.lattice import (
    Bottom,
    Contradiction,
    IntervalValue,
)
from lattice_propagator.primitives import FunctionalPropagator, PropagatorNetwork
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


def test_vehicle_localization_degenerate_estimation() -> None:
    """Vehicle localization: camera bounding box, 3x BLE proxies, and door constraint."""
    net = PropagatorNetwork("CarLocalization")
    NetworkTMS(net)
    pos = net.add_cell("car_pos")

    c_cam = net.add_cell("camera", IntervalValue(5.0, 7.0))
    c_ble = net.add_cell("ble_proxies", IntervalValue(4.0, 9.0))
    c_door = net.add_cell("door", IntervalValue(0.0, 18.0))

    b_cam = DegenerateBranch("camera", c_cam, priority=1.0)
    b_ble = DegenerateBranch("ble", c_ble, priority=0.8)
    b_door = DegenerateBranch("door", c_door, priority=0.5)

    pipe = add_degenerate_pipeline(net, pos, [b_cam, b_ble, b_door])
    net.run()

    # Consensus in garage bay
    assert pos.value == IntervalValue(5.0, 7.0)
    assert pipe.status == "consensus"
    assert pipe.is_degraded is False

    # Simulate camera unable to see car (e.g. car moved to driveway)
    pipe.retract_branch("camera", reason="car_in_driveway")
    c_ble.set_value(IntervalValue(22.0, 26.0), overwrite=True)
    c_door.set_value(IntervalValue(18.0, 40.0), overwrite=True)
    net.run()

    # Degrades gracefully to BLE + Driveway door constraint
    assert pos.value == IntervalValue(22.0, 26.0)
    assert pipe.is_degraded is True
    assert pipe.status == "degraded"


def test_triangulation_with_degeneracy_scenarios() -> None:
    """Test 2D multilateration triangulation with camera degeneracy across 5 scenarios."""

    def build_network():
        net = PropagatorNetwork("Triangulation_With_Degeneracy")
        NetworkTMS(net)

        d1 = net.add_cell("d1_P1_NW", unit="ft")
        d2 = net.add_cell("d2_P2_NE", unit="ft")
        d3 = net.add_cell("d3_P3_SW", unit="ft")
        d4 = net.add_cell("d4_P4_SE", unit="ft")

        raw_cam_x = net.add_cell("raw_cam_x", unit="ft")
        raw_cam_y = net.add_cell("raw_cam_y", unit="ft")

        ble_x = net.add_cell("ble_x", unit="ft")
        ble_y = net.add_cell("ble_y", unit="ft")

        # Multilateration baseline equations
        def calc_x12(v1: IntervalValue, v2: IntervalValue) -> IntervalValue:
            return (v1 * v1 - v2 * v2 + 900.0) / 60.0

        def calc_x34(v3: IntervalValue, v4: IntervalValue) -> IntervalValue:
            return (v3 * v3 - v4 * v4 + 900.0) / 60.0

        def calc_y13(v1: IntervalValue, v3: IntervalValue) -> IntervalValue:
            return (v1 * v1 - v3 * v3 + 400.0) / 40.0

        def calc_y24(v2: IntervalValue, v4: IntervalValue) -> IntervalValue:
            return (v2 * v2 - v4 * v4 + 400.0) / 40.0

        net.add_propagator(
            FunctionalPropagator("prop_x12", calc_x12, [d1, d2], ble_x, overwrite=False)
        )
        net.add_propagator(
            FunctionalPropagator("prop_x34", calc_x34, [d3, d4], ble_x, overwrite=False)
        )
        net.add_propagator(
            FunctionalPropagator("prop_y13", calc_y13, [d1, d3], ble_y, overwrite=False)
        )
        net.add_propagator(
            FunctionalPropagator("prop_y24", calc_y24, [d2, d4], ble_y, overwrite=False)
        )

        # Identity & Bay Gating
        gated_cam_x = net.add_cell("gated_cam_x", unit="ft")
        gated_cam_y = net.add_cell("gated_cam_y", unit="ft")

        def gate_x(bx: Any, by: Any, cx: Any) -> Any:
            if not (isinstance(bx, IntervalValue) and isinstance(by, IntervalValue)):
                return Bottom()
            in_bay2 = (
                bx.max_val >= 10.0
                and bx.min_val <= 20.0
                and by.max_val >= 0.0
                and by.min_val <= 20.0
            )
            return cx if in_bay2 else Bottom()

        def gate_y(bx: Any, by: Any, cy: Any) -> Any:
            if not (isinstance(bx, IntervalValue) and isinstance(by, IntervalValue)):
                return Bottom()
            in_bay2 = (
                bx.max_val >= 10.0
                and bx.min_val <= 20.0
                and by.max_val >= 0.0
                and by.min_val <= 20.0
            )
            return cy if in_bay2 else Bottom()

        net.add_propagator(
            FunctionalPropagator(
                "gate_cam_x", gate_x, [ble_x, ble_y, raw_cam_x], gated_cam_x, overwrite=False
            )
        )
        net.add_propagator(
            FunctionalPropagator(
                "gate_cam_y", gate_y, [ble_x, ble_y, raw_cam_y], gated_cam_y, overwrite=False
            )
        )

        target_x = net.add_cell("car_bumper_x", unit="ft")
        target_y = net.add_cell("car_bumper_y", unit="ft")

        pipe_x = add_degenerate_pipeline(
            net,
            target_x,
            [
                DegenerateBranch("camera_x", gated_cam_x, priority=1.0),
                DegenerateBranch("ble_x", ble_x, priority=0.8),
            ],
            mode="consensus",
        )
        pipe_y = add_degenerate_pipeline(
            net,
            target_y,
            [
                DegenerateBranch("camera_y", gated_cam_y, priority=1.0),
                DegenerateBranch("ble_y", ble_y, priority=0.8),
            ],
            mode="consensus",
        )

        return net, (d1, d2, d3, d4), (raw_cam_x, raw_cam_y), (target_x, target_y), (pipe_x, pipe_y)

    def set_scenario(
        net, d_cells, cam_cells, true_x, true_y, err_ble=1.0, cam_box=None, p1_offline=False
    ):
        d1, d2, d3, d4 = d_cells
        cam_x, cam_y = cam_cells
        p1, p2, p3, p4 = (0.0, 0.0), (30.0, 0.0), (0.0, 20.0), (30.0, 20.0)

        dist1 = math.hypot(true_x - p1[0], true_y - p1[1])
        dist2 = math.hypot(true_x - p2[0], true_y - p2[1])
        dist3 = math.hypot(true_x - p3[0], true_y - p3[1])
        dist4 = math.hypot(true_x - p4[0], true_y - p4[1])

        if p1_offline:
            d1.set_value(Bottom(), overwrite=True)
        else:
            d1.set_value(IntervalValue(max(0.0, dist1 - err_ble), dist1 + err_ble), overwrite=True)
        d2.set_value(IntervalValue(max(0.0, dist2 - err_ble), dist2 + err_ble), overwrite=True)
        d3.set_value(IntervalValue(max(0.0, dist3 - err_ble), dist3 + err_ble), overwrite=True)
        d4.set_value(IntervalValue(max(0.0, dist4 - err_ble), dist4 + err_ble), overwrite=True)

        if cam_box is not None:
            cam_x.set_value(cam_box[0], overwrite=True)
            cam_y.set_value(cam_box[1], overwrite=True)
        else:
            cam_x.set_value(Bottom(), overwrite=True)
            cam_y.set_value(Bottom(), overwrite=True)

        net.run()

    # Scenario 1: Middle Bay (Consensus)
    net, d_cells, cam_cells, (tx, ty), (px, _py) = build_network()
    set_scenario(
        net,
        d_cells,
        cam_cells,
        15.0,
        6.0,
        err_ble=1.0,
        cam_box=(IntervalValue(14.0, 16.0), IntervalValue(5.0, 7.0)),
    )
    assert px.status == "consensus"
    assert tx.value == IntervalValue(14.0, 16.0)
    assert ty.value == IntervalValue(5.0, 7.0)

    # Scenario 2: Driveway (Degraded)
    net, d_cells, cam_cells, (tx, ty), (px, _py) = build_network()
    set_scenario(net, d_cells, cam_cells, 15.0, 30.0, err_ble=1.5, cam_box=None)
    assert px.status == "degraded"
    assert tx.value.contains(15.0)
    assert ty.value.contains(30.0)
    assert ty.value.min_val > 20.0  # Confirmed in driveway

    # Scenario 3: Left Bay (Bay 1)
    net, d_cells, cam_cells, (tx, ty), (px, _py) = build_network()
    set_scenario(net, d_cells, cam_cells, 5.0, 6.0, err_ble=1.0, cam_box=None)
    assert px.status == "degraded"
    assert tx.value.contains(5.0)
    assert ty.value.contains(6.0)
    span_x3 = tx.value.max_val - tx.value.min_val
    span_y3 = ty.value.max_val - ty.value.min_val

    # Scenario 4: Driveway with Guest in Middle Bay (Identity Gated)
    net, d_cells, cam_cells, (tx, ty), (px, _py) = build_network()
    set_scenario(
        net,
        d_cells,
        cam_cells,
        15.0,
        30.0,
        err_ble=1.5,
        cam_box=(IntervalValue(14.0, 16.0), IntervalValue(5.0, 7.0)),
    )
    assert px.status == "degraded"
    # Camera was rejected: our bumper remains in driveway
    assert ty.value.min_val > 20.0
    assert tx.value.contains(15.0)
    assert ty.value.contains(30.0)

    # Scenario 5: Left Bay with Proxy P1 Offline (Degraded Accuracy Comparison)
    net, d_cells, cam_cells, (tx, ty), (px, _py) = build_network()
    set_scenario(net, d_cells, cam_cells, 5.0, 6.0, err_ble=1.0, cam_box=None, p1_offline=True)
    assert px.status == "degraded"
    assert tx.value.contains(5.0)
    assert ty.value.contains(6.0)
    span_x5 = tx.value.max_val - tx.value.min_val
    span_y5 = ty.value.max_val - ty.value.min_val
    assert span_x5 > span_x3
    # Y-span more than doubles without P1
    assert span_y5 > 2.0 * span_y3
