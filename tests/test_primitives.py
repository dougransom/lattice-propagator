"""Unit tests for the Generalized Propagator Network Primitives."""

import math
from types import MappingProxyType

from lattice_propagator.lattice import (
    BOTTOM,
    Contradiction,
    DiscreteDomain,
    FlatValue,
    GaussianValue,
    IntervalValue,
    MapLattice,
)
from lattice_propagator.primitives import (
    AllDifferentPropagator,
    ArithmeticPropagator,
    BoundedLinearPropagator,
    Cell,
    ChoiceEngine,
    KalmanEstimatorPropagator,
    LagPropagator,
    MobileLinkPropagator,
    PropagatorNetwork,
    RatePropagator,
    ThresholdPropagator,
    TrajectoryEnvelopePropagator,
    TrajectorySegment,
    lift_propagator,
)


def test_arithmetic_propagator_gaussian():
    """Verify linear combination of Gaussian random variables (e.g. power balance)."""
    net = PropagatorNetwork("PowerBalance")
    solar = net.add_cell("Solar", GaussianValue(mean=5000.0, variance=100.0))
    load = net.add_cell("Load", GaussianValue(mean=2000.0, variance=50.0))
    net_power = net.add_cell("NetPower")

    # Net = 1.0 * Solar - 1.0 * Load
    p = ArithmeticPropagator(
        "PowerCalc", inputs=[solar, load], output=net_power, weights=[1.0, -1.0]
    )
    net.add_propagator(p)
    net.run()

    res = net_power.value
    assert isinstance(res, GaussianValue)
    # Expected mean: 5000 - 2000 = 3000
    assert math.isclose(res.mean, 3000.0, abs_tol=1e-3)
    # Expected variance: 100 + 50 = 150
    assert math.isclose(res.variance, 150.0, abs_tol=1e-3)


def test_arithmetic_propagator_intervals():
    """Verify interval arithmetic propagation."""
    net = PropagatorNetwork("IntervalSum")
    c1 = net.add_cell("C1", IntervalValue(10.0, 20.0))
    c2 = net.add_cell("C2", IntervalValue(5.0, 15.0))
    c3 = net.add_cell("C3")

    p = ArithmeticPropagator("Sum", inputs=[c1, c2], output=c3, weights=[1.0, 1.0])
    net.add_propagator(p)
    net.run()

    res = c3.value
    assert isinstance(res, IntervalValue)
    assert math.isclose(res.min_val, 15.0, abs_tol=1e-3)
    assert math.isclose(res.max_val, 35.0, abs_tol=1e-3)


def test_rate_propagator_and_eta():
    """Verify rate calculations and time-to-threshold interval estimation."""
    net = PropagatorNetwork("Rate")
    pos = net.add_cell("Distance")
    speed = net.add_cell("Speed")
    eta = net.add_cell("ETA")

    rate_p = RatePropagator(
        "Kinematics", input_cell=pos, output_rate_cell=speed, output_eta_cell=eta, threshold=500.0
    )
    net.add_propagator(rate_p)

    # Observation 1: 5000m at t=0
    rate_p.update_observation(5000.0, 0.0, net)
    net.run()

    # Observation 2: 4000m at t=50s (moving closer at -20 m/s = 72 km/h)
    rate_p.update_observation(4000.0, 50.0, net)
    net.run()

    speed_val = speed.value
    assert isinstance(speed_val, GaussianValue)
    assert math.isclose(speed_val.mean, -20.0, abs_tol=1e-3)

    eta_val = eta.value
    assert isinstance(eta_val, IntervalValue)
    # Distance to threshold (500m) is 4000 - 500 = 3500m
    # Nominal time = 3500 / 20 = 175s
    # Bounds [175 * 0.85, 175 * 1.2] = [148.75, 210.0]
    assert 140.0 < eta_val.min_val < 155.0
    assert 200.0 < eta_val.max_val < 220.0


def test_lag_propagator_thermal_inertia():
    """Verify first-order RC thermal lag modeling (exponential smoothing)."""
    net = PropagatorNetwork("ThermalLag")
    outdoor = net.add_cell("Outdoor", GaussianValue(mean=30.0, variance=0.1))
    indoor = net.add_cell("Indoor", GaussianValue(mean=20.0, variance=0.1))
    projected = net.add_cell("Projected")

    # Building thermal time constant tau = 10.0 hours (or arbitrary time unit)
    lag = LagPropagator(
        "BuildingLag", target_cell=outdoor, state_cell=indoor, output_cell=projected, tau=10.0
    )
    net.add_propagator(lag)

    # Step by dt = 1.0 time unit
    lag.step(dt=1.0)
    res = projected.value
    assert isinstance(res, GaussianValue)
    # alpha = 1 - exp(-1/10) ~= 0.09516
    # next_mu = 20 + 0.09516 * (30 - 20) ~= 20.95
    assert 20.9 < res.mean < 21.1


def test_bounded_linear_propagator():
    """Verify comfort band target modulation driven by electricity tariff / solar signal."""
    net = PropagatorNetwork("ComfortOptimizer")
    price = net.add_cell("Tariff")
    target = net.add_cell("EffectiveTarget")

    # Comfort interval: [20.0°C, 22.5°C], nominal = 21.0°C, baseline price = $0.20/kWh
    # Sensitivity = 10.0 (°C per $/kWh)
    modulator = BoundedLinearPropagator(
        name="TOUModulator",
        signal_cell=price,
        output_cell=target,
        acceptable_range=IntervalValue(20.0, 22.5),
        nominal_target=21.0,
        baseline_signal=0.20,
        sensitivity=10.0,
    )
    net.add_propagator(modulator)

    # Scenario A: Peak Price ($0.45/kWh) -> Target relaxes down to min comfort (20.0°C)
    price.set_value(GaussianValue(mean=0.45, variance=0.001))
    net.run()
    res_peak = target.value
    assert isinstance(res_peak, GaussianValue)
    # Adjustment = 10.0 * (0.20 - 0.45) = -2.5 -> 21.0 - 2.5 = 18.5 -> clamped to 20.0°C
    assert math.isclose(res_peak.mean, 20.0, abs_tol=1e-3)

    # Scenario B: Negative / Cheap Price ($0.05/kWh) -> Target tightens up to max comfort (22.5°C, pre-heating)
    price.set_value(GaussianValue(mean=0.05, variance=0.001), overwrite=True)
    net.run()
    res_cheap = target.value
    assert isinstance(res_cheap, GaussianValue)
    # Adjustment = 10.0 * (0.20 - 0.05) = +1.5 -> 21.0 + 1.5 = 22.5 -> clamped to 22.5°C
    assert math.isclose(res_cheap.mean, 22.5, abs_tol=1e-3)


def test_threshold_propagator():
    """Verify threshold comparator triggering."""
    net = PropagatorNetwork("AlertThreshold")
    temp = net.add_cell("Temp", GaussianValue(mean=18.5, variance=0.1))
    freeze_alert = net.add_cell("FreezeAlert")

    p = ThresholdPropagator(
        "FreezeDetector", input_cell=temp, output_bool_cell=freeze_alert, threshold=19.0, below=True
    )
    net.add_propagator(p)
    net.run()

    val = freeze_alert.value
    assert isinstance(val, IntervalValue)
    assert val.min_val == 1.0  # Triggered!


def test_propagator_network_mermaid():
    """Verify Mermaid diagram generation for composed network."""
    net = PropagatorNetwork("SimpleNet")
    c1 = net.add_cell("A", GaussianValue(mean=1.0, variance=0.1))
    c2 = net.add_cell("B")
    p = ArithmeticPropagator("Adder", inputs=[c1], output=c2, offset=5.0)
    net.add_propagator(p)
    net.run()

    mermaid = net.generate_mermaid()
    assert "graph LR" in mermaid
    assert "P_Adder" in mermaid
    assert "C_A" in mermaid


def test_lag_propagator_intervals():
    """Verify lag propagation with interval bounds."""
    net = PropagatorNetwork("IntervalLag")
    t = net.add_cell("Target", IntervalValue(20.0, 25.0))
    s = net.add_cell("State", IntervalValue(10.0, 15.0))
    out = net.add_cell("Out")

    lag = LagPropagator("Lag", target_cell=t, state_cell=s, output_cell=out, tau=5.0)
    net.add_propagator(lag)
    lag.step(dt=2.5)

    res = out.value
    assert isinstance(res, IntervalValue)
    assert 10.0 < res.min_val < 20.0
    assert 15.0 < res.max_val < 25.0


def test_rate_propagator_from_interval_and_threshold_above():
    """Verify rate propagator alert with interval input and threshold above."""
    net = PropagatorNetwork("IntervalRate")
    pos = net.add_cell("Pos", IntervalValue(100.0, 200.0))
    rate = net.add_cell("Rate")
    p = RatePropagator("RateP", input_cell=pos, output_rate_cell=rate)
    net.add_propagator(p)
    net.run()

    # Threshold above
    val = net.add_cell("Val", GaussianValue(mean=25.0, variance=0.1))
    alert = net.add_cell("Alert")
    tp = ThresholdPropagator(
        "HeatAlert", input_cell=val, output_bool_cell=alert, threshold=24.0, below=False
    )
    net.add_propagator(tp)
    net.run()

    res = alert.value
    assert isinstance(res, IntervalValue)
    assert res.min_val == 1.0


def test_all_different_propagator_chain():
    """Verify chain deduction (naked singles) with AllDifferentPropagator."""
    net = PropagatorNetwork("NakedSinglesChain")
    c1 = net.add_cell("C1", DiscreteDomain.single(1))
    c2 = net.add_cell("C2", DiscreteDomain(candidates={1, 2}))
    c3 = net.add_cell("C3", DiscreteDomain(candidates={1, 2, 3}))

    p = AllDifferentPropagator("AllDiff", [c1, c2, c3])
    net.add_propagator(p)
    net.run()

    assert c1.value.value == 1
    assert c2.value.value == 2
    assert c3.value.value == 3


def test_all_different_propagator_hidden_singles():
    """Verify hidden single deduction in a discrete domain unit."""
    net = PropagatorNetwork("HiddenSingles")
    c1 = net.add_cell("C1", DiscreteDomain(candidates={1, 2}))
    c2 = net.add_cell("C2", DiscreteDomain(candidates={1, 3}))
    c3 = net.add_cell("C3", DiscreteDomain(candidates={1, 2, 3, 4}))

    p = AllDifferentPropagator("AllDiff", [c1, c2, c3])
    net.add_propagator(p)
    net.run()

    # 4 only exists in c3, so c3 collapses to 4
    assert c3.value.is_determined
    assert c3.value.value == 4


def test_all_different_propagator_duplicate_contradiction():
    """Verify contradiction detection when two cells share the same determined value."""
    net = PropagatorNetwork("DuplicateConflict")
    c1 = net.add_cell("C1", DiscreteDomain.single(5))
    c2 = net.add_cell("C2", DiscreteDomain.single(5))

    p = AllDifferentPropagator("AllDiff", [c1, c2])
    net.add_propagator(p)
    net.run()

    assert any(isinstance(c.value, Contradiction) for c in [c1, c2])


def test_all_different_propagator_exhaustion_contradiction():
    """Verify contradiction detection when eliminating a value exhausts a cell's candidate set."""
    net = PropagatorNetwork("ExhaustionConflict")
    c1 = net.add_cell("C1", DiscreteDomain.single(1))
    c2 = net.add_cell("C2", DiscreteDomain.single(2))
    # C3 can only be 1 or 2, but both are claimed by peers
    c3 = net.add_cell("C3", DiscreteDomain(candidates={1, 2}))

    p = AllDifferentPropagator("AllDiff", [c1, c2, c3])
    net.add_propagator(p)
    net.run()

    assert isinstance(c3.value, Contradiction)
    assert "exhausted all candidates" in c3.value.reason


def test_kalman_estimator_constant_velocity():
    """Verify linear Kalman estimator tracks position and velocity under constant speed."""
    net = PropagatorNetwork("KalmanTracking")
    meas = net.add_cell("RawDistance")
    est_pos = net.add_cell("EstimatedDistance")
    est_vel = net.add_cell("EstimatedVelocity")

    kf = KalmanEstimatorPropagator(
        "Tracker",
        measurement_cell=meas,
        output_state_cell=est_pos,
        output_rate_cell=est_vel,
        process_noise_q=0.05,
        default_measurement_noise_r=4.0,
    )
    net.add_propagator(kf)

    # True trajectory: x(t) = 1000 - 20 * t (moving towards home at 20 m/s)
    true_v = -20.0
    for t in range(15):
        noisy_z = 1000.0 + true_v * t + (0.5 if t % 2 == 0 else -0.5)
        kf.step(noisy_z, r=4.0, dt=1.0)

    # Check that estimated position and velocity have converged closely
    pos_val = est_pos.value
    vel_val = est_vel.value
    assert isinstance(pos_val, GaussianValue)
    assert isinstance(vel_val, GaussianValue)

    # Expected position at t=14 is 1000 - 280 = 720
    assert abs(pos_val.mean - 720.0) < 5.0
    # Expected velocity is -20.0 m/s
    assert abs(vel_val.mean - true_v) < 2.0
    # Posterior variance should have narrowed from initial 100.0/10.0
    assert pos_val.variance < 4.0
    assert vel_val.variance < 2.0


def test_kalman_estimator_spike_rejection():
    """Verify that an isolated measurement spike is smoothed out by the filter."""
    net = PropagatorNetwork("KalmanSpikeTest")
    meas = net.add_cell("Temp")
    est_temp = net.add_cell("EstTemp")
    est_rate = net.add_cell("EstRate")

    kf = KalmanEstimatorPropagator(
        "TempFilter",
        measurement_cell=meas,
        output_state_cell=est_temp,
        output_rate_cell=est_rate,
        process_noise_q=0.01,
        default_measurement_noise_r=1.0,
    )

    # Steady state around 21.0C
    for _ in range(10):
        kf.step(21.0, r=1.0, dt=1.0)

    assert abs(est_temp.value.mean - 21.0) < 0.1
    assert abs(est_rate.value.mean) < 0.05

    # Sudden one-off sensor glitch spike: 28.0C
    kf.step(28.0, r=1.0, dt=1.0)

    # The filter dampens the 7.0C spike significantly
    assert est_temp.value.mean < 25.0

    # Next reading returns to normal (21.1C)
    kf.step(21.1, r=1.0, dt=1.0)
    assert est_temp.value.mean < 23.5

    # Subsequent readings converge back to baseline
    for _ in range(5):
        kf.step(21.0, r=1.0, dt=1.0)
    assert abs(est_temp.value.mean - 21.0) < 0.2


def test_kalman_estimator_network_reactive_alert():
    """Verify KalmanEstimatorPropagator reacts when cell values update in a PropagatorNetwork."""
    net = PropagatorNetwork("ReactiveKalman")
    meas = net.add_cell("Observation")
    pos = net.add_cell("State")
    rate = net.add_cell("Rate")

    kf = KalmanEstimatorPropagator(
        "KF",
        measurement_cell=meas,
        output_state_cell=pos,
        output_rate_cell=rate,
        process_noise_q=0.1,
    )
    net.add_propagator(kf)

    # Initial measurement via Gaussian
    meas.set_value(GaussianValue(mean=50.0, variance=0.5))
    net.run()

    assert isinstance(pos.value, GaussianValue)
    assert pos.value.mean == 50.0
    assert isinstance(rate.value, GaussianValue)
    assert rate.value.mean == 0.0

    # Observation via IntervalValue
    meas.set_value(IntervalValue(min_val=51.0, max_val=53.0), overwrite=True)
    net.run()

    assert isinstance(pos.value, GaussianValue)
    assert 50.0 < pos.value.mean < 53.0

    # Reset
    kf.reset(x=10.0, v=2.0)
    assert kf.x == 10.0
    assert kf.v == 2.0


def test_trajectory_segment_validation():
    """Verify TrajectorySegment validation, duration checks, and scalar promotion."""
    seg1 = TrajectorySegment(duration=10.0, bounds=IntervalValue(0.0, 100.0), name="ramp")
    assert seg1.duration == 10.0
    assert seg1.bounds == IntervalValue(0.0, 100.0)
    assert seg1.transition == "linear"

    # Scalar bounds promotion to IntervalValue
    seg2 = TrajectorySegment(duration=5.0, bounds=50.0, transition="step", name="hold")
    assert seg2.bounds == IntervalValue(50.0, 50.0)

    try:
        TrajectorySegment(duration=-1.0, bounds=IntervalValue(0.0, 1.0))
        assert False, "Negative duration should raise ValueError"
    except ValueError:
        pass


def test_trajectory_envelope_propagator_linear_ramp():
    """Verify multi-segment linear interpolation and holding final values."""
    net = PropagatorNetwork("LinearTrajectory")
    time_cell = net.add_cell("Time", FlatValue(0.0))
    target_cell = net.add_cell("Target")
    phase_cell = net.add_cell("Phase")

    # 0s -> 30s: 100 down to 0; 30s -> 40s: hold at 0
    segments = [
        TrajectorySegment(
            duration=30.0, bounds=IntervalValue(0.0, 0.0), transition="linear", name="fade_out"
        ),
        TrajectorySegment(
            duration=10.0, bounds=IntervalValue(0.0, 0.0), transition="hold", name="hold_off"
        ),
    ]
    p = TrajectoryEnvelopePropagator(
        "SceneFade",
        time_cell=time_cell,
        output_cell=target_cell,
        segments=segments,
        initial_bounds=IntervalValue(100.0, 100.0),
        phase_cell=phase_cell,
    )
    net.add_propagator(p)

    # t = 0s -> 100.0
    net.run()
    assert target_cell.value == IntervalValue(100.0, 100.0)
    assert phase_cell.value == DiscreteDomain.single("fade_out")

    # t = 15s -> 50.0
    p.set_time(15.0)
    net.run()
    val_15 = target_cell.value
    assert isinstance(val_15, IntervalValue)
    assert math.isclose(val_15.min_val, 50.0, abs_tol=1e-3)
    assert math.isclose(val_15.max_val, 50.0, abs_tol=1e-3)

    # t = 30s -> 0.0
    p.set_time(30.0)
    net.run()
    val_30 = target_cell.value
    assert isinstance(val_30, IntervalValue)
    assert math.isclose(val_30.min_val, 0.0, abs_tol=1e-3)

    # t = 50s (> 40s total duration) -> holds final 0.0
    p.set_time(50.0)
    net.run()
    assert target_cell.value == IntervalValue(0.0, 0.0)
    assert phase_cell.value == DiscreteDomain.single("hold_off")


def test_trajectory_envelope_propagator_smooth_and_step():
    """Verify smooth cosine S-curve easing and step transitions."""
    net = PropagatorNetwork("SmoothAndStep")
    time_cell = net.add_cell("Time", FlatValue(0.0))
    target_cell = net.add_cell("Target")

    segments = [
        TrajectorySegment(
            duration=10.0, bounds=IntervalValue(100.0, 100.0), transition="smooth", name="s_curve"
        ),
        TrajectorySegment(
            duration=5.0, bounds=IntervalValue(200.0, 200.0), transition="step", name="step_jump"
        ),
    ]
    p = TrajectoryEnvelopePropagator(
        "SmoothProp",
        time_cell=time_cell,
        output_cell=target_cell,
        segments=segments,
        initial_bounds=IntervalValue(0.0, 0.0),
    )
    net.add_propagator(p)

    # At midpoint t=5s of 10s smooth ramp: (1 - cos(pi * 0.5)) / 2 = 0.5 -> 50.0
    p.set_time(5.0)
    net.run()
    val_5 = target_cell.value
    assert isinstance(val_5, IntervalValue)
    assert math.isclose(val_5.min_val, 50.0, abs_tol=1e-3)

    # In step transition segment (t=12s): jumps immediately to 200.0
    p.set_time(12.0)
    net.run()
    assert target_cell.value == IntervalValue(200.0, 200.0)


def test_trajectory_envelope_propagator_enable_and_retraction():
    """Verify enable gating and automatic retraction to BOTTOM when deactivated."""
    net = PropagatorNetwork("EnableGating")
    time_cell = net.add_cell("Time", FlatValue(5.0))
    enable_cell = net.add_cell("Enable", DiscreteDomain.single(True))
    target_cell = net.add_cell("Target")
    phase_cell = net.add_cell("Phase")

    segments = [TrajectorySegment(duration=10.0, bounds=IntervalValue(100.0, 100.0), name="ramp")]
    p = TrajectoryEnvelopePropagator(
        "GatedProp",
        time_cell=time_cell,
        output_cell=target_cell,
        segments=segments,
        enable_cell=enable_cell,
        phase_cell=phase_cell,
        initial_bounds=IntervalValue(0.0, 0.0),
    )
    net.add_propagator(p)

    # Active
    net.run()
    assert target_cell.value == IntervalValue(50.0, 50.0)
    assert phase_cell.value == DiscreteDomain.single("ramp")

    # Deactivate -> retacts to BOTTOM
    enable_cell.set_value(DiscreteDomain.single(False), overwrite=True)
    net.run()
    assert target_cell.value == BOTTOM
    assert phase_cell.value == BOTTOM

    # Reactivate
    enable_cell.set_value(DiscreteDomain.single(True), overwrite=True)
    net.run()
    assert target_cell.value == IntervalValue(50.0, 50.0)


def test_trajectory_envelope_interval_time_and_loop():
    """Verify envelope evaluation under uncertain interval time and loop mode."""
    net = PropagatorNetwork("IntervalTimeAndLoop")
    time_cell = net.add_cell("Time")
    target_cell = net.add_cell("Target")

    # Total duration = 20s
    segments = [
        TrajectorySegment(duration=10.0, bounds=IntervalValue(100.0, 100.0), transition="linear"),
        TrajectorySegment(duration=10.0, bounds=IntervalValue(0.0, 0.0), transition="linear"),
    ]
    p = TrajectoryEnvelopePropagator(
        "LoopingProp",
        time_cell=time_cell,
        output_cell=target_cell,
        segments=segments,
        initial_bounds=IntervalValue(0.0, 0.0),
        loop=True,
    )
    net.add_propagator(p)

    # t = 25s with loop -> 25 % 20 = 5s (halfway through first segment -> 50.0)
    time_cell.set_value(FlatValue(25.0))
    net.run()
    assert math.isclose(target_cell.value.min_val, 50.0, abs_tol=1e-3)

    # Time interval [2.0, 8.0] -> bounds [20.0, 80.0]
    time_cell.set_value(IntervalValue(2.0, 8.0), overwrite=True)
    net.run()
    res = target_cell.value
    assert isinstance(res, IntervalValue)
    assert math.isclose(res.min_val, 20.0, abs_tol=1e-3)
    assert math.isclose(res.max_val, 80.0, abs_tol=1e-3)


def test_trajectory_envelope_squishing_and_custom_functions():
    """Verify sigmoid, tanh, exponential easing, and custom evaluation callables."""
    time_cell = Cell("Time")
    target_cell = Cell("Target")

    # Sigmoid transition
    seg_sigmoid = TrajectorySegment(duration=10.0, bounds=100.0, transition="sigmoid")
    prop_sigmoid = TrajectoryEnvelopePropagator(
        "SigmoidProp", time_cell, target_cell, [seg_sigmoid], initial_bounds=0.0
    )
    # At t=0 -> 0.0, t=5.0 -> 50.0, t=10.0 -> 100.0
    assert math.isclose(prop_sigmoid.evaluate_at(0.0).center, 0.0, abs_tol=1e-3)
    assert math.isclose(prop_sigmoid.evaluate_at(5.0).center, 50.0, abs_tol=1e-3)
    assert math.isclose(prop_sigmoid.evaluate_at(10.0).center, 100.0, abs_tol=1e-3)

    # Tanh transition
    seg_tanh = TrajectorySegment(duration=10.0, bounds=100.0, transition="tanh")
    prop_tanh = TrajectoryEnvelopePropagator(
        "TanhProp", time_cell, target_cell, [seg_tanh], initial_bounds=0.0
    )
    assert math.isclose(prop_tanh.evaluate_at(0.0).center, 0.0, abs_tol=1e-3)
    assert math.isclose(prop_tanh.evaluate_at(5.0).center, 50.0, abs_tol=1e-3)
    assert math.isclose(prop_tanh.evaluate_at(10.0).center, 100.0, abs_tol=1e-3)

    # Exponential transition
    seg_exp = TrajectorySegment(duration=10.0, bounds=100.0, transition="exponential")
    prop_exp = TrajectoryEnvelopePropagator(
        "ExpProp", time_cell, target_cell, [seg_exp], initial_bounds=0.0
    )
    assert math.isclose(prop_exp.evaluate_at(0.0).center, 0.0, abs_tol=1e-3)
    assert prop_exp.evaluate_at(5.0).center > 80.0  # Rapid initial rise
    assert math.isclose(prop_exp.evaluate_at(10.0).center, 100.0, abs_tol=1e-3)

    # Custom callable evaluation (e.g. quadratic curve u^2)
    seg_custom = TrajectorySegment(duration=10.0, bounds=100.0, custom_eval=lambda u: u**2)
    prop_custom = TrajectoryEnvelopePropagator(
        "CustomProp", time_cell, target_cell, [seg_custom], initial_bounds=0.0
    )
    # At u=0.5 (t=5.0), u^2 = 0.25 -> 25.0
    assert math.isclose(prop_custom.evaluate_at(5.0).center, 25.0, abs_tol=1e-3)


def test_abstract_collection_interfaces():
    """Verify that Propagators, Cells, and Networks accept abstract Sequences and Mappings."""
    net = PropagatorNetwork("AbstractCollectionsNet")

    # 1. Cell accepts propagators as a tuple Sequence
    c1 = Cell("c1", propagators=())
    assert isinstance(c1.propagators, list)

    # 2. lift_propagator accepts tuple Sequence for inputs
    c2 = net.add_cell("c2", FlatValue(10))
    c3 = net.add_cell("c3", FlatValue(20))
    c_out = net.add_cell("c_out")
    prop = lift_propagator(
        "add_lifted",
        lambda a, b: FlatValue(a.val + b.val),
        (c2, c3),  # tuple Sequence
        c_out,
    )
    assert prop.inputs == [c2, c3]
    net.add_propagator(prop)
    net.run()
    assert c_out.value == FlatValue(30)

    # 3. derive_provenance and derive_premise accept Sequence and Mapping
    params_proxy = MappingProxyType({"rule": "custom_rule", "scale": 1.5})
    just, _conf, _is_assump, _support = prop.derive_provenance(
        antecedents=(c2, c3),
        parameters=params_proxy,
    )
    assert just.rule_name == "FunctionalPropagator"
    assert just.parameters["rule"] == "custom_rule"

    # 4. AllDifferentPropagator accepts tuple Sequence
    d1 = net.add_cell("d1", DiscreteDomain.range(1, 4))
    d2 = net.add_cell("d2", DiscreteDomain.range(1, 4))
    d3 = net.add_cell("d3", DiscreteDomain.range(1, 4))
    alldiff = AllDifferentPropagator("alldiff", (d1, d2, d3))  # tuple
    assert len(alldiff.cells) == 3

    # 5. ChoiceEngine accepts tuple Sequence
    engine = ChoiceEngine(net, variables=(d1, d2, d3))  # tuple
    assert engine.variables == [d1, d2, d3]

    # 6. TrajectoryEnvelopePropagator accepts tuple Sequence
    t_cell = net.add_cell("time", FlatValue(0.0))
    traj_out = net.add_cell("traj_out")
    seg = TrajectorySegment(duration=5.0, bounds=50.0)
    traj_prop = TrajectoryEnvelopePropagator(
        "traj",
        t_cell,
        traj_out,
        (seg,),  # tuple Sequence
    )
    assert len(traj_prop.segments) == 1

    # 7. MobileLinkPropagator accepts Mapping (MappingProxyType) and tuple Sequence
    chan = net.add_cell("chan", FlatValue("target_a"))
    payload = net.add_cell("payload", FlatValue("hello"))
    target_a = net.add_cell("target_a")
    target_b = net.add_cell("target_b")

    link_map = MobileLinkPropagator(
        "link_map",
        chan,
        payload,
        targets=MappingProxyType({"target_a": target_a, "target_b": target_b}),
    )
    assert "target_a" in link_map.target_map

    link_seq = MobileLinkPropagator(
        "link_seq",
        chan,
        payload,
        targets=(target_a, target_b),  # tuple Sequence
    )
    assert "target_a" in link_seq.target_map

    # 8. MapLattice accepts Mapping (MappingProxyType)
    ml = MapLattice(MappingProxyType({"key": FlatValue(123)}))
    assert ml.mapping["key"] == FlatValue(123)
